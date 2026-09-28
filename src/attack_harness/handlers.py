"""Fixed model-tool handlers over verified inputs and ordinary operations."""

import base64

from operator_contracts import ContractError
from operator_contracts.startup import require

from .artifacts import ArtifactPublisher, ArtifactRejected
from .observations import ObservationReader, ObservationRejected
from .tools import HandlerResult, ToolError


_DEPENDENCIES = {
    "artifact_publish": frozenset({
        "engine.artifact_begin", "engine.artifact_put_part", "engine.artifact_commit",
    }),
    "injection_delete": frozenset({"engine.injection_delete"}),
    "observation_read": frozenset({"engine.observation_read"}),
    "record_append": frozenset({"engine.record_append"}),
    "restore_request": frozenset({"engine.restore_request"}),
    "snapshot_inspect": frozenset({"engine.snapshot_inspect"}),
    "snapshot_list": frozenset({"engine.snapshot_list"}),
    "snapshot_request": frozenset({"engine.snapshot_request"}),
    "attempt_execute": frozenset({"engine.attempt_execute"}),
}


def _operation_error(error):
    require(type(error) is dict and error.get("effect_state") == "none")
    return ToolError(error["code"], error["message"], outcome="preflight-rejected")


class FixedHandlers:
    """Compose the release-owned, explicitly named callable handler map.

    Tools backed by host operations are installed only when every dependency was
    advertised at admission. ``reference_read`` is local and is always present.
    Attempt execution and finalization are installed by their dedicated services.
    """

    def __init__(self, protocol, inputs, client, loop, *, artifacts=None,
                 observations=None, attempts=None):
        self.protocol = protocol
        self.inputs = inputs
        self.client = client
        self.loop = loop
        self.artifacts = artifacts or ArtifactPublisher(protocol, client)
        self.observations = observations or ObservationReader(client)
        self.attempts = attempts

    def handlers(self):
        candidates = {
            "artifact_publish": self.artifact_publish,
            "injection_delete": self.injection_delete,
            "observation_read": self.observation_read,
            "record_append": self.record_append,
            "reference_read": self.reference_read,
            "restore_request": self.restore_request,
            "snapshot_inspect": self.snapshot_inspect,
            "snapshot_list": self.snapshot_list,
            "snapshot_request": self.snapshot_request,
        }
        available = self.client.operations
        return {
            name: handler for name, handler in candidates.items()
            if name == "reference_read" or _DEPENDENCIES[name] <= available
        }

    def raw_handlers(self):
        if (self.attempts is None or
                not _DEPENDENCIES["attempt_execute"] <= self.client.operations):
            return {}
        return {"attempt_execute": self.attempts}

    def reference_read(self, arguments):
        try:
            source, content = self.inputs.entry(arguments["reference_id"])
        except ContractError:
            raise ToolError("INVALID_REFERENCE", "Unknown reference ID.") from None
        offset = arguments["offset"]
        if offset > len(content):
            raise ToolError("INVALID_RANGE", "Reference offset exceeds content size.")
        selected = content[offset:offset + arguments["max_bytes"]]
        if selected:
            self.loop.reserve_read("content", source["digest"], offset, len(selected))
            self.loop.settle_read(len(selected))
        return HandlerResult({
            "status": "ok",
            "reference_id": source["entry_id"],
            "source": source,
            "offset": offset,
            "raw_length": len(selected),
            "eof": offset + len(selected) == len(content),
            "content": base64.b64encode(selected).decode("ascii"),
            "encoding": "base64",
        })

    def artifact_publish(self, arguments):
        try:
            artifact = self.artifacts.publish_tool(arguments)
        except ArtifactRejected as error:
            raise _operation_error(error.error) from None
        if artifact.purpose == "payload":
            self.loop.payload_committed(artifact.digest)
        return HandlerResult({
            "status": "committed",
            "artifact_receipt": artifact.receipt_id,
            "purpose": artifact.purpose,
            "artifact": artifact.descriptor(),
        })

    def observation_read(self, arguments):
        try:
            chunk = self.observations.read(
                arguments["receipt_id"], arguments["entry_id"],
                arguments["offset"], arguments["max_bytes"],
            )
        except ObservationRejected as error:
            raise _operation_error(error.error) from None
        if chunk.content:
            require(chunk.artifact is not None)
            self.loop.reserve_read("observation", chunk.artifact["digest"],
                                   chunk.offset, len(chunk.content))
            self.loop.settle_read(len(chunk.content))
        return HandlerResult({
            "status": "ok",
            "receipt_id": chunk.receipt_id,
            "entry_id": chunk.entry_id,
            "availability": chunk.availability,
            "offset": chunk.offset,
            "content": base64.b64encode(chunk.content).decode("ascii"),
            "encoding": "base64",
            "raw_length": len(chunk.content),
            "eof": chunk.eof,
            "artifact": chunk.artifact,
            "truncated": chunk.truncated,
            "reason": chunk.reason,
        })

    def _ordinary(self, operation, arguments, *, outcome="success"):
        operation_id = self.client.operation_id(
            operation.removeprefix("engine.").replace("_", "-")
        )
        reply = self.client.request(operation, arguments, operation_id=operation_id)
        if reply.error is not None:
            raise _operation_error(reply.error)
        return HandlerResult(reply.result, outcome)

    def injection_delete(self, arguments):
        return self._ordinary("engine.injection_delete", arguments)

    def record_append(self, arguments):
        return self._ordinary("engine.record_append", arguments)

    def restore_request(self, arguments):
        return self._ordinary("engine.restore_request", arguments, outcome="restored")

    def snapshot_inspect(self, arguments):
        return self._ordinary("engine.snapshot_inspect", arguments)

    def snapshot_list(self, arguments):
        return self._ordinary("engine.snapshot_list", arguments)

    def snapshot_request(self, arguments):
        return self._ordinary("engine.snapshot_request", arguments)
