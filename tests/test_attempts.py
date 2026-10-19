import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import HarnessLoop

from attack_harness.artifacts import CommittedArtifact
from attack_harness.attempts import AttemptExecutor
from attack_harness.runtime import RuntimeStopped
from attack_harness.tools import Dispatcher, ToolCall, ToolError


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 10,
}


class Reply:
    def __init__(self, *, result=None, error=None):
        self.result, self.error = result, error


class Client:
    operations = frozenset({"engine.attempt_execute"})

    def __init__(self, status="completed"):
        self.status = status
        self.index = 0
        self.requests = []
        self.failure = None

    def operation_id(self, purpose):
        self.index += 1
        return f"{purpose}-{self.index}"

    def request(self, operation, body, *, operation_id):
        self.requests.append((operation, body, operation_id))
        if self.status == "rejected":
            return Reply(result={
                "api_version": "operator.dev/engine-attempt-result/v1alpha2",
                "kind": "EngineAttemptResult", "request_id": operation_id,
                "attempt_id": "host-attempt-1", "status": "rejected",
                "stage": "host-validation", "target_contact": "none",
                "invocation_state": "not-dispatched", "cleanup_state": "not-needed",
                "retry_disposition": "correct-and-resubmit",
                "errors": [{"code": "POLICY_DENIED", "instance_path": "",
                            "message": "host rejected attempt"}],
            })
        result = {
            "api_version": "operator.dev/engine-attempt-result/v1alpha2",
            "kind": "EngineAttemptResult", "request_id": operation_id,
            "attempt_id": "host-attempt-1", "receipt_id": "receipt-1",
            "status": self.status,
            "stage": "complete" if self.status == "completed" else "delivery",
            "target_contact": "attempted",
            "invocation_state": "succeeded" if self.status == "completed" else "failed",
            "cleanup_state": "not-needed", "retry_disposition": "do-not-retry",
            "errors": [] if self.status == "completed" else [{
                "code": "DELIVERY_FAILED", "instance_path": "", "message": "failed",
            }],
        }
        if self.status == "completed":
            result["feedback"] = {
                "profile": "black-box", "collection_state": "complete",
                "boundary": "invocation-completed", "categories": [
                    {"kind": kind, "state": "empty"} for kind in (
                        "target_output", "operation_error", "injection_delivery", "oracle_outcome")
                ], "entries": [],
            }
        return Reply(result=result)

    def fail(self, reason, *, receipt=None):
        self.failure = (reason, receipt)
        raise RuntimeStopped(reason, receipt=receipt)


class Artifacts:
    def __init__(self, descriptor, content):
        self.descriptor, self._content = descriptor, content
        self.value = CommittedArtifact("artifact-1", "payload", retained=True,
                                       **descriptor)

    def committed(self, descriptor, purpose):
        if purpose != "payload" or descriptor != self.descriptor:
            raise ContractError("not committed")
        return self.value

    def content(self, receipt_id):
        if receipt_id != "artifact-1":
            raise ContractError("not retained")
        return self._content


class AttemptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.root)
        cls.context = json.loads((cls.root / "fixtures/engine-context-example.json").read_text())
        cls.bundle = {"scenarios": [{"scenario_id": "scenario-marker"}]}
        cls.content = b'{"query":"hello"}'
        cls.descriptor = {
            "digest": raw_digest(cls.content), "size_bytes": len(cls.content),
            "media_type": "application/json", "canonicalization": "raw",
        }

    def loop(self):
        loop = HarnessLoop(LIMITS)
        loop.begin_model()
        loop.accept_response(1)
        loop.start_tool("attempt_execute")
        return loop

    def arguments(self, **changes):
        value = {"operation_id": "invoke", "input": {"encoding": "json", "value": {"query": "hello"}}}
        value.update(changes)
        return value

    def executor(self, client=None):
        client = client or Client()
        loop = self.loop()
        executor = AttemptExecutor(self.protocol, client,
                                   Artifacts(self.descriptor, self.content),
                                   self.context, self.bundle, loop)
        return loop, client, executor

    def test_invalid_arguments_do_not_allocate_or_dispatch(self):
        _, client, executor = self.executor()
        for raw in (b"[]", b"{}", b'{"request_id":"forged"}'):
            with self.assertRaises(ToolError):
                executor(ToolCall("bad", "attempt_execute", raw, batch_id="batch-1"))
        self.assertEqual(client.index, 0)
        self.assertEqual(client.requests, [])
        self.assertEqual(executor.receipts, frozenset())

    def test_complete_request_uses_trusted_identity_and_duplicate_is_local(self):
        loop, client, executor = self.executor()
        call = ToolCall("attempt-call", "attempt_execute",
                        _canonical_value(self.arguments(), 1 << 20), batch_id="batch-1")
        result = executor(call)
        self.assertEqual(result.outcome, "success")
        self.assertEqual(executor(call), result)
        self.assertEqual(len(client.requests), 1)
        operation, request, operation_id = client.requests[0]
        self.assertEqual(operation, "engine.attempt_execute")
        self.assertEqual(request, self.arguments())
        self.assertTrue(operation_id.startswith("attempt-"))
        self.assertEqual(executor.receipts, {"receipt-1"})
        self.assertEqual(loop.snapshot()["tool_calls"], 1)

    def test_host_rejection_is_not_an_execution_receipt(self):
        _, client, executor = self.executor(Client("rejected"))
        raw = _canonical_value(self.arguments(), 1 << 20)
        first = executor(ToolCall("same", "attempt_execute", raw, batch_id="batch-1"))
        second = executor(ToolCall("same", "attempt_execute", raw, batch_id="batch-2"))
        self.assertEqual(first.outcome, "preflight-rejected")
        self.assertEqual(second.outcome, "preflight-rejected")
        self.assertNotEqual(client.requests[0][2], client.requests[1][2])
        self.assertEqual(executor.reference_category("same"), "rejected submission")
        self.assertFalse(executor.receipts)

    def test_dispatcher_counts_typed_local_rejection_as_invalid(self):
        loop = HarnessLoop(LIMITS)
        loop.begin_model()
        client = Client()
        executor = AttemptExecutor(self.protocol, client,
                                   Artifacts(self.descriptor, self.content),
                                   self.context, self.bundle, loop)
        dispatcher = Dispatcher(self.protocol, loop, {},
                                raw_handlers={"attempt_execute": executor})
        results = dispatcher.dispatch([
            ToolCall("empty", "attempt_execute", b"{}", batch_id="batch-1")
        ])
        self.assertEqual(results[0].outcome, "invalid")
        self.assertEqual(json.loads(results[0].content)["status"], "error")
        self.assertEqual(loop.snapshot()["invalid_tool_calls"], 1)

    def test_failed_attempt_is_terminal_after_validated_receipt(self):
        client = Client("failed")
        _, _, executor = self.executor(client)
        with self.assertRaises(RuntimeStopped):
            executor(ToolCall("attempt-call", "attempt_execute",
                _canonical_value(self.arguments(), 1 << 20), batch_id="batch-1"))
        self.assertEqual(client.failure, ("attempt-failed", "receipt-1"))


if __name__ == "__main__":
    unittest.main()
