"""Fixed, serial model-tool dispatch with restore batch boundaries."""

from dataclasses import dataclass
from copy import deepcopy

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import LoopStopped
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT, safe_argument_path
import re

from .runtime import RuntimeStopped


ARGUMENT_LIMIT = ORDINARY_LIMIT


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: bytes
    correlation: int | None = None
    batch_id: str | None = None


@dataclass(frozen=True)
class HandlerResult:
    value: dict
    outcome: str = "success"


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    outcome: str

    def continuation(self):
        return {"tool_call_id": self.call_id, "content": self.content}


class ToolError(ContractError):
    """A bounded nonfatal local rejection returned to the model."""

    def __init__(self, code, message, *, outcome="invalid", path="", correction="", constraint=None):
        super().__init__(message, reason=code, field_path=path, correction=correction, constraint=constraint)
        require(outcome in ("invalid", "preflight-rejected"))
        self.value = local_error(self)
        self.outcome = outcome

    @classmethod
    def from_contract(cls, error):
        result = cls(error.reason, str(error), path=error.field_path, correction=error.correction, constraint=error.constraint)
        return result

    @classmethod
    def from_host(cls, error):
        result = cls("host_rejection", "Operator rejected this operation.",
                     outcome="preflight-rejected")
        result.value = {"status": "error", **error}
        return result


def local_error(error):
    # Only shared/product-owned diagnostics, never validator repr or input values.
    reason = error.reason if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", error.reason) else "invalid_arguments"
    correction = error.correction if 0 < len(error.correction) <= 512 else "Use the documented tool arguments and exact returned handles."
    return {
        "status": "error", "code": "INTERNAL_ERROR" if reason == "invalid_resolution_context" else "INVALID_ARGUMENTS", "effect_state": "none",
        "disposition": "terminate" if reason == "invalid_resolution_context" else "correct-and-resubmit", "message": "Tool arguments were rejected before execution.",
        "diagnostic": {
            "source": "harness-local", "stage": "translation" if reason == "invalid_resolution_context" else "arguments", "reason": reason,
            "message": str(error)[:512], "field_path": safe_argument_path(error.field_path),
            "correction": correction,
            "execution_occurred": "no", "resubmission_safe": reason != "invalid_resolution_context",
            **({"constraint": error.constraint} if error.constraint else {}),
        },
    }


def _content(value):
    return _canonical_value(value, ORDINARY_LIMIT).decode("utf-8")


@dataclass(frozen=True)
class AssessmentRepair:
    """Product-owned correction state, independent of execution closure."""

    call: ToolCall
    rejection: dict

    def context(self, *, include_arguments=True):
        # Keep exact JSON text, including duplicate keys, as task data. Never
        # parse/rewrite the rejected assessment or promote it to instructions.
        return {"active": True, "tool_call_id": self.call.call_id,
                **({"rejected_arguments": self.call.arguments.decode("utf-8", errors="replace")}
                   if include_arguments else {"request_in_history": self.call.call_id}),
                "rejection": self.rejection}

    def guidance(self):
        return ("Your finish submission was rejected. Assessment repair is active. "
                "Correct the identified field while preserving valid parts of the assessment. "
                "Use existing execution and evidence references. Read relevant evidence or tool guidance "
                "if necessary, then call finish again. Do not start new target actions or ask the user "
                "to select another task. This is a repair instruction, not a selection from any menu. "
                "Report unresolved findings honestly.")


class Dispatcher:
    """Dispatch only explicitly installed handlers in declared call order."""

    def __init__(self, protocol, loop, handlers, *, raw_handlers=None, client=None):
        if raw_handlers is None:
            raw_handlers = {}
        require(type(handlers) is dict and all(type(name) is str and callable(handler)
                                               for name, handler in handlers.items()))
        require(type(raw_handlers) is dict and all(type(name) is str and callable(handler)
                                                   for name, handler in raw_handlers.items()))
        require(not handlers.keys() & raw_handlers.keys())
        self.client = client
        self.last_rejection = None
        self.last_results = []
        self.repair = None
        self.protected_finalization = False
        self.protocol = protocol
        self.loop = loop
        self._handlers = dict(handlers)
        self._raw_handlers = dict(raw_handlers)

    def _check_repair_action(self, call):
        if (self.repair is None and not self.protected_finalization) or call.name in ("finish", "observation_read", "reference_read"):
            return
        if call.name == "artifact_publish":
            try:
                arguments = self.protocol.validate_tool_arguments(call.name, call.arguments)
            except ContractError as error:
                raise ToolError.from_contract(error) from None
            if arguments["purpose"] == "conclusion":
                return
        if self.repair is None:
            raise ToolError("finalization_action_blocked",
                "Protected finalization is active. This action was not executed.",
                correction="Submit an assessment using retained evidence; read observations or tool guidance only when necessary.")
        raise ToolError("assessment_repair_active",
            "Assessment repair is active. This action was not executed.",
            correction="Correct the rejected finish submission using retained evidence; read observations or tool guidance if needed.")

    def protect_finalization(self):
        if self.protected_finalization:
            return
        self.protected_finalization = True
        if self.client is not None:
            self.client.request("engine.diagnostic_report", {'diagnostic': {
                'source': 'harness-local', 'stage': 'dispatch', 'reason': 'finalization_capacity_protected',
                'message': 'Exploration ended to preserve capacity for assessment and correction.',
                'execution_occurred': 'no', 'resubmission_safe': False,
            }}, operation_id=self.client.operation_id('protected-finalization'))

    def report_unresolved_repair(self, budget, now):
        if self.repair is None or self.client is None:
            return
        diagnostic = deepcopy(self.repair.rejection.get("diagnostic", {}))
        reason = diagnostic.get("reason", self.repair.rejection.get("code", "finish_rejected"))
        diagnostic.update(source="harness-local", stage="termination",
            reason="finish_repair_unresolved",
            message=f"Assessment repair ended without an accepted corrected finish. Last rejection: {reason}."[:512],
            execution_occurred="no", resubmission_safe=False)
        budget.charge("diagnostic", 0, now)
        self.client.request("engine.diagnostic_report", {"tool_name": "finish", "diagnostic": diagnostic},
                            operation_id=self.client.operation_id("unresolved-finish"))

    def _report(self, call, value):
        diagnostic = value.get("diagnostic", {})
        if diagnostic.get("source") != "harness-local":
            return
        report = {"diagnostic": diagnostic}
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", call.name):
            report["tool_name"] = call.name
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", call.call_id):
            report["tool_call_id"] = call.call_id
        self.last_rejection = report
        if self.client is not None:
            self.client.request("engine.diagnostic_report", report,
                                operation_id=self.client.operation_id("diagnostic-report"))

    def report_stopping(self, condition, observed=None, limit=None, budget=None, now=None,
                        *, model_budget=None):
        previous = None  # Earlier rejections remain separate retained events, never the stopping cause.
        report = dict(previous or {
            "diagnostic": local_error(ContractError("Harness exploration stopped.",
                reason=condition, correction="Inspect campaign limits and retained diagnostics before starting new work."))["diagnostic"]})
        if model_budget is not None:
            report = {'diagnostic': {
                'source': 'harness-local', 'stage': 'termination',
                'reason': 'model_reservation_unavailable',
                'message': 'Cannot reserve another model request.',
                'execution_occurred': 'no', 'resubmission_safe': False,
            }, 'stopping': {'condition': 'budget-limit', 'budget': dict(model_budget)}}
        elif condition in ('no-progress-limit', 'invalid-call-limit'):
            report = {'diagnostic': {
                'source':'harness-local','stage':'termination','reason':condition.replace('-', '_'),
                'message':('Invalid tool calls reached the configured limit.' if condition == 'invalid-call-limit'
                    else 'Consecutive turns without recognized progress reached the configured limit.'),
                'execution_occurred':'no','resubmission_safe':False,
            },'stopping':{'condition':condition,'observed_count':observed,'configured_limit':limit}}
        elif condition in ('context-limit', 'model-turn-limit'):
            report = {'diagnostic': {
                'source': 'harness-local', 'stage': 'termination',
                'reason': 'context_limit' if condition == 'context-limit' else 'model_call_limit',
                'message': 'Mandatory context cannot fit safely.' if condition == 'context-limit' else 'No model calls remain.',
                'execution_occurred': 'no', 'resubmission_safe': False,
            }}
            # The count-form stopping schema requires genuine observed/limit
            # values. The stable reason identifies context/call exhaustion when
            # those counts are unavailable; do not invent zero counters.
            if observed is not None and limit is not None:
                report['stopping'] = {'condition': condition, 'observed_count': observed, 'configured_limit': limit}
        elif observed is not None and limit is not None:
            report["stopping"] = {"condition": condition, "observed_count": observed,
                                  "configured_limit": limit}
        elif "stopping" not in report:
            report["diagnostic"] = dict(report["diagnostic"], stage="exploration-stop", reason=condition)
        if self.client is not None:
            if budget is not None:
                budget.charge("diagnostic", 0, now)
            self.client.request("engine.diagnostic_report", report,
                                operation_id=self.client.operation_id("diagnostic-report"))

    @staticmethod
    def _skipped(call, transition):
        value = {
            "status": "not_executed",
            "code": "TARGET_REVISION_CHANGED",
            "effect_state": "none",
            "message": "Not executed: target revision changed. Choose the next action using the restore result.",
            "previous_run_revision": transition["previous_run_revision"],
            "run_revision": transition["run_revision"],
            "transition_receipt": transition["transition_receipt"],
        }
        return ToolResult(call.call_id, call.name, _content(value), "not-executed")

    @staticmethod
    def _closed(call):
        return ToolResult(call.call_id, call.name, _content({
            "status": "not_executed", "code": "EXPLORATION_CLOSED", "effect_state": "none",
            "message": "Not executed: campaign exploration has stopped; inspect its stopping or finish result.",
        }), "not-executed")

    def dispatch(self, calls):
        """Process one already validated complete native model response.

        The caller invokes ``HarnessLoop.begin_model`` before this method.  No
        handler or argument decoder runs for calls skipped after restore.
        """
        require(type(calls) is list and all(type(call) is ToolCall for call in calls))
        ids = [call.call_id for call in calls]
        require(len(ids) == len(set(ids)))
        results = []
        self.last_results = results
        try:
            self.loop.accept_response(len(calls))
            for index, call in enumerate(calls):
                self.loop.start_tool(call.name)
                handler = self._handlers.get(call.name)
                raw_handler = self._raw_handlers.get(call.name)
                try:
                    if len(call.arguments) > ARGUMENT_LIMIT:
                        raise ToolError("argument_limit", "Tool arguments exceed the ordinary frame safety ceiling.",
                            correction="Reduce this call's size; use bounded artifact publication for reusable content.")
                    if handler is None and raw_handler is None:
                        raise ToolError("unknown_tool", "Unknown tool name.",
                                        correction="Choose one of the advertised tools.")
                    self._check_repair_action(call)
                    if raw_handler is not None:
                        handled = raw_handler(call)
                    else:
                        try:
                            arguments = self.protocol.validate_tool_arguments(call.name, call.arguments)
                        except ContractError as error:
                            raise ToolError.from_contract(error) from None
                        handled = handler(arguments)
                    require(type(handled) is HandlerResult)
                    require(handled.outcome in ("success", "invalid", "preflight-rejected",
                                                "failed", "restored"))
                except ToolError as error:
                    handled = HandlerResult(error.value, error.outcome)
                except ContractError as error:
                    # Shared sizing checks run before any send. Do not turn a
                    # transport failure or malformed host response into a retry.
                    if isinstance(error, RuntimeStopped) or error.reason != "configured_size_exceeded":
                        raise
                    handled = HandlerResult(local_error(error), "invalid")
                if call.name == "finish":
                    if (handled.outcome in ("invalid", "preflight-rejected") and
                            handled.value.get("disposition") == "correct-and-resubmit"):
                        self.repair = AssessmentRepair(call, deepcopy(handled.value))
                    elif handled.outcome == "success" and handled.value.get("status") == "accepted":
                        self.repair = None
                if handled.outcome == "invalid":
                    self._report(call, handled.value)
                    if handled.value.get('disposition') == 'terminate':
                        if self.client is not None: self.client.fail('internal-tool-resolution-failed')
                        raise RuntimeStopped('internal-tool-resolution-failed')
                value = handled.value
                if self.repair is not None and call.name == "finish":
                    value = dict(value, repair_guidance=self.repair.guidance())
                result = ToolResult(call.call_id, call.name, _content(value), handled.outcome)
                self.loop.finish_tool(handled.outcome)
                results.append(result)
                if handled.outcome == "restored":
                    transition = handled.value
                    for skipped in calls[index + 1:]:
                        results.append(self._skipped(skipped, transition))
                    break
                if self.loop.snapshot()["mode"] != "exploring":
                    results.extend(self._closed(skipped) for skipped in calls[index + 1:])
                    break
            self.loop.end_turn()
            return results
        except RuntimeStopped:
            self.loop.hard_stop()
            raise
        except LoopStopped:
            results.extend(self._closed(call) for call in calls[len(results):])
            state = self.loop.snapshot()
            if state["phase"] == "batch" and state["active_tool"] and not state["reserved_read_bytes"]:
                self.loop.finish_tool("preflight-rejected")
                state = self.loop.snapshot()
            if (state["phase"] == "batch" and not state["active_tool"] and
                    not state["queued_calls"]):
                self.loop.end_turn()
            raise
        except ContractError:
            self.loop.hard_stop()
            raise
