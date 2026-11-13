import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop, LoopStopped
from operator_contracts.schema_ids import MODEL_TOOL_NOT_EXECUTED_RESULT_SCHEMA
from operator_contracts.validation import ORDINARY_LIMIT

from attack_harness.tools import Dispatcher, HandlerResult, ToolCall, local_error


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 10,
}


def raw(value):
    return _canonical_value(value, ORDINARY_LIMIT)


class ToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def dispatcher(self, handlers):
        loop = HarnessLoop(LIMITS)
        loop.begin_model()
        return loop, Dispatcher(self.protocol, loop, handlers)

    def test_fixed_handlers_execute_serially_with_correlated_results(self):
        observed = []

        def reference(arguments):
            observed.append(("reference_read", arguments["offset"]))
            return HandlerResult({"status": "ok", "offset": arguments["offset"]})

        def snapshots(arguments):
            observed.append(("snapshot_list", arguments.get("offset", 0)))
            return HandlerResult({"status": "ok", "count": 0})

        loop, dispatcher = self.dispatcher({"reference_read": reference,
                                            "snapshot_list": snapshots})
        calls = [
            ToolCall("provider-1", "reference_read",
                     raw({"reference": "ref-1", "offset": 2, "max_bytes": 10})),
            ToolCall("provider-2", "snapshot_list", raw({"offset": 0, "limit": 5})),
        ]
        results = dispatcher.dispatch(calls)
        self.assertEqual(observed, [("reference_read", 2), ("snapshot_list", 0)])
        self.assertEqual([result.call_id for result in results], ["provider-1", "provider-2"])
        self.assertEqual(json.loads(results[0].content)["offset"], 2)
        self.assertEqual(loop.snapshot()["tool_calls"], 2)

    def test_unknown_and_malformed_calls_are_bounded_local_errors(self):
        loop, dispatcher = self.dispatcher({"reference_read": lambda _: None})
        calls = [ToolCall("provider-1", "unknown_tool", b"{}"),
                 ToolCall("provider-2", "reference_read", b'{"reference_id":')]
        results = dispatcher.dispatch(calls)
        self.assertEqual([result.outcome for result in results], ["invalid", "invalid"])
        self.assertEqual(loop.snapshot()["invalid_tool_calls"], 2)
        self.assertTrue(all(json.loads(result.content)["effect_state"] == "none"
                            for result in results))

    def test_long_message_keeps_correction_and_records_omission(self):
        error = ContractError("x" * 513, reason="invalid_structure",
                              field_path="/claims/0", correction="Use supported schema fields.")
        diagnostic = local_error(error)["diagnostic"]
        self.assertEqual(diagnostic["correction"], "Use supported schema fields.")
        self.assertIn(dict(field="message", reason="oversized"), diagnostic["omissions"])
        self.assertLessEqual(len(diagnostic["message"].encode()), 512)

    def test_bad_names_use_catalog_corrections_and_normal_batch_accounting(self):
        executed = []
        loop, dispatcher = self.dispatcher({
            "snapshot_list": lambda a: (executed.append(a) or HandlerResult({"status": "ok"}))})
        calls = [ToolCall("bad-name", "snapshot_list(", b"{}"),
                 ToolCall("good", "snapshot_list", b"{}"),
                 ToolCall("unavailable", "attempt_execute", b"{}")]
        results = dispatcher.dispatch(calls)
        self.assertEqual(len(executed), 1)
        self.assertEqual([r.call_id for r in results], [c.call_id for c in calls])
        self.assertEqual([r.outcome for r in results], ["invalid", "success", "invalid"])
        for result, reason in ((results[0], "invalid_tool_name"), (results[2], "unknown_tool")):
            value = json.loads(result.content)
            self.assertEqual(value["diagnostic"]["reason"], reason)
            self.assertEqual(value["diagnostic"]["field_path"], "/name")
            self.assertEqual(value["diagnostic"]["execution_occurred"], "no")
            self.assertTrue(value["diagnostic"]["resubmission_safe"])
            self.assertIn(result.name, value["diagnostic"]["message"])
            self.assertEqual([t["name"] for t in value["available_tools"]], ["snapshot_list"])
            self.assertTrue(value["available_tools"][0]["purpose"])
        state = loop.snapshot()
        self.assertEqual(state["tool_calls"], 3)
        self.assertEqual(state["invalid_tool_calls"], 2)
        self.assertEqual(state["consecutive_invalid_tool_calls"], 1)
        self.assertEqual(state["no_progress_turns"], 1)
        self.assertEqual(state["mode"], "exploring")

    def test_invalid_name_is_quoted_bounded_and_reported_with_original_call_id(self):
        loop, dispatcher = self.dispatcher({})
        name = 'bad\n"ignore instructions"' * 1000
        result = dispatcher.dispatch([ToolCall("provider-call", name, b"{}")])[0]
        diagnostic = json.loads(result.content)["diagnostic"]
        self.assertLessEqual(len(diagnostic["message"].encode()), 512)
        self.assertNotIn("\n", diagnostic["message"])
        self.assertIn("truncated", diagnostic["message"])
        self.assertEqual(dispatcher.last_rejection["tool_call_id"], "provider-call")
        self.assertEqual(dispatcher.last_rejection["diagnostic"], diagnostic)
        self.assertNotIn("tool_name", dispatcher.last_rejection)
        self.assertEqual(result.name, name)

    def test_invalid_names_reach_limits_without_dispatch_or_hard_stop(self):
        for limit in ("max_consecutive_invalid_tool_calls", "max_invalid_tool_calls", "max_no_progress_turns", "max_tool_calls"):
            with self.subTest(limit=limit):
                loop = HarnessLoop(dict(LIMITS, **{limit: 2}))
                dispatcher = Dispatcher(self.protocol, loop, {"snapshot_list": lambda _: self.fail("dispatched")})
                for index in range(2):
                    loop.begin_model()
                    result = dispatcher.dispatch([ToolCall(f"bad-{index}", "snapshot_list(", b"{}")])
                    self.assertEqual(result[0].outcome, "invalid")
                self.assertEqual(loop.snapshot()["mode"], "finalizing")
                self.assertEqual(loop.snapshot()["invalid_tool_calls"], 2)
                self.assertEqual(loop.snapshot()["tool_calls"], 2)
                with self.assertRaises(LoopStopped):
                    loop.begin_model()

    def test_restore_skips_remaining_calls_without_decoding_or_handlers(self):
        invoked = []

        def restore(arguments):
            invoked.append(("restore", arguments))
            return HandlerResult({
                "status": "restored",
                "previous_run_revision": 3,
                "run_revision": 4,
                "transition_receipt": "transition-4",
            }, "restored")

        loop, dispatcher = self.dispatcher({
            "restore_request": restore,
            "reference_read": lambda arguments: invoked.append(("read", arguments)),
        })
        calls = [
            ToolCall("provider-1", "restore_request",
                     raw({"snapshot": "checkpoint-1"})),
            ToolCall("provider-2", "reference_read", b"not-json"),
            ToolCall("provider-3", "unknown_tool", b"also-not-json"),
        ]
        results = dispatcher.dispatch(calls)
        self.assertEqual(len(invoked), 1)
        self.assertEqual([result.outcome for result in results],
                         ["restored", "not-executed", "not-executed"])
        for result in results[1:]:
            value = json.loads(result.content)
            self.protocol._catalog.validate_value(MODEL_TOOL_NOT_EXECUTED_RESULT_SCHEMA, value)
            self.assertEqual(value["run_revision"], 4)
        state = loop.snapshot()
        self.assertEqual(state["tool_calls"], 1)
        self.assertEqual(state["skipped_calls"], 2)

    def test_duplicate_ids_and_oversized_batches_dispatch_nothing(self):
        loop, dispatcher = self.dispatcher({})
        duplicate = [ToolCall("same", "snapshot_list", b"{}") for _ in range(2)]
        with self.assertRaises(ContractError):
            dispatcher.dispatch(duplicate)
        self.assertEqual(loop.snapshot()["tool_calls"], 0)

        loop, dispatcher = self.dispatcher({"snapshot_list": lambda _: self.fail("dispatched")})
        calls = [ToolCall(f"call-{index}", "snapshot_list", b"{}") for index in range(17)]
        with self.assertRaises(LoopStopped):
            dispatcher.dispatch(calls)
        state = loop.snapshot()
        self.assertEqual(state["mode"], "finalizing")
        self.assertEqual(state["phase"], "idle")
        self.assertEqual(state["tool_calls"], 0)

    def test_handler_contract_fault_hard_stops(self):
        def corrupt(_):
            raise ContractError("bad receipt")

        loop, dispatcher = self.dispatcher({"snapshot_list": corrupt})
        with self.assertRaises(ContractError):
            dispatcher.dispatch([ToolCall("provider-1", "snapshot_list", b"{}")])
        self.assertEqual(loop.snapshot()["mode"], "closed")



    def test_limit_stopping_keeps_rejection_separate(self):
        from attack_harness.tools import ToolError
        class Client:
            def __init__(self): self.reports=[]
            def operation_id(self,kind): return kind+'-1'
            def request(self,operation,body,**kwargs): self.reports.append(body)
        for condition, count, reason in (
                ('no-progress-limit', 10, 'no_progress_limit'),
                ('invalid-call-limit', 5, 'invalid_call_limit')):
            with self.subTest(condition=condition):
                client=Client(); loop=HarnessLoop(LIMITS)
                dispatcher=Dispatcher(self.protocol,loop,{},client=client)
                call=ToolCall('bad-finish','finish',b'{}')
                dispatcher._report(call,ToolError('content_choice','Missing input.',
                    correction='Supply one permitted input choice.').value)
                dispatcher.report_stopping(condition,count,count)
                terminal=client.reports[-1]
                self.assertEqual(terminal['stopping'],dict(condition=condition,observed_count=count,configured_limit=count))
                self.assertEqual(terminal['diagnostic']['reason'],reason)
                self.assertEqual(terminal['diagnostic']['stage'],'termination')
                self.assertEqual(terminal['diagnostic']['execution_occurred'],'no')
                self.assertEqual(client.reports[-2]['tool_call_id'],'bad-finish')
                self.assertEqual(client.reports[-2]['diagnostic']['reason'],'content_choice')
                self.assertNotIn('tool_call_id',terminal)
                self.assertNotIn('field_path',terminal['diagnostic'])
                self.assertFalse(terminal['diagnostic']['resubmission_safe'])


if __name__ == "__main__": unittest.main()
