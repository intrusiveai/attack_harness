from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol, ContractError
from operator_contracts.loop import HarnessLoop

from attack_harness.artifacts import CommittedArtifact
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.runtime import RuntimeStopped
from attack_harness.tools import Dispatcher, ToolCall


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 10,
}


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        self.now += 1
        return self.now


class Inputs:
    def __init__(self):
        self.binding = {
            "campaign_id": "campaign-1", "launch_id": "launch-1", "run_revision": 1,
            "input_tree_digest": "sha256:" + "1" * 64,
            "engine_context_digest": "sha256:" + "2" * 64,
            "prompt_digest": "sha256:" + "3" * 64,
            "skill_set_digest": "sha256:" + "4" * 64,
            "image_digest": "sha256:" + "5" * 64,
            "release_record_digest": "sha256:" + "6" * 64,
            "contract_package_digest": "sha256:" + "7" * 64,
            "contract_package_version": "1.0.0",
        }

    def conclusion_binding(self, revision):
        result = deepcopy(self.binding)
        result["run_revision"] = revision
        return result

    def bundle(self):
        return {"objectives": [{"objective_id": "objective-1"}],
                "scenarios": [{"scenario_id": "scenario-1"}]}

    def entry(self, entry_id):
        if entry_id != "reference-1":
            from operator_contracts import ContractError
            raise ContractError("unknown")
        return {"entry_id": entry_id, "size_bytes": 10}, b"0123456789"


class Reply:
    def __init__(self, result):
        self.result, self.error = result, None


class Client:
    campaign_id = "campaign-1"
    launch_id = "launch-1"
    run_revision = 4
    operations = frozenset({"engine.artifact_begin", "engine.artifact_put_part",
                            "engine.artifact_commit", "engine.record_append",
                            "engine.finish"})

    def __init__(self, events, *, bad_stop=False):
        self.events = events
        self.index = 0
        self.bad_stop = bad_stop
        self.failed = None

    def operation_id(self, purpose):
        self.index += 1
        return f"{purpose}-{self.index}"

    def request(self, operation, body, *, operation_id):
        self.events.append((operation, deepcopy(body)))
        if operation == "engine.finish":
            if self.bad_stop:
                reply = Reply(None)
                reply.error = {"code": "INVALID_ARGUMENTS", "effect_state": "none",
                    "disposition": "correct-and-resubmit", "message": "Unknown receipt.",
                    "diagnostic": {"source": "operator", "field_path": "/assessment/objectives/0/attempt_receipt_refs/0"}}
                return reply
            return Reply({"status": "accepted", "stop_receipt": "stop-1",
                "execution_admission": "closed", "assessment_state": "unavailable" if "unavailable" in body else "committed",
                "exit_required": True, "exit_within_ms": 5000, "finalization_status": "pending"})
        self.fail("unexpected-operation")

    def fail(self, reason, *, receipt=None):
        self.failed = (reason, receipt)
        raise RuntimeStopped(reason, receipt=receipt)


class Artifacts:
    def __init__(self, events):
        self.events = events
        self.raw = None

    def artifact(self, receipt):
        if receipt == "artifact-1": return object()
        raise ContractError("unknown receipt")


class Attempts:
    receipts = frozenset({"attempt-1"})
    def reference_category(self, value):
        return {"attempt-1": "execution receipt", "rejected-call": "rejected submission"}.get(value)


class Observations:
    def observed(self, receipt_id, entry_id):
        return (receipt_id, entry_id) == ("attempt-1", "entry-1")


class ConclusionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def draft(self):
        return {"finish_reason": "objectives-addressed", "assessment": {
            "summary": "No attempt was needed.", "objectives": [{"objective_id": "objective-1",
                "outcome": "not-tested", "summary": "Not tested."}]}}

    def setup_finalizer(self, *, bad_stop=False):
        events = []
        clock = Clock()
        loop = HarnessLoop(LIMITS)
        loop.begin_model()
        client = Client(events, bad_stop=bad_stop)
        artifacts = Artifacts(events)
        finalizer = ConclusionFinalizer(
            self.protocol, client, Inputs(), loop, artifacts,
            attempts=Attempts(), observations=Observations(),
            record_receipts={"record-previous"}, campaign_deadline_ms=10000,
            artifact_remaining=1 << 20, clock=clock,
        )
        return events, loop, client, artifacts, finalizer

    def dispatch(self, loop, finalizer, arguments):
        return Dispatcher(self.protocol, loop, {"finish": finalizer.stage}).dispatch([
            ToolCall("finish-1", "finish", json.dumps(arguments).encode())])[0]

    def test_minimal_zero_attempt_finishes_once_with_cleanup_pending(self):
        events, loop, _, _, finalizer = self.setup_finalizer()
        result = self.dispatch(loop, finalizer, self.draft())
        self.assertEqual(result.outcome, "success")
        self.assertEqual([e[0] for e in events], ["engine.finish"])
        self.assertEqual(finalizer.finish()["finalization_status"], "pending")
        self.assertEqual(loop.snapshot()["mode"], "finalizing")
        self.assertEqual(finalizer.finish(), result.value if hasattr(result, "value") else json.loads(result.content))
        self.assertEqual(len(events), 1)

    def test_rejected_submission_and_artifact_are_not_execution_receipts(self):
        for ref in ("rejected-call", "artifact-1"):
            events, loop, _, _, finalizer = self.setup_finalizer()
            draft = self.draft()
            draft["assessment"]["objectives"][0]["attempt_receipt_refs"] = [ref]
            result = self.dispatch(loop, finalizer, draft)
            diagnostic = json.loads(result.content)["diagnostic"]
            self.assertEqual(diagnostic["reason"], "reference_category")
            self.assertEqual(diagnostic["field_path"], "/objectives/0/attempt_receipt_refs/0")
            self.assertFalse(finalizer.pending)
            self.assertFalse(events)

    def test_host_rejection_remains_correctable_and_keeps_diagnostic(self):
        events, loop, _, _, finalizer = self.setup_finalizer(bad_stop=True)
        result = self.dispatch(loop, finalizer, self.draft())
        self.assertEqual(result.outcome, "preflight-rejected")
        self.assertEqual(json.loads(result.content)["diagnostic"]["source"], "operator")
        self.assertEqual(loop.snapshot()["mode"], "exploring")
        self.assertFalse(finalizer.pending)

    def test_explicit_unavailable_finish_preserves_specific_reason(self):
        events, loop, _, _, finalizer = self.setup_finalizer()
        loop.accept_response(0)
        loop.end_turn()
        result = finalizer.finish_unavailable("invalid-call-limit")
        self.assertEqual(result["assessment_state"], "unavailable")
        self.assertEqual(events, [("engine.finish", {"finish_reason": "harness-error",
            "unavailable": {"reason": "invalid-call-limit"}})])


if __name__ == "__main__": unittest.main()
