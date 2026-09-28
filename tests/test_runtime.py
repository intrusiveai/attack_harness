from collections import deque
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.validation import ORDINARY_LIMIT

from attack_harness.runtime import OrdinaryClient, RuntimeStopped


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds=.001):
        self.now += seconds


class FakeTransport:
    def __init__(self, protocol, responder=None):
        self.protocol = protocol
        self.responder = responder
        self.inbound = {"ordinary-in": deque(), "control-in": deque()}
        self.sent = []
        self.pending = deque()
        self.closed = False

    def send(self, lane, raw):
        if self.closed:
            raise ContractError("closed")
        self.protocol.validate_lane_message(lane, raw)
        self.sent.append((lane, raw))
        if self.responder is not None:
            reply = self.responder(raw)
            if reply is not None:
                self.pending.append(reply)

    def pump(self):
        if self.closed:
            raise ContractError("closed")
        if self.pending:
            self.inbound["ordinary-in"].append(self.pending.popleft())

    def take(self, lane):
        return self.inbound[lane].popleft() if self.inbound[lane] else None

    def close(self):
        self.closed = True


class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(source)
        cases = json.loads((source / "fixtures/ordinary-protocol.json").read_text())
        cls.responses = {
            case["name"]: case["response"]
            for case in cases if case.get("valid") and "response" in case
        }
        cls.operations = sorted(item["name"] for item in cls.protocol.operations())

    def admission(self):
        return {
            "campaign_id": "campaign-1",
            "launch_id": "launch-1",
            "run_revision": 3,
            "operations": self.operations,
        }

    def responder(self, fixture_name):
        template = self.responses[fixture_name]

        def respond(raw):
            request = self.protocol.validate_request(raw)
            response = deepcopy(template)
            for key in ("campaign_id", "launch_id", "run_revision", "call_id", "operation_id", "operation"):
                response[key] = request[key]
            return _canonical_value(response, ORDINARY_LIMIT)
        return respond

    @staticmethod
    def artifact_body():
        return {
            "purpose": "payload",
            "artifact": {
                "digest": "sha256:" + "0" * 64,
                "size_bytes": 2,
                "media_type": "application/json",
                "canonicalization": "raw",
            },
        }

    def test_correlated_request_and_exact_local_duplicate(self):
        transport = FakeTransport(self.protocol, self.responder("artifact_begin response"))
        client = OrdinaryClient(self.protocol, transport, self.admission())
        reply = client.request("engine.artifact_begin", self.artifact_body(), operation_id="upload-operation")
        self.assertEqual(reply.result["upload_id"], "upload-1")
        self.assertEqual(len(transport.sent), 1)
        duplicate = client.request("engine.artifact_begin", self.artifact_body(), operation_id="upload-operation")
        self.assertEqual(duplicate.response_raw, reply.response_raw)
        self.assertEqual(len(transport.sent), 1)
        changed = self.artifact_body()
        changed["purpose"] = "carrier"
        with self.assertRaises(ContractError):
            client.request("engine.artifact_begin", changed, operation_id="upload-operation")

    def test_restore_advances_revision_once_and_next_request_uses_it(self):
        restore = self.responder("restore_request response")
        artifact = self.responder("artifact_begin response")

        def respond(raw):
            request = self.protocol.validate_request(raw)
            return (restore if request["operation"] == "engine.restore_request" else artifact)(raw)

        transport = FakeTransport(self.protocol, respond)
        client = OrdinaryClient(self.protocol, transport, self.admission())
        body = {"source_session": "source-1", "checkpoint_id": "checkpoint-1"}
        client.request("engine.restore_request", body, operation_id="restore-1")
        self.assertEqual(client.run_revision, 4)
        client.request("engine.restore_request", body, operation_id="restore-1")
        self.assertEqual(client.run_revision, 4)
        client.request("engine.artifact_begin", self.artifact_body(), operation_id="upload-2")
        sent = self.protocol.validate_request(transport.sent[-1][1])
        self.assertEqual(sent["run_revision"], 4)

    def test_terminal_error_and_host_terminate_stop_without_retry(self):
        transport = FakeTransport(self.protocol, self.responder("error OUTCOME_UNKNOWN unknown terminate"))
        client = OrdinaryClient(self.protocol, transport, self.admission())
        with self.assertRaises(RuntimeStopped) as caught:
            client.request("engine.artifact_begin", self.artifact_body(), operation_id="uncertain-1")
        self.assertEqual(caught.exception.reason, "operation-failed")
        self.assertTrue(transport.closed)

        transport = FakeTransport(self.protocol)
        client = OrdinaryClient(self.protocol, transport, self.admission())
        control = {
            "api_version": "operator.dev/engine-pipe/v1alpha1",
            "kind": "terminate",
            "seq": 0,
            "campaign_id": "campaign-1",
            "launch_id": "launch-1",
            "run_revision": 999,
            "body": {"reason": "user-request", "stop_receipt": "stop-1", "exit_required": True},
        }
        transport.inbound["control-in"].append(_canonical_value(control, ORDINARY_LIMIT))
        with self.assertRaises(RuntimeStopped) as caught:
            client.tick()
        self.assertEqual(caught.exception.reason, "user-request")
        self.assertEqual(caught.exception.receipt, "stop-1")

    def test_response_deadline_is_nonrenewing(self):
        clock = Clock()
        transport = FakeTransport(self.protocol)
        client = OrdinaryClient(self.protocol, transport, self.admission(), clock=clock,
                                idle=lambda: clock.advance(.011))
        with self.assertRaises(RuntimeStopped) as caught:
            client.request("engine.artifact_begin", self.artifact_body(),
                           operation_id="timeout-1", timeout_ms=10)
        self.assertEqual(caught.exception.reason, "deadline-exceeded")
        self.assertEqual(len(transport.sent), 1)


if __name__ == "__main__":
    unittest.main()
