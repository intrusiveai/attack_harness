import base64
from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.loop import HarnessLoop

from attack_harness.artifacts import CommittedArtifact
from attack_harness.handlers import FixedHandlers


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 10,
}


@dataclass(frozen=True)
class Reply:
    result: dict | None = None
    error: dict | None = None


class Inputs:
    def __init__(self):
        self.source = {
            "entry_id": "ref-1", "root_kind": "input", "path": "references/one.txt",
            "role": "reference", "media_type": "text/plain", "size_bytes": 6,
            "digest": "sha256:" + "1" * 64,
        }

    def entry(self, identifier):
        if identifier != "ref-1":
            from operator_contracts import ContractError
            raise ContractError("unknown")
        return deepcopy(self.source), b"abcdef"


class Client:
    def __init__(self, operations, responses=()):
        self.operations = frozenset(operations)
        self.responses = list(responses)
        self.requests = []
        self.index = 0

    def operation_id(self, purpose):
        self.index += 1
        return f"{purpose}-{self.index}"

    def request(self, operation, body, *, operation_id):
        self.requests.append((operation, deepcopy(body), operation_id))
        return self.responses.pop(0)


class Artifacts:
    def publish_tool(self, arguments):
        return CommittedArtifact("artifact-1", arguments["purpose"],
                                 "sha256:" + "2" * 64, 4,
                                 arguments["media_type"], "raw", True)


class Observations:
    def read(self, receipt_id, entry_id, offset, max_bytes):
        from attack_harness.observations import ObservationChunk
        return ObservationChunk(receipt_id, entry_id, offset, b"data", True,
                                "available", {"digest": "sha256:" + "3" * 64,
                                "size_bytes": offset + 4,
                                "media_type": "text/plain"}, False, "")


class HandlerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def service(self, operations=(), responses=()):
        loop = HarnessLoop(LIMITS)
        loop.begin_model()
        loop.accept_response(1)
        loop.start_tool("reference_read")
        client = Client(operations, responses)
        return loop, client, FixedHandlers(
            self.protocol, Inputs(), client, loop,
            artifacts=Artifacts(), observations=Observations(),
        )

    def test_reference_read_returns_exact_range_and_charges_bytes(self):
        loop, _, service = self.service()
        result = service.reference_read({"reference_id": "ref-1", "offset": 2,
                                         "max_bytes": 3})
        self.assertEqual(base64.b64decode(result.value["content"]), b"cde")
        self.assertEqual(result.value["source"]["path"], "references/one.txt")
        self.assertFalse(result.value["eof"])
        self.assertEqual(loop.snapshot()["read_bytes"], 3)

    def test_only_advertised_direct_handlers_are_installed(self):
        _, _, service = self.service({"engine.injection_delete", "engine.snapshot_list"})
        self.assertEqual(set(service.handlers()), {
            "reference_read", "injection_delete", "snapshot_list",
        })

    def test_artifact_and_observation_progress_accounting(self):
        loop, _, service = self.service()
        artifact = service.artifact_publish({"purpose": "payload",
            "media_type": "text/plain", "content": {"encoding": "utf8", "text": "data"}})
        self.assertEqual(artifact.value["artifact_receipt"], "artifact-1")
        observed = service.observation_read({"receipt_id": "receipt-1", "entry_id": "entry-1",
                                             "offset": 0, "max_bytes": 8})
        self.assertEqual(base64.b64decode(observed.value["content"]), b"data")
        self.assertEqual(loop.snapshot()["read_bytes"], 4)

    def test_direct_operation_preserves_result_and_known_error_is_preflight(self):
        success = Reply(result={"receipt_id": "delete-1", "attempt_receipt_id": "attempt-1",
                                "action_id": "action-1", "outcome": "already_absent"})
        loop, client, service = self.service({"engine.injection_delete"}, [success])
        result = service.injection_delete({"attempt_receipt_id": "attempt-1",
                                           "action_id": "action-1"})
        self.assertEqual(result.value["outcome"], "already_absent")
        self.assertEqual(client.requests[0][0], "engine.injection_delete")

        error = Reply(error={"code": "POLICY_DENIED", "message": "not permitted",
                             "effect_state": "none", "disposition": "gap-and-continue"})
        _, _, service = self.service({"engine.injection_delete"}, [error])
        from attack_harness.tools import ToolError
        with self.assertRaises(ToolError) as caught:
            service.injection_delete({"attempt_receipt_id": "attempt-1",
                                      "action_id": "action-1"})
        self.assertEqual(caught.exception.value["code"], "POLICY_DENIED")


if __name__ == "__main__":
    unittest.main()
