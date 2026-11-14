"""Controlled checkpoint continuity; no live-provider behavior claims."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import Protocol
from attack_harness.composition import compose_campaign
from test_conversation_checkpoints import PrefixHost
from test_instruction_boundary import CODECS
from test_scenario_delivery import ScenarioInputs
from scenario_loading_fixture import loading_bundle
from test_vertical_slice import Clock, LIMITS, Reply


NOTE = ('Baseline lookup assessed using execution-1 and observation-1; only external output inspected. '
        'Independent commitment remains unresolved. Revisit refund requirements for the final assessment, not another invocation.')


class ContinuityHost(PrefixHost):
    def __init__(self, protocol, *, repair_first=False, cooperate=True):
        super().__init__(protocol)
        self.repair_first, self.cooperate = repair_first, cooperate
        self.trim = False
        self.review_turn = None
        self.comment = ''

    def _calls(self, turn):
        task = self._task()
        self.comment = ''
        def select(identifier):
            entry = next(s for s in task['scenario_index'] if s['scenario_id'] == identifier)
            return (f'select-{turn}', 'reference_read', {'reference': entry['reference_id']})
        def finish(valid):
            return (f'finish-{turn}', 'finish', dict(finish_reason='no-useful-next-experiment',
                summary='Two scenarios inspected; independent effects unresolved.',
                objectives=[dict(objective_id='support', outcome='inconclusive' if valid else 'supported',
                    summary='Only external outputs inspected.', **({'observations':['observation-1','observation-2']} if valid else {}))],
                uncertainties=[dict(kind='evidence-gap', description='No independent state evidence.')]))
        if turn == 1:
            return [select('baseline')]
        if turn in (2, 5):
            return [(f'snapshot-{turn}', 'snapshot_request', {}),
                (f'execute-{turn}', 'attempt_execute', dict(origin='scenario',
                    scenario_id='baseline' if turn == 2 else 'refund', operation_id='invoke', json={'query':'bounded experiment'}))]
        if turn in (3, 6):
            return [(f'read-{turn}', 'observation_read', {'observation':f'observation-{1 if turn == 3 else 2}'})]
        if turn == 4:
            self.comment = NOTE
            return [('record', 'record_append', dict(kind='progress', summary='Baseline output inspected.',
                decision='Assess remaining evidence gaps at finish; do not replay.',
                attempts=['execution-1'], observations=['observation-1'])), select('refund')]
        if turn == 7:
            self.comment = 'Refund response assessed with observation-2; commitment unresolved. Review baseline evidence before finish.'
            return [('restore', 'restore_request', {'snapshot':'checkpoint-1'})]
        if self.repair_first and turn == 8:
            return [finish(False)]
        if self.repair_first and 9 <= turn <= 11:
            return [select('baseline' if turn % 2 else 'refund'),
                    (f'blocked-{turn}', 'attempt_execute', dict(origin='scenario', scenario_id='baseline', operation_id='invoke', text='do not execute'))]
        if self.repair_first:
            return [finish(True)]
        if task['continuity']['phase'] == 'assessment' and self.cooperate:
            if self.review_turn is None:
                self.review_turn = turn
                return [('blocked-before-finish', 'snapshot_request', {}), finish(False)]
            return [finish(True)]
        return [select('baseline' if turn % 2 == 0 else 'refund')]

    def _model_result(self, turn, calls):
        result = super()._model_result(turn, calls)
        if not self.comment:
            return result
        response = result['response']
        prefix, assistant = self.bound[-1]
        if self.codec == 'openai-chat-text-tools-v1':
            response['choices'][0]['message']['content'] = self.comment
            assistant = [deepcopy(response['choices'][0]['message'])]
        elif self.codec == 'openai-responses-text-tools-v1':
            message = dict(type='message', role='assistant', id=f'msg-{turn}', status='completed',
                content=[dict(type='output_text', text=self.comment, annotations=[])])
            response['output'].append(message)
            assistant = deepcopy(response['output'])
        elif self.codec == 'anthropic-messages-text-tools-v1':
            response['content'].append(dict(type='text', text=self.comment))
            assistant = [dict(role='assistant', content=deepcopy(response['content']))]
        elif self.codec == 'bedrock-converse-text-tools-v1':
            response['output']['message']['content'].append(dict(text=self.comment))
            assistant = [deepcopy(response['output']['message'])]
        else:
            response['candidates'][0]['content']['parts'].append(dict(text=self.comment))
            assistant = [deepcopy(response['candidates'][0]['content'])]
        self.bound[-1] = (prefix, assistant)
        return result

    def request(self, operation, body, *, operation_id):
        if operation == 'engine.finish' and 'unavailable' in body:
            self.events.append((operation, deepcopy(body), operation_id))
            return Reply(dict(status='accepted', execution_admission='closed', assessment_state='unavailable',
                exit_required=True, exit_within_ms=5000, finalization_status='pending', stop_receipt='unavailable'))
        return super().request(operation, body, operation_id=operation_id)


class CheckpointContinuityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def campaign(self, filename, **kwargs):
        host = ContinuityHost(self.protocol, **kwargs)
        bundle = loading_bundle()
        bundle['scenarios'] = bundle['scenarios'][:2]
        bundle['coverage']['completion_guidance'] = 'Assess both supplied scenarios; report independent evidence gaps.'
        inputs = ScenarioInputs(self.protocol, self.root, bundle, host, filename)
        limits = dict(LIMITS, max_model_turns=40, max_no_progress_turns=10)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            'limits': {'harness':limits, 'campaign':{'model_tokens':1000000}},
            'remaining_limits':{'campaign_time_ms':100000, 'artifact_bytes':2 << 20}})
        campaign = compose_campaign(self.protocol, session, clock=Clock())
        host.conversation = campaign.adaptive.conversation
        return campaign, host

    def assert_continuity(self, campaign, host):
        tasks = [host.task_from_request(r) for r in host.model_requests]
        final = tasks[-1]
        self.assertEqual(len(host.attempt_ids), 2)
        self.assertEqual(host.reads, 2)
        self.assertGreater(host.checked_prefixes, 0)
        self.assertEqual(len(final['scenario_index']), 2)
        self.assertEqual(len(final['evidence']['executions']), 2)
        self.assertEqual(len(final['evidence']['restores']), 1)
        notes = final['continuity']['model_notes']
        self.assertEqual(notes['provenance'], 'model-interpretation-not-evidence')
        self.assertEqual(next(n['text'] for n in notes['entries'] if n['scenario_id']=='baseline'), NOTE)
        self.assertNotIn('Controlled private reasoning', json.dumps(notes))
        self.assertNotIn('Controlled reasoning', json.dumps(notes))
        record = final['model_records']['entries'][0]
        self.assertEqual(record['record'], 'record-1')
        self.assertEqual(record['scenario_id'], 'baseline')
        self.assertEqual(record['submitted']['observations'], ['observation-1'])
        self.assertIn('not-verified-outcomes', final['model_records']['provenance'])
        self.assertEqual(final['continuity']['phase'], 'assessment')
        self.assertEqual(len(final['campaign_activity']), 5)  # two attempts, two snapshots, restore
        self.assertIn('assessment_repair_active' if host.repair_first else 'finalization_action_blocked',
                      json.dumps(host.model_requests))
        self.assertEqual(len(json.loads(host.conclusion_raw)['objectives'][0]['attempt_receipt_refs']), 2)
        self.assertEqual(campaign.adaptive.loop.snapshot()['model_turns'], len(host.model_requests))
        self.assertTrue(all(r['purpose']=='generation' for r in host.model_requests))

    def test_navigation_stall_transitions_and_correction_finishes_across_codecs(self):
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host = self.campaign(filename)
                self.assertEqual(campaign.run()['assessment_state'], 'committed')
                self.assert_continuity(campaign, host)
                review = host.task_from_request(host.model_requests[host.review_turn-1])
                self.assertEqual(review['continuity']['no_progress_turns'], 8)
                self.assertEqual(review['continuity']['phase_reason'], 'navigation-stalled')
                self.assertIn('repeated scenario navigation', review['harness_notice'])
                self.assertEqual(review['continuity']['no_progress_limit'], 10)
                self.assertGreater(review['scenario_index'][0]['selections'], 2)
                # Same active scenario on consecutive revisits no longer recreates
                # an indistinguishable task: navigation/counts are continuous.
                baseline = [host.task_from_request(r) for r in host.model_requests
                    if (host.task_from_request(r)['active_scenario'] or {}).get('scenario_id') == 'baseline']
                self.assertNotEqual(baseline[-1]['continuity'], baseline[-2]['continuity'])
                self.assertTrue(campaign.adaptive.dispatcher.assessment_review)
                self.assertIn('finalization_action_blocked', json.dumps(host.model_requests))

    def test_repair_review_crosses_checkpoints_without_reopening_execution(self):
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host = self.campaign(filename, repair_first=True)
                self.assertEqual(campaign.run()['assessment_state'], 'committed')
                self.assert_continuity(campaign, host)
                tasks = [host.task_from_request(r) for r in host.model_requests[8:]]
                self.assertTrue(all(t['continuity']['phase']=='assessment' for t in tasks))
                self.assertTrue(all('assessment_repair' in t for t in tasks))
                self.assertEqual(len({t['conversation_checkpoint']['conversation'] for t in tasks}), 4)

    def test_uncooperative_navigation_hits_unchanged_limit_without_assessment(self):
        campaign, host = self.campaign('responses-model-codec.json', cooperate=False)
        self.assertEqual(campaign.run()['assessment_state'], 'unavailable')
        self.assertIsNone(host.conclusion_raw)
        self.assertEqual(len(host.attempt_ids), 2)
        self.assertEqual(campaign.adaptive.loop.snapshot()['no_progress_turns'], 10)
        self.assertEqual(host.events[-1][1]['unavailable']['reason'], 'no-progress-limit')
        self.assertTrue(any(host.task_from_request(r)['continuity']['phase']=='assessment' for r in host.model_requests))

    def test_notes_and_record_projection_are_bounded_without_invented_handles(self):
        campaign, host = self.campaign('responses-model-codec.json')
        campaign.run()
        delivery = campaign.handlers.scenario_delivery
        delivery.remember_response(SimpleNamespace(public_text=lambda: 'execution-from-model ' + 'é' * 3000))
        note = delivery.notes[None]
        self.assertTrue(note['truncated'])
        self.assertLessEqual(len(note['text'].encode()), 2048)
        tools = campaign.handlers.model_tools
        for i in range(12):
            h = tools.register('record', {'record_receipt_id':f'large-{i}'}, available=True)
            tools.resources[h]['assessment_context'] = dict(scenario_id='baseline', submitted={'summary':'x'*5000})
        facts = tools.context_facts(set())
        self.assertGreater(facts['model_records']['omitted_records'], 0)
        self.assertLess(len(json.dumps(facts['model_records'])), 9000)
        self.assertEqual(len([r for r in tools.resources.values() if r['kind']=='record']), 13)
        self.assertNotIn('execution-from-model', tools.resources)
