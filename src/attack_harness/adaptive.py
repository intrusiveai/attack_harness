"""Provider-native conversation construction and serialized adaptive turns."""

from copy import deepcopy
import json
import math

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import LoopStopped
from operator_contracts.startup import require
from operator_contracts.validation import decode, ORDINARY_LIMIT

from .model_turns import native_batch
from .runtime import RuntimeStopped


class NativeConversation:
    """Mutable native history for exactly one installed model codec."""

    def __init__(self, protocol, policy_raw, task, *, compact_at=1 << 20, remaining=None,
                 model_allowance=None):
        require(type(policy_raw) is bytes and type(task) is str and task)
        require(type(compact_at) is int and compact_at > 0)
        self.protocol = protocol
        self.policy_raw = policy_raw
        self.policy = protocol._catalog.validate(
            "urn:operator:schema:model-codec-policy:v1alpha1", policy_raw)
        self.codec = self.policy["codec_id"]
        self._task = task
        self.task_generation = 0
        self.delivered_task_generation = -1
        self._summary = ""
        self._compact_at = compact_at
        self._segments = 0
        self._compactions = []
        self._request = self._initial(task)
        self._groups = []
        self._budget = None
        self._last_bytes = 0
        self._remaining = dict(remaining or {})
        self._context_limits = self.policy['context_limits']
        self._model_allowance = model_allowance
        self.model_admission_failure = None
        self._finalizing = False

    @property
    def task(self):
        return self._task

    def replace_task(self, task):
        """Replace task data without dropping native tool history or compaction provenance."""
        require(type(task) is str and task)
        field = self._history_field()
        index = 1 if self.codec == "openai-chat-text-tools-v1" else 0
        self._request[field][index] = self._initial(task + self._summary + self._finalization_guidance())[field][index]
        self._task = task
        self.task_generation += 1

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

    def observe_budget(self, result, request_raw):
        # native_batch has already checked this snapshot against policy and response.
        self._budget = deepcopy(result['context_budget'])
        self._last_bytes = len(request_raw)
        self._remaining = dict(model_tokens=self._budget['remaining_model_tokens'],model_turns=self._budget['remaining_model_turns'])

    def _estimated_tokens(self, raw):
        # A conservative local heuristic, never provider usage or exact admission.
        ratio = 1.1*self._budget['input_tokens']/max(1,self._last_bytes) if self._budget else 0.5
        return math.ceil(len(raw)*ratio)

    def model_reservation(self):
        return self._context_limits['maximum_prompt_tokens'] + self._context_limits['maximum_completion_tokens']

    def can_fund_model(self):
        reserve = self.model_reservation()
        remaining = self._remaining.get('model_tokens', reserve)
        self.model_admission_failure = None
        if remaining < reserve:
            if self._model_allowance is not None:
                require(0 <= remaining <= self._model_allowance <= 2**53 - 1)
                self.model_admission_failure = dict(kind='model-tokens',
                    total_allowance=self._model_allowance,
                    consumed=self._model_allowance - remaining, remaining=remaining,
                    next_request_reservation=reserve)
            return False
        return self._remaining.get('model_turns', 1) > 0

    def _finalization_guidance(self):
        if not self._finalizing:
            return ''
        return ('\n\nHarness budget notice: move to finish now using retained evidence. '
                'Budget is approaching the reserve for an assessment request and one bounded correction. '
                'Report gaps honestly; optional elaboration is unnecessary. Correct a rejected finish '
                'without replaying completed target operations. Acceptance does not mean cleanup completed.')

    def prepare_finalization(self):
        # Start before the two-request reserve is crossed. Admission still uses
        # the latest host accounting on every request, including compaction.
        if not self._finalizing and (
                self._remaining.get('model_tokens', float('inf')) <= 3 * self.model_reservation()
                or self._remaining.get('model_turns', float('inf')) <= 3):
            self._finalizing = True
            self.replace_task(self._task)

    def needs_compaction(self):
        if self._segments == 0:
            return False
        try: _, raw = self.body()
        except ContractError:return True
        return (len(raw)>=self._compact_at or bool(self._budget and self._budget['near_prompt_limit'])
                or self._estimated_tokens(raw)>=self._context_limits['warning_threshold_tokens'])

    def compaction_body(self):
        """Build a tool-suppressed request over complete native history."""
        field = self._history_field()
        history = self._request[field]
        if self.codec == "openai-chat-text-tools-v1":
            history = history[1:]  # The exact privileged prompt remains in _initial().
        history_raw = _canonical_value(history, ORDINARY_LIMIT)
        # Preserve exact returned identities separately from model-written summaries.
        identities={(v['kind'],v['identifier']) for v in getattr(self,'_compaction_ledger',[])}
        keys={'execution','observation','readable_observation','citation','artifact','record','hypothesis','reference','snapshot','session','injection'}
        def collect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in keys and isinstance(item,str) and len(item)<=128:identities.add((key,item))
                    collect(item)
            elif isinstance(value,list):
                for item in value:collect(item)
        def returned(content):
            # Parse only product tool-result envelopes, never model prose or an
            # observation's embedded JSON text as a source of returned handles.
            if isinstance(content, str):
                try: content = json.loads(content)
                except (ValueError, RecursionError): return
            collect(content)
        for item in history:
            if self.codec == "openai-chat-text-tools-v1" and item.get("role") == "tool":
                returned(item.get("content"))
            elif self.codec == "openai-responses-text-tools-v1" and item.get("type") == "function_call_output":
                returned(item.get("output"))
            elif item.get("role") == "user":
                for block in item.get("content", []) if isinstance(item.get("content"), list) else item.get("parts", []):
                    if block.get("type") == "tool_result": returned(block.get("content"))
                    if "toolResult" in block:
                        for part in block["toolResult"].get("content", []): returned(part.get("text"))
                    if "functionResponse" in block: returned(block["functionResponse"].get("response", {}).get("output"))
        require(len(identities)<=4096)
        ledger=[dict(kind=k,identifier=v) for k,v in sorted(identities)]
        instruction=("Summarize selected campaign history concisely. Preserve task, unresolved work, exact handles, "
                     "observed outcomes and uncertainty. Omitted history is not evidence; inspect retained evidence "
                     "using its handles when needed. Summary is interpretation. Selected history follows:\n")
        groups=list(self._groups)
        # Keep whole native assistant/tool groups. Never send an oversized full
        # history with another instruction wrapped around it.
        while True:
            source=instruction+_canonical_value(dict(task=self._task,identities=ledger,selected_groups=groups,
                omitted_complete_groups=len(self._groups)-len(groups)),ORDINARY_LIMIT).decode('utf-8')
            request=self._initial(source)
            if self.codec in ("openai-chat-text-tools-v1",
                              "openai-responses-text-tools-v1"):
                request["tool_choice"] = "none"
            elif self.codec == "anthropic-messages-text-tools-v1":
                request["tool_choice"] = {"type": "none"}
            elif self.codec == "bedrock-converse-text-tools-v1":
                request.pop("toolConfig", None)
            elif self.codec == "gemini-text-tools-v1":
                request["toolConfig"]["functionCallingConfig"]["mode"] = "NONE"
            candidate=_canonical_value(request,ORDINARY_LIMIT)
            if len(candidate)<1<<20 and self._estimated_tokens(candidate)<self._context_limits['warning_threshold_tokens']:break
            require(bool(groups))
            groups.pop(0)
        self._compaction_ledger=ledger
        body = {key: deepcopy(self.policy[key])
                for key in ("codec_id", "profile_id", "profile_digest")}
        body["request"] = request
        raw = _canonical_value(body, ORDINARY_LIMIT)
        self.protocol.validate_model_request(self.policy_raw, raw)
        return body, raw, raw_digest(history_raw), self._segments

    def apply_compaction(self, summary, source_digest, omitted_segments):
        require(type(summary) is str and summary and len(summary) <= 128 << 10)
        require(type(source_digest) is str and type(omitted_segments) is int
                and omitted_segments > 0)
        record = {
            "generation": len(self._compactions) + 1,
            "source_digest": source_digest,
            "omitted_complete_segments": omitted_segments,
            "summary_provenance": "model-generated-not-evidence",
        }
        self._compactions.append(record)
        summary_suffix = "\n\nCompacted campaign history:\n" + \
            _canonical_value({**record, "summary": summary, "retained_identities":getattr(self,"_compaction_ledger",[])}, 256 << 10).decode("utf-8")
        compacted = self._task + summary_suffix + self._finalization_guidance()
        require(len(compacted) <= 1 << 20)
        self._summary = summary_suffix
        self._request = self._initial(compacted)
        _, compacted_raw = self.body()
        require(len(compacted_raw) < 1 << 20 and
                self._estimated_tokens(compacted_raw) < self._context_limits['maximum_prompt_tokens'])
        self._segments = 0
        self._groups=[]
        # Compaction consumed a real call; its remaining budget is retained.

    def _history_field(self):
        return "input" if self.codec == "openai-responses-text-tools-v1" else (
            "contents" if self.codec == "gemini-text-tools-v1" else "messages")

    def extend(self, segment_raw):
        segment = decode(segment_raw, ORDINARY_LIMIT)
        require(type(segment) is list)
        field = self._history_field()
        self._request[field].extend(segment)
        self._segments += 1
        self._groups.append(deepcopy(segment))

    def prompt_again(self, text="Continue with the next useful tool action or finish."):
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

    def __init__(self, protocol, client, loop, dispatcher, conversation, finalizer, *, limits=None):
        self.limits = limits or {}
        self.protocol = protocol
        self.client = client
        self.loop = loop
        self.dispatcher = dispatcher
        self.conversation = conversation
        self.finalizer = finalizer

    def _unavailable_reason(self):
        state = self.loop.snapshot()
        for counter in ("consecutive_invalid_tool_calls", "invalid_tool_calls"):
            if "max_" + counter in self.limits and state[counter] >= self.limits["max_" + counter]:
                return "invalid-call-limit"
        return "budget-limit" if state["reason"] == "budget-limit" else "local-error"

    def _finish_unavailable(self, reason, *, model_admission=False):
        state = self.loop.snapshot()
        if state["mode"] == "exploring":
            self.loop.stop("budget-limit" if reason == "budget-limit" else "harness-error")
        if self.limits:
            if model_admission:
                accounting = self.conversation.model_admission_failure
                if accounting is not None:
                    self.dispatcher.report_stopping('budget-limit',
                        budget=self.finalizer.budget(), now=self.finalizer.clock(), model_budget=accounting)
                else:
                    self.dispatcher.report_stopping('model-turn-limit',
                        budget=self.finalizer.budget(), now=self.finalizer.clock())
                return self.finalizer.finish_unavailable(reason)
            condition, observed, limit = reason, None, None
            for counter, kind in (
                ("consecutive_invalid_tool_calls", "invalid-call-limit"),
                ("invalid_tool_calls", "invalid-call-limit"),
                ("tool_calls", "tool-call-limit"), ("model_turns", "model-turn-limit"),
                ("no_progress_turns", "local-error"), ("read_bytes", "budget-limit"),
            ):
                maximum = self.limits["max_" + counter]
                if state[counter] >= maximum:
                    condition, observed, limit = kind, state[counter], maximum
                    break
            if observed is None and reason == "budget-limit":
                if state["skipped_calls"] > self.limits["max_tool_calls_per_response"]:
                    condition, observed, limit = "tool-call-limit", state["skipped_calls"], self.limits["max_tool_calls_per_response"]
            self.dispatcher.report_stopping(condition, observed, limit,
                self.finalizer.budget(), self.finalizer.clock())
        return self.finalizer.finish_unavailable(reason)

    def run(self):
        while self.loop.snapshot()["mode"] == "exploring":
            if not self.conversation.can_fund_model():
                return self._finish_unavailable("budget-limit", model_admission=True)
            self.conversation.prepare_finalization()
            if self.conversation.needs_compaction():
                try:
                    self.loop.begin_model(True)
                except LoopStopped:
                    break
                try:
                    body, request_raw, source_digest, omitted = \
                        self.conversation.compaction_body()
                except ContractError:
                    if self.loop.snapshot()["phase"] == "model":
                        self.loop.accept_response(0)
                        self.loop.stop("no-useful-next-experiment")
                        self.loop.end_turn()
                    return self._finish_unavailable("context-limit")
                try:
                    reply = self.client.request(
                        "engine.model_generate", body,
                        operation_id=self.client.operation_id("model-compaction"),
                    )
                    if reply.error is not None:
                        self.client.fail("model-compaction-failed")
                    result_raw = _canonical_value(reply.result, ORDINARY_LIMIT)
                    batch = native_batch(self.protocol, self.conversation.policy_raw,
                                         request_raw, result_raw)
                except RuntimeStopped:
                    self.loop.hard_stop()
                    raise
                except ContractError as error:
                    self.loop.hard_stop()
                    self.client.fail("model-compaction-contract-failed", cause=error)
                self.conversation.observe_budget(reply.result,request_raw)
                self.loop.accept_response(0)
                if batch.disposition != "text":
                    self.loop.stop("no-useful-next-experiment")
                    self.loop.end_turn()
                    return self._finish_unavailable("context-limit")
                try:
                    self.conversation.apply_compaction(
                        batch.text(), source_digest, omitted)
                except ContractError:
                    self.loop.stop("no-useful-next-experiment")
                    self.loop.end_turn()
                    return self._finish_unavailable("context-limit")
                self.loop.end_turn()
                continue
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
                return self._finish_unavailable("context-limit")
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
                self.conversation.delivered_task_generation = self.conversation.task_generation
            except RuntimeStopped:
                self.loop.hard_stop()
                raise
            except ContractError as error:
                self.loop.hard_stop()
                self.client.fail("model-contract-failed", cause=error)

            self.conversation.observe_budget(reply.result,request_raw)
            if batch.disposition == "tool-calls":
                try:
                    results = self.dispatcher.dispatch(list(batch.calls))
                except LoopStopped:
                    if self.loop.snapshot()["mode"] == "finalizing":
                        if self.dispatcher.last_results:
                            self.conversation.extend(batch.continuation(self.dispatcher.last_results))
                        break
                    raise
                if self.finalizer.pending:
                    return self.finalizer.finish()
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
            return self._finish_unavailable(self._unavailable_reason())
        raise RuntimeStopped("closed")
