"""Provider-native conversation construction and serialized adaptive turns."""

from copy import deepcopy

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import LoopStopped
from operator_contracts.startup import require
from operator_contracts.validation import decode, ORDINARY_LIMIT

from .model_turns import native_batch
from .runtime import RuntimeStopped


class NativeConversation:
    """Mutable native history for exactly one installed model codec."""

    def __init__(self, protocol, policy_raw, task):
        require(type(policy_raw) is bytes and type(task) is str and task)
        self.protocol = protocol
        self.policy_raw = policy_raw
        self.policy = protocol._catalog.validate(
            "urn:operator:schema:model-codec-policy:v1alpha1", policy_raw)
        self.codec = self.policy["codec_id"]
        self._request = self._initial(task)

    def _initial(self, task):
        policy = self.policy
        codec = self.codec
        if codec == "openai-chat-text-tools-v1":
            return {
                "model": policy["request_model"],
                "messages": [
                    {"role": policy["instruction_role"], "content": policy["prompt"]},
                    {"role": "user", "content": task},
                ],
                "max_completion_tokens": policy["max_completion_tokens"],
                "stream": False, "store": False, "n": 1,
                "parallel_tool_calls": True, "tools": policy["tools"],
                "tool_choice": "auto",
            }
        if codec == "openai-responses-text-tools-v1":
            return {
                "model": policy["request_model"], "instructions": policy["prompt"],
                "input": [{"role": "user", "content": task}],
                "max_output_tokens": policy["max_output_tokens"],
                "stream": False, "store": False, "parallel_tool_calls": True,
                "include": ["reasoning.encrypted_content"], "truncation": "disabled",
                "reasoning": policy["reasoning"], "tools": policy["tools"],
                "tool_choice": "auto", "text": {"format": {"type": "text"}},
            }
        if codec == "anthropic-messages-text-tools-v1":
            return {
                "model": policy["request_model"], "system": policy["prompt"],
                "messages": [{"role": "user", "content": task}],
                "max_tokens": policy["max_tokens"], "stream": False,
                "thinking": policy["thinking"], "tools": policy["tools"],
                "tool_choice": {"type": "auto"},
            }
        if codec == "bedrock-converse-text-tools-v1":
            request = {
                "system": [{"text": policy["prompt"]}],
                "messages": [{"role": "user", "content": [{"text": task}]}],
                "inferenceConfig": {"maxTokens": policy["max_tokens"]},
            }
            if policy["tools"]:
                request["toolConfig"] = {
                    "tools": policy["tools"], "toolChoice": {"auto": {}},
                }
            return request
        if codec == "gemini-text-tools-v1":
            request = {
                "systemInstruction": {"parts": [{"text": policy["prompt"]}]},
                "contents": [{"role": "user", "parts": [{"text": task}]}],
                "generationConfig": {
                    "maxOutputTokens": policy["max_output_tokens"],
                    "candidateCount": 1,
                    "thinkingConfig": policy["thinking_config"],
                },
                "tools": policy["tools"],
            }
            if policy["tools"]:
                request["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
            return request
        raise ContractError("unsupported model codec")

    def body(self):
        body = {key: deepcopy(self.policy[key])
                for key in ("codec_id", "profile_id", "profile_digest")}
        body["request"] = deepcopy(self._request)
        raw = _canonical_value(body, ORDINARY_LIMIT)
        self.protocol.validate_model_request(self.policy_raw, raw)
        return body, raw

    def extend(self, segment_raw):
        segment = decode(segment_raw, ORDINARY_LIMIT)
        require(type(segment) is list)
        field = "input" if self.codec == "openai-responses-text-tools-v1" else (
            "contents" if self.codec == "gemini-text-tools-v1" else "messages")
        self._request[field].extend(segment)

    def prompt_again(self, text="Continue with the next useful tool action or request_stop."):
        require(type(text) is str and text)
        if self.codec == "openai-responses-text-tools-v1":
            item = {"role": "user", "content": text}
            self._request["input"].append(item)
        elif self.codec == "gemini-text-tools-v1":
            self._request["contents"].append({"role": "user", "parts": [{"text": text}]})
        elif self.codec == "bedrock-converse-text-tools-v1":
            self._request["messages"].append({"role": "user", "content": [{"text": text}]})
        else:
            self._request["messages"].append({"role": "user", "content": text})


class AdaptiveHarness:
    """Run admitted model turns until conclusion, graceful exhaustion, or failure."""

    def __init__(self, protocol, client, loop, dispatcher, conversation, finalizer):
        self.protocol = protocol
        self.client = client
        self.loop = loop
        self.dispatcher = dispatcher
        self.conversation = conversation
        self.finalizer = finalizer

    def _unavailable_reason(self):
        reason = self.loop.snapshot()["reason"]
        if reason == "budget-limit":
            return "budget-limit"
        return "local-error"

    def run(self):
        while self.loop.snapshot()["mode"] == "exploring":
            try:
                self.loop.begin_model()
            except LoopStopped:
                break
            try:
                body, request_raw = self.conversation.body()
            except ContractError:
                self.loop.accept_response(0)
                self.loop.stop("no-useful-next-experiment")
                self.loop.end_turn()
                return self.finalizer.finish_unavailable("context-limit")
            try:
                reply = self.client.request(
                    "engine.model_generate", body,
                    operation_id=self.client.operation_id("model-generate"),
                )
                if reply.error is not None:
                    self.client.fail("model-generation-failed")
                result_raw = _canonical_value(reply.result, ORDINARY_LIMIT)
                batch = native_batch(self.protocol, self.conversation.policy_raw,
                                     request_raw, result_raw)
            except RuntimeStopped:
                self.loop.hard_stop()
                raise
            except ContractError:
                self.loop.hard_stop()
                self.client.fail("model-contract-failed")

            if batch.disposition == "tool-calls":
                try:
                    results = self.dispatcher.dispatch(list(batch.calls))
                except LoopStopped:
                    if self.loop.snapshot()["mode"] == "finalizing":
                        break
                    raise
                if self.finalizer.pending:
                    return self.finalizer.finish()
                if self.loop.snapshot()["mode"] == "exploring":
                    self.conversation.extend(batch.continuation(results))
                continue

            self.loop.accept_response(0)
            if batch.disposition in ("text", "refusal"):
                self.conversation.extend(batch.continuation([]))
            if batch.disposition == "text":
                self.conversation.prompt_again()
            else:
                self.loop.stop("no-useful-next-experiment")
            self.loop.end_turn()

        if self.loop.snapshot()["mode"] == "finalizing":
            return self.finalizer.finish_unavailable(self._unavailable_reason())
        raise RuntimeStopped("closed")
