"""Exact five-message startup coordinator and fixed transport selection."""

from dataclasses import dataclass
import os
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.startup import require
from operator_contracts.validation import CONTROL_LIMIT

from .fifo import FIFO
from .inputs import Inputs
from .runtime import OrdinaryClient, RuntimeStopped
from .spool import Spool


@dataclass(frozen=True)
class AdmittedSession:
    inputs: Inputs
    client: OrdinaryClient
    admission: dict


def transport_from_environment(protocol, environ=os.environ):
    """Select only the launcher-owned installed transport adapter."""
    value = environ.get("OPERATOR_TRANSPORT")
    require(value in ("fifo", "spool"))
    return FIFO(protocol) if value == "fifo" else Spool(protocol)


class Startup:
    """Coordinate startup without reading campaign data before confinement."""

    def __init__(self, protocol, transport, transport_name, loader_digest,
                 install_confinement, *, inputs_factory=Inputs,
                 clock=time.monotonic, idle=lambda: time.sleep(.001),
                 inputs_options=None):
        require(transport_name in ("fifo", "spool") and callable(install_confinement))
        self.protocol = protocol
        self.transport = transport
        self.transport_name = transport_name
        self.loader_digest = loader_digest
        self.install_confinement = install_confinement
        self.inputs_factory = inputs_factory
        self.clock = clock
        self.idle = idle
        self.inputs_options = dict(inputs_options or {})
        self._deadline = clock() + 60
        self._bootstrap = None

    def _fail(self, reason="protocol-error"):
        self.transport.close()
        raise RuntimeStopped(reason)

    def _pump(self):
        if self.clock() >= self._deadline:
            self._fail("deadline-exceeded")
        try:
            self.transport.pump()
        except (OSError, RuntimeError, ContractError):
            self._fail()

    def _next_control(self, expected):
        while True:
            self._pump()
            raw = self.transport.take("control-in")
            if raw is None:
                self.idle()
                continue
            try:
                message = self.protocol.validate_control("host", raw)
                if message["kind"] == "terminate":
                    self._fail(message["body"]["reason"])
                require(message["kind"] == expected)
                if self._bootstrap is not None:
                    require(all(message[key] == self._bootstrap[key]
                                for key in ("campaign_id", "launch_id", "run_revision")))
                return raw, message
            except RuntimeStopped:
                raise
            except ContractError:
                self._fail()

    def _tick_inputs(self):
        """Service termination while immutable input reads yield control."""
        self._pump()
        raw = self.transport.take("control-in")
        if raw is None:
            return
        try:
            message = self.protocol.validate_control("host", raw)
            require(message["campaign_id"] == self._bootstrap["campaign_id"] and
                    message["launch_id"] == self._bootstrap["launch_id"] and
                    message["kind"] == "terminate")
            self._fail(message["body"]["reason"])
        except RuntimeStopped:
            raise
        except ContractError:
            self._fail()

    def _send_control(self, kind, sequence, body):
        message = {
            "api_version": "operator.dev/engine-pipe/v1alpha1",
            "kind": kind,
            "seq": sequence,
            "campaign_id": self._bootstrap["campaign_id"],
            "launch_id": self._bootstrap["launch_id"],
            "run_revision": self._bootstrap["run_revision"],
            "body": body,
        }
        raw = _canonical_value(message, CONTROL_LIMIT)
        self.protocol.validate_control("guest", raw)
        self.transport.send("control-out", raw)
        return raw

    def run(self):
        try:
            bootstrap_raw, bootstrap = self._next_control("bootstrap")
            self._bootstrap = bootstrap
            body = bootstrap["body"]
            pin = self.protocol.package_identity()
            require(pin is not None and body["contract"]["version"] == pin["package_version"]
                    and body["contract"]["digest"] == pin["package_digest"])
            require(all(body["contract"][key] == value
                        for key, value in self.protocol.registry_digests().items()))
            require(body["transport"] == self.transport_name)
            require((body["host_platform"].startswith("linux/") and self.transport_name == "fifo") or
                    (body["host_platform"].startswith("darwin/") and self.transport_name == "spool"))
            self._deadline = min(self._deadline, self.clock() + body["timeout_ms"] / 1000)

            pin_descriptors = getattr(self.transport, "pin_descriptors", None)
            if pin_descriptors is not None:
                pin_descriptors()
            self.install_confinement()
            ready_body = {key: value for key, value in body.items() if key != "timeout_ms"}
            ready_raw = self._send_control("confinement_ready", 0, ready_body)

            initialize_raw, initialize = self._next_control("initialize")
            self._deadline = self.clock() + initialize["body"]["timeout_ms"] / 1000
            inputs = self.inputs_factory(
                self.protocol, (bootstrap_raw, ready_raw, initialize_raw), self.loader_digest,
                tick=self._tick_inputs, **self.inputs_options,
            )
            initialized_raw = self._send_control("initialized", 1, inputs.initialized_body())
            admission_raw, admission_message = self._next_control("admission_open")
            admission = inputs.admit(initialized_raw, admission_raw)
            merged = dict(admission,
                          campaign_id=admission_message["campaign_id"],
                          launch_id=admission_message["launch_id"],
                          run_revision=admission_message["run_revision"])
            client = OrdinaryClient(self.protocol, self.transport, merged,
                                    clock=self.clock, idle=self.idle)
            return AdmittedSession(inputs, client, admission)
        except RuntimeStopped:
            raise
        except (OSError, RuntimeError, ContractError):
            self._fail()
