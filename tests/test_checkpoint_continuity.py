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
            return (f'select-{turn}', 'scenario_select', {'reference': entry['reference_id']})
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
            return [('record', 'record_progress', dict(summary='Baseline output inspected.',
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
        handoffs = final['continuity']['assessment_handoffs']
        self.assertEqual(handoffs['provenance'], 'model-interpretation-not-evidence')
        self.assertNotIn(NOTE, json.dumps(final))  # Arbitrary commentary is no longer carried.
        self.assertNotIn('Controlled private reasoning', json.dumps(handoffs))
        self.assertNotIn('Controlled reasoning', json.dumps(handoffs))
        record = handoffs['entries'][0]
        self.assertEqual(record['record'], 'record-1')
        self.assertEqual(record['scenario_id'], 'baseline')
        self.assertEqual(record['submitted']['observations'], ['observation-1'])
        self.assertEqual(record['submitted']['summary'], 'Baseline output inspected.')
        self.assertNotIn('model_records', final)
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

    def test_public_commentary_is_not_a_handoff_and_other_records_remain_bounded(self):
        campaign, host = self.campaign('responses-model-codec.json')
        campaign.run()
        delivery = campaign.handlers.scenario_delivery
        before = deepcopy(delivery.handoffs)
        delivery.begin_response(SimpleNamespace(public_text=lambda: 'execution-from-model ' + 'é' * 3000))
        self.assertEqual(delivery.handoffs, before)
        tools = campaign.handlers.model_tools
        for i in range(12):
            h = tools.register('record', {'record_receipt_id':f'large-{i}'}, available=True)
            tools.resources[h]['assessment_context'] = dict(scenario_id='baseline', submitted={'summary':'x'*5000})
        facts = tools.context_facts(set())
        self.assertGreater(facts['model_records']['omitted_records'], 0)
        self.assertLess(len(json.dumps(facts['model_records'])), 9000)
        self.assertEqual(len([r for r in tools.resources.values() if r['kind']=='record']), 13)
        self.assertNotIn('execution-from-model', tools.resources)


class HandoffHost(ContinuityHost):
    """Deliberate handoff, rejected replacement, correction, review and finish."""
    def __init__(self, protocol, *, selection_first=False, force_checkpoint=False, host_rejection=False):
        super().__init__(protocol)
        self.selection_first = selection_first
        self.force_checkpoint = force_checkpoint
        self.host_rejection = host_rejection
        self.oversized = dict(summary='Routine narration. ' * 150 +
            ' IMPORTANT: independent commitment is unresolved.', decision='Review refund next.',
            observations=['observation-1'])

    def _calls(self, turn):
        task = self._task()
        self.comment = ''
        def select(identifier):
            reference = next(s['reference_id'] for s in task['scenario_index'] if s['scenario_id']==identifier)
            return (f'select-{turn}', 'scenario_select', dict(reference=reference))
        def progress(summary, observations, decision='Review remaining evidence gaps; do not replay.'):
            return (f'progress-{turn}', 'record_progress', dict(summary=summary,
                decision=decision, observations=observations))
        if turn <= 3:
            return super()._calls(turn)
        if turn == 4:
            return [progress('Old baseline assessment; unresolved state evidence.', ['observation-1'])]
        if turn == 5:
            record = (f'oversized-{turn}', 'record_progress', self.oversized)
            calls = [record, select('refund')]
            return list(reversed(calls)) if self.selection_first else calls
        if turn == 6:
            if self.host_rejection == 'gap':
                return [('read-guide', 'reference_read', dict(reference='tool-guide:record_progress'))]
            return [progress('Baseline output inspected; independent commitment is unresolved.', ['observation-1']), select('refund')]
        if turn == 7:
            return [('refund-execution', 'attempt_execute', dict(origin='scenario', scenario_id='refund',
                operation_id='invoke', json={'query':'bounded second experiment'}))]
        if turn == 8:
            return [('refund-read', 'observation_read', dict(observation='observation-2'))]
        if turn == 9:
            return [progress('Refund output inspected; independent commitment remains unresolved.', ['observation-2']),
                ('invalid-finish', 'finish', dict(finish_reason='no-useful-next-experiment', summary='Unverified.',
                    objectives=[dict(objective_id='support', outcome='supported', summary='Missing evidence.')]))]
        if turn == 10:
            # Assessment continuity is permitted without reopening exploration or
            # clearing the exact rejected finish. Scope is campaign-wide here.
            calls = [progress('Two external outputs inspected; state evidence remains unresolved.', ['observation-1','observation-2']),
                     select('baseline')]
            return list(reversed(calls)) if self.selection_first else calls
        if turn == 11:
            return [('reread', 'observation_read', dict(observation='observation-1')), select('refund')]
        return [('finish', 'finish', dict(finish_reason='no-useful-next-experiment', summary='Both scenarios partially assessed.',
            objectives=[dict(objective_id='support', outcome='inconclusive', summary='Independent commitment unverified.',
                observations=['observation-1','observation-2'])]))]

    def request(self, operation, body, *, operation_id):
        if self.host_rejection and operation == 'engine.record_append' and len(self.model_requests)==5:
            reply = Reply({})
            reply.error = dict(code='INVALID_ARGUMENTS', effect_state='none', disposition='correct-and-resubmit',
                message='Correct the summary before recording.', diagnostic=dict(source='operator', stage='validation',
                    reason='invalid_structure', field_path='/summary', correction='Describe the observed limitation accurately.',
                    message='Correct the summary.', execution_occurred='no', resubmission_safe=True))
            if self.host_rejection == 'gap':
                reply.error.update(code='LIMIT_EXCEEDED', disposition='gap-and-continue')
                reply.error['diagnostic'].update(reason='progress_rate_limit', resubmission_safe=False,
                    correction='Continue permitted work; do not retry immediately.')
            return reply
        result = super().request(operation, body, operation_id=operation_id)
        if self.force_checkpoint and operation == 'engine.model_generate':
            self.conversation._compact_at = 1 if len(self.model_requests)==5 else 1 << 20
        return result


class PurposeBuiltHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def campaign(self, filename, **kwargs):
        host = HandoffHost(self.protocol, **kwargs)
        bundle = loading_bundle()
        bundle['scenarios'] = bundle['scenarios'][:2]
        inputs = ScenarioInputs(self.protocol, self.root, bundle, host, filename)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            'limits': {'harness':dict(LIMITS, max_model_turns=30), 'campaign':{'model_tokens':1000000}},
            'remaining_limits':{'campaign_time_ms':100000, 'artifact_bytes':2 << 20}})
        campaign = compose_campaign(self.protocol, session, clock=Clock())
        host.conversation = campaign.adaptive.conversation
        return campaign, host

    def test_rejected_replacement_keeps_context_and_repairs_before_switch_across_codecs(self):
        for filename in CODECS:
            for selection_first in (False, True):
                with self.subTest(codec=filename, selection_first=selection_first):
                    campaign, host = self.campaign(filename, selection_first=selection_first)
                    self.assertEqual(campaign.run()['assessment_state'], 'committed')
                    self.assertEqual(len(host.attempt_ids), 2)
                    self.assertEqual(host.reads, 3)
                    self.assertEqual(len(host.model_requests), 12)
                    self.assertGreater(host.checked_prefixes, 0)
                    failed = host.model_requests[5]
                    self.assertEqual(host.task_from_request(failed)['active_scenario']['scenario_id'], 'baseline')
                    self.assertGreater(len(failed['conversation']), 1)  # failed navigation did not discard context
                    self.assertEqual(host.checkpoint_ids[4], host.checkpoint_ids[5])
                    self.assertIn('configured_size_exceeded', json.dumps(failed))
                    self.assertIn('Preserve unresolved obligations', json.dumps(failed))
                    next_task = host.task_from_request(host.model_requests[6])
                    self.assertEqual(next_task['active_scenario']['scenario_id'], 'refund')
                    entries = next_task['continuity']['assessment_handoffs']['entries']
                    self.assertEqual(len(entries), 1)
                    self.assertEqual(entries[0]['submitted']['summary'], 'Baseline output inspected; independent commitment is unresolved.')
                    self.assertNotIn('Old baseline assessment', json.dumps(next_task))
                    self.assertNotIn('Routine narration', json.dumps(next_task))
                    self.assertNotIn('checkpoint_handoff_rejection', next_task)
                    final = host.task_from_request(host.model_requests[-1])
                    entries = final['continuity']['assessment_handoffs']['entries']
                    self.assertEqual({e['scenario_id'] for e in entries}, {'baseline','refund',None})
                    self.assertTrue(all(t['continuity']['phase']=='assessment' and 'assessment_repair' in t
                        for t in [host.task_from_request(r) for r in host.model_requests[9:]]))
                    self.assertEqual(len([op for op,_,_ in host.events if op=='engine.record_append']), 4)
                    self.assertEqual(len(json.loads(host.conclusion_raw)['objectives'][0]['attempt_receipt_refs']), 2)
                    self.assertEqual(campaign.adaptive.loop.snapshot()['model_turns'], 12)
                    self.assertTrue(all(r['purpose']=='generation' for r in host.model_requests))

    def test_forced_checkpoint_retains_entire_rejected_handoff_and_previous_accepted_one(self):
        campaign, host = self.campaign('anthropic-model-codec.json', force_checkpoint=True, selection_first=True)
        self.assertEqual(campaign.run()['assessment_state'], 'committed')
        failed = host.task_from_request(host.model_requests[5])
        rejection = failed['checkpoint_handoff_rejection']
        self.assertEqual(json.loads(rejection['rejected_arguments']), host.oversized)
        self.assertIn('IMPORTANT: independent commitment is unresolved.', rejection['rejected_arguments'])
        self.assertEqual(rejection['scenario_id'], 'baseline')
        self.assertEqual(rejection['rejection']['diagnostic']['reason'], 'configured_size_exceeded')
        self.assertEqual(failed['continuity']['assessment_handoffs']['entries'][0]['submitted']['summary'],
                         'Old baseline assessment; unresolved state evidence.')
        self.assertTrue(failed['continuity']['recent_navigation'][-1]['cancelled'])
        self.assertEqual(len(host.model_requests[5]['conversation']), 1)

    def test_complete_handoff_byte_limit_and_required_decision(self):
        from operator_contracts.canonical import _canonical_value
        from attack_harness.tools import ToolError
        campaign, _ = self.campaign('model-codec.json')
        delivery = campaign.handlers.scenario_delivery
        value = dict(summary='é', decision='Revisit an unresolved finding.')
        value['summary'] += 'x' * (delivery.handoff_limit - len(_canonical_value(value, 1 << 20)))
        delivery.validate_handoff(value)
        value['summary'] += 'é'
        with self.assertRaises(ToolError) as caught:
            delivery.validate_handoff(value)
        self.assertIn(str(delivery.handoff_limit + 2), str(caught.exception))
        delivery.validate_handoff(dict(summary='Unresolved evidence.'))

    def test_host_rejection_preserves_precise_correction_before_reselection(self):
        campaign, host = self.campaign('model-codec.json', host_rejection=True, selection_first=True)
        host.oversized['summary'] = 'A short but rejected assessment.'
        self.assertEqual(campaign.run()['assessment_state'], 'committed')
        failed = json.dumps(host.model_requests[5])
        self.assertIn('Describe the observed limitation accurately.', failed)
        self.assertIn('/summary', failed)
        self.assertIn('Pending scenario navigation is cancelled', failed)
        self.assertEqual(len(host.attempt_ids), 2)
        self.assertIsNone(campaign.handlers.scenario_delivery.handoff_rejection)

    def test_duplicate_keys_remain_exact_and_invalid_citations_do_not_create_handoffs(self):
        from attack_harness.tools import ToolCall
        from operator_contracts.canonical import _canonical_value
        campaign, host = self.campaign('model-codec.json')
        tools = campaign.handlers.model_tools
        delivery = campaign.handlers.scenario_delivery
        raw = b'{"summary":"First","summary":"Second","decision":"Review"}'
        result = tools.dispatch(ToolCall('duplicate', 'record_progress', raw))
        self.assertEqual(result.outcome, 'invalid')
        self.assertEqual(delivery.handoff_rejection['rejected_arguments'], raw.decode())
        self.assertEqual(delivery.handoffs, {})
        request, _ = campaign.adaptive.conversation.body()
        retained = host.task_from_request(request)['checkpoint_handoff_rejection']
        self.assertEqual(retained['rejected_arguments'], raw.decode())
        bad = dict(summary='Unsupported statement.', decision='Review.', observations=['invented'])
        result = tools.dispatch(ToolCall('bad-reference', 'record_progress', _canonical_value(bad, 4096)))
        self.assertEqual(result.outcome, 'invalid')
        self.assertIn('/observations/0', json.dumps(result.value))
        self.assertEqual(delivery.handoffs, {})
        self.assertFalse(any(op=='engine.record_append' for op,_,_ in host.events))
        self.assertTrue(delivery.handoff_rejection['known_progress'])

    def test_host_gap_retains_validated_handoff_without_record_handle_or_retry_gate(self):
        campaign, host = self.campaign('bedrock-model-codec.json', host_rejection='gap', selection_first=True)
        host.oversized['summary'] = 'Independent commitment remains unresolved.'
        self.assertEqual(campaign.run()['assessment_state'], 'committed')
        task = host.task_from_request(host.model_requests[5])
        self.assertEqual(task['active_scenario']['scenario_id'], 'refund')
        baseline = task['continuity']['assessment_handoffs']['entries'][0]
        self.assertEqual(baseline['scenario_id'], 'baseline')
        self.assertEqual(baseline['submitted'], host.oversized)
        self.assertIsNone(baseline['record'])
        self.assertEqual(baseline['retention'], 'harness-only')
        self.assertEqual(baseline['host_rejection']['disposition'], 'gap-and-continue')
        self.assertNotIn('checkpoint_handoff_rejection', task)
        self.assertEqual(len(host.attempt_ids), 2)
