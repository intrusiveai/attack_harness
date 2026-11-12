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
    "finish": frozenset({"engine.finish"}),
}


def _operation_error(error):
    require(type(error) is dict and error.get("effect_state") == "none")
    return ToolError.from_host(error)


class FixedHandlers:
    """Compose the release-owned, explicitly named callable handler map.

    Tools backed by host operations are installed only when every dependency was
    advertised at admission. ``reference_read`` is local and is always present.
    Attempt execution and finalization are installed by their dedicated services.
    """

    def __init__(self, protocol, inputs, client, loop, *, artifacts=None,
                 observations=None, attempts=None, finalizer=None,
                 record_receipts=None, scenario_delivery=None):
        self.protocol = protocol
        self.inputs = inputs
        self.client = client
        self.loop = loop
        self.artifacts = artifacts or ArtifactPublisher(protocol, client)
        self.observations = observations or ObservationReader(client)
        self.attempts = attempts
        self.finalizer = finalizer
        self.record_receipts = record_receipts if record_receipts is not None else set()
        self.scenario_delivery = scenario_delivery

    def handlers(self):
        # All model calls cross the shared normalization boundary with call identity.
        return {}

    def canonical_handlers(self):
        candidates = {
            "artifact_publish": self.artifact_publish,
            "injection_delete": self.injection_delete,
            "observation_read": self.observation_read,
            "record_append": self.record_append,
            "reference_read": self.reference_read,
            "finish": self.finish,
            "restore_request": self.restore_request,
            "snapshot_inspect": self.snapshot_inspect,
            "snapshot_list": self.snapshot_list,
            "snapshot_request": self.snapshot_request,
        }
        available = self.client.operations
        return {
            name: handler for name, handler in candidates.items()
            if ((name == "reference_read" or _DEPENDENCIES[name] <= available)
                and (name != "finish" or self.finalizer is not None))
        }

    def raw_handlers(self):
        from .model_tools import ModelTools
        if not hasattr(self, "model_tools"):
            self.model_tools = ModelTools(self)
        names = set(self.canonical_handlers())
        if self.attempts is not None and _DEPENDENCIES["attempt_execute"] <= self.client.operations:
            names.add("attempt_execute")
        return {name: self.model_tools.dispatch for name in names}

    def reference_read(self, arguments):
        task = None
        try:
            if self.scenario_delivery is not None and arguments["reference_id"] in self.scenario_delivery.references:
                source, content, task = self.scenario_delivery.reference(arguments["reference_id"])
            else:
                source, content = self.inputs.entry(arguments["reference_id"])
        except ContractError as error:
            if error.reason in ("scenario_context_limit", "task_context_limit"):
                raise ToolError.from_contract(error) from None
            raise ToolError("invalid_reference", "Unknown reference.", path="/reference", correction="Use a reference from the input reference index or tool-guide:<advertised tool name>; do not invent a reference.") from None
        offset = arguments["offset"]
        if task is not None:
            if offset != 0:
                raise ToolError("range_exceeded", "Scenario selection is not a paginated read.",
                    path="/offset", correction="Use offset 0 to load the complete scenario in the next task message.")
            self.scenario_delivery.activate(content, task)
            return HandlerResult({"status": "scenario-selected", "reference": source["entry_id"],
                "scenario_id": source["scenario_id"],
                "message": "The selected scenario is now active. Its complete instructions are in the current task. Act on them; no acknowledgment or pagination is needed."})
        if offset > len(content):
            raise ToolError("range_exceeded", "Reference offset exceeds content size.", path="/offset", correction=f"Use an offset from 0 through {len(content)} for this reference, or start at 0. An offset equal to size returns EOF.")
        selected = content[offset:offset + arguments.get("max_bytes",4096)]
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
            **_present_content(selected,source["media_type"]),
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
                arguments["offset"], arguments.get("max_bytes",4096),
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
            **_present_content(chunk.content,(chunk.artifact or {}).get("media_type","application/octet-stream")),
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
        result = self._ordinary("engine.record_append", arguments)
        self.record_receipts.add(result.value["receipt_id"])
        return result

    def finish(self, arguments):
        return self.finalizer.stage(arguments)

    def restore_request(self, arguments):
        return self._ordinary("engine.restore_request", arguments, outcome="restored")

    def snapshot_inspect(self, arguments):
        return self._ordinary("engine.snapshot_inspect", arguments)

    def snapshot_list(self, arguments):
        return self._ordinary("engine.snapshot_list", arguments)

    def snapshot_request(self, arguments):
        return self._ordinary("engine.snapshot_request", arguments)


def _present_content(content, media_type):
    if media_type == 'application/json' or media_type.startswith('text/'):
        try:return dict(content=content.decode('utf-8'),encoding='utf8',decoding='complete')
        except UnicodeError:pass
    return dict(content=base64.b64encode(content).decode('ascii'),encoding='base64',decoding='binary-or-incomplete-utf8')
