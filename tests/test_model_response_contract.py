"""Shared model-response fixtures through controlled native Harness conversations."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.model_tools import tool_guidance
from operator_contracts.target_context import compact_target_context
from attack_harness.composition import build_task, compose_campaign
from scenario_loading_fixture import LoadingHost, loading_bundle
from test_instruction_boundary import CODECS
from test_scenario_delivery import ScenarioInputs
from test_vertical_slice import Clock, LIMITS


class ModelResponseHost(LoadingHost):
    def __init__(self, protocol):
        super().__init__(protocol)
        self.operations |= {'engine.injection_delete'}

    def _calls(self, turn):
        task = self._task()
        if task['active_scenario'] is None:
            return [('select', 'reference_read', {'reference': task['scenario_index'][0]['reference_id']})]
        self.step += 1
        if self.step in (1, 2):
            args = deepcopy(self.invalid if self.step == 1 else self.valid)
            args['scenario_id'] = task['active_scenario']['scenario_id']
            return [('invoke-' + str(self.step), 'attempt_execute', args)]
        if self.step == 3:
            return [('read', 'observation_read', {'observation': 'observation-1'})]
        return [('finish', 'finish', dict(finish_reason='no-useful-next-experiment',
            summary='Target output inspected; downstream acceptance remains unverified.',
            objectives=[dict(objective_id='support', outcome='inconclusive',
                             summary='No independent proof of downstream tool execution.', observations=['observation-1'])]))]


class ModelResponseContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)
        cls.fixtures = json.loads((cls.root / 'fixtures/tool-normalization.json').read_text())
        cls.target = next(c['target'] for c in json.loads((cls.root / 'fixtures/compact-target-context.json').read_text())
                          if c['name'] == 'model-response-injection')

    def inputs(self, host, codec):
        inputs = ScenarioInputs(self.protocol, self.root, loading_bundle(), host, codec)
        inputs._context['target'] = deepcopy(self.target)
        inputs._context['model']['tool_selection']['injection_surfaces'] = ['model_response']
        _, inputs.details = compact_target_context(self.protocol, _canonical_value(self.target, 4 << 20))
        inputs.context_raw = _canonical_value(inputs._context, 4 << 20)
        self.protocol.validate_engine_context(inputs.context_raw)
        return inputs

    def test_selected_capability_and_deferred_guidance_come_from_shared_contract(self):
        inputs = self.inputs(ModelResponseHost(self.protocol), 'model-codec.json')
        action = next(a for a in self.target['capabilities']['actions'] if a['surface'] == 'model_response')
        task = json.loads(build_task(inputs))
        self.assertEqual(task['target']['model_response'], {k: action[k] for k in ('model_codecs', 'placement_root')})
        guidance = json.loads(tool_guidance(self.protocol, 'attempt_execute'))['examples']['model_response_setup']
        self.assertIn('not Harness responses', guidance)
        self.assertIn('response_written', guidance)
        self.assertNotIn(guidance, json.dumps(task))  # Deferred, not recurring prompt text.
        inputs._context['model']['tool_selection']['injection_surfaces'] = []
        self.assertNotIn('model_response', json.loads(build_task(inputs))['target'])

    def test_corrected_injection_observation_and_finish_across_native_codecs(self):
        valid = next(f for f in self.fixtures if f['name'] == 'model response openai_responses')
        invalid = next(f for f in self.fixtures if f['name'] == 'model response missing codec openai_responses')
        for codec in CODECS:
            with self.subTest(codec=codec):
                host = ModelResponseHost(self.protocol)
                host.valid, host.invalid = valid['arguments'], invalid['arguments']
                inputs = self.inputs(host, codec)
                session = SimpleNamespace(inputs=inputs, client=host, admission={
                    'limits': {'harness': dict(LIMITS, max_model_turns=30), 'campaign': {'model_tokens': 1000000}},
                    'remaining_limits': {'campaign_time_ms': 100000, 'artifact_bytes': 2 << 20}})
                campaign = compose_campaign(self.protocol, session, clock=Clock())
                host.conversation = campaign.adaptive.conversation
                result = campaign.run()
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertTrue(result['exit_required'])
                self.assertEqual(result['finalization_status'], 'pending')
                self.assertEqual(len(host.attempt_ids), 1)
                self.assertEqual(len(host.model_requests), 5)
                sent = next(b for op, b, _ in host.events if op == 'engine.attempt_execute')
                self.assertEqual(sent['pre_actions'][0]['parameters'], valid['expected']['arguments']['pre_actions'][0]['parameters'])
                self.assertEqual(sent['injection_input'], valid['expected']['arguments']['injection_input'])
                self.assertEqual(sent['injection_input']['value']['tool_calls'][0]['arguments'], '{invalid')
                feedback = [json.loads(c[k]) for c, k in host.conversation._tool_outputs(host.model_requests[2]['conversation'][1:])]
                error = next(v['diagnostic'] for v in feedback if 'diagnostic' in v)
                self.assertEqual(error['reason'], invalid['reason'])
                self.assertEqual(error['field_path'], invalid['path'])
                self.assertEqual(error['correction'], invalid['correction'])
                self.assertIn('first observed result', json.dumps(host.model_requests[-1]))
                self.assertEqual(json.loads(host.conclusion_raw)['objectives'][0]['outcome'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
