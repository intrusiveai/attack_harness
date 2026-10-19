"""Controlled model recovery and termination using the real Harness runtime."""
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop
from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.artifacts import ArtifactPublisher
from attack_harness.attempts import AttemptExecutor
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.tools import Dispatcher, ToolCall
from test_vertical_slice import ScriptedHost, Inputs, Clock, Reply, LIMITS


class SimpleHost(ScriptedHost):
    def __init__(self, protocol, mode):
        super().__init__(protocol, [], [b'{"answer":"MARKER"}'])
        self.mode = mode
        self.operations |= {"engine.diagnostic_report"}

    def _calls(self, turn):
        if self.mode == "exhausted" or (self.mode == "corrected" and turn == 1):
            return [(f"bad-{turn}", "attempt_execute", {"operation_id": "invoke"})]
        turn -= self.mode == "corrected"
        if turn == 1:
            return [("invoke", "attempt_execute", {"operation_id": "invoke", "input": {
                "encoding": "json", "value": {"query": "return MARKER"}}})]
        if turn == 2:
            return [("read", "observation_read", {"receipt_id": "attempt-receipt-1",
                "entry_id": "target-output", "offset": 0, "max_bytes": 1024})]
        return [("finish", "finish", {"finish_reason": "objectives-addressed",
            "assessment": {"summary": "Marker observed.", "objectives": [{
                "objective_id": "objective-marker", "outcome": "supported", "summary": "Marker returned.",
                "attempt_receipt_refs": ["attempt-receipt-1"]}]}})]

    def request(self, operation, body, *, operation_id):
        if operation == "engine.diagnostic_report":
            self.protocol._catalog.validate_value("urn:operator:schema:engine-diagnostic-report-request:v1alpha1", body)
            self.events.append((operation, body, operation_id))
            return Reply({})
        if operation == "engine.finish" and "unavailable" in body:
            self.events.append((operation, body, operation_id))
            return Reply({"status": "accepted", "stop_receipt": "stop-1", "execution_admission": "closed",
                "assessment_state": "unavailable", "exit_required": True, "exit_within_ms": 5000,
                "finalization_status": "pending"})
        return super().request(operation, body, operation_id=operation_id)


class SimpleCampaignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def run_campaign(self, mode, **overrides):
        host = SimpleHost(self.protocol, mode)
        limits = dict(LIMITS, max_consecutive_invalid_tool_calls=5)
        limits.update(overrides)
        loop = HarnessLoop(limits)
        artifacts = ArtifactPublisher(self.protocol, host)
        inputs = Inputs({})
        observations = ObservationReader(host)
        attempts = AttemptExecutor(self.protocol, host, artifacts, {}, {}, loop)
        finalizer = ConclusionFinalizer(self.protocol, host, inputs, loop, artifacts,
            attempts=attempts, observations=observations, campaign_deadline_ms=100000,
            artifact_remaining=2 << 20, clock=Clock())
        handlers = FixedHandlers(self.protocol, inputs, host, loop, artifacts=artifacts,
            observations=observations, attempts=attempts, finalizer=finalizer)
        dispatcher = Dispatcher(self.protocol, loop, handlers.handlers(), raw_handlers=handlers.raw_handlers(), client=host)
        policy = {"codec_id": "openai-chat-text-tools-v1", "profile_id": "vertical-slice-profile",
            "profile_digest": "sha256:" + "9" * 64, "request_model": "fixture-model",
            "response_models": ["fixture-model-2026"], "instruction_role": "developer",
            "prompt": "Controlled test.", "max_completion_tokens": 4096,
            "tools": json.loads(self.protocol.model_tools("openai-chat-text-tools-v1", sorted(host.operations)))}
        conversation = NativeConversation(self.protocol, _canonical_value(policy, 4 << 20), "Run campaign.")
        result = AdaptiveHarness(self.protocol, host, loop, dispatcher, conversation, finalizer, limits=limits).run()
        return host, loop, conversation, result

    def test_basic_direct_workflow_has_three_host_calls(self):
        host, _, _, result = self.run_campaign("direct")
        self.assertEqual([op for op, _, _ in host.events if op != "engine.model_generate"],
            ["engine.attempt_execute", "engine.observation_read", "engine.finish"])
        self.assertEqual(result["finalization_status"], "pending")

    def test_model_corrects_missing_input_then_completes(self):
        host, loop, _, result = self.run_campaign("corrected")
        feedback = json.dumps(host.model_requests[1])
        self.assertIn("/input", feedback)
        self.assertIn("harness-local", feedback)
        self.assertEqual(len(host.attempt_ids), 1)
        self.assertEqual(loop.snapshot()["invalid_tool_calls"], 1)
        self.assertEqual(result["assessment_state"], "committed")

    def test_five_invalid_calls_retain_last_feedback_and_stopping_report(self):
        host, loop, conversation, result = self.run_campaign("exhausted")
        self.assertEqual(len(host.attempt_ids), 0)
        reports = [b for op, b, _ in host.events if op == "engine.diagnostic_report"]
        self.assertEqual(len(reports), 6)
        self.assertEqual(reports[-1]["stopping"], {"condition": "invalid-call-limit",
            "observed_count": 5, "configured_limit": 5})
        self.assertEqual(reports[-1]["tool_call_id"], "bad-5")
        self.assertIn("bad-5", str(conversation._request))
        self.assertEqual(host.events[-1][1]["unavailable"]["reason"], "invalid-call-limit")
        self.assertEqual(result["assessment_state"], "unavailable")

    def test_read_budget_exhaustion_can_finish_without_an_assessment(self):
        host, _, _, result = self.run_campaign("direct", max_read_bytes=1)
        self.assertEqual(result["assessment_state"], "unavailable")
        self.assertEqual(host.events[-1][1]["unavailable"]["reason"], "budget-limit")
        report = next(body for operation, body, _ in reversed(host.events) if operation == "engine.diagnostic_report")
        self.assertEqual(report["stopping"]["configured_limit"], 1)
        self.assertEqual(len(host.attempt_ids), 1)

    def test_duplicate_keys_and_missing_range_have_safe_actionable_paths(self):
        for tool, raw, path, correction in (
            ("attempt_execute", b'{"operation_id":"invoke","input":{"encoding":"json","encoding":"utf8","text":"secret"}}',
             "/input/encoding", "each JSON key once"),
            ("finish", json.dumps({"finish_reason": "objectives-addressed", "assessment": {
                "summary": "Untested", "objectives": [], "uncertainties": [{"gap_id": "gap",
                "kind": "evidence-gap", "description": "missing", "input_refs": [{"entry_id": "entry", "range": {}}]}]}}).encode(),
             "/assessment/uncertainties/0/input_refs/0/range/length", "offset and length"),
        ):
            loop = HarnessLoop(LIMITS); loop.begin_model()
            dispatcher = Dispatcher(self.protocol, loop, {tool: lambda _: self.fail("invalid call executed")})
            result = dispatcher.dispatch([ToolCall("call", tool, raw)])[0]
            diagnostic = json.loads(result.content)["diagnostic"]
            self.assertEqual(diagnostic["field_path"], path)
            self.assertIn(correction, diagnostic["correction"])
            self.assertNotIn("secret", result.content)


if __name__ == "__main__": unittest.main()
