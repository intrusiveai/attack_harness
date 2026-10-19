"""One correctable finish request; accepted closure is not completed cleanup."""
from copy import deepcopy
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.simple import normalize_assessment
from operator_contracts.startup import require

from .artifacts import CONCLUSION_LIMIT
from .tools import HandlerResult, ToolError


class ConclusionFinalizer:
    def __init__(self, protocol, client, inputs, loop, artifacts, *, attempts=None,
                 observations=None, record_receipts=None, campaign_deadline_ms,
                 artifact_remaining, clock=lambda: int(time.monotonic() * 1000)):
        self.protocol, self.client, self.inputs, self.loop = protocol, client, inputs, loop
        self.artifacts, self.attempts, self.observations = artifacts, attempts, observations
        self.record_receipts = record_receipts if record_receipts is not None else set()
        self.campaign_deadline_ms, self.artifact_remaining = campaign_deadline_ms, artifact_remaining
        self.clock = clock
        self._result = None
        self._budget = None

    @property
    def pending(self):
        return self._result is not None

    def _reference_error(self, reference, path, expected):
        category = self.attempts.reference_category(reference) if self.attempts else None
        if reference in self.record_receipts:
            category = "assessment-record receipt"
        try:
            self.artifacts.artifact(reference)
            category = "artifact receipt"
        except ContractError:
            pass
        if category and category != expected:
            message = ("This submission was rejected before execution and has no execution receipt."
                       if category == "rejected submission" else
                       f"This reference is an {category}; this field requires an {expected}.")
            raise ToolError("reference_category", message, path=path,
                            correction="Use an accepted receipt of the required category. Remove references to rejected submissions and report the objective as not tested.")

    def _verify_references(self, draft):
        for group in ("objectives", "hypotheses", "claims", "coverage", "uncertainties"):
            for index, item in enumerate(draft[group]):
                for key, category in (("attempt_receipt_refs", "execution receipt"),
                                      ("record_refs", "assessment-record receipt")):
                    for n, ref in enumerate(item.get(key, [])):
                        self._reference_error(ref, f"/{group}/{index}/{key}/{n}", category)
        for n, ref in enumerate(draft["record_refs"]):
            self._reference_error(ref, f"/record_refs/{n}", "assessment-record receipt")
        for group in ("claims", "uncertainties"):
            for i, item in enumerate(draft[group]):
                for n, ref in enumerate(item["observation_refs"]):
                    if self.observations is None or not self.observations.observed(
                            ref["attempt_receipt_id"], ref["entry_id"]):
                        raise ToolError("evidence_not_inspected", "This observation has not been inspected.",
                            path=f"/{group}/{i}/observation_refs/{n}",
                            correction="Read the permitted observation using its execution receipt and entry ID before citing its contents.")
        # Operator resolves campaign membership, historical references, ownership,
        # visibility and ranges against authoritative retained state.

    def stage(self, arguments):
        require(self._result is None)
        if "assessment" in arguments:
            binding = _canonical_value(self.inputs.conclusion_binding(self.client.run_revision), CONCLUSION_LIMIT)
            try:
                draft = normalize_assessment(self.protocol,
                    _canonical_value(arguments["assessment"], CONCLUSION_LIMIT), binding,
                    arguments["finish_reason"])
            except ContractError as error:
                raise ToolError.from_contract(error) from None
            self._verify_references(draft)
        if self.clock() >= self.campaign_deadline_ms:
            self.client.fail("deadline-exceeded")
        reply = self.client.request("engine.finish", arguments,
                                    operation_id=self.client.operation_id("finish"))
        if reply.error is not None:
            raise ToolError.from_host(reply.error)
        result = reply.result
        require(result["status"] == "accepted" and result["execution_admission"] == "closed"
                and result["exit_required"] and result["exit_within_ms"] == 5000
                and result["finalization_status"] == "pending")
        self._result = deepcopy(result)
        self.loop.stop("no-useful-next-experiment")
        return HandlerResult(result)

    def finish(self):
        require(self.pending)
        return deepcopy(self._result)

    def budget(self):
        if self._budget is None:
            self._budget = self.loop.begin_finalization(
                self.clock(), self.campaign_deadline_ms, self.artifact_remaining)
        return self._budget

    def finish_unavailable(self, reason):
        require(not self.pending)
        if self.loop.snapshot()["mode"] == "exploring":
            self.loop.stop("budget-limit" if reason == "budget-limit" else "harness-error")
        self.budget().charge("finish", 0, self.clock())
        mapped = reason if reason in ("context-limit", "budget-limit") else "harness-error"
        if self.loop.snapshot()["reason"] == "no-useful-next-experiment":
            mapped = "no-useful-next-experiment"
        return self.stage({"finish_reason": mapped, "unavailable": {"reason": reason}}).value
