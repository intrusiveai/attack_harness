"""Append-only native prefixes and deterministic checkpoints; no live provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from attack_harness.composition import compose_campaign
from attack_harness.runtime import RuntimeStopped
from scenario_loading_fixture import LoadingHost, loading_bundle
from test_scenario_delivery import ScenarioInputs
from test_instruction_boundary import CODECS
from test_vertical_slice import Clock, LIMITS


class PrefixHost(LoadingHost):
    """A controlled provider rejecting a retained native response on a changed prefix."""
    def __init__(self, protocol):
        super().__init__(protocol)
        self.bound = []
        self.checked_prefixes = 0
        self.checkpoint_ids = []
        self.same_batch = True
        self.trim = True

    def fail(self, reason, *, receipt=None, cause=None):
        raise RuntimeStopped(reason, receipt=receipt) from cause

    def request(self, operation, body, *, operation_id):
        if operation == 'engine.model_generate':
            history = body['conversation']
            if self.bound and self.checkpoint_ids[-1] == self.conversation._checkpoint_number:
                prefix, assistant = self.bound[-1]
                if history[:len(prefix) + len(assistant)] != prefix + assistant:
                    raise AssertionError('Native response or its preceding messages changed')
            for prefix, assistant in self.bound:
                if any(item == assistant[0] for item in history):
                    expected = prefix + assistant
                    if history[:len(expected)] != expected:
                        raise AssertionError('Retained native response is bound to a different conversation')
                    self.checked_prefixes += 1
            self.checkpoint_ids.append(self.conversation._checkpoint_number)
        return super().request(operation, body, operation_id=operation_id)

    def _calls(self, turn):
        calls = super()._calls(turn)
        if any(c[1] == 'observation_read' for c in calls) and self.step in (3, 6):
            # Reproduce the archive: an observation changes inspection state,
            # followed by another model request before switching scenarios.
            calls = [c for c in calls if c[1] != 'reference_read']
        return calls

    def _model_result(self, turn, calls):
        result = super()._model_result(turn, calls)
        response = result['response']
        # Opaque fixture blocks exercise preservation, not real signature verification.
        if self.codec == 'anthropic-messages-text-tools-v1':
            response['content'].insert(0, dict(type='thinking', thinking='Controlled private reasoning.', signature=f'opaque-{turn}'))
            assistant = [dict(role='assistant', content=deepcopy(response['content']))]
        elif self.codec == 'bedrock-converse-text-tools-v1':
            response['output']['message']['content'].insert(0, dict(reasoningContent=dict(reasoningText=dict(text='Controlled reasoning.', signature=f'opaque-{turn}'))))
            assistant = [deepcopy(response['output']['message'])]
        elif self.codec == 'openai-responses-text-tools-v1':
            response['output'].insert(0, dict(type='reasoning', id=f'rs-{turn}', summary=[], encrypted_content=f'opaque-{turn}'))
            assistant = deepcopy(response['output'])
        elif self.codec == 'gemini-text-tools-v1':
            response['candidates'][0]['content']['parts'].insert(0, dict(text='Controlled reasoning.', thought=True, thoughtSignature=f'opaque-{turn}'))
            assistant = [deepcopy(response['candidates'][0]['content'])]
        else:
            assistant = [deepcopy(response['choices'][0]['message'])]
        self.bound.append((deepcopy(self.model_requests[-1]['conversation']), assistant))
        return result


class ConversationCheckpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def campaign(self, filename):
        host = PrefixHost(self.protocol)
        inputs = ScenarioInputs(self.protocol, self.root, loading_bundle(), host, filename)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            'limits': {'harness': dict(LIMITS, max_model_turns=30), 'campaign': {'model_tokens':1000000}},
            'remaining_limits': {'campaign_time_ms':100000, 'artifact_bytes':2 << 20}})
        campaign = compose_campaign(self.protocol, session, clock=Clock())
        host.conversation = campaign.adaptive.conversation
        return campaign, host, inputs

    def test_signed_prefixes_scenario_switches_restore_and_repair_across_codecs(self):
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, inputs = self.campaign(filename)
                result = campaign.run()
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertGreater(host.checked_prefixes, 3)
                self.assertGreater(len(set(host.checkpoint_ids)), 3)
                self.assertEqual(len(host.attempt_ids), 2)
                self.assertEqual(host.reads, 4)
                self.assertEqual(host.run_revision, 2)
                self.assertEqual(campaign.adaptive.loop.snapshot()['model_turns'], len(host.model_requests))
                self.assertTrue(all(r['purpose'] == 'generation' for r in host.model_requests))
                for previous, current, old_id, new_id in zip(host.model_requests, host.model_requests[1:], host.checkpoint_ids, host.checkpoint_ids[1:]):
                    if old_id == new_id:
                        self.assertEqual(current['conversation'][:len(previous['conversation'])], previous['conversation'])
                    else:
                        self.assertEqual(len(current['conversation']), 1)
                        self.assertNotIn('opaque-', json.dumps(current))
                tasks = [host.task_from_request(r) for r in host.model_requests]
                assessment = next(t for t in tasks if 'assessment_scope' in t)
                self.assertIsNone(assessment['active_scenario'])
                self.assertEqual(len(assessment['scenario_index']), 4)
                self.assertEqual(assessment['campaign']['objectives'], inputs.bundle()['objectives'])
                self.assertEqual({a['execution'] for a in assessment['campaign_activity'] if 'execution' in a}, {'execution-1','execution-2'})
                self.assertTrue(any('scenario_context_required' in json.dumps(r) for r in host.model_requests))
                self.assertTrue(any('assessment_repair_active' in json.dumps(r) for r in host.model_requests))
                self.assertEqual(len(json.loads(host.conclusion_raw)['objectives'][0]['attempt_receipt_refs']), 2)

    def test_task_changes_wait_for_the_complete_native_batch(self):
        campaign, host, inputs = self.campaign('anthropic-model-codec.json')
        c = campaign.adaptive.conversation
        body, _ = c.body()
        c.submitted(body)
        old = deepcopy(c._request)
        from attack_harness.composition import build_task
        c.replace_task(build_task(inputs, active_scenario='baseline'))
        self.assertEqual(c._request, old)
        with self.assertRaises(ContractError):
            c.body()  # Cannot discard an unresolved response/tool-result batch.
        c.extend(_canonical_value([dict(role='assistant', content=[dict(type='text', text='Selection completed.')])], 4 << 20))
        fresh, _ = c.body()
        self.assertEqual(len(fresh['conversation']), 1)
        self.assertEqual(host.task_from_request(fresh)['active_scenario'], inputs.bundle()['scenarios'][0])
        self.assertEqual(body['conversation'], old['messages'])

    def test_budget_notice_after_repair_renews_context_without_resetting_repair(self):
        campaign, host, _ = self.campaign('anthropic-model-codec.json')
        c = campaign.adaptive.conversation
        from attack_harness.tools import AssessmentRepair, ToolCall
        repair = AssessmentRepair(ToolCall('bad', 'finish', b'{"summary":"first","summary":"again"}'),
            {'diagnostic': {'reason':'duplicate_key', 'field_path':'/summary', 'correction':'Use each key once.'}})
        c.set_repair(repair)
        previous, _ = c.body()
        self.assertNotIn('Harness budget notice', json.dumps(previous))
        c._remaining = dict(model_tokens=2*c.model_reservation(), model_turns=2)
        c.prepare_finalization()
        fresh, _ = c.body()
        self.assertIn('Harness budget notice', json.dumps(fresh))
        self.assertIn('Your finish submission was rejected', json.dumps(fresh))
        self.assertEqual(host.task_from_request(fresh)['assessment_repair'], repair.context())
        self.assertNotIn('Harness budget notice', json.dumps(previous))
        self.assertEqual(c._remaining['model_turns'], 2)

    def test_accidental_prefix_or_policy_mutation_stops_before_another_provider_call(self):
        for change in ('message', 'policy', 'raw-policy'):
            with self.subTest(change=change):
                campaign, host, _ = self.campaign('anthropic-model-codec.json')
                c = campaign.adaptive.conversation
                c.body()
                if change == 'message':
                    c._request['messages'][0]['content'] += 'Changed task.'
                elif change == 'policy':
                    c.policy['request_model'] = 'different-model'
                else:
                    c.policy_raw += b' '
                with self.assertRaises(RuntimeStopped) as caught:
                    campaign.run()
                self.assertEqual(caught.exception.__cause__.reason, 'conversation_prefix_changed')
                self.assertEqual(len(host.model_requests), 0)
