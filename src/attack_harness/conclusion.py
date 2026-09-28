"""Bound conclusion staging and ordered artifact/record/stop finalization."""

from copy import deepcopy
import hashlib
import time

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value
from operator_contracts.startup import require

from .artifacts import ArtifactRejected, CONCLUSION_LIMIT
from .runtime import RuntimeStopped
from .tools import HandlerResult, ToolError


class ConclusionFinalizer:
    """Stage once during dispatch, then finish after the model batch is closed."""

    def __init__(self, protocol, client, inputs, loop, artifacts, *, attempts=None,
                 observations=None, record_receipts=None, campaign_deadline_ms,
                 artifact_remaining, clock=lambda: int(time.monotonic() * 1000)):
        require(type(campaign_deadline_ms) is int and campaign_deadline_ms >= 0)
        require(type(artifact_remaining) is int and artifact_remaining >= 0)
        self.protocol = protocol
        self.client = client
        self.inputs = inputs
        self.loop = loop
        self.artifacts = artifacts
        self.attempts = attempts
        self.observations = observations
        self.record_receipts = record_receipts if record_receipts is not None else set()
        self.campaign_deadline_ms = campaign_deadline_ms
        self.artifact_remaining = artifact_remaining
        self.clock = clock
        self._pending = None
        self._finished = False

    @property
    def pending(self):
        return self._pending is not None and not self._finished

    def _known_attempts(self):
        return frozenset() if self.attempts is None else self.attempts.receipts

    def _verify_references(self, draft):
        known_attempts = self._known_attempts()
        known_records = set(self.record_receipts)
        bundle = self.inputs.bundle()
        objective_ids = {item["objective_id"] for item in bundle["objectives"]}
        scenario_ids = {item["scenario_id"] for item in bundle["scenarios"]}

        for objective in draft["objectives"]:
            require(objective["objective_id"] in objective_ids)
        for hypothesis in draft["hypotheses"]:
            require(set(hypothesis["objective_refs"]) <= objective_ids)
            provenance = hypothesis["provenance"]
            require(provenance.get("scenario_id") is None or
                    provenance["scenario_id"] in scenario_ids)
        for coverage in draft["coverage"]:
            require(coverage["objective_id"] in objective_ids)

        groups = [draft["objectives"], draft["hypotheses"], draft["claims"],
                  draft["coverage"]]
        for group in groups:
            for item in group:
                require(set(item["attempt_receipt_refs"]) <= known_attempts)
                if "record_refs" in item:
                    require(set(item["record_refs"]) <= known_records)
        require(set(draft["record_refs"]) <= known_records)

        for item in [*draft["claims"], *draft["uncertainties"]]:
            for reference in item["observation_refs"]:
                require(self.observations is not None and self.observations.observed(
                    reference["attempt_receipt_id"], reference["entry_id"]))
        for gap in draft["uncertainties"]:
            require(set(gap["record_refs"]) <= known_records)
            for reference in gap["input_refs"]:
                descriptor, _ = self.inputs.entry(reference["entry_id"])
                require(descriptor["root_kind"] == "input")
                span = reference.get("range")
                require(span is None or span["offset"] + span["length"] <= descriptor["size_bytes"])

    def stage(self, draft):
        require(not self._finished and self._pending is None)
        try:
            self._verify_references(draft)
            conclusion = {
                "api_version": "operator.dev/engine-conclusion/v1alpha2",
                "kind": "EngineConclusion",
                "binding": self.inputs.conclusion_binding(self.client.run_revision),
                **deepcopy(draft),
            }
            raw = _canonical_value(conclusion, CONCLUSION_LIMIT)
            self.protocol.validate_conclusion(raw)
        except ContractError:
            raise ToolError("CONCLUSION_INVALID",
                            "Conclusion references or content are invalid.",
                            outcome="invalid") from None
        self._pending = (conclusion, raw)
        stop_reason = draft["finish_reason"]
        loop_reason = stop_reason if stop_reason in ("budget-limit", "harness-error") \
            else "no-useful-next-experiment"
        self.loop.stop(loop_reason)
        return HandlerResult({
            "status": "finalization-requested",
            "finish_reason": stop_reason,
            "conclusion_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        })

    def finish(self):
        require(self.pending)
        conclusion, raw = self._pending
        try:
            budget = self.loop.begin_finalization(
                self.clock(), self.campaign_deadline_ms, self.artifact_remaining,
            )
            charged_bytes = False

            def charge_artifact(_operation, _body):
                nonlocal charged_bytes
                size = 0 if charged_bytes else len(raw)
                budget.charge("conclusion-artifact", size, self.clock())
                charged_bytes = True

            artifact = self.artifacts.publish(
                "conclusion", "application/json", raw,
                canonicalization="raw", before_request=charge_artifact,
            )
            budget.charge("conclusion-record", 0, self.clock())
            record_reply = self.client.request("engine.record_append", {
                "record_kind": "conclusion",
                "record": {
                    "artifact_receipt": artifact.receipt_id,
                    "finish_reason": conclusion["finish_reason"],
                },
            }, operation_id=self.client.operation_id("conclusion-record"))
            require(record_reply.error is None)
            record = record_reply.result
            require(record["record_kind"] == "conclusion" and
                    record["assertion_origin"] == "harness")
            attribution = record["attribution"]
            require(attribution == {
                "campaign_id": self.client.campaign_id,
                "launch_id": self.client.launch_id,
                "run_revision": self.client.run_revision,
            })
            budget.charge("stop", 0, self.clock())
            stop_reply = self.client.request("engine.request_stop", {
                "finish_reason": conclusion["finish_reason"],
                "conclusion": {
                    "state": "committed",
                    "artifact_receipt": artifact.receipt_id,
                    "record_receipt": record["receipt_id"],
                },
            }, operation_id=self.client.operation_id("request-stop"))
            require(stop_reply.error is None)
            result = stop_reply.result
            require(result["status"] == "accepted" and
                    result["conclusion_state"] == "committed" and
                    result["execution_admission"] == "closed" and
                    result["exit_required"] and result["exit_within_ms"] == 5000 and
                    result["finalization_status"] == "pending")
            self._finished = True
            return deepcopy(result)
        except RuntimeStopped:
            raise
        except ArtifactRejected as error:
            reason = "budget-limit" if error.error["code"] == "ARTIFACT_BUDGET_EXCEEDED" \
                else "local-error"
            try:
                return self._stop_unavailable(budget, reason)
            except RuntimeStopped:
                raise
            except ContractError:
                self.client.fail("finalization-failed")
        except ContractError:
            self.client.fail("finalization-failed")

    def _stop_unavailable(self, budget, reason):
        require(reason in ("context-limit", "budget-limit", "local-error",
                           "serialization-failed"))
        budget.charge("stop", 0, self.clock())
        finish_reason = reason if reason in ("context-limit", "budget-limit") \
            else "harness-error"
        reply = self.client.request("engine.request_stop", {
            "finish_reason": finish_reason,
            "conclusion": {"state": "unavailable", "reason": reason},
        }, operation_id=self.client.operation_id("request-stop"))
        require(reply.error is None)
        result = reply.result
        require(result["status"] == "accepted" and
                result["conclusion_state"] == "unavailable" and
                result["execution_admission"] == "closed" and
                result["exit_required"] and result["exit_within_ms"] == 5000 and
                result["finalization_status"] == "pending")
        self._finished = True
        return deepcopy(result)

    def finish_unavailable(self, reason):
        """Finish an already graceful, idle loop when no draft can be retained."""
        require(not self._finished and self._pending is None)
        state = self.loop.snapshot()
        if state["mode"] == "exploring":
            mapped = reason if reason in ("budget-limit",) else "harness-error"
            self.loop.stop(mapped)
            state = self.loop.snapshot()
        require(state["mode"] == "finalizing" and state["phase"] == "idle")
        try:
            budget = self.loop.begin_finalization(
                self.clock(), self.campaign_deadline_ms, self.artifact_remaining,
            )
            return self._stop_unavailable(budget, reason)
        except RuntimeStopped:
            raise
        except ContractError:
            self.client.fail("finalization-failed")
