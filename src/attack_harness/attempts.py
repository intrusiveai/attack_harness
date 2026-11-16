"""Simple execution submissions; Operator retains input and owns attempt metadata."""
from copy import deepcopy

from operator_contracts import ContractError
from operator_contracts.startup import require
from operator_contracts.simple import validate_attempt_origin
from operator_contracts.validation import decode, ORDINARY_LIMIT
from .tools import HandlerResult, ToolError


class AttemptExecutor:
    """Retain correlated results without inventing host execution receipts."""

    def __init__(self, protocol, client, artifacts, context, bundle, loop, *, scenario_delivery=None):
        self.protocol, self.client, self.loop = protocol, client, loop
        self._scenarios = frozenset(s["scenario_id"] for s in bundle.get("scenarios", ()))
        self._history = {}
        self._receipts = set()
        self._rejected_submissions = set()
        self._attempt_ids = set()
        self.dispatched = False
        self.scenario_delivery = scenario_delivery

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

    def reject_submission(self, call_id):
        self._rejected_submissions.add(call_id)

    def __call__(self, call):
        """Canonical service entry; model dispatch uses shared normalization first."""
        try:
            arguments = decode(call.arguments, ORDINARY_LIMIT)
            require(type(arguments) is dict)
            validate_attempt_origin(arguments, self._scenarios)
            self.protocol._catalog.validate_value(
                self.protocol._operations["engine.attempt_execute"]["request_schema"], arguments)
        except ContractError as error:
            self._rejected_submissions.add(call.call_id)
            raise ToolError.from_contract(error) from None
        return self.execute(call, arguments)

    def execute(self, call, arguments):
        key = (call.batch_id, call.call_id, call.correlation)
        previous = self._history.get(key)
        if previous is not None:
            require(previous[0] == call.arguments)
            return deepcopy(previous[1])
        try:
            validate_attempt_origin(arguments, self._scenarios)
            if arguments["origin"] == "scenario" and self.scenario_delivery is not None:
                self.scenario_delivery.require(arguments["scenario_id"])
        except ToolError:
            self._rejected_submissions.add(call.call_id)
            raise
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
