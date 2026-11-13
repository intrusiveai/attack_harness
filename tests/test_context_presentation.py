"""Presentation reductions preserve requirements and never reinterpret target data."""
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from attack_harness.composition import build_task
from test_scenario_delivery import ScenarioHost, ScenarioInputs, support_bundle


class ContextPresentationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def test_task_uses_real_input_shape_and_complete_requirements(self):
        inputs = ScenarioInputs(self.protocol, self.root, support_bundle(), ScenarioHost(self.protocol))
        operation = inputs._context['target']['capabilities']['operations'][0]
        # Regression: the target's input name, not a hardcoded configuration example.
        shape = operation['delivery']['input']['schema']
        shape['properties'] = {'message': {'type': 'string', 'minLength': 1}}
        shape['required'] = ['message']
        from operator_contracts.canonical import _canonical_value
        from operator_contracts.target_context import compact_target_context
        _, inputs.details = compact_target_context(self.protocol, _canonical_value(inputs._context['target'], 4 << 20))
        initial = json.loads(build_task(inputs))
        task = json.loads(build_task(inputs, active_scenario='baseline'))
        self.assertIsNone(initial['active_scenario'])
        self.assertEqual(task['active_scenario'], inputs.bundle()['scenarios'][0])
        for key in ('objectives', 'coverage', 'evidence', 'context'):
            self.assertEqual(task['campaign'][key], inputs.bundle()[key])
        self.assertEqual(len(task['scenario_index']), 4)
        self.assertEqual(task['target']['operations'][0]['input']['schema'], shape)
        self.assertTrue(task['target']['resources'])  # Later work stays discoverable.
        for resource in task['target']['resources']:
            self.assertTrue(inputs.entry(resource['details_reference'])[1])
        for field in ('campaign_id','launch_id','run_revision','context_limits','remaining_limits',
                      'size_limits','operation_timeouts_ms','producer','schema_version','capability_projection_digest'):
            self.assertNotIn('"'+field+'":', json.dumps(task))
        for field in ('portfolio','scenario_references','scenario_delivery_state','context_delivery',
                      'execution_records','reference_handles','shared_tool_guidance'):
            self.assertNotIn(field, task)
        self.assertNotIn('engine.', json.dumps(task))
        self.assertNotIn('QA_CONFIG_OK', inputs.prompt_raw.decode())
        self.assertLess(len(inputs.prompt_raw), 2000)
        self.assertEqual(initial['scenario_index'], task['scenario_index'])

    def test_discovered_endpoints_keep_shared_references_and_exact_selector_details(self):
        fixture = next(f for f in json.loads((self.root / 'fixtures/compact-target-context.json').read_text())
                       if f['name'] == 'discoverable-injection-targets')
        inputs = ScenarioInputs(self.protocol, self.root, support_bundle(), ScenarioHost(self.protocol))
        inputs._context['target'] = fixture['target']
        from operator_contracts.canonical import _canonical_value
        from operator_contracts.target_context import compact_target_context
        raw, inputs.details = compact_target_context(self.protocol, _canonical_value(fixture['target'], 4 << 20))
        shared_services = json.loads(raw)['capabilities']['services']
        task = json.loads(build_task(inputs))
        kinds = set()
        for service in shared_services:
            presented = next(r for r in task['target']['resources'] if r.get('service_id') == service['service_id'])
            self.assertEqual(presented.get('endpoints'), service.get('endpoints'))
            for endpoint in presented.get('endpoints', []):
                kinds.add(endpoint['kind'])
                _, content = inputs.entry(endpoint['details_reference'])
                detail = json.loads(content)
                original = next(s for s in fixture['target']['capabilities']['services'] if s['service_id'] == service['service_id'])
                self.assertEqual(detail['resource'], next(e for e in original['endpoints'] if e['id'] == endpoint['id']))
                self.assertEqual(detail['service_id'], service['service_id'])
                # Selector facts stay in the verified reference, not every task.
                for field in ('methods', 'paths', 'keys', 'mutable_fields', 'delivery'):
                    self.assertNotIn(field, endpoint)
        self.assertTrue({'http-route-set', 'state-collection'} <= kinds)


if __name__ == '__main__':
    unittest.main()
