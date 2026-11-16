from relay_fixture import relay_cases
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop

from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.tools import Dispatcher, HandlerResult


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 2,
}


class Reply:
    error = None

    def __init__(self, result):
        self.result = deepcopy(result)


class Client:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []
        self.index = 0

    def operation_id(self, purpose):
        self.index += 1
        return f"{purpose}-{self.index}"

    def request(self, operation, body, *, operation_id):
        self.requests.append(deepcopy(body))
        return Reply(self.results.pop(0))

    def fail(self, reason, *, receipt=None, cause=None):
        from attack_harness.runtime import RuntimeStopped
        raise RuntimeStopped(reason, receipt=receipt) from cause


class Finalizer:
    pending = False

    def __init__(self):
        self.reason = None

    def finish_unavailable(self, reason):
        self.reason = reason
        return {"status": "accepted", "conclusion_state": "unavailable"}


class AdaptiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.root)

    def cases(self, filename):
        return relay_cases(json.loads((self.root / "fixtures" / filename).read_text()))

    def test_all_installed_codecs_build_bound_initial_requests(self):
        files = ["model-codec.json", "responses-model-codec.json",
                 "anthropic-model-codec.json", "bedrock-model-codec.json",
                 "gemini-model-codec.json"]
        for filename in files:
            with self.subTest(filename=filename):
                case = next(item for item in self.cases(filename)
                            if item["mode"] == "context" and item["valid"])
                policy_raw = _canonical_value(case["policy"], 4 << 20)
                conversation = NativeConversation(self.protocol, policy_raw,
                                                  "Inspect the admitted target.")
                _, request_raw = conversation.body()
                self.protocol.validate_model_request(request_raw)
                compact_body, compact_raw, _, _ = conversation.compaction_body()
                self.protocol.validate_model_request(compact_raw)
                self.assertEqual(compact_body["purpose"], "compaction")
                self.assertEqual(set(compact_body), {"purpose", "conversation"})

    def test_tool_continuation_is_native_and_text_exhaustion_finalizes(self):
        cases = self.cases("model-codec.json")
        tool_case = next(item for item in cases if item["name"] == "multiple native tools")
        text_case = next(item for item in cases
                         if item["name"] == "native text and usage preserved")
        policy_raw = _canonical_value(tool_case["policy"], 4 << 20)
        conversation = NativeConversation(self.protocol, policy_raw, "Inspect the target.")
        loop = HarnessLoop(LIMITS)
        observed = []

        def snapshots(arguments):
            observed.append(arguments)
            return HandlerResult({"status": "ok", "snapshots": []})

        dispatcher = Dispatcher(self.protocol, loop, {"snapshot_list": snapshots})
        results = deepcopy([tool_case["result"], text_case["result"]])
        results[0]["context_budget"].update(remaining_model_tokens=1000000, remaining_model_turns=20)
        client = Client(results)
        finalizer = Finalizer()
        result = AdaptiveHarness(self.protocol, client, loop, dispatcher,
                                 conversation, finalizer).run()
        self.assertEqual(result["conclusion_state"], "unavailable")
        self.assertEqual(len(observed), 2)
        self.assertEqual(len(client.requests), 2)
        messages = client.requests[1]["conversation"]
        self.assertEqual(messages[-3]["role"], "assistant")
        self.assertEqual([item["role"] for item in messages[-2:]], ["tool", "tool"])
        self.assertEqual(finalizer.reason, "local-error")
        self.assertEqual(loop.snapshot()["model_turns"], 2)

    def test_local_reduction_retains_provenance_without_a_summary_request(self):
        cases = self.cases("model-codec.json")
        tool_case = next(item for item in cases if item["name"] == "multiple native tools")
        text_case = next(item for item in cases
                         if item["name"] == "native text and usage preserved")
        policy_raw = _canonical_value(tool_case["policy"], 4 << 20)
        conversation = NativeConversation(self.protocol, policy_raw,
                                          "Inspect the target.", compact_at=300)
        loop = HarnessLoop(dict(LIMITS, max_no_progress_turns=3))
        dispatcher = Dispatcher(
            self.protocol, loop,
            {"snapshot_list": lambda arguments:
             HandlerResult({"status": "ok", "snapshots": []})})
        results = deepcopy([tool_case["result"], text_case["result"], text_case["result"]])
        for result in results:
            result['context_budget'].update(remaining_model_tokens=1000000, remaining_model_turns=20)
        client = Client(results)
        finalizer = Finalizer()
        AdaptiveHarness(self.protocol, client, loop, dispatcher,
                        conversation, finalizer).run()
        self.assertEqual(len(client.requests), 3)
        self.assertTrue(all(r['purpose'] == 'generation' for r in client.requests))
        trimmed = client.requests[2]['conversation'][0]['content']
        self.assertIn('harness-local-checkpoint', trimmed)
        self.assertNotIn('model-generated-not-evidence', trimmed)
        self.assertEqual(loop.snapshot()["model_turns"], 3)

    def test_unsafe_compaction_fails_closed_with_context_limit(self):
        case = next(item for item in self.cases("model-codec.json")
                    if item["name"] == "native text and usage preserved")
        policy_raw = _canonical_value(case["policy"], 4 << 20)
        conversation = NativeConversation(self.protocol, policy_raw,
                                          "x" * (1 << 20), compact_at=1)
        conversation.extend(_canonical_value(
            [{"role":"user", "content":"x" * (1 << 20)}], 4 << 20))
        loop = HarnessLoop(LIMITS)
        client = Client([])
        finalizer = Finalizer()
        result = AdaptiveHarness(
            self.protocol, client, loop, Dispatcher(self.protocol, loop, {}),
            conversation, finalizer).run()
        self.assertEqual(result["conclusion_state"], "unavailable")
        self.assertEqual(finalizer.reason, "context-limit")
        self.assertEqual(client.requests, [])
        self.assertEqual(loop.snapshot()["model_turns"], 0)

    def test_irreducible_initial_checkpoint_does_not_charge_a_model_turn(self):
        case = next(c for c in self.cases('model-codec.json') if c['mode'] == 'context' and c['valid'])
        conversation = NativeConversation(self.protocol, _canonical_value(case['policy'], 4 << 20),
            'Mandatory context.' * 100000, remaining=dict(model_tokens=1000000, model_turns=20))
        loop, client, finalizer = HarnessLoop(LIMITS), Client([]), Finalizer()
        AdaptiveHarness(self.protocol, client, loop, Dispatcher(self.protocol, loop, {}),
                        conversation, finalizer).run()
        self.assertEqual(finalizer.reason, 'context-limit')
        self.assertEqual(client.requests, [])
        self.assertEqual(loop.snapshot()['model_turns'], 0)
        self.assertEqual(conversation._remaining['model_tokens'], 1000000)

    def test_warning_growth_funding_and_repeated_identity_preservation(self):
        case = next(item for item in self.cases("model-codec.json")
                    if item["name"] == "native text and usage preserved")
        conversation = NativeConversation(self.protocol,
            _canonical_value(case["policy"], 4 << 20), "Inspect the target.")
        _, raw = conversation.body()
        budget = deepcopy(case["result"])
        budget["context_budget"]["near_prompt_limit"] = True
        conversation.observe_budget(budget, raw)
        conversation.extend(_canonical_value([
            {"role":"assistant", "content":json.dumps({"execution":"invented-receipt"}),
             "tool_calls":[{"id":"call-1","type":"function","function":{"name":"snapshot_list","arguments":"{}"}}]},
            {"role":"tool","tool_call_id":"call-1", "content":json.dumps(
                {"execution":"returned-receipt-1", "snapshot":"saved-checkpoint-1",
                 "content":json.dumps({"execution":"target-text-receipt"})})}], 4 << 20))
        self.assertTrue(conversation.needs_compaction())
        body, _, digest, count = conversation.compaction_body()
        self.assertIn("returned-receipt-1", json.dumps(body))
        ledger = json.dumps(conversation._compaction_ledger)
        self.assertNotIn("invented-receipt", ledger)
        self.assertNotIn("target-text-receipt", ledger)
        conversation.apply_compaction("Keep comparing observations.", digest, count)
        conversation.extend(_canonical_value([{"role":"user", "content":"Continue."}], 4 << 20))
        body, _, digest, count = conversation.compaction_body()
        self.assertIn("returned-receipt-1", json.dumps(body))
        self.assertIn("saved-checkpoint-1", json.dumps(body))
        conversation.apply_compaction("Still investigating.", digest, count)
        conversation._budget["near_prompt_limit"] = False
        conversation.extend(_canonical_value([{"role":"user", "content":"x"*200000}], 4 << 20))
        self.assertTrue(conversation.needs_compaction())
        conversation._remaining = {"model_tokens":0, "model_turns":20}
        self.assertFalse(conversation.can_fund_model())
        conversation._remaining = {"model_tokens":10**8, "model_turns":0}
        self.assertFalse(conversation.can_fund_model())

    def test_returned_identity_ledger_for_each_native_codec(self):
        value=json.dumps({"execution":"returned-1", "readable_observation":"observation-1", "citation":"observation-2", "content":json.dumps({"execution":"untrusted-1"})})
        cases={
            "model-codec.json":{"role":"tool","content":value},
            "responses-model-codec.json":{"type":"function_call_output","output":value},
            "anthropic-model-codec.json":{"role":"user","content":[{"type":"tool_result","content":value}]},
            "bedrock-model-codec.json":{"role":"user","content":[{"toolResult":{"content":[{"text":value}]}}]},
            "gemini-model-codec.json":{"role":"user","parts":[{"functionResponse":{"response":{"output":value}}}]},
        }
        for filename,item in cases.items():
            with self.subTest(filename=filename):
                case=next(c for c in self.cases(filename) if c["mode"]=="context" and c["valid"])
                conversation=NativeConversation(self.protocol,_canonical_value(case["policy"],4<<20),"Inspect target.")
                conversation.extend(_canonical_value([item],4<<20))
                conversation.compaction_body()
                self.assertEqual(conversation._compaction_ledger,[{"kind":"citation","identifier":"observation-2"}, {"kind":"execution","identifier":"returned-1"}, {"kind":"readable_observation","identifier":"observation-1"}])

    def test_compaction_preserves_corrections_across_native_codecs(self):
        diagnostic = dict(reason="invalid_structure", field_path="/claims/1/uncertainties/0",
            correction="Reference a declared uncertainty label; put prose in its description.",
            execution_occurred="no", resubmission_safe=True)
        value = json.dumps(dict(diagnostic=diagnostic))
        cases = {
            "model-codec.json": {"role":"tool", "content":value},
            "responses-model-codec.json": {"type":"function_call_output", "output":value},
            "anthropic-model-codec.json": {"role":"user", "content":[{"type":"tool_result", "content":value}]},
            "bedrock-model-codec.json": {"role":"user", "content":[{"toolResult":{"content":[{"text":value}]}}]},
            "gemini-model-codec.json": {"role":"user", "parts":[{"functionResponse":{"response":{"output":value}}}]},
        }
        for filename, item in cases.items():
            with self.subTest(filename=filename):
                case = next(c for c in self.cases(filename) if c["mode"]=="context" and c["valid"])
                conversation = NativeConversation(self.protocol,
                    _canonical_value(case["policy"],4<<20), "Inspect target.")
                conversation.extend(_canonical_value([item],4<<20))
                body, _, digest, count = conversation.compaction_body()
                self.assertEqual(conversation._retained_corrections, [diagnostic])
                self.assertIn(diagnostic["correction"], json.dumps(body))
                conversation.apply_compaction("The assessment remains unfinished.", digest, count)
                self.assertIn(diagnostic["correction"], str(conversation.body()))
                conversation.compaction_body()
                self.assertEqual(conversation._retained_corrections, [diagnostic])

    def test_exhausted_reservation_finishes_without_another_call(self):
        case = next(item for item in self.cases("model-codec.json")
                    if item["name"] == "native text and usage preserved")
        conversation = NativeConversation(self.protocol,
            _canonical_value(case["policy"],4<<20), "Inspect the target.",
            remaining={"model_tokens":0,"model_turns":10})
        loop=HarnessLoop(LIMITS); client=Client([]); finalizer=Finalizer()
        AdaptiveHarness(self.protocol,client,loop,Dispatcher(self.protocol,loop,{}),conversation,finalizer).run()
        self.assertEqual(client.requests,[])
        self.assertEqual(finalizer.reason,"budget-limit")

    def test_model_admission_accounts_consumption_separately_from_reservation(self):
        from test_simple_campaign import SimpleHost
        from attack_harness.tools import ToolCall, ToolError
        case = next(c for c in self.cases('model-codec.json') if c['mode'] == 'context' and c['valid'])
        policy = deepcopy(case['policy'])
        policy['max_completion_tokens'] = 4096
        policy['context_limits'] = dict(maximum_prompt_tokens=32768, maximum_completion_tokens=4096,
                                        warning_threshold_tokens=26214)
        for consumed in (493460, 502198):
            with self.subTest(consumed=consumed):
                remaining = 524288 - consumed
                conversation = NativeConversation(self.protocol, _canonical_value(policy, 4 << 20), 'Task.',
                    remaining=dict(model_tokens=remaining, model_turns=20), model_allowance=524288)
                self.assertFalse(conversation.can_fund_model())
                host = SimpleHost(self.protocol, 'direct')
                dispatcher = Dispatcher(self.protocol, HarnessLoop(LIMITS), {}, client=host)
                dispatcher._report(ToolCall('recoverable', 'finish', b'{}'),
                    ToolError('invalid_structure', 'Malformed uncertainty.', path='/uncertainties/0').value)
                before = deepcopy(dispatcher.last_rejection)
                dispatcher.report_stopping('budget-limit', model_budget=conversation.model_admission_failure)
                report = host.events[-1][1]
                self.assertEqual(report, dict(diagnostic=dict(source='harness-local', stage='termination',
                    reason='model_reservation_unavailable', message='Cannot reserve another model request.',
                    execution_occurred='no', resubmission_safe=False), stopping=dict(condition='budget-limit',
                    budget=dict(kind='model-tokens', total_allowance=524288, consumed=consumed,
                                remaining=remaining, next_request_reservation=36864))))
                self.assertEqual(dispatcher.last_rejection, before)
                self.assertEqual(host.events[0][1], before)

    def test_early_finish_uses_current_reservation_and_survives_task_replacement(self):
        case = next(c for c in self.cases('model-codec.json') if c['mode'] == 'context' and c['valid'])
        conversation = NativeConversation(self.protocol, _canonical_value(case['policy'], 4 << 20), 'Task.')
        reservation = conversation.model_reservation()
        conversation._remaining = dict(model_tokens=3 * reservation + 1, model_turns=20)
        conversation.prepare_finalization()
        self.assertNotIn('Harness budget notice', str(conversation.body()))
        conversation._remaining['model_tokens'] -= 1
        self.assertFalse(conversation.prepare_finalization())  # Exactly three reservations allow exploration.
        conversation._remaining['model_tokens'] -= 1
        self.assertTrue(conversation.prepare_finalization())
        self.assertTrue(conversation.can_fund_model())
        self.assertIn('exploration has ended', str(conversation.body()))
        conversation.replace_task('Updated complete task.')
        self.assertIn('Harness budget notice', str(conversation.body()))
        conversation._remaining['model_tokens'] = reservation - 1
        self.assertFalse(conversation.can_fund_model())


if __name__ == "__main__":
    unittest.main()
