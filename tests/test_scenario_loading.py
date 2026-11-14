"""Complete controlled campaigns across native codecs and bounded history."""
import json
import os
from pathlib import Path
import unittest
from attack_harness.composition import build_task
from attack_harness.tools import ToolCall
from operator_contracts import Protocol
from operator_contracts.canonical import raw_digest
from scenario_loading_fixture import run_loading
from test_instruction_boundary import CODECS
import test_scenario_delivery as scenario_fixture
from test_vertical_slice import Reply


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
                self.assertIsNone(first['active_scenario'])
                self.assertEqual(len(first['scenario_index']), 4)
                for request in host.model_requests:
                    task = host.task_from_request(request)
                    self.assertEqual(task['campaign']['coverage'], inputs.bundle()['coverage'])
                    self.assertEqual(len(task['scenario_index']), 4)
                    active = ([task['active_scenario']] if task['active_scenario'] else [])
                    self.assertLessEqual(len(active), 1)
                    if active:
                        original = next(s for s in inputs.bundle()['scenarios'] if s['scenario_id'] == active[0]['scenario_id'])
                        self.assertEqual(active[0], original)
                    # No scenario bodies in the tool exchanges: selection returns a confirmation.
                    history = json.dumps(request['conversation'][1:])
                    self.assertNotIn('coverage_obligations', history)
                    self.assertNotIn('expected_observations', history)
                last = host.task_from_request(host.model_requests[-1])
                facts = last['evidence']
                self.assertEqual([x['scenario_id'] for x in facts['executions']], ['baseline', 'refund'])
                self.assertTrue(all(x['status'] == 'completed' for x in facts['executions']))
                self.assertTrue(all(x['observations'][0]['inspected'][0]['content_in_prompt'] for x in facts['executions']))
                self.assertEqual([s['scenario_id'] for s in last['scenario_index'] if s['instructions'] == 'not-loaded'], ['malformed', 'union'])
                self.assertEqual(facts['restores'][0]['restored_snapshot'], 'checkpoint-2')
                self.assertEqual(host.run_revision, 2)
                self.assertNotIn('run_revision', facts['restores'][0])
                snapshots = {x['handle']: x for x in facts['other_handles'] if x['kind'] == 'checkpoint'}
                self.assertEqual(snapshots['checkpoint-2']['snapshot_metadata']['parent'], 'checkpoint-1')
                self.assertTrue(snapshots['checkpoint-1']['available'])
                self.assertIn('harness-local-checkpoint', json.dumps(host.model_requests[-1]))
                self.assertIsNone(campaign.adaptive.dispatcher.repair)  # Cleared only after acceptance.
                self.assertTrue(any('Your finish submission was rejected' in json.dumps(r) for r in host.model_requests))
                self.assertTrue(any('assessment_repair_active' in json.dumps(r) for r in host.model_requests))
                self.assertEqual(len(json.loads(host.conclusion_raw)['objectives'][0]['attempt_receipt_refs']), 2)
                # Raw audit requests remain unchanged when subsequent history is trimmed.
                self.assertTrue(any('first observed result' in json.dumps(r) for r in host.model_requests[:-1]))
                self.assertFalse(campaign.adaptive.conversation._compactions)

    def test_active_activity_switches_and_revisits_without_resetting_evidence(self):
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, inputs, result = run_loading(
                    self.protocol, self.root, filename, trim=True, same_batch=True)
                tasks = [host.task_from_request(r) for r in host.model_requests]
                self.assertEqual(tasks[0]['active_scenario_activity'], [])
                baseline = [t for t in tasks if t['active_scenario'] and t['active_scenario']['scenario_id'] == 'baseline']
                refund = [t for t in tasks if t['active_scenario'] and t['active_scenario']['scenario_id'] == 'refund']
                # Same-response withheld attempt is retained as non-execution.
                withheld = baseline[0]['active_scenario_activity']
                self.assertEqual(len(withheld), 1)
                self.assertEqual(withheld[0]['status'], 'not-executed')
                self.assertEqual(withheld[0]['reason'], 'scenario_context_required')
                self.assertNotIn('execution', withheld[0])
                self.assertEqual(refund[0]['active_scenario_activity'], [])
                before_read = next(t for t in baseline if any(a.get('execution') == 'execution-1'
                    for a in t['active_scenario_activity']))
                execution = next(a for a in before_read['active_scenario_activity'] if a.get('execution') == 'execution-1')
                self.assertEqual(execution['operation_id'], 'invoke')
                self.assertEqual(execution['requested_purpose'], 'Test the active scenario requirements.')
                self.assertEqual(execution['status'], 'completed')
                # This snapshot is taken on revisit; incremental reads did not rewrite its predecessor.
                self.assertTrue(execution['observations'][0]['inspected'])
                self.assertEqual(execution['observations'][0]['readable'][0]['handle'], 'observation-1')
                revisited = next(t for t in baseline if any(a.get('execution') == 'execution-1'
                    and a['observations'][0]['inspected'] for a in t['active_scenario_activity']))
                self.assertFalse(any(a.get('execution') == 'execution-2' for a in revisited['active_scenario_activity']))
                self.assertTrue(any(a.get('snapshot') == 'checkpoint-1' for a in revisited['active_scenario_activity']))
                self.assertTrue(any(a.get('restored_snapshot') == 'checkpoint-2'
                    for t in tasks for a in t.get('campaign_activity', [])))
                last = tasks[-1]
                self.assertEqual(last['active_scenario']['scenario_id'], 'refund')
                actions = last['active_scenario_activity']
                self.assertEqual(sum(a.get('execution') == 'execution-2' for a in actions), 1)
                self.assertFalse(any(a.get('execution') == 'execution-1' for a in actions))
                self.assertTrue(next(a for a in actions if a.get('execution') == 'execution-2')
                                ['observations'][0]['inspected'][0]['content_in_prompt'])
                self.assertEqual([e['execution'] for e in last['evidence']['executions']], ['execution-1', 'execution-2'])
                # The tracker is a checkpoint snapshot, never repeated in ordinary tool history.
                for request in host.model_requests:
                    self.assertNotIn('active_scenario_activity', json.dumps(request['conversation'][1:]))
                self.assertEqual(result['assessment_state'], 'committed')
                self.assertEqual(json.loads(host.conclusion_raw)['objectives'][0]['outcome'], 'inconclusive')
                self.assertEqual(len(host.attempt_ids), 2)

    def test_host_rejection_duplicate_and_exploratory_actions_keep_truthful_associations(self):
        fixture = scenario_fixture.ScenarioDeliveryTest()
        fixture.protocol, fixture.root = self.protocol, self.root
        campaign, host, inputs = fixture.campaign()
        conversation, loop = campaign.adaptive.conversation, campaign.adaptive.loop
        conversation.replace_task(build_task(inputs, active_scenario='baseline'))
        conversation.delivered_task_generation = conversation.task_generation
        original_request = host.request
        sent = []

        def reject(operation, body, *, operation_id):
            if operation == 'engine.attempt_execute':
                sent.append(body)
                reply = Reply({})
                reply.error = dict(code='NOT_PERMITTED', message='Operation not permitted.',
                                   effect_state='none', disposition='correct-and-resubmit')
                return reply
            return original_request(operation, body, operation_id=operation_id)

        host.request = reject
        rejected = ToolCall('rejected', 'attempt_execute', json.dumps(dict(origin='scenario',
            scenario_id='baseline', operation_id='invoke', json={'query': 'test'})).encode())
        for _ in range(2):
            loop.begin_model()
            campaign.adaptive.dispatcher.dispatch([rejected])
        task = host.task_from_request(conversation.body()[0])
        self.assertEqual(len(sent), 1)
        self.assertEqual(task['active_scenario_activity'], [dict(tool='attempt_execute',
            operation_id='invoke', status='not-executed', reason='NOT_PERMITTED')])
        self.assertEqual(len(host.attempt_ids), 0)
        host.request = original_request
        loop.begin_model()
        campaign.adaptive.dispatcher.dispatch([ToolCall('explore', 'attempt_execute', json.dumps(dict(
            origin='exploratory', operation_id='invoke', json={'query': 'explore'})).encode())])
        self.assertEqual(host.task_from_request(conversation.body()[0]), task)
        conversation._schedule_checkpoint('context-limit')
        task = host.task_from_request(conversation.body()[0])
        self.assertEqual(len(task['active_scenario_activity']), 1)  # No fabricated scenario association.
        self.assertEqual(task['evidence']['executions'][0]['origin'], 'exploratory')


if __name__ == '__main__':
    unittest.main()
