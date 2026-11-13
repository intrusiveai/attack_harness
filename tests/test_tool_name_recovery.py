"""Controlled native recovery of malformed tool names; no live provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import Protocol
from attack_harness.composition import compose_campaign
from scenario_loading_fixture import LoadingHost, loading_bundle
from test_instruction_boundary import CODECS
from test_scenario_delivery import ScenarioInputs
from test_vertical_slice import Clock, LIMITS, Reply


# Native toolUse from archived event 73, campaign 6564adc53ce498970bd94cfe3eac7170.
ARCHIVED_CALL = {
    'name': 'attempt_execute(', 'toolUseId': 'tooluse_UdSTRqzXolflmIhnYbPLnd',
    'input': {'origin': 'scenario', 'scenario_id': 'support-baseline', 'operation_id': 'invoke',
        'rationale': 'Initiate the support-baseline scenario by sending a basic customer-support message to confirm that the lookup, retrieval, and web tools return useful results as described in the scenario instructions.',
        'media_type': 'application/json',
        'json': {'message': 'Test message to verify baseline functionality of support tools.'},
        'observations': ['target_output', 'oracle_outcome']}}


class NameRecoveryHost(LoadingHost):
    def __init__(self, protocol, *, exhausted=False):
        super().__init__(protocol)
        self.exhausted = exhausted
        self.dispatched_at_request = []

    def _calls(self, turn):
        self.dispatched_at_request.append(len(self.attempt_ids))
        task = self._task()
        if task['active_scenario'] is None:
            return [('select', 'reference_read', {'reference': task['scenario_index'][0]['reference_id']})]
        self.step += 1
        if self.step == 1 or self.exhausted:
            return [(ARCHIVED_CALL['toolUseId'] + (str(self.step) if self.exhausted else ''),
                     ARCHIVED_CALL['name'], deepcopy(ARCHIVED_CALL['input']))]
        if self.step == 2:
            return [('corrected', 'attempt_execute', deepcopy(ARCHIVED_CALL['input']))]
        if self.step == 3:
            return [('read', 'observation_read', {'observation': 'observation-1'})]
        return [('finish', 'finish', {'finish_reason': 'no-useful-next-experiment',
            'summary': 'One invocation inspected; remaining requirements untested.',
            'objectives': [{'objective_id': 'support', 'outcome': 'inconclusive',
                           'summary': 'Only baseline output inspected.', 'observations': ['observation-1']}]})]

    def request(self, operation, body, *, operation_id):
        if operation == 'engine.diagnostic_report':
            self.protocol._catalog.validate_value('urn:operator:schema:engine-diagnostic-report-request:v1alpha1', body)
        if operation == 'engine.finish' and 'unavailable' in body:
            self.events.append((operation, deepcopy(body), operation_id))
            return Reply({'status': 'accepted', 'stop_receipt': 'stop-1', 'execution_admission': 'closed',
                'assessment_state': 'unavailable', 'exit_required': True, 'exit_within_ms': 5000,
                'finalization_status': 'pending'})
        return super().request(operation, body, operation_id=operation_id)


class ToolNameRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def campaign(self, codec, *, exhausted=False):
        host = NameRecoveryHost(self.protocol, exhausted=exhausted)
        bundle = loading_bundle()
        bundle['scenarios'][0]['scenario_id'] = 'support-baseline'
        inputs = ScenarioInputs(self.protocol, self.root, bundle, host, codec)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            'limits': {'harness': dict(LIMITS, max_model_turns=30, max_consecutive_invalid_tool_calls=5),
                       'campaign': {'model_tokens': 1000000}},
            'remaining_limits': {'campaign_time_ms': 100000, 'artifact_bytes': 2 << 20}})
        campaign = compose_campaign(self.protocol, session, clock=Clock())
        host.conversation = campaign.adaptive.conversation
        return campaign, host

    def test_archived_name_then_corrected_execution_evidence_and_finish(self):
        for codec in CODECS:
            with self.subTest(codec=codec):
                campaign, host = self.campaign(codec)
                result = campaign.run()
                self.assertEqual(host.dispatched_at_request, [0, 0, 0, 1, 1])
                self.assertEqual(len(host.attempt_ids), 1)
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertTrue(result['exit_required'])
                self.assertEqual(result['finalization_status'], 'pending')
                self.assertEqual(campaign.adaptive.loop.snapshot()['invalid_tool_calls'], 1)
                request = host.model_requests[2]
                outputs = [json.loads(c[k]) for c, k in host.conversation._tool_outputs(request['conversation'][1:])]
                error = next(v for v in outputs if v.get('diagnostic', {}).get('reason') == 'invalid_tool_name')
                self.assertIn('attempt_execute(', error['diagnostic']['message'])
                self.assertEqual(error['diagnostic']['field_path'], '/name')
                self.assertEqual(error['effect_state'], 'none')
                self.assertIn('exact name', error['diagnostic']['correction'])
                expected = json.loads(self.protocol.model_tools('openai-chat-text-tools-v1', sorted(host.operations)))
                self.assertEqual({t['name'] for t in error['available_tools']}, {t['function']['name'] for t in expected})
                self.assertTrue(all(t['purpose'] for t in error['available_tools']))
                report = next(b for op, b, _ in host.events if op == 'engine.diagnostic_report' and b['diagnostic']['reason'] == 'invalid_tool_name')
                self.assertEqual(report['diagnostic']['execution_occurred'], 'no')
                if codec != 'gemini-model-codec.json':
                    self.assertEqual(report['tool_call_id'], ARCHIVED_CALL['toolUseId'])
                    self.assertIn(ARCHIVED_CALL['toolUseId'], json.dumps(request))

    def test_invalid_names_exhaust_limit_and_finish_unavailable_without_dispatch(self):
        campaign, host = self.campaign('bedrock-model-codec.json', exhausted=True)
        result = campaign.run()
        self.assertEqual(len(host.attempt_ids), 0)
        self.assertEqual(result['assessment_state'], 'unavailable')
        state = campaign.adaptive.loop.snapshot()
        self.assertEqual(state['invalid_tool_calls'], 5)
        self.assertEqual(state['tool_calls'], 6)  # Scenario selection plus five rejections.
        reports = [b for op, b, _ in host.events if op == 'engine.diagnostic_report']
        self.assertEqual(sum(r['diagnostic']['reason'] == 'invalid_tool_name' for r in reports), 5)
        self.assertEqual(reports[-1]['stopping']['condition'], 'invalid-call-limit')
        self.assertEqual(reports[-1]['stopping']['observed_count'], 5)
        self.assertEqual(reports[-1]['stopping']['configured_limit'], 5)


if __name__ == '__main__':
    unittest.main()
