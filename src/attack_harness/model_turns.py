"""Lossless extraction and continuation of installed provider-native tool calls."""

from dataclasses import dataclass

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.schema_ids import ENGINE_MODEL_GENERATE_RESULT_SCHEMA
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT

from .tools import ToolCall, ToolResult


@dataclass(frozen=True)
class NativeBatch:
    protocol: object
    result_raw: bytes
    codec_id: str
    disposition: str
    calls: tuple[ToolCall, ...]

    def continuation(self, results):
        require(type(results) is list and len(results) == len(self.calls)
                and all(type(result) is ToolResult for result in results))
        require(all(result.call_id == call.call_id
                    for call, result in zip(self.calls, results)))
        if self.codec_id == "gemini-text-tools-v1":
            native = [{"part_index": call.correlation, "content": result.content}
                      for call, result in zip(self.calls, results)]
            return self.protocol.gemini_continuation(self.result_raw, native)
        native = [result.continuation() for result in results]
        if self.codec_id == "openai-chat-text-tools-v1":
            return self.protocol.chat_continuation(self.result_raw, native)
        if self.codec_id == "openai-responses-text-tools-v1":
            return self.protocol.responses_continuation(self.result_raw, native)
        if self.codec_id == "anthropic-messages-text-tools-v1":
            return self.protocol.anthropic_continuation(self.result_raw, native)
        if self.codec_id == "bedrock-converse-text-tools-v1":
            return self.protocol.bedrock_continuation(self.result_raw, native)
        raise ContractError("unsupported model codec")


def _object(value):
    return _canonical_value(value, ORDINARY_LIMIT)


def native_batch(protocol, policy_raw, request_raw, result_raw):
    """Validate a complete native result before exposing any requested tool."""
    protocol.validate_model_exchange(policy_raw, request_raw, result_raw)
    disposition = protocol.model_disposition(result_raw)
    body = protocol._catalog.validate(ENGINE_MODEL_GENERATE_RESULT_SCHEMA, result_raw)
    codec = body["codec_id"]
    response = body["response"]
    batch_id = raw_digest(result_raw)
    calls = []
    if disposition == "tool-calls":
        if codec == "openai-chat-text-tools-v1":
            values = response["choices"][0]["message"].get("tool_calls") or []
            calls = [ToolCall(value["id"], value["function"]["name"],
                              value["function"]["arguments"].encode("utf-8"),
                              batch_id=batch_id)
                     for value in values]
        elif codec == "openai-responses-text-tools-v1":
            values = [item for item in response["output"] if item.get("type") == "function_call"]
            calls = [ToolCall(value["call_id"], value["name"],
                              value["arguments"].encode("utf-8"), batch_id=batch_id)
                     for value in values]
        elif codec == "anthropic-messages-text-tools-v1":
            values = [item for item in response["content"] if item["type"] == "tool_use"]
            calls = [ToolCall(value["id"], value["name"], _object(value["input"]),
                              batch_id=batch_id)
                     for value in values]
        elif codec == "bedrock-converse-text-tools-v1":
            values = [item["toolUse"] for item in response["output"]["message"]["content"]
                      if "toolUse" in item]
            calls = [ToolCall(value["toolUseId"], value["name"], _object(value["input"]),
                              batch_id=batch_id)
                     for value in values]
        elif codec == "gemini-text-tools-v1":
            parts = response["candidates"][0]["content"]["parts"]
            for index, part in enumerate(parts):
                if "functionCall" not in part:
                    continue
                value = part["functionCall"]
                identifier = value.get("id", f"gemini-part-{index}")
                calls.append(ToolCall(identifier, value["name"], _object(value["args"]),
                                      index, batch_id))
        else:
            raise ContractError("unsupported model codec")
    elif disposition == "usage-unknown":
        # Unknown billed usage cannot be treated as zero or followed by effects.
        raise ContractError("model usage unknown")
    ids = [call.call_id for call in calls]
    require(len(ids) == len(set(ids)))
    return NativeBatch(protocol, result_raw, codec, disposition, tuple(calls))
