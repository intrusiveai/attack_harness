"""Fixed, serial model-tool dispatch with restore batch boundaries."""

from dataclasses import dataclass

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import LoopStopped
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT

from .runtime import RuntimeStopped


ARGUMENT_LIMIT = 256 << 10


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: bytes


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

    def __init__(self, code, message, *, outcome="preflight-rejected"):
        super().__init__("model tool rejected")
        require(outcome in ("invalid", "preflight-rejected"))
        self.value = {
            "status": "error",
            "code": code,
            "effect_state": "none",
            "message": message[:512],
        }
        self.outcome = outcome


def _content(value):
    return _canonical_value(value, ORDINARY_LIMIT).decode("utf-8")


class Dispatcher:
    """Dispatch only explicitly installed handlers in declared call order."""

    def __init__(self, protocol, loop, handlers):
        require(type(handlers) is dict and all(type(name) is str and callable(handler)
                                               for name, handler in handlers.items()))
        self.protocol = protocol
        self.loop = loop
        self._handlers = dict(handlers)

    @staticmethod
    def _invalid(call, message="Invalid tool name or arguments."):
        return ToolResult(call.call_id, call.name, _content({
            "status": "error",
            "code": "INVALID_TOOL_CALL",
            "effect_state": "none",
            "message": message,
        }), "invalid")

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

    def dispatch(self, calls):
        """Process one already validated complete native model response.

        The caller invokes ``HarnessLoop.begin_model`` before this method.  No
        handler or argument decoder runs for calls skipped after restore.
        """
        require(type(calls) is list and all(type(call) is ToolCall for call in calls))
        ids = [call.call_id for call in calls]
        require(len(ids) == len(set(ids)))
        require(all(0 < len(call.arguments) <= ARGUMENT_LIMIT for call in calls))
        results = []
        try:
            self.loop.accept_response(len(calls))
            for index, call in enumerate(calls):
                self.loop.start_tool(call.name)
                handler = self._handlers.get(call.name)
                if handler is None:
                    result = self._invalid(call, "Unknown tool name.")
                    self.loop.finish_tool("invalid")
                    results.append(result)
                    continue
                try:
                    arguments = self.protocol.validate_tool_arguments(call.name, call.arguments)
                except ContractError:
                    result = self._invalid(call)
                    self.loop.finish_tool("invalid")
                    results.append(result)
                    continue
                try:
                    handled = handler(arguments)
                    require(type(handled) is HandlerResult)
                    require(handled.outcome in ("success", "preflight-rejected", "failed", "restored"))
                except ToolError as error:
                    handled = HandlerResult(error.value, error.outcome)
                result = ToolResult(call.call_id, call.name, _content(handled.value), handled.outcome)
                self.loop.finish_tool(handled.outcome)
                results.append(result)
                if handled.outcome == "restored":
                    transition = handled.value
                    for skipped in calls[index + 1:]:
                        results.append(self._skipped(skipped, transition))
                    break
                if self.loop.snapshot()["mode"] != "exploring":
                    break
            self.loop.end_turn()
            return results
        except RuntimeStopped:
            self.loop.hard_stop()
            raise
        except LoopStopped:
            state = self.loop.snapshot()
            if (state["phase"] == "batch" and not state["active_tool"] and
                    not state["queued_calls"]):
                self.loop.end_turn()
            raise
        except ContractError:
            self.loop.hard_stop()
            raise
