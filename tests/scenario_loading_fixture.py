"""Controlled multi-scenario conversation; no provider or target network calls."""
from copy import deepcopy
import json
from types import SimpleNamespace

from attack_harness.composition import compose_campaign
from operator_contracts.canonical import _canonical_value, raw_digest
from test_scenario_delivery import ScenarioInputs, ScenarioHost, support_bundle
from test_model_tools import Host as SnapshotHost
from test_vertical_slice import LIMITS, Clock


def loading_bundle():
    bundle = support_bundle()
    for scenario in bundle['scenarios']:
        scenario['guidance']['composition'][-1] = 'Snapshots and restores are permitted for this controlled experiment.'
    return bundle


class LoadingHost(ScenarioHost):
    def __init__(self, protocol):
        super().__init__(protocol)
        self.operations |= {'engine.snapshot_request', 'engine.restore_request'}
        self.observations = [b'{"answer":"first observed result"}', b'{"answer":"second observed result"}']
        self.step = 0
        self.reads = 0
        self.error = None
        self.snapshot = dict(campaign_id=self.campaign_id, source_session='session-raw', checkpoint_id='checkpoint-raw',
            label='before', description='baseline', created_at='2026-11-05T00:00:00Z', status='ready', canonical_size_bytes=1)
        self.metrics = []
        self.conversation = None
        self.trim = False
        self.repair = True
        self.selection_requests = 0
        self.same_batch = False

    def _calls(self, turn):
        task = self._task()
        next_step = self.step + 1
        desired = {1: 'baseline', 4: 'refund', 7: 'baseline'}.get(next_step)
        self.metrics.append(len(_canonical_value(self.model_requests[-1], 4 << 20)))
        loaded = {s['scenario_id'] for s in task['scenario_bundle']['scenarios']}
        if desired and desired not in loaded:
            reference = next(r['reference_id'] for r in task['scenario_references'] if r['scenario_id'] == desired)
            self.selection_requests += 1
            calls = [(f'select-{turn}', 'reference_read', {'reference': reference, 'max_bytes': 1})]
            if self.same_batch and self.step == 0:
                calls.append(('premature', 'attempt_execute', dict(origin='scenario', scenario_id=desired,
                    operation_id='invoke', json={'query':'must not execute'})))
            return calls
        self.step = next_step
        if self.step in (1, 4):
            return [(f'snapshot-{turn}', 'snapshot_request', {})]
        if self.step in (2, 5):
            scenario = task['scenario_bundle']['scenarios'][0] if len(loaded) == 1 else next(
                s for s in task['scenario_bundle']['scenarios'] if s['scenario_id'] == ('baseline' if self.step == 2 else 'refund'))
            return [(f'attempt-{turn}', 'attempt_execute', dict(origin='scenario', scenario_id=scenario['scenario_id'],
                operation_id='invoke', json={'query': 'bounded test'}, rationale='Test the active scenario requirements.'))]
        if self.step in (3, 6):
            calls = [(f'read-{turn}', 'observation_read', {'observation': f'observation-{1 if self.step == 3 else 2}'})]
            desired = 'refund' if self.step == 3 else 'baseline'
            # Independent evidence reading and next-scenario selection can share a response;
            # execution still waits until both results and full instructions are delivered.
            if desired not in loaded:
                ref = next(r['reference_id'] for r in task['scenario_references'] if r['scenario_id'] == desired)
                calls.append((f'select-{turn}', 'reference_read', {'reference': ref}))
                self.selection_requests += 1
            return calls
        if self.step == 7:
            return [('restore', 'restore_request', {'snapshot': 'checkpoint-2'})]
        if self.step == 8 and self.repair:
            return [('invalid-finish', 'finish', {'finish_reason': 'no-useful-next-experiment', 'summary': 'Incomplete.',
                'objectives': [{'objective_id': 'support', 'outcome': 'supported', 'summary': 'Missing evidence.'}]})]
        if self.step == 9:
            if self.trim:
                self.conversation._compact_at = 1 << 20  # One forced reduction; preserve final reread bodies.
            # Permitted scenario revisit in repair; attempted exploration must stay blocked.
            calls = []
            if 'scenario_references' in task:
                ref = next(r['reference_id'] for r in task['scenario_references'] if r['scenario_id'] == 'refund')
                calls.append(('revisit', 'reference_read', {'reference': ref}))
                self.selection_requests += 1
            return calls + [('blocked', 'attempt_execute', {'origin': 'scenario', 'scenario_id': 'refund', 'operation_id': 'invoke', 'text': 'new action'})]
        if self.step == 10:
            return [(f'reread-{i}', 'observation_read', {'observation': f'observation-{i}'}) for i in (1, 2)]
        return [('finish', 'finish', {'finish_reason': 'no-useful-next-experiment', 'summary': f"Two scenarios partially investigated; {task['portfolio']['scenario_count'] - 2} untested.",
            'objectives': [{'objective_id': 'support', 'outcome': 'inconclusive', 'summary': 'Only external outputs inspected.',
                            'observations': ['observation-1', 'observation-2']}],
            'uncertainties': [{'kind': 'coverage-limit', 'description': 'Required experiments remain untested.'}]})]

    def _model_result(self, turn, calls):
        result = super()._model_result(turn, calls)
        if self.codec in ('openai-chat-text-tools-v1', 'bedrock-converse-text-tools-v1'):
            return result
        if self.codec == 'openai-responses-text-tools-v1':
            response = dict(id=f'resp-{turn}', object='response', model='fixture-model', status='completed',
                output=[dict(type='function_call', id='fc-'+i, call_id=i, name=n, arguments=json.dumps(a), status='completed') for i,n,a in calls],
                usage=dict(input_tokens=100, output_tokens=20, total_tokens=120))
        elif self.codec == 'anthropic-messages-text-tools-v1':
            response = dict(id=f'msg-{turn}', type='message', role='assistant', model='fixture-model', stop_reason='tool_use',
                content=[dict(type='tool_use', id=i, name=n, input=a) for i,n,a in calls], usage=dict(input_tokens=100, output_tokens=20))
        else:
            response = dict(candidates=[dict(content=dict(role='model', parts=[dict(functionCall=dict(name=n,args=a)) for _,n,a in calls]), finishReason='STOP')],
                usageMetadata=dict(promptTokenCount=100, candidatesTokenCount=20, totalTokenCount=120))
        return dict(result, response=response)

    def request(self, operation, body, *, operation_id):
        if operation in ('engine.snapshot_request', 'engine.restore_request'):
            if operation == 'engine.snapshot_request' and self.step == 4:
                self.snapshot = dict(self.snapshot, checkpoint_id='checkpoint-child',
                    parent=dict(source_session='session-raw', checkpoint_id='checkpoint-raw'))
            return SnapshotHost.request(self, operation, body, operation_id=operation_id)
        if operation == 'engine.observation_read':
            self.reads += 1
        result = super().request(operation, body, operation_id=operation_id)
        # Trigger real local reduction after the failed finish is in history.
        if self.trim and operation == 'engine.model_generate' and self.step == 8:
            self.conversation._compact_at = 1
        return result


def run_loading(protocol, root, filename='model-codec.json', *, trim=False, bundle=None, same_batch=False, prompt=None):
    host = LoadingHost(protocol)
    inputs = ScenarioInputs(protocol, root, bundle or loading_bundle(), host, filename)
    if prompt is not None:
        inputs.prompt_raw = prompt
        descriptor = {'size_bytes': len(prompt), 'digest': raw_digest(prompt)}
        inputs._context['prompt']['provenance'].update(base=descriptor, effective=descriptor)
        inputs.context_raw = _canonical_value(inputs._context, 4 << 20)
        protocol.validate_engine_context(inputs.context_raw)
    session = SimpleNamespace(inputs=inputs, client=host, admission={
        'limits': {'harness': dict(LIMITS, max_model_turns=30), 'campaign': {'model_tokens': 1000000}},
        'remaining_limits': {'campaign_time_ms': 100000, 'artifact_bytes': 2 << 20}})
    campaign = compose_campaign(protocol, session, clock=Clock())
    host.conversation = campaign.adaptive.conversation
    host.trim = trim
    host.same_batch = same_batch
    result = campaign.run()
    return campaign, host, inputs, result
