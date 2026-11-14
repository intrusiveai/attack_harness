"""Controlled reserve admission, dispatch and no-model trimming workflows."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol, ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop
from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.artifacts import ArtifactPublisher
from attack_harness.attempts import AttemptExecutor
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.tools import Dispatcher, ToolCall
from test_simple_campaign import SimpleHost
from test_vertical_slice import Inputs, Clock, LIMITS
from test_instruction_boundary import CODECS, tool_segment
import test_instruction_boundary as boundary

R = 36864
ATTEMPT = dict(origin='exploratory', operation_id='invoke', json={'query': 'marker'})
FINISH = dict(finish_reason='budget-limit', summary='Incomplete investigation.',
    objectives=[dict(objective_id='objective-marker', outcome='not-tested', summary='Objective not established.')])


class BudgetHost(SimpleHost):
    def __init__(self, protocol, tokens, calls, steps):
        super().__init__(protocol, 'budget')
        self.tokens, self.calls, self.steps = tokens, calls, steps

    def _calls(self, turn):
        step = self.steps[turn - 1]
        return step.get('calls', [])

    def request(self, operation, body, *, operation_id):
        result = super().request(operation, body, operation_id=operation_id)
        if operation != 'engine.model_generate':
            return result
        step = self.steps[self.model_turn - 1]
        expected = 'compaction' if step.get('compaction') else 'generation'
        if body['purpose'] != expected:
            raise AssertionError('Unexpected model-based compaction/admission')
        prompt, completion = step.get('usage', (100, 20))
        self.tokens -= prompt + completion
        self.calls -= 1
        result.result['context_budget'].update(input_tokens=prompt, output_tokens=completion,
            total_tokens=prompt + completion, remaining_prompt_tokens=32768 - prompt,
            near_prompt_limit=prompt >= 26214, remaining_model_tokens=self.tokens, remaining_model_turns=self.calls)
        result.result['response']['usage'].update(prompt_tokens=prompt, completion_tokens=completion,
                                                total_tokens=prompt + completion)
        if 'text' in step:
            choice = result.result['response']['choices'][0]
            choice['message'].pop('tool_calls')
            choice['message']['content'] = step['text']
            choice['finish_reason'] = 'stop'
        return result


class FinalizationCapacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ['OPERATOR_CONTRACT_SOURCE']))

    def run_campaign(self, tokens, calls, steps, *, seed=None, max_calls=20, task='Original objective-marker.'):
        host = BudgetHost(self.protocol, tokens, calls, steps)
        limits = dict(LIMITS, max_model_turns=max_calls, max_consecutive_invalid_tool_calls=5)
        loop = HarnessLoop(limits)
        artifacts = ArtifactPublisher(self.protocol, host)
        inputs = Inputs({})
        observations = ObservationReader(host)
        attempts = AttemptExecutor(self.protocol, host, artifacts, {}, {}, loop)
        finalizer = ConclusionFinalizer(self.protocol, host, inputs, loop, artifacts,
            attempts=attempts, observations=observations, campaign_deadline_ms=100000,
            artifact_remaining=2 << 20, clock=Clock())
        handlers = FixedHandlers(self.protocol, inputs, host, loop, artifacts=artifacts,
            observations=observations, attempts=attempts, finalizer=finalizer)
        dispatcher = Dispatcher(self.protocol, loop, {}, raw_handlers=handlers.raw_handlers(), client=host)
        policy = dict(codec_id='openai-chat-text-tools-v1', profile_id='vertical-slice-profile',
            profile_digest='sha256:'+'9'*64, request_model='fixture-model', response_models=['fixture-model-2026'],
            instruction_role='developer', prompt='Controlled finalization test.', max_completion_tokens=4096,
            context_limits=dict(maximum_prompt_tokens=32768, maximum_completion_tokens=4096, warning_threshold_tokens=26214),
            tools=json.loads(self.protocol.model_tools('openai-chat-text-tools-v1', sorted(host.operations))))
        conversation = NativeConversation(self.protocol, _canonical_value(policy, 4 << 20), task,
            remaining=dict(model_tokens=tokens, model_turns=calls), model_allowance=524288)
        if seed:
            seed(conversation)
        result = AdaptiveHarness(self.protocol, host, loop, dispatcher, conversation, finalizer, limits=limits).run()
        return host, dispatcher, conversation, result, loop

    def test_exact_token_and_call_boundaries_and_sticky_dispatch_restriction(self):
        for tokens, calls, executed in ((3*R, 3, 1), (3*R-1, 3, 0), (4*R, 2, 0), (4*R, 3, 1)):
            with self.subTest(tokens=tokens, calls=calls):
                host, dispatcher, c, result, loop = self.run_campaign(tokens, calls, [
                    dict(calls=[('attempt', 'attempt_execute', ATTEMPT)]),
                    dict(calls=[('finish', 'finish', FINISH)]),
                ])
                self.assertEqual(len(host.attempt_ids), executed)
                self.assertEqual(result['assessment_state'], 'committed')
                first = json.dumps(host.model_requests[0])
                self.assertEqual('exploration has ended' in first, not executed)
                self.assertIn('exploration has ended', json.dumps(host.model_requests[1]))
                self.assertTrue(dispatcher.protected_finalization)
                self.assertIsNone(dispatcher.repair)  # Budget pressure is not a rejected finish.
                transitions = [b for op,b,_ in host.events if op=='engine.diagnostic_report'
                    and b['diagnostic']['reason']=='finalization_capacity_protected']
                self.assertEqual(len(transitions), 1)
                self.assertNotIn('stopping', transitions[0])
                self.assertEqual(c._remaining['model_tokens'], tokens-240)  # No reserve double-charge.
                self.assertEqual(loop.snapshot()['model_turns'], 2)

    def test_harness_local_call_limit_also_protects_first_request(self):
        host, _, _, result, _ = self.run_campaign(4*R, 20, [dict(calls=[('finish','finish',FINISH)])], max_calls=2)
        self.assertIn('exploration has ended', json.dumps(host.model_requests[0]))
        self.assertEqual(result['assessment_state'], 'committed')

    def test_protected_requests_allow_rejected_finish_then_correction_at_last_reservation(self):
        def seed(c):
            c.extend(_canonical_value([{'role':'assistant','content':'Older discussion. '*500}], 4<<20))
        host, dispatcher, c, result, loop = self.run_campaign(R+120, 2, [
            dict(calls=[('bad','finish',dict(FINISH, observations=[]))]),
            dict(calls=[('fixed','finish',FINISH)]),
        ], seed=seed)
        self.assertEqual(result['assessment_state'], 'committed')
        self.assertEqual(len(host.model_requests), 2)
        self.assertEqual(len(host.attempt_ids), 0)
        self.assertIn('Your finish submission was rejected', json.dumps(host.model_requests[1]))
        self.assertIn('Unsupported fields', json.dumps(host.model_requests[1]))
        self.assertIn('unsupported_fields', json.dumps(host.model_requests[1]))
        self.assertIsNone(dispatcher.repair)
        self.assertEqual(c._remaining['model_tokens'], R-120)

    def test_archived_allowance_trims_locally_instead_of_spending_last_request_on_summary(self):
        def seed(c):
            c.extend(_canonical_value([{'role':'assistant','content':'Historical observation. '*10000}], 4<<20))
        host, _, c, result, loop = self.run_campaign(38615, 20,
            [dict(calls=[('finish','finish',FINISH)])], seed=seed)
        self.assertEqual(len(host.model_requests), 1)
        self.assertEqual(result['assessment_state'], 'committed')
        request = json.dumps(host.model_requests[0])
        self.assertIn('harness-local-checkpoint', request)
        self.assertIn('Original objective-marker', request)
        self.assertIn('exploration has ended', request)
        self.assertEqual(c._local_omissions, 1)
        self.assertEqual(loop.snapshot()['model_turns'], 1)
        self.assertEqual(c._remaining['model_tokens'], 38495)

    def test_local_reduction_does_not_spend_a_funded_model_call(self):
        def seed(c):
            c.extend(_canonical_value([{'role':'assistant','content':'Old history. '*800}], 4<<20))
            c._compact_at = 1
        host, _, c, result, loop = self.run_campaign(3*R, 3, [
            dict(calls=[('finish','finish',FINISH)]),
        ], seed=seed)
        self.assertEqual([r['purpose'] for r in host.model_requests], ['generation'])
        self.assertEqual(result['assessment_state'], 'committed')
        self.assertEqual(loop.snapshot()['model_turns'], 1)
        self.assertEqual(c._remaining['model_tokens'], 3*R-120)

    def test_insufficient_allowance_and_irreducible_context_have_distinct_truthful_results(self):
        for tokens, calls, task, reason in ((R-1,20,'Task.','model_reservation_unavailable'),
                (2*R,0,'Task.','model_call_limit'), (2*R,2,'Mandatory task.'*100000,'context_limit')):
            with self.subTest(reason=reason):
                host, _, c, result, loop = self.run_campaign(tokens,calls,[],task=task)
                self.assertEqual(len(host.model_requests), 0)
                self.assertEqual(result['assessment_state'], 'unavailable')
                reports = [b for op,b,_ in host.events if op=='engine.diagnostic_report']
                self.assertEqual(reports[0]['diagnostic']['reason'], 'finalization_capacity_protected')
                self.assertEqual(reports[-1]['diagnostic']['reason'], reason)
                if reason=='context_limit':
                    self.assertEqual(host.events[-1][1]['finish_reason'], 'context-limit')
                self.assertEqual(loop.snapshot()['model_turns'], 0)
        host, _, _, result, _ = self.run_campaign(R, 1, [dict(calls=[('finish','finish',FINISH)])])
        self.assertEqual(result['assessment_state'], 'committed')
        self.assertEqual(len(host.model_requests), 1)

    def test_local_trim_preserves_repair_original_task_and_verified_handles_across_codecs(self):
        fixture = boundary.InstructionBoundaryTest()
        fixture.protocol, fixture.root = self.protocol, Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, inputs = fixture.campaign(filename)
                a = campaign.adaptive; c = a.conversation
                from attack_harness.composition import build_task
                c.replace_task(build_task(inputs, active_scenario='baseline'))
                original, privileged = c.task, deepcopy(c.policy)
                c.delivered_task_generation=c.task_generation
                a.loop.begin_model()
                results=a.dispatcher.dispatch([
                    ToolCall('invoke','attempt_execute',json.dumps(dict(ATTEMPT,origin='scenario',scenario_id='baseline')).encode()),
                    ToolCall('read','observation_read',b'{"observation":"observation-1"}'),
                    ToolCall('bad','finish',b'{"summary":"keep valid parts","objectives":[]}'),
                ])
                c.set_repair(a.dispatcher.repair)
                raw='Older optional proposals. '*10000
                if c.codec=='gemini-text-tools-v1':group=[{'role':'model','parts':[{'text':raw}]}]
                elif c.codec=='bedrock-converse-text-tools-v1':group=[{'role':'assistant','content':[{'text':raw}]}]
                else:group=[{'role':'assistant','content':raw}]
                c.extend(_canonical_value(group,4<<20))
                c.extend(_canonical_value(tool_segment(c.codec,results[1].content),4<<20))
                c._remaining=dict(model_tokens=2*c.model_reservation(),model_turns=2)
                c.prepare_finalization();a.dispatcher.protect_finalization()
                before=c._remaining.copy();counter=a.loop.snapshot()
                resources=deepcopy(campaign.handlers.model_tools.resources)
                c.trim_for_finalization()
                body,_=c.body();text=json.dumps(body)
                self.assertIn('harness-local-checkpoint',text)
                self.assertIn('keep valid parts',text)
                self.assertIn('Your finish submission was rejected',text)
                self.assertIn('observation-1',text)
                self.assertNotIn('execution-from-target-prose',json.dumps(c._compaction_ledger))
                self.assertEqual(json.loads(c.task)["campaign"], json.loads(original)["campaign"])
                self.assertIsNone(json.loads(c.task)["active_scenario"])
                self.assertIn("campaign_activity", text)
                self.assertEqual(c.policy,privileged)
                self.assertEqual(c._remaining,before);self.assertEqual(a.loop.snapshot(),counter)
                self.assertEqual(campaign.handlers.model_tools.resources,resources)
                self.assertFalse(any(op=='engine.model_generate' for op,_,_ in host.events))
                a.loop.begin_model()
                blocked=a.dispatcher.dispatch([ToolCall('new','attempt_execute',json.dumps(ATTEMPT).encode())])[0]
                self.assertIn('assessment_repair_active',blocked.content)
                self.assertEqual(len(host.attempt_ids),1)
                with self.assertRaises(ContractError):c.compaction_body()


if __name__=='__main__':unittest.main()
