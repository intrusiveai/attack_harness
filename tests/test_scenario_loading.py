"""Complete controlled campaigns across native codecs and bounded history."""
import json
import os
from pathlib import Path
import unittest
from operator_contracts import Protocol
from operator_contracts.canonical import raw_digest
from scenario_loading_fixture import run_loading
from test_instruction_boundary import CODECS


class ScenarioLoadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def test_switch_read_restore_repair_and_finish_across_codecs(self):
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, inputs, result = run_loading(self.protocol, self.root, filename, trim=True, same_batch=True)
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertEqual(result['finalization_status'], 'pending')
                self.assertEqual(len(host.attempt_ids), 2)
                self.assertTrue(any('scenario_context_required' in json.dumps(r) for r in host.model_requests))
                self.assertEqual(host.reads, 4)  # Two initial reads and two deliberate final rereads.
                self.assertEqual(inputs.bundle(), json.loads(inputs.bundle_raw))
                self.assertEqual(raw_digest(inputs.bundle_raw), inputs.context()['scenario_bundle']['digest'])
                first = host.task_from_request(host.model_requests[0])
                self.assertEqual(first['scenario_bundle']['scenarios'], [])
                self.assertEqual(len(first['scenario_references']), 4)
                for request in host.model_requests:
                    task = host.task_from_request(request)
                    self.assertEqual(task['scenario_bundle']['coverage'], inputs.bundle()['coverage'])
                    self.assertEqual(len(task['scenario_references']), 4)
                    active = task['scenario_bundle']['scenarios']
                    self.assertLessEqual(len(active), 1)
                    if active:
                        original = next(s for s in inputs.bundle()['scenarios'] if s['scenario_id'] == active[0]['scenario_id'])
                        self.assertEqual(active[0], original)
                    # No scenario bodies in the tool exchanges: selection returns a confirmation.
                    history = json.dumps(request['conversation'][1:])
                    self.assertNotIn('coverage_obligations', history)
                    self.assertNotIn('expected_observations', history)
                last = host.task_from_request(host.model_requests[-1])
                facts = last['execution_records']
                self.assertEqual([x['scenario_id'] for x in facts['executions']], ['baseline', 'refund'])
                self.assertTrue(all(x['status'] == 'completed' for x in facts['executions']))
                self.assertTrue(all(x['observations'][0]['inspected'][0]['content_in_prompt'] for x in facts['executions']))
                self.assertEqual(last['scenario_delivery_state']['instructions_not_yet_delivered'], ['malformed', 'union'])
                self.assertEqual(facts['restores'][0]['restored_snapshot'], 'checkpoint-2')
                self.assertEqual(facts['restores'][0]['run_revision'], 2)
                snapshots = {x['handle']: x for x in facts['other_handles'] if x['kind'] == 'checkpoint'}
                self.assertEqual(snapshots['checkpoint-2']['snapshot_metadata']['parent'], 'checkpoint-1')
                self.assertTrue(snapshots['checkpoint-1']['available'])
                self.assertIn('harness-local-trimming', json.dumps(host.model_requests[-1]))
                self.assertIsNone(campaign.adaptive.dispatcher.repair)  # Cleared only after acceptance.
                self.assertTrue(any('Your finish submission was rejected' in json.dumps(r) for r in host.model_requests))
                self.assertTrue(any('assessment_repair_active' in json.dumps(r) for r in host.model_requests))
                self.assertEqual(len(json.loads(host.conclusion_raw)['objectives'][0]['attempt_receipt_refs']), 2)
                # Raw audit requests remain unchanged when subsequent history is trimmed.
                self.assertTrue(any('first observed result' in json.dumps(r) for r in host.model_requests[:-1]))
                self.assertFalse(campaign.adaptive.conversation._compactions)


if __name__ == '__main__':
    unittest.main()
