"""Reduced native contexts retain verified state and complete repair workflows."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol, ContractError
from operator_contracts.canonical import _canonical_value
from attack_harness.composition import build_task
from attack_harness.tools import ToolCall
from context_overhead_fixture import MeasuredHost, MeasuredInputs, measure
from test_instruction_boundary import CODECS, tool_segment
import test_instruction_boundary as boundary
import base64


class ContextOverheadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(cls.root)

    def test_reference_projection_keeps_discovery_and_shared_examples(self):
        inputs = MeasuredInputs(self.protocol, self.root, MeasuredHost(self.protocol))
        originals = deepcopy(inputs.reference_index())
        task = json.loads(build_task(inputs))
        projected = task['reference_handles']
        self.assertEqual([r['entry_id'] for r in projected], [r['entry_id'] for r in originals])
        self.assertLess(len(json.dumps(projected)), len(json.dumps(originals)))
        for entry in projected:
            self.assertFalse({'digest','schema_id','root_kind','path'} & entry.keys())
            self.assertTrue(entry.get('name') or entry['entry_id'].startswith('tool-guide:'))
            canonical, raw = inputs.entry(entry['entry_id'])
            self.assertEqual(canonical['entry_id'], entry['entry_id'])
            self.assertEqual(len(raw), entry['size_bytes'])
        self.assertEqual(inputs.reference_index(), originals)
        self.assertEqual(task['scenario_bundle'], inputs.bundle())
        self.assertEqual(task['portfolio'], dict(scenario_count=4,
            scenario_ids=[s['scenario_id'] for s in inputs.bundle()['scenarios']]))
        example = task['shared_tool_guidance']['finish']['minimal_inline_example']
        self.assertEqual(example['objectives'][0]['objective_id'], 'support')
        self.assertIn('readable_observation', json.dumps(task['shared_tool_guidance']))
        self.assertNotIn('optional_uncertainty_example', json.dumps(task['shared_tool_guidance']))

    def test_controlled_sequence_commits_without_replay_or_model_summary(self):
        metrics = measure(self.protocol, self.root)
        self.assertEqual(metrics['assessment_state'], 'committed')
        self.assertEqual(metrics['target_invocations'], 4)
        self.assertEqual(metrics['model_compaction_calls'], 0)
        # The fixture rereads only if the bytes needed for its claim were removed.
        self.assertEqual(metrics['evidence_rereads'], int(metrics['evidence_reread_required']))
        self.assertEqual(metrics['evidence_reads'], 4 + metrics['evidence_rereads'])
        self.assertIsNone(metrics['actual_provider_usage'])

    def test_estimate_includes_fixed_prompt_and_tools_without_resending_them(self):
        from types import SimpleNamespace
        from test_vertical_slice import LIMITS, Clock
        from attack_harness.composition import compose_campaign
        host=MeasuredHost(self.protocol)
        inputs=MeasuredInputs(self.protocol,self.root,host)
        session=SimpleNamespace(inputs=inputs,client=host,admission={
            'limits':{'harness':LIMITS,'campaign':{'model_tokens':1000000}},
            'remaining_limits':{'campaign_time_ms':100000,'artifact_bytes':2<<20,
                                'model_tokens':1000000,'model_turns':30}})
        c=compose_campaign(self.protocol,session,clock=Clock()).adaptive.conversation
        body,raw=c.body()
        self.assertEqual(set(body), {'purpose','conversation'})
        self.assertGreater(c._fixed_context_bytes, len(inputs.prompt_raw))
        self.assertGreater(c._estimated_tokens(raw), len(raw)*0.5)
        c.observe_budget(dict(context_budget=dict(input_tokens=10000,
            remaining_model_tokens=900000,remaining_model_turns=29)), raw)
        self.assertEqual(c._estimated_tokens(raw), 11000)

    def test_local_reduction_keeps_verified_associations_and_range_state_in_every_codec(self):
        fixture = boundary.InstructionBoundaryTest()
        fixture.protocol, fixture.root = self.protocol, self.root
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, inputs = fixture.campaign(filename)
                a = campaign.adaptive; c = a.conversation
                original_request = host.request
                def sliced_request(operation, body, *, operation_id):
                    reply = original_request(operation, body, operation_id=operation_id)
                    if operation == 'engine.observation_read':
                        result = reply.result
                        raw = base64.b64decode(result['content'])
                        chunk = raw[body['offset']:body['offset'] + body['max_bytes']]
                        result.update(content=base64.b64encode(chunk).decode(), raw_length=len(chunk),
                                      eof=body['offset'] + len(chunk) == len(raw))
                    return reply
                host.request = sliced_request
                original_task, policy = c.task, deepcopy(c.policy)
                c.delivered_task_generation = c.task_generation
                a.loop.begin_model()
                results = a.dispatcher.dispatch([
                    ToolCall('execute', 'attempt_execute', json.dumps(dict(origin='scenario',scenario_id='baseline',operation_id='invoke',json={'query':'lookup'})).encode()),
                    ToolCall('read', 'observation_read', b'{"observation":"observation-1","max_bytes":32}'),
                ])
                output = json.loads(results[1].content)
                citation = output['citation']
                self.assertNotEqual(citation, 'observation-1')
                c.extend(_canonical_value(tool_segment(c.codec, results[1].content), 4<<20))
                self.assertEqual(c._present_citations(c._request[c._history_field()]), {citation})
                facts = campaign.handlers.model_tools.context_facts({citation})
                execution = facts['executions'][0]
                self.assertEqual(execution['scenario_id'], 'baseline')
                self.assertEqual(execution['origin'], 'scenario')
                self.assertEqual(execution['execution'], 'execution-1')
                evidence = execution['observations'][0]
                self.assertEqual(evidence['inspected'], [dict(citation=citation,content_in_prompt=True)])
                self.assertFalse(campaign.handlers.model_tools.resources['observation-1']['inspected'])
                snapshot = deepcopy(campaign.handlers.model_tools.resources)
                c._compact_at = 1  # Drop every removable group, not mandatory context.
                budget, loop = c._remaining.copy(), a.loop.snapshot()
                c.reduce_context()
                body, raw = c.body()  # Native codec validation including tool relationships.
                text = json.dumps(body)
                self.assertIn('harness-local-trimming', text)
                self.assertIn('content_in_prompt', text)
                self.assertIn(citation, text)
                self.assertNotIn('execution-from-target-prose', text)
                self.assertEqual(c.task, original_task); self.assertEqual(c.policy, policy)
                self.assertEqual(c._remaining, budget); self.assertEqual(a.loop.snapshot(), loop)
                self.assertEqual(campaign.handlers.model_tools.resources, snapshot)
                self.assertFalse(c._present_citations(c._request[c._history_field()]))
                self.assertIn('"content_in_prompt": false', c._summary)
                self.assertFalse(any(op=='engine.model_generate' for op,_,_ in host.events))
                # Inspection was preserved, but a whole unread observation is still invalid.
                a.loop.begin_model()
                invalid = a.dispatcher.dispatch([ToolCall('bad','finish',json.dumps(dict(
                    finish_reason='no-useful-next-experiment',summary='Only partial evidence inspected.',
                    objectives=[dict(objective_id='support',outcome='inconclusive',summary='Unknown.')],
                    claims=[dict(statement='Unsupported whole entry.',interpretation='supported',confidence='low',assurance='external-response',observations=['observation-1'])])).encode())])[0]
                self.assertNotEqual(invalid.outcome, 'success')
                self.assertEqual(len(host.attempt_ids), 1)

    def test_exact_duplicate_key_repair_block_survives_local_reduction_in_every_codec(self):
        fixture = boundary.InstructionBoundaryTest()
        fixture.protocol, fixture.root = self.protocol, self.root
        for filename in CODECS:
            with self.subTest(codec=filename):
                campaign, host, _ = fixture.campaign(filename)
                a=campaign.adaptive; c=a.conversation
                raw = b'{"summary":"first","summary":"second","finish_reason":"budget-limit"}'
                a.loop.begin_model()
                result = a.dispatcher.dispatch([ToolCall('bad','finish',raw)])[0]
                c.set_repair(a.dispatcher.repair)
                # A native result group with real rejection feedback; exact bad
                # JSON stays in independent repair state even on object codecs.
                c.extend(_canonical_value(tool_segment(c.codec,result.content),4<<20))
                c.prompt_again()
                c._compact_at=1
                c.reduce_context()
                _, request_raw=c.body()
                self.assertEqual(a.dispatcher.repair.call.arguments,raw)
                self.assertIn(raw.decode(), c._repair.context()['rejected_arguments'])
                task=c._request[c._history_field()][0]
                text=json.dumps(task)
                self.assertIn('rejected_arguments', text)
                self.assertEqual(request_raw.decode().count('field_path'), 1)  # One diagnostic object, not repeated history copies.
                self.assertIn('/summary', text)
                a.loop.begin_model()
                blocked=a.dispatcher.dispatch([ToolCall('blocked','attempt_execute',b'{"origin":"exploratory","operation_id":"invoke","text":"new"}')])[0]
                self.assertIn('assessment_repair_active', blocked.content)
                self.assertEqual(len(host.attempt_ids),0)


if __name__=='__main__':unittest.main()
