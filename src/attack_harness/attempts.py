"""Allocated attempt construction, semantic preflight, and terminal handling."""

from copy import deepcopy

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from operator_contracts import ContractError
from operator_contracts.attempts import AllocationError, AttemptAllocator
from operator_contracts.schema_ids import ENGINE_ATTEMPT_REQUEST_SCHEMA, ENGINE_ATTEMPT_RESULT_SCHEMA
from operator_contracts.startup import require
from operator_contracts.validation import decode, ORDINARY_LIMIT

from .tools import HandlerResult, ToolError


_PLACEMENTS = {
    "replace": "replace",
    "prepend_text": "prepend",
    "append_text": "append",
    "insert_array": "insert",
    "merge_object": "merge",
}
_SELECTORS = {
    "arguments_pointer": "arguments_json_pointer",
    "request_body_pointer": "request_body_json_pointer",
}


def _offline(_):
    raise Unresolvable("schema absent from admitted capability")


def _error(code, path, message):
    return {"code": code, "instance_path": path, "message": message}


class _Rejected(Exception):
    def __init__(self, code, path, message):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


class AttemptExecutor:
    """One campaign-lifetime attempt allocator retained across target restores."""

    def __init__(self, protocol, client, artifacts, context, bundle, loop):
        require(type(context) is dict and type(bundle) is dict)
        self.protocol = protocol
        self.client = client
        self.artifacts = artifacts
        self.context = deepcopy(context)
        self.bundle = deepcopy(bundle)
        self.loop = loop
        self.allocator = AttemptAllocator(context["attempt_index_high_watermark"])
        self._history = {}
        self._parents = {}
        self._receipts = set()
        capabilities = context["target"]["capabilities"]
        self._operations = {item["operation_id"]: item
                            for item in capabilities["operations"]}
        self._actions = tuple(capabilities["actions"])
        self._scenarios = {item["scenario_id"] for item in bundle["scenarios"]}

    @property
    def high_watermark(self):
        return self.allocator.high_watermark

    @property
    def receipts(self):
        return frozenset(self._receipts)

    def _rejected(self, allocation, code, path, message, *, outcome="invalid"):
        value = {
            "api_version": "operator.dev/engine-attempt-result/v1alpha2",
            "kind": "EngineAttemptResult",
            "request_id": allocation.request_id,
            "attempt_id": allocation.attempt_id,
            "status": "rejected",
            "stage": "guest-validation",
            "target_contact": "none",
            "invocation_state": "not-dispatched",
            "cleanup_state": "not-needed",
            "retry_disposition": "correct-and-resubmit",
            "errors": [_error(code, path, message)],
        }
        self.protocol._catalog.validate_value(ENGINE_ATTEMPT_RESULT_SCHEMA, value)
        return HandlerResult(value, outcome)

    def _artifact(self, descriptor, purpose, path):
        try:
            artifact = self.artifacts.committed(descriptor, purpose)
        except ContractError:
            raise _Rejected("ARTIFACT_MISMATCH", path,
                            "Artifact descriptor is not a committed matching artifact.") from None
        try:
            content = self.artifacts.content(artifact.receipt_id)
        except ContractError:
            raise _Rejected("ARTIFACT_UNAVAILABLE", path,
                            "Committed artifact bytes are unavailable for validation.") from None
        return artifact, content

    def _validate_input(self, arguments, payload_content, carrier_content):
        invocation = arguments["invocation"]
        operation = self._operations.get(invocation["operation_id"])
        if operation is None or operation["delivery_status"] != "described":
            raise _Rejected("UNSUPPORTED_CAPABILITY", "/invocation/operation_id",
                            "Invocation operation is not available.")
        descriptor = arguments[invocation["input_source"]]
        content = payload_content if invocation["input_source"] == "payload" else carrier_content
        delivery = operation["delivery"]["input"]
        if invocation["media_type"] != descriptor["media_type"] or (
                delivery["media_type"] != descriptor["media_type"]):
            raise _Rejected("BINDING_MISMATCH", "/invocation/media_type",
                            "Invocation media type does not match the selected artifact and operation.")
        maximum = min(operation["maximum_input_bytes"], delivery["max_bytes"])
        if len(content) > maximum:
            raise _Rejected("LIMIT_EXCEEDED", "/invocation",
                            "Invocation content exceeds the admitted operation limit.")
        encoding = delivery["encoding"]
        if encoding == "utf8":
            try:
                content.decode("utf-8", errors="strict")
            except UnicodeError:
                raise _Rejected("PAYLOAD_FORMAT", "/invocation",
                                "Invocation content is not valid UTF-8.") from None
        elif encoding == "json":
            try:
                value = decode(content, maximum)
                schema = delivery.get("schema")
                if schema is not None:
                    Draft202012Validator.check_schema(schema)
                    Draft202012Validator(schema, registry=Registry(retrieve=_offline)).validate(value)
            except (ContractError, SchemaError, ValidationError, Unresolvable):
                raise _Rejected("PAYLOAD_FORMAT", "/invocation",
                                "Invocation content does not match the admitted JSON input contract.") from None

    def _validate_actions(self, arguments, payload_content):
        actions = arguments["pre_actions"]
        if len({item["action_id"] for item in actions}) != len(actions):
            raise _Rejected("INVALID_ARGUMENTS", "/pre_actions",
                            "Setup action IDs must be unique.")
        decoded_payload = None
        if actions:
            try:
                decoded_payload = decode(payload_content, ORDINARY_LIMIT)
            except ContractError:
                raise _Rejected("PAYLOAD_FORMAT", "/payload",
                                "Injection payload is not valid canonical JSON.") from None
        for index, action in enumerate(actions):
            parameters = action["parameters"]
            path = f"/pre_actions/{index}/parameters"
            if parameters["payload_digest"] != arguments["payload"]["digest"]:
                raise _Rejected("ARTIFACT_MISMATCH", path + "/payload_digest",
                                "Setup payload digest does not match the committed payload.")
            selector = {_SELECTORS.get(key, key) for key in parameters["selector"]}
            placement = _PLACEMENTS[parameters["placement"]["operation"]]
            supported = any(
                capability["action_type"] == action["action_type"]
                and capability["surface"] == parameters["surface"]
                and parameters["scope"] in capability["scopes"]
                and placement in capability["placements"]
                and selector <= set(capability["selector_fields"])
                for capability in self._actions
            )
            if not supported:
                raise _Rejected("UNSUPPORTED_CAPABILITY", path,
                                "Setup action is not supported by the admitted target capability.")
            operation = parameters["placement"]["operation"]
            if operation in ("prepend_text", "append_text") and type(decoded_payload) is not str:
                raise _Rejected("PAYLOAD_FORMAT", "/payload",
                                "Text placement requires a JSON string payload.")
            if operation == "merge_object":
                allowed = set(parameters["placement"]["allowed_fields"])
                if type(decoded_payload) is not dict or not set(decoded_payload) <= allowed:
                    raise _Rejected("PAYLOAD_FORMAT", "/payload",
                                    "Object merge payload exceeds its allowed fields.")

    def _semantic(self, arguments, payload_content, carrier_content):
        if arguments["origin"] == "scenario" and arguments["scenario_id"] not in self._scenarios:
            raise _Rejected("BINDING_MISMATCH", "/scenario_id",
                            "Scenario ID is not present in the verified scenario bundle.")
        parent_id = arguments.get("parent_attempt_id")
        if parent_id is None:
            if arguments["generation"] != 1:
                raise _Rejected("LINEAGE_INVALID", "/generation",
                                "A root attempt must use generation one.")
        else:
            parent = self._parents.get(parent_id)
            if parent is None or parent != (arguments["thread_id"], arguments["generation"] - 1):
                raise _Rejected("LINEAGE_INVALID", "/parent_attempt_id",
                                "Parent attempt is not a known prior generation in this thread.")
        self._validate_input(arguments, payload_content, carrier_content)
        self._validate_actions(arguments, payload_content)

    def __call__(self, call):
        key = (call.batch_id, call.call_id, call.correlation)
        previous = self._history.get(key)
        if previous is not None:
            require(previous[0] == call.arguments)
            return previous[1]
        try:
            value = decode(call.arguments, ORDINARY_LIMIT)
            require(type(value) is dict)
        except ContractError:
            raise ToolError("INVALID_TOOL_CALL", "Invalid attempt arguments.",
                            outcome="invalid") from None

        request_id = self.client.operation_id("attempt-request")
        attempt_id = self.client.operation_id("attempt")
        try:
            allocation = self.allocator.allocate(call.arguments, request_id, attempt_id)
        except AllocationError as error:
            result = self._rejected(error.allocation, "UNKNOWN_FIELD", "",
                                    "Attempt arguments contain reserved bookkeeping fields.")
            self._history[key] = (call.arguments, result)
            return result

        try:
            arguments = self.protocol.validate_tool_arguments("attempt_execute", call.arguments)
        except ContractError:
            result = self._rejected(allocation, "INVALID_ARGUMENTS", "",
                                    "Attempt arguments do not match the fixed tool schema.")
            self._history[key] = (call.arguments, result)
            return result

        try:
            _, payload_content = self._artifact(arguments["payload"], "payload", "/payload")
            carrier_content = None
            if "carrier" in arguments:
                _, carrier_content = self._artifact(arguments["carrier"], "carrier", "/carrier")
            request = {
                "api_version": "operator.dev/engine-attempt-request/v1alpha2",
                "kind": "EngineAttemptRequest",
                "request_id": allocation.request_id,
                "attempt_id": allocation.attempt_id,
                "attempt_index": allocation.attempt_index,
                "generator": {
                    "kind": "operator-engine",
                    "release_digest": self.context["release"]["image_digest"],
                },
                **arguments,
            }
            self.protocol._catalog.validate_value(ENGINE_ATTEMPT_REQUEST_SCHEMA, request)
            self._semantic(arguments, payload_content, carrier_content)
        except _Rejected as error:
            result = self._rejected(allocation, error.code, error.path, error.message)
            self._history[key] = (call.arguments, result)
            return result
        except ContractError:
            result = self._rejected(allocation, "INVALID_ARGUMENTS", "",
                                    "Attempt request failed complete structural validation.")
            self._history[key] = (call.arguments, result)
            return result

        reply = self.client.request("engine.attempt_execute", request,
                                    operation_id=allocation.request_id)
        if reply.error is not None:
            code = reply.error["code"]
            if code not in {"INVALID_ARGUMENTS", "LIMIT_EXCEEDED", "UNSUPPORTED_CAPABILITY",
                            "POLICY_DENIED", "IDEMPOTENCY_CONFLICT", "STATE_CHANGED"}:
                code = "POLICY_DENIED"
            result = self._rejected(allocation, code, reply.error.get("instance_path", ""),
                                    reply.error["message"], outcome="preflight-rejected")
            self._history[key] = (call.arguments, result)
            return result
        result = reply.result
        require(result.get("request_id", allocation.request_id) == allocation.request_id)
        require(result.get("attempt_id", allocation.attempt_id) == allocation.attempt_id)
        status = result["status"]
        if status == "rejected":
            handled = HandlerResult(result, "preflight-rejected")
            self._history[key] = (call.arguments, handled)
            return handled
        receipt = result["receipt_id"]
        self._receipts.add(receipt)
        self._parents[allocation.attempt_id] = (arguments["thread_id"], arguments["generation"])
        if status == "completed":
            self.loop.experiment_completed(receipt)
            handled = HandlerResult(result)
            self._history[key] = (call.arguments, handled)
            return handled
        require(status in ("failed", "unknown"))
        self.client.fail(f"attempt-{status}", receipt=receipt)
