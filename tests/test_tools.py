import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop, LoopStopped
from operator_contracts.schema_ids import MODEL_TOOL_NOT_EXECUTED_RESULT_SCHEMA
from operator_contracts.validation import ORDINARY_LIMIT

from attack_harness.tools import Dispatcher, HandlerResult, ToolCall


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
                     raw({"reference_id": "ref-1", "offset": 2, "max_bytes": 10})),
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
                     raw({"source_session": "source-1", "checkpoint_id": "checkpoint-1"})),
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


if __name__ == "__main__":
    unittest.main()
