"""Simple execution submissions; Operator retains input and owns attempt metadata."""
from copy import deepcopy

from operator_contracts import ContractError
from operator_contracts.startup import require
from .tools import HandlerResult, ToolError


class AttemptExecutor:
    """Retain correlated results without inventing host execution receipts."""

    def __init__(self, protocol, client, artifacts, context, bundle, loop):
        self.protocol, self.client, self.loop = protocol, client, loop
        self._history = {}
        self._receipts = set()
        self._rejected_submissions = set()
        self._attempt_ids = set()
        self.dispatched = False

    @property
    def receipts(self):
        return frozenset(self._receipts)

    def reference_category(self, value):
        if value in self._receipts:
            return "execution receipt"
        if value in self._rejected_submissions:
            return "rejected submission"
        if value in self._attempt_ids:
            return "attempt ID"
        return None

    def __call__(self, call):
        key = (call.batch_id, call.call_id, call.correlation)
        previous = self._history.get(key)
        if previous is not None:
            require(previous[0] == call.arguments)
            return deepcopy(previous[1])
        try:
            arguments = self.protocol.validate_tool_arguments("attempt_execute", call.arguments)
        except ContractError as error:
            self._rejected_submissions.add(call.call_id)
            raise ToolError.from_contract(error) from None
        operation_id = self.client.operation_id("attempt")
        reply = self.client.request("engine.attempt_execute", arguments, operation_id=operation_id)
        if reply.error is not None:
            self._rejected_submissions.update((call.call_id, operation_id))
            handled = HandlerResult({"status": "error", **reply.error}, "preflight-rejected")
        else:
            result = reply.result
            if result["status"] == "rejected":
                self._rejected_submissions.update((call.call_id, operation_id))
                if "attempt_id" in result:
                    self._rejected_submissions.add(result["attempt_id"])
                handled = HandlerResult(result, "preflight-rejected")
            else:
                receipt = result["receipt_id"]
                self._receipts.add(receipt)
                if "attempt_id" in result:
                    self._attempt_ids.add(result["attempt_id"])
                self.dispatched |= result.get("invocation_state") != "not-dispatched"
                if result["status"] == "completed":
                    self.loop.experiment_completed(receipt)
                    handled = HandlerResult(result)
                else:
                    require(result["status"] in ("failed", "unknown"))
                    self.client.fail(f"attempt-{result['status']}", receipt=receipt)
        self._history[key] = (call.arguments, handled)
        return deepcopy(handled)
