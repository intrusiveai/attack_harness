"""Single-threaded admitted ordinary-operation scheduler.

The physical FIFO/spool implementations own transfer deadlines and sequencing.
This module owns operation correlation, response deadlines, launch-scoped control
handling, duplicate suppression, and the active target revision.
"""

from copy import deepcopy
from dataclasses import dataclass
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT, MAX_SAFE_INTEGER


@dataclass(frozen=True)
class OperationReply:
    """One fully correlated ordinary result or typed host error."""

    request_raw: bytes
    response_raw: bytes
    message: dict

    @property
    def result(self):
        return deepcopy(self.message.get("result"))

    @property
    def error(self):
        return deepcopy(self.message.get("error"))


class RuntimeStopped(ContractError):
    """The launch cannot issue more ordinary work."""

    def __init__(self, reason, *, receipt=None):
        super().__init__("attack harness runtime stopped")
        self.reason = reason
        self.receipt = receipt


class OrdinaryClient:
    """Serialized guest client for a successfully admitted launch.

    ``transport`` is either :class:`FIFO` or :class:`Spool`.  The caller must
    retain this instance across healthy target restores.  Calls are never retried:
    a second use of an already completed operation ID is resolved from the local
    immutable result cache, and an uncertain call stops the client.
    """

    def __init__(self, protocol, transport, admission, *,
                 clock=time.monotonic, idle=lambda: time.sleep(.001)):
        require(type(admission) is dict)
        required = {"campaign_id", "launch_id", "run_revision", "operations"}
        require(required <= admission.keys())
        require(type(admission["operations"]) is list)
        registered = {item["name"]: item for item in protocol.operations()}
        operations = admission["operations"]
        require(operations == sorted(set(operations)) and all(name in registered for name in operations))
        require(type(admission["run_revision"]) is int and 0 <= admission["run_revision"] <= MAX_SAFE_INTEGER)

        self.protocol = protocol
        self.transport = transport
        self.clock = clock
        self.idle = idle
        self.campaign_id = admission["campaign_id"]
        self.launch_id = admission["launch_id"]
        self.run_revision = admission["run_revision"]
        self.operations = frozenset(operations)
        self._registry = registered
        self._ordinary_seq = 0
        self._call_index = 0
        self._operation_index = 0
        self._active = False
        self._stopped = False
        self._stop_reason = None
        self._history = {}

    @property
    def stopped(self):
        return self._stopped

    def _close(self, reason, *, receipt=None):
        self._stopped = True
        self._stop_reason = RuntimeStopped(reason, receipt=receipt)
        self.transport.close()
        raise self._stop_reason

    def close(self):
        if not self._stopped:
            self._stopped = True
            self.transport.close()

    def _identifier(self, kind):
        if kind == "call":
            self._call_index += 1
            value = self._call_index
        else:
            self._operation_index += 1
            value = self._operation_index
        require(value <= MAX_SAFE_INTEGER)
        return f"{kind}-{value:016d}"

    def operation_id(self, purpose="operation"):
        """Allocate a durable ID for a new trusted wrapper operation."""
        require(not self._stopped and type(purpose) is str and purpose)
        return f"{purpose}-{self._identifier('operation').removeprefix('operation-')}"

    def _control(self):
        while True:
            raw = self.transport.take("control-in")
            if raw is None:
                return
            message = self.protocol.validate_control("host", raw)
            if (message["campaign_id"] != self.campaign_id or
                    message["launch_id"] != self.launch_id or
                    message["kind"] != "terminate"):
                self._close("protocol-error")
            self._close(message["body"]["reason"], receipt=message["body"].get("stop_receipt"))

    def tick(self):
        """Pump transport once and service every captured control message first."""
        if self._stopped:
            raise self._stop_reason or RuntimeStopped("closed")
        try:
            self.transport.pump()
            self._control()
        except RuntimeStopped:
            raise
        except (OSError, ContractError):
            self._close("protocol-error")

    def request(self, operation, body, *, operation_id=None, timeout_ms=None):
        """Submit one operation and wait while continuing to pump control.

        Typed nonterminal host errors are returned in :class:`OperationReply`.
        Unknown effects, terminal dispositions, timeout, or channel/protocol loss
        stop the runtime and are never converted into a replacement operation.
        """
        require(not self._stopped and not self._active)
        require(operation in self.operations and type(body) is dict)
        metadata = self._registry[operation]
        if timeout_ms is None:
            timeout_ms = metadata["timeout_ms"]
        require(type(timeout_ms) is int and 0 < timeout_ms <= metadata["timeout_ms"])
        if operation_id is None:
            operation_id = self.operation_id(operation.removeprefix("engine.").replace("_", "-"))
        require(type(operation_id) is str)

        body_raw = _canonical_value(body, ORDINARY_LIMIT)
        identity = (operation, body_raw)
        previous = self._history.get(operation_id)
        if previous is not None:
            require(previous[0] == identity)
            return previous[1]

        call_id = self._identifier("call")
        request = {
            "api_version": "operator.dev/engine-pipe/v1alpha1",
            "kind": "request",
            "seq": self._ordinary_seq,
            "campaign_id": self.campaign_id,
            "launch_id": self.launch_id,
            "run_revision": self.run_revision,
            "call_id": call_id,
            "operation_id": operation_id,
            "operation": operation,
            "timeout_ms": timeout_ms,
            "body": body,
        }
        raw = _canonical_value(request, ORDINARY_LIMIT)
        self.protocol.validate_request(raw)
        deadline = self.clock() + timeout_ms / 1000
        self._active = True
        try:
            self.transport.send("ordinary-out", raw)
            self._ordinary_seq += 1
            while True:
                if self.clock() >= deadline:
                    self._close("deadline-exceeded")
                self.tick()
                response = self.transport.take("ordinary-in")
                if response is None:
                    self.idle()
                    continue
                if self.clock() >= deadline:
                    self._close("deadline-exceeded")
                message = self.protocol.validate_response(raw, response)
                reply = OperationReply(raw, response, deepcopy(message))
                error = message.get("error")
                if error is not None and (error["effect_state"] == "unknown" or
                                          error["disposition"] == "terminate"):
                    self._close("operation-failed")
                if operation == "engine.restore_request" and error is None:
                    result = message["result"]
                    if (result["previous_run_revision"] != self.run_revision or
                            result["run_revision"] <= self.run_revision or
                            result["harness_disposition"] != "continue"):
                        self._close("protocol-error")
                    self.run_revision = result["run_revision"]
                if operation == "engine.request_stop" and error is None:
                    result = message["result"]
                    if result["status"] != "accepted" or not result["exit_required"]:
                        self._close("protocol-error")
                    self._history[operation_id] = (identity, reply)
                    self._stopped = True
                    return reply
                self._history[operation_id] = (identity, reply)
                return reply
        except RuntimeStopped:
            raise
        except (OSError, ContractError):
            self._close("protocol-error")
        finally:
            self._active = False
