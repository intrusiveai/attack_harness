from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
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
                            "engine.request_stop"})

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
        if operation == "engine.record_append":
            return Reply({"receipt_id": "record-1", "record_kind": "conclusion",
                "assertion_origin": "harness", "attribution": {
                    "campaign_id": self.campaign_id, "launch_id": self.launch_id,
                    "run_revision": self.run_revision}})
        if operation == "engine.request_stop":
            requested_state = body["conclusion"]["state"]
            return Reply({"status": "accepted", "stop_receipt": "stop-1",
                "execution_admission": "closed",
                "conclusion_state": ("unavailable" if self.bad_stop
                                     else requested_state),
                "exit_required": True, "exit_within_ms": 5000,
                "finalization_status": "pending"})
        self.fail("unexpected-operation")

    def fail(self, reason, *, receipt=None):
        self.failed = (reason, receipt)
        raise RuntimeStopped(reason, receipt=receipt)


class Artifacts:
    def __init__(self, events):
        self.events = events
        self.raw = None

    def publish(self, purpose, media_type, content, *, canonicalization, before_request):
        self.raw = content
        for operation, body in (
            ("engine.artifact_begin", {"purpose": purpose}),
            ("engine.artifact_put_part", {"offset": 0}),
            ("engine.artifact_commit", {"upload_id": "upload-1"}),
        ):
            before_request(operation, body)
            self.events.append((operation, deepcopy(body)))
        return CommittedArtifact("artifact-1", purpose, "sha256:" + "8" * 64,
                                 len(content), media_type, canonicalization, True)


class Attempts:
    receipts = frozenset({"attempt-1"})


class Observations:
    def observed(self, receipt_id, entry_id):
        return (receipt_id, entry_id) == ("attempt-1", "entry-1")


class ConclusionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def draft(self):
        return {
            "status": "completed", "finish_reason": "objectives-addressed",
            "summary": "Bounded assessment completed.",
            "objectives": [{"objective_id": "objective-1", "outcome": "inconclusive",
                "summary": "One experiment ran.", "attempt_receipt_refs": ["attempt-1"],
                "record_refs": ["record-previous"]}],
            "hypotheses": [], "claims": [],
            "coverage": [{"objective_id": "objective-1", "status": "tested",
                "reason": "One attempt completed.", "attempt_receipt_refs": ["attempt-1"]}],
            "uncertainties": [], "record_refs": ["record-previous"],
        }

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

    def test_stages_in_batch_then_commits_artifact_record_and_stop(self):
        events, loop, _, artifacts, finalizer = self.setup_finalizer()
        dispatcher = Dispatcher(self.protocol, loop, {"request_stop": finalizer.stage})
        results = dispatcher.dispatch([ToolCall("finish-1", "request_stop",
            json.dumps(self.draft(), separators=(",", ":")).encode())])
        self.assertEqual(results[0].outcome, "success")
        self.assertTrue(finalizer.pending)
        self.assertEqual(loop.snapshot()["mode"], "finalizing")
        self.assertEqual(events, [])

        acknowledgement = finalizer.finish()
        self.assertEqual(acknowledgement["stop_receipt"], "stop-1")
        self.assertEqual([event[0] for event in events], [
            "engine.artifact_begin", "engine.artifact_put_part", "engine.artifact_commit",
            "engine.record_append", "engine.request_stop",
        ])
        conclusion = self.protocol.validate_conclusion(artifacts.raw)
        self.assertEqual(conclusion["binding"]["run_revision"], 4)
        self.assertFalse(finalizer.pending)

    def test_unknown_receipt_is_a_local_invalid_without_finalization(self):
        events, loop, _, _, finalizer = self.setup_finalizer()
        draft = self.draft()
        draft["objectives"][0]["attempt_receipt_refs"] = ["unknown-attempt"]
        dispatcher = Dispatcher(self.protocol, loop, {"request_stop": finalizer.stage})
        results = dispatcher.dispatch([ToolCall("finish-1", "request_stop",
            json.dumps(draft, separators=(",", ":")).encode())])
        self.assertEqual(results[0].outcome, "invalid")
        self.assertFalse(finalizer.pending)
        self.assertEqual(loop.snapshot()["mode"], "exploring")
        self.assertEqual(events, [])

    def test_conflicting_stop_acknowledgement_is_terminal(self):
        _, loop, client, _, finalizer = self.setup_finalizer(bad_stop=True)
        dispatcher = Dispatcher(self.protocol, loop, {"request_stop": finalizer.stage})
        dispatcher.dispatch([ToolCall("finish-1", "request_stop",
            json.dumps(self.draft(), separators=(",", ":")).encode())])
        with self.assertRaises(RuntimeStopped):
            finalizer.finish()
        self.assertEqual(client.failed, ("finalization-failed", None))

    def test_explicit_unavailable_stop_has_no_artifact_or_record(self):
        events, loop, _, _, finalizer = self.setup_finalizer()
        loop.accept_response(0)
        loop.end_turn()
        result = finalizer.finish_unavailable("context-limit")
        self.assertEqual(result["conclusion_state"], "unavailable")
        self.assertEqual([event[0] for event in events], ["engine.request_stop"])
        self.assertEqual(events[0][1], {
            "finish_reason": "context-limit",
            "conclusion": {"state": "unavailable", "reason": "context-limit"},
        })


if __name__ == "__main__":
    unittest.main()
