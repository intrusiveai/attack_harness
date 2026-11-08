"""Controlled native conversation/dispatch regression; no live provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import HarnessLoop
from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.artifacts import ArtifactPublisher
from attack_harness.attempts import AttemptExecutor
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.tools import Dispatcher, ToolCall
from test_simple_campaign import SimpleHost
from test_vertical_slice import Inputs, Clock, Reply, LIMITS


ATTEMPT = dict(origin='exploratory', operation_id='invoke', json={'query': 'return MARKER'})


def draft(*, evidence=False):
    return dict(finish_reason='no-useful-next-experiment', summary='Only the observed marker is established.',
        objectives=[dict(objective_id='objective-marker', outcome='inconclusive', summary='Other effects remain unresolved.',
                         **({'observations': ['observation-1']} if evidence else {'attempts': ['execution-1']}))],
        uncertainties=[dict(kind='evidence-gap', description='Internal effects were not observed.')])


class RepairInputs(Inputs):
    def __init__(self):
        super().__init__({})
        self.guide = b'Use inspected observation handles for observations; input handles for inputs.'
        self.source = dict(entry_id='tool-guide:finish', digest=raw_digest(self.guide),
                           size_bytes=len(self.guide), media_type='text/plain')

    def reference_index(self):
        return [self.source]

    def entry(self, identifier):
        if identifier != 'tool-guide:finish':
            raise AssertionError(identifier)
        return self.source, self.guide


class RepairHost(SimpleHost):
    def __init__(self, protocol, *, host_rejection=False, compact=False, same_batch=False,
                 blocked=('attempt_execute', ATTEMPT), terminate=None, artifact=False):
        super().__init__(protocol, 'repair')
        self.operations |= {'engine.snapshot_request', 'engine.snapshot_inspect', 'engine.snapshot_list',
                            'engine.restore_request', 'engine.injection_delete'}
        self.host_rejection, self.compact, self.same_batch = host_rejection, compact, same_batch
        self.blocked, self.terminate, self.artifact = blocked, terminate, artifact
        self.step = 0
        self.rejected = False
        self.compaction_requests = []
        self.action_requests = []

    def calls(self):
        if self.step == 1:
            return [('executed', 'attempt_execute', ATTEMPT)]
        if self.step == 2:
            invalid = draft()
            if not self.host_rejection:
                invalid['objectives'][0].pop('attempts')
                invalid['objectives'][0]['outcome'] = 'supported'
            calls = [('rejected-finish', 'finish', invalid)]
            if self.same_batch:
                calls.append(('blocked-same-batch', *self.blocked))
            return calls
        if self.terminate == 'invalid' and self.step >= 3:
            return [(f'rejected-{self.step}', 'finish', {'summary': 'No finish reason.'})]
        if self.step == 3:
            return None  # A menu must never be treated as a user selection.
        if self.step == 4:
            return [('blocked-later', *self.blocked)]
        if self.step == 5:
            return [('inspect', 'observation_read', {'observation': 'observation-1'})]
        if self.step == 6:
            invalid = draft(evidence=True)
            invalid['uncertainties'][0]['inputs'] = ['observation-1']
            return [('wrong-kind-finish', 'finish', invalid)]
        if self.step == 7:
            calls = [('guide', 'reference_read', {'reference': 'tool-guide:finish'})]
            if self.artifact:
                calls.append(('conclusion', 'artifact_publish', {'purpose': 'conclusion',
                    'media_type': 'application/json', 'json': {'summary': 'Retained conclusion content.'}}))
            return calls
        if self.step == 8:
            return [('corrected-finish', 'finish', draft(evidence=True))]
        raise AssertionError(self.step)

    def request(self, operation, body, *, operation_id):
        if operation == 'engine.model_generate':
            self.events.append((operation, deepcopy(body), operation_id))
            self.model_requests.append(deepcopy(body))
            self.model_turn += 1
            compacting = body['request'].get('tool_choice') == 'none'
            if compacting:
                self.compaction_requests.append(deepcopy(body))
                calls = None
            else:
                self.step += 1
                self.action_requests.append(deepcopy(body))
                calls = self.calls()
            result = self._model_result(self.model_turn, calls or [])
            if calls is None:
                choice = result['response']['choices'][0]
                choice['message'].pop('tool_calls')
                choice['message']['content'] = ('Summary deliberately omits correction and handles.' if compacting
                    else 'Would you like me to retrieve receipts, tickets, or notifications? Choose a task.')
                choice['finish_reason'] = 'stop'
            result['context_budget']['near_prompt_limit'] = self.compact and self.step == 4 and not compacting
            if result['context_budget']['near_prompt_limit']:
                result['context_budget'].update(input_tokens=26214, total_tokens=26234, remaining_prompt_tokens=6554)
                result['response']['usage'].update(prompt_tokens=26214, total_tokens=26234)
            if self.terminate == 'tokens' and self.step == 3:
                result['context_budget']['remaining_model_tokens'] = 30828
            return self._checked(operation, result)
        if operation == 'engine.finish' and 'assessment' in body and self.host_rejection and not self.rejected:
            self.rejected = True
            self.events.append((operation, deepcopy(body), operation_id))
            reply = Reply({})
            reply.error = dict(code='INVALID_ARGUMENTS', effect_state='none', disposition='correct-and-resubmit',
                message='Assessment evidence does not support this summary.', diagnostic=dict(
                    source='operator', stage='references', reason='assessment_evidence',
                    field_path='/assessment/objectives/0/summary', message='Revise the unsupported summary.',
                    correction='Describe only the retained evidence and unresolved effects.',
                    execution_occurred='no', resubmission_safe=True))
            return reply
        return super().request(operation, body, operation_id=operation_id)


class AssessmentRepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ['OPERATOR_CONTRACT_SOURCE']))

    def campaign(self, **options):
        host = RepairHost(self.protocol, **options)
        limits = dict(LIMITS, max_consecutive_invalid_tool_calls=5)
        loop = HarnessLoop(limits)
        inputs = RepairInputs()
        artifacts = ArtifactPublisher(self.protocol, host)
        observations = ObservationReader(host)
        attempts = AttemptExecutor(self.protocol, host, artifacts, {}, {}, loop)
        finalizer = ConclusionFinalizer(self.protocol, host, inputs, loop, artifacts,
            attempts=attempts, observations=observations, campaign_deadline_ms=100000,
            artifact_remaining=2 << 20, clock=Clock())
        handlers = FixedHandlers(self.protocol, inputs, host, loop, artifacts=artifacts,
            observations=observations, attempts=attempts, finalizer=finalizer)
        dispatcher = Dispatcher(self.protocol, loop, {}, raw_handlers=handlers.raw_handlers(), client=host)
        policy = dict(codec_id='openai-chat-text-tools-v1', profile_id='vertical-slice-profile',
            profile_digest='sha256:' + '9' * 64, request_model='fixture-model',
            response_models=['fixture-model-2026'], instruction_role='developer', prompt='Controlled test.',
            max_completion_tokens=4096, context_limits=dict(maximum_prompt_tokens=32768,
                maximum_completion_tokens=4096, warning_threshold_tokens=26214),
            tools=json.loads(self.protocol.model_tools('openai-chat-text-tools-v1', sorted(host.operations))))
        conversation = NativeConversation(self.protocol, _canonical_value(policy, 4 << 20),
            'Original objective-marker: establish observed effects, retaining uncertainty.', model_allowance=524288)
        result = AdaptiveHarness(self.protocol, host, loop, dispatcher, conversation, finalizer, limits=limits).run()
        return host, dispatcher, conversation, result, handlers

    def test_local_and_host_repair_survive_menu_block_exploration_and_finish(self):
        for host_rejection in (False, True):
            for same_batch in (False, True):
                with self.subTest(host_rejection=host_rejection, same_batch=same_batch):
                    host, dispatcher, conversation, result, handlers = self.campaign(
                        host_rejection=host_rejection, same_batch=same_batch)
                    self.assertEqual(result['assessment_state'], 'committed')
                    self.assertEqual(result['finalization_status'], 'pending')
                    self.assertEqual(len(host.attempt_ids), 1)
                    self.assertIsNone(dispatcher.repair)
                    for request in host.action_requests[2:]:
                        text = json.dumps(request)
                        self.assertIn('Assessment repair is active', text)
                        self.assertIn('Original objective-marker', text)
                        self.assertNotIn('Continue with the next useful tool action', text)
                        self.assertIn('rejected_arguments', text)
                    prompt_after_menu = host.action_requests[3]['request']['messages'][-1]['content']
                    self.assertIn('not a selection from any menu', prompt_after_menu)
                    self.assertIn('/objectives/0/summary' if host_rejection else '/objectives/0/attempts', prompt_after_menu)
                    self.assertIn('assessment_repair_active', json.dumps(host.action_requests[4]))
                    self.assertIn('/uncertainties/0/inputs/0', json.dumps(host.action_requests[7]))
                    assessment = json.loads(host.conclusion_raw)
                    self.assertEqual(assessment['objectives'][0]['outcome'], 'inconclusive')
                    self.assertEqual(assessment['uncertainties'][0]['description'], 'Internal effects were not observed.')
                    self.assertTrue(handlers.model_tools.resources['observation-1']['inspected'])

    def test_compaction_cannot_clear_repair_or_lose_submission_handles_and_objectives(self):
        host, dispatcher, conversation, result, handlers = self.campaign(compact=True)
        self.assertEqual(len(host.compaction_requests), 1)
        for request in [host.compaction_requests[0], host.action_requests[4]]:
            text = json.dumps(request)
            for required in ('rejected_arguments', '/objectives/0/attempts', 'execution-1',
                             'observation-1', 'Original objective-marker', 'Assessment repair is active'):
                self.assertIn(required, text)
        self.assertEqual(result['assessment_state'], 'committed')
        self.assertEqual(len(host.attempt_ids), 1)

    def test_only_reads_finish_and_conclusion_publication_are_permitted(self):
        for blocked in [('snapshot_request', {}), ('snapshot_list', {}),
                        ('snapshot_inspect', {'snapshot': 'unknown'}),
                        ('restore_request', {'snapshot': 'unknown'}),
                        ('injection_delete', {'injection': 'unknown'}),
                        ('record_append', {'kind': 'hypothesis'}),
                        ('artifact_publish', {'purpose': 'payload', 'media_type': 'text/plain', 'text': 'new input'})]:
            with self.subTest(tool=blocked[0]):
                host, _, _, result, _ = self.campaign(blocked=blocked, artifact=True)
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertIn('assessment_repair_active', json.dumps(host.action_requests[4]))
                uploads = [b for op, b, _ in host.events if op == 'engine.artifact_begin']
                self.assertEqual([u['purpose'] for u in uploads], ['conclusion'])
                self.assertFalse(any(op in ('engine.' + name for name in
                    ('snapshot_request', 'snapshot_list', 'snapshot_inspect', 'restore_request', 'injection_delete', 'record_append'))
                    for op, _, _ in host.events))

    def test_termination_separates_stopping_cause_and_unresolved_repair(self):
        for condition in ('invalid', 'tokens'):
            with self.subTest(condition=condition):
                host, dispatcher, conversation, result, _ = self.campaign(terminate=condition)
                self.assertEqual(result['assessment_state'], 'unavailable')
                self.assertEqual(len(host.attempt_ids), 1)
                reports = [b for op, b, _ in host.events if op == 'engine.diagnostic_report']
                self.assertEqual(reports[-2]['diagnostic']['reason'], 'finish_repair_unresolved')
                self.assertIn('field_path', reports[-2]['diagnostic'])
                self.assertNotIn('field_path', reports[-1]['diagnostic'])
                self.assertNotIn('tool_name', reports[-1])
                if condition == 'tokens':
                    self.assertEqual(reports[-1]['diagnostic']['reason'], 'model_reservation_unavailable')
                    self.assertEqual(reports[-1]['stopping']['budget'], dict(kind='model-tokens',
                        total_allowance=524288, consumed=493460, remaining=30828, next_request_reservation=36864))
                else:
                    self.assertEqual(reports[-1]['stopping'], dict(condition='invalid-call-limit',
                        observed_count=5, configured_limit=5))
                self.assertIsNotNone(dispatcher.repair)
                self.assertIn('rejected_arguments', json.dumps(conversation._request))

    def test_duplicate_arguments_and_repair_context_survive_every_native_codec(self):
        raw = b'{"finish_reason":"budget-limit","summary":"first","summary":"second","objectives":[]}'
        loop = HarnessLoop(LIMITS)
        dispatcher = Dispatcher(self.protocol, loop, {'finish': lambda _: self.fail('invalid finish dispatched')})
        loop.begin_model()
        dispatcher.dispatch([ToolCall('duplicate-finish', 'finish', raw)])
        self.assertEqual(dispatcher.repair.call.arguments, raw)
        self.assertEqual(dispatcher.repair.rejection['diagnostic']['field_path'], '/summary')
        source = Path(os.environ['OPERATOR_CONTRACT_SOURCE']) / 'fixtures'
        for filename in ('model-codec.json', 'responses-model-codec.json', 'anthropic-model-codec.json',
                         'bedrock-model-codec.json', 'gemini-model-codec.json'):
            with self.subTest(codec=filename):
                cases = json.loads((source / filename).read_text())
                case = next(c for c in cases if c['mode'] == 'context' and c['valid'])
                conversation = NativeConversation(self.protocol, _canonical_value(case['policy'], 4 << 20),
                                                  'Original campaign objectives.')
                conversation.set_repair(dispatcher.repair)
                conversation.prompt_again()
                _, body = conversation.body()
                self.assertIn(b'/summary', body)
                _, _, digest, _ = conversation.compaction_body()
                conversation.apply_compaction('Forget the rejected finish.', digest, 1)
                _, body = conversation.body()
                self.assertIn(b'Assessment repair is active', body)
                self.assertIn(b'Original campaign objectives.', body)
                self.assertEqual(conversation._repair.context()['rejected_arguments'].encode(), raw)


if __name__ == '__main__':
    unittest.main()
