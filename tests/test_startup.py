from collections import deque
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.validation import CONTROL_LIMIT

from attack_harness.runtime import RuntimeStopped
from attack_harness.startup import Startup


class Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, seconds=.1):
        self.now += seconds


class StartupTransport:
    def __init__(self, inbound, events):
        self.inbound = deque(inbound)
        self.events = events
        self.sent = []
        self.closed = False

    def pump(self):
        self.events.append("pump")

    def take(self, lane):
        if lane == "control-in" and self.inbound:
            return self.inbound.popleft()
        return None

    def send(self, lane, raw):
        self.events.append("send:" + lane)
        self.sent.append(raw)

    def pin_descriptors(self):
        self.events.append("pin")

    def close(self):
        self.closed = True


class FakeInputs:
    events = None

    def __init__(self, protocol, prefix, loader_digest, *, tick, **_):
        self.protocol = protocol
        self.prefix = prefix
        self.loader_digest = loader_digest
        self.tick = tick
        self.events.append("inputs")
        self.initialize = protocol.validate_control("host", prefix[2])

    def initialized_body(self):
        body = deepcopy(self.initialize["body"])
        body.pop("timeout_ms")
        bootstrap = self.protocol.validate_control("host", self.prefix[0])
        body["contract"] = bootstrap["body"]["contract"]
        return body

    def admit(self, initialized, admission):
        self.events.append("admit")
        self.protocol.validate_control("guest", initialized)
        return deepcopy(self.protocol.validate_control("host", admission)["body"])


class StartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        protocol = Protocol(source)
        files = {path.name: path.read_bytes() for path in source.glob("*.schema.json")}
        files.update({name: (source / name).read_bytes() for name in ("catalog.json", "operations.json")})
        profiles = {"jcs-v1": "semantics/digests", "manifest-paths-v1": "semantics/paths",
                    "harness-loop-v1": "semantics/limits"}
        files.update({name: b"Test semantic profile.\n" for name in profiles.values()})
        manifest, cls.pin = protocol.build_package_manifest("0.0.0", files, profiles)
        cls.protocol = protocol.load_verified_protocol(manifest, files, cls.pin)
        cls.example = json.loads((source / "fixtures/startup-example.json").read_text())

    def messages(self, *, transport="fifo", platform="linux/amd64"):
        messages = deepcopy(self.example)
        contract = {"version": self.pin["package_version"], "digest": self.pin["package_digest"],
                    **self.protocol.registry_digests()}
        messages[0]["body"]["contract"] = contract
        messages[0]["body"]["transport"] = transport
        messages[0]["body"]["host_platform"] = platform
        messages[1]["body"] = {key: value for key, value in messages[0]["body"].items()
                                if key != "timeout_ms"}
        messages[3]["body"]["contract"] = contract
        return [_canonical_value(message, CONTROL_LIMIT) for message in messages]

    def test_exact_order_confinement_precedes_inputs_and_admission(self):
        wire = self.messages()
        events = []
        FakeInputs.events = events
        transport = StartupTransport((wire[0], wire[2], wire[4]), events)
        startup = Startup(self.protocol, transport, "fifo", "sha256:" + "1" * 64,
                          lambda: events.append("confine"), inputs_factory=FakeInputs)
        session = startup.run()
        self.assertEqual(events.index("pin") + 1, events.index("confine"))
        self.assertLess(events.index("confine"), events.index("inputs"))
        self.assertLess(events.index("inputs"), events.index("admit"))
        self.assertEqual(session.client.run_revision, 3)
        self.assertEqual([self.protocol.validate_control("guest", raw)["kind"]
                          for raw in transport.sent], ["confinement_ready", "initialized"])

    def test_transport_platform_mismatch_fails_before_confinement(self):
        wire = self.messages(transport="spool", platform="darwin/arm64")
        events = []
        transport = StartupTransport((wire[0],), events)
        startup = Startup(self.protocol, transport, "fifo", "loader",
                          lambda: events.append("confine"), inputs_factory=FakeInputs)
        with self.assertRaises(RuntimeStopped):
            startup.run()
        self.assertNotIn("confine", events)
        self.assertTrue(transport.closed)

    def test_confinement_failure_closes_before_inputs(self):
        wire = self.messages()
        events = []
        FakeInputs.events = events
        transport = StartupTransport((wire[0],), events)

        def fail():
            events.append("confine")
            raise RuntimeError("seccomp unavailable")

        startup = Startup(self.protocol, transport, "fifo", "loader", fail,
                          inputs_factory=FakeInputs)
        with self.assertRaises(RuntimeStopped):
            startup.run()
        self.assertTrue(transport.closed)
        self.assertNotIn("inputs", events)

    def test_launch_terminate_and_startup_deadline_are_terminal(self):
        wire = self.messages()
        terminate = deepcopy(self.example[0])
        terminate.update(kind="terminate", seq=1)
        terminate["body"] = {"reason": "user-request", "exit_required": True}
        terminate_raw = _canonical_value(terminate, CONTROL_LIMIT)
        events = []
        transport = StartupTransport((wire[0], terminate_raw), events)
        startup = Startup(self.protocol, transport, "fifo", "loader", lambda: None,
                          inputs_factory=FakeInputs)
        with self.assertRaises(RuntimeStopped) as caught:
            startup.run()
        self.assertEqual(caught.exception.reason, "user-request")

        clock = Clock()
        transport = StartupTransport((), [])
        startup = Startup(self.protocol, transport, "fifo", "loader", lambda: None,
                          inputs_factory=FakeInputs, clock=clock,
                          idle=lambda: clock.advance(1))
        with self.assertRaises(RuntimeStopped) as caught:
            startup.run()
        self.assertEqual(caught.exception.reason, "deadline-exceeded")


if __name__ == "__main__":
    unittest.main()
