"""Lossless extraction and continuation of installed provider-native tool calls."""

from dataclasses import dataclass

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.schema_ids import ENGINE_MODEL_GENERATE_RESULT_SCHEMA
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT, decode
from . import native_model

from .tools import ToolCall, ToolResult


@dataclass(frozen=True)
class NativeBatch:
    protocol: object
    result_raw: bytes
    codec_id: str
    disposition: str
    calls: tuple[ToolCall, ...]

    def _text(self):
        """Return supported native text without treating it as evidence."""
        require(self.disposition == "text")
        body = self.protocol._catalog.validate(
            ENGINE_MODEL_GENERATE_RESULT_SCHEMA, self.result_raw)
        response = body["response"]
        if self.codec_id == "openai-chat-text-tools-v1":
            values = [response["choices"][0]["message"].get("content")]
        elif self.codec_id == "openai-responses-text-tools-v1":
            values = [part["text"] for item in response["output"]
                      if item.get("type") == "message"
                      for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"]
        elif self.codec_id == "anthropic-messages-text-tools-v1":
            values = [item["text"] for item in response["content"]
                      if isinstance(item, dict) and item.get("type") == "text"]
        elif self.codec_id == "bedrock-converse-text-tools-v1":
            values = [item["text"] for item in
                      response["output"]["message"]["content"] if "text" in item]
        elif self.codec_id == "gemini-text-tools-v1":
            values = [item["text"] for item in
                      response["candidates"][0]["content"]["parts"] if "text" in item]
        else:
            raise ContractError("unsupported model codec")
        require(all(value is None or type(value) is str for value in values))
        text = "\n".join(value for value in values if value)
        require(text != "")
        return text

    def text(self):
        try:
            return self._text()
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ContractError("Provider response lacks usable text for continuation; no tools were dispatched.") from None

    def continuation(self, results):
        require(type(results) is list and len(results) == len(self.calls)
                and all(type(result) is ToolResult for result in results))
        require(all(result.call_id == call.call_id
                    for call, result in zip(self.calls, results)))
        return native_model.continuation(self.codec_id, decode(self.result_raw, ORDINARY_LIMIT)["response"], self.calls, results)


def _object(value):
    return _canonical_value(value, ORDINARY_LIMIT)


def _native_batch(protocol, policy_raw, request_raw, result_raw):
    """Validate a complete native result before exposing any requested tool."""
    protocol.validate_model_exchange(policy_raw, request_raw, result_raw)
    codec = decode(policy_raw, ORDINARY_LIMIT)["codec_id"]
    response = decode(result_raw, ORDINARY_LIMIT)["response"]
    disposition = native_model.disposition(codec, response)
    body = protocol._catalog.validate(ENGINE_MODEL_GENERATE_RESULT_SCHEMA, result_raw)
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
            values = [item for item in response["content"] if isinstance(item, dict) and item.get("type") == "tool_use"]
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
                calls.append(ToolCall(identifier, value["name"], _object(value.get("args", {})),
                                      index, batch_id))
        else:
            raise ContractError("unsupported model codec")
    elif disposition == "usage-unknown":
        # Unknown billed usage cannot be treated as zero or followed by effects.
        raise ContractError("model usage unknown")
    ids = [call.call_id for call in calls]
    require(len(ids) == len(set(ids)))
    return NativeBatch(protocol, result_raw, codec, disposition, tuple(calls))


def native_batch(protocol, policy_raw, request_raw, result_raw):
    try:
        return _native_batch(protocol, policy_raw, request_raw, result_raw)
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ContractError("Provider response lacks fields needed for tool interpretation; no tools were dispatched.") from None
