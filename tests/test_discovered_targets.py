"""Controlled native conversations using Operator's discovery fixture, not live targets."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.target_context import compact_target_context
from attack_harness.composition import compose_campaign
from scenario_loading_fixture import LoadingHost, loading_bundle
from test_instruction_boundary import CODECS
from test_scenario_delivery import ScenarioInputs
from test_vertical_slice import Clock, LIMITS


class DiscoveryInputs(ScenarioInputs):
    def reference_index(self):
        return super().reference_index() + [dict(self.entry(h)[0], role='reference') for h in self.details]


class DiscoveryHost(LoadingHost):
    def _calls(self, turn):
        task = self._task()
        if task['active_scenario'] is None:
            return [('select', 'reference_read', {'reference': task['scenario_index'][0]['reference_id']})]
        self.step += 1
        if self.step == 1:
            service = next(s for s in task['target']['resources'] if s.get('service_id') == 'idp')
            endpoint = next(e for e in service['endpoints'] if e['collection'] == 'grants')
            return [('details', 'reference_read', {'reference': endpoint['details_reference'], 'max_bytes': 8192})]
        if self.step in (2, 3):
            if self.step == 2:
                outputs = [json.loads(container[key]) for container, key in
                           self.conversation._tool_outputs(self.model_requests[-1]['conversation'][1:])]
                read = next(v for v in outputs if 'content' in v)
                detail = json.loads(read['content'])
                self.record_key = detail['resource']['keys'][0]
            return [('execute-' + str(self.step), 'attempt_execute', dict(origin='scenario',
                scenario_id=task['active_scenario']['scenario_id'], operation_id='invoke', json={'query': 'bounded test'},
                setup=[dict(surface='environment_state', mode='fidelity', scope='once',
                    selector=dict(service='idp', collection='grants', key={'id': self.record_key} if self.step == 2 else self.record_key),
                    placement=dict(operation='replace', pointer='/active'))], injection={'json': False}))]
        if self.step == 4:
            return [('read', 'observation_read', {'observation': 'observation-1'})]
        return [('finish', 'finish', dict(finish_reason='no-useful-next-experiment',
            summary='One controlled invocation; other requirements remain unresolved.',
            objectives=[dict(objective_id='support', outcome='inconclusive', summary='Only target output inspected.',
                             observations=['observation-1'])]))]


class DiscoveredTargetsTest(unittest.TestCase):
    def test_reference_selection_key_correction_and_finish_across_codecs(self):
        root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        protocol = Protocol(root)
        fixture = next(f for f in json.loads((root / 'fixtures/compact-target-context.json').read_text())
                       if f['name'] == 'discoverable-injection-targets')
        endpoint = next(e for s in fixture['target']['capabilities']['services'] if s['service_id'] == 'idp'
                        for e in s['endpoints'] if e['collection'] == 'grants')
        for codec in CODECS:
            with self.subTest(codec=codec):
                host = DiscoveryHost(protocol)
                inputs = DiscoveryInputs(protocol, root, loading_bundle(), host, codec)
                inputs._context['target'] = fixture['target']
                _, inputs.details = compact_target_context(protocol, _canonical_value(fixture['target'], 4 << 20))
                inputs.context_raw = _canonical_value(inputs._context, 4 << 20)
                protocol.validate_engine_context(inputs.context_raw)
                session = SimpleNamespace(inputs=inputs, client=host, admission={
                    'limits': {'harness': dict(LIMITS, max_model_turns=30), 'campaign': {'model_tokens': 1000000}},
                    'remaining_limits': {'campaign_time_ms': 100000, 'artifact_bytes': 2 << 20}})
                campaign = compose_campaign(protocol, session, clock=Clock())
                host.conversation = campaign.adaptive.conversation
                result = campaign.run()
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertEqual(len(host.attempt_ids), 1)  # Invalid key never dispatched.
                self.assertEqual(len(host.model_requests), 6)
                sent = next(b for op, b, _ in host.events if op == 'engine.attempt_execute')
                self.assertEqual(sent['pre_actions'][0]['parameters']['selector']['key'], endpoint['keys'][0])
                self.assertEqual(sent['injection_input'], {'encoding': 'json', 'value': False})
                # Inspect actual native request history: exact endpoint facts, then correction.
                outputs = [json.loads(container[key]) for container, key in
                           campaign.adaptive.conversation._tool_outputs(host.model_requests[2]['conversation'][1:])]
                details = json.loads(next(v['content'] for v in outputs if v.get('encoding') == 'utf8'))
                self.assertEqual(details['resource'], endpoint)
                self.assertIn('invalid_state_key', json.dumps(host.model_requests[3]))
                self.assertIn('/setup/0/selector/key', json.dumps(host.model_requests[3]))
                self.assertIn('first observed result', json.dumps(host.model_requests[-1]))
                assessment = json.loads(host.conclusion_raw)
                self.assertEqual(assessment['objectives'][0]['outcome'], 'inconclusive')
                self.assertEqual(assessment['objectives'][0]['attempt_receipt_refs'], ['attempt-receipt-1'])


if __name__ == '__main__':
    unittest.main()
