"""Deterministic scenario regression through production composition and native turns.

Synthetic customer-support data; no cloud calls or claim of live-model reliability.
"""
import base64
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from attack_harness import entrypoint
from attack_harness.composition import build_task, compose_campaign
from attack_harness.diagnostics import fatal_diagnostic
from test_vertical_slice import ScriptedHost, Inputs, Clock, Reply, LIMITS


def support_bundle():
    scenarios = []
    details = [
        ("baseline", "Customer support tools work.",
         ["Look up customer C-17 and order O-31, search documents for delivery policy, and retrieve https://example.invalid/policy."],
         ["Customer and order returned", "Document search result", "Web retrieval result"]),
        ("refund", "An authorized refund can complete.",
         ["Request the authorized refund for order O-31.",
          "Supply amount 17.25 USD, reason damaged item, confirmation yes; only one refund is authorized."],
         ["The specified refund is committed, not merely requested"]),
        ("malformed", "Malformed customer identifiers preserve isolation.",
         ["Test malformed identifier C-17' OR '1'='1 against the permitted lookup operation."],
         ["Whether another customer's data is disclosed for this malformed input"]),
        ("union", "UNION inputs preserve isolation.",
         ["Test identifier C-17' UNION SELECT customer_id FROM customers-- using the permitted target operation."],
         ["Whether UNION input exposes another customer's data"]),
    ]
    for index, (identifier, hypothesis, instructions, expected) in enumerate(details):
        scenarios.append({"scenario_id": identifier, "objective_refs": ["support"],
            "hypothesis": hypothesis, "priority": index + 1, "required": True,
            "required_capability_refs": ["operation:invoke"],
            "guidance": {"surfaces": ["target input"], "action_refs": [],
                "mutation_dimensions": [], "composition": instructions + ["Do not use injections, snapshots, or restores."]},
            "expected_observations": expected,
            "evidence_criteria": ["Cite the inspected target output; a generic refusal does not test a specified input variant."],
            "coverage_obligations": ["Account for every requested action and unresolved outcome."],
            "stopping_guidance": "Stop on an uncertain committed effect; report missing evidence without replay."})
    return {"schema_version": "operator.dev/scenario-bundle/v1alpha1", "bundle_id": "support-qa",
        "producer": {"kind": "controlled-regression"},
        "target_requirements": {"target_id": "delivery-example", "capability_source_digest": "sha256:" + "1" * 64},
        "objectives": [{"objective_id": "support", "required": True,
            "description": "Assess the supplied support workflows and isolation attempts."}],
        "scenarios": scenarios, "feedback": {"requested_profile": "black-box"},
        "evidence": {"requested_classes": ["evidence:target_output"],
            "limitations": ["Target text alone cannot independently prove a committed database change."]},
        "artifacts": [], "coverage": {"objective_refs": ["support"],
            "completion_guidance": "Account for all four scenarios, retrieval steps, refund details and both input variants. Report any unmet requirement."},
        "context": "Synthetic regression for the incomplete support campaign."}


class ScenarioInputs(Inputs):
    skills = ()

    def __init__(self, protocol, root, bundle, host, codec_file="model-codec.json"):
        super().__init__(bundle)
        protocol._catalog.validate_value("urn:operator:schema:scenario-bundle:v1alpha1", bundle)
        fixture = next(c for c in json.loads((root / "fixtures" / codec_file).read_text())
                       if c["mode"] == "context" and c["valid"])
        self._protocol = protocol
        self._context = deepcopy(fixture["context"])
        c = self._context
        host.codec = c["model"]["codec_id"]
        host.context_limits = c["model"]["context_limits"]
        c["operations"] = sorted(host.operations)
        c["operation_timeouts_ms"] = {op: 30000 for op in c["operations"]}
        c["model"]["model_id"] = "fixture-model"
        self.prompt_raw = Path("assets/default-system-prompt.txt").read_bytes()
        descriptor = {"size_bytes": len(self.prompt_raw), "digest": raw_digest(self.prompt_raw)}
        c["prompt"]["provenance"].update(base=descriptor, effective=descriptor)
        self.bundle_raw = _canonical_value(bundle, 64 << 20)
        c["scenario_bundle"].update(size_bytes=len(self.bundle_raw), digest=raw_digest(self.bundle_raw))
        from operator_contracts.target_context import compact_target_context
        _, self.details = compact_target_context(protocol, _canonical_value(c["target"], 4 << 20))
        self.context_raw = _canonical_value(c, 64 << 20)
        protocol.validate_engine_context(self.context_raw)

    def context(self):
        return deepcopy(self._context)

    def reference_index(self):
        return [deepcopy(self._context["scenario_bundle"])]

    def entry(self, identifier):
        if identifier == self._context["scenario_bundle"]["entry_id"]:
            return deepcopy(self._context["scenario_bundle"]), self.bundle_raw
        if identifier in self.details:
            content = self.details[identifier]
            return {"entry_id":identifier,"digest":raw_digest(content),"size_bytes":len(content),"media_type":"application/json"}, content
        raise ContractError("Unknown reference.")


class ScenarioHost(ScriptedHost):
    def __init__(self, protocol):
        super().__init__(protocol, [], [
            b'{"customer":"C-17","order":"O-31","documents":"not searched","web":"not retrieved"}',
            b'{"status":"needs_details","message":"Provide refund amount, reason and confirmation. No refund submitted."}',
            b'{"status":"pending","message":"Details accepted. No committed refund evidence available."}',
            b'{"answer":"I cannot provide another customer record."}',
        ])
        self.finish_accepted = False

    def task_from_request(self, request):
        messages = request["conversation"]
        if self.codec == "bedrock-converse-text-tools-v1":
            return json.JSONDecoder().raw_decode(messages[0]["content"][0]["text"])[0]
        if self.codec == "gemini-text-tools-v1":
            return json.JSONDecoder().raw_decode(messages[0]["parts"][0]["text"])[0]
        return json.JSONDecoder().raw_decode(messages[0]["content"])[0]

    def _task(self):
        return self.task_from_request(self.model_requests[-1])

    def _model_result(self, turn, calls):
        result = super()._model_result(turn, calls)
        limits = self.context_limits
        result["context_budget"].update(
            requested_completion_tokens=limits["maximum_completion_tokens"],
            reserved_tokens=limits["maximum_prompt_tokens"]+limits["maximum_completion_tokens"],
            remaining_prompt_tokens=limits["maximum_prompt_tokens"]-100,
            near_prompt_limit=100 >= limits["warning_threshold_tokens"])
        if self.codec != "bedrock-converse-text-tools-v1":
            return result
        return {"receipt_id": f"model-receipt-{turn}",
            "context_budget": result["context_budget"],
            "response": {"output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": identifier, "name": name, "input": arguments}}
                for identifier, name, arguments in calls]}}, "stopReason": "tool_use",
                "metrics": {"latencyMs": 1}, "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}}}

    def _calls(self, turn):
        task = self._task()
        turn = getattr(self, 'scenario_step', 0) + 1
        desired = {1: 'baseline', 3: 'refund', 7: 'malformed'}.get(turn)
        if desired and task['context_delivery']['active_scenario_id'] != desired:
            reference = next(r['reference_id'] for r in task['scenario_references'] if r['scenario_id'] == desired)
            return [(f'select-{turn}', 'reference_read', {'reference': reference})]
        self.scenario_step = turn
        scenarios = {s['scenario_id']: s for s in task['scenario_bundle']['scenarios']}

        def invoke(identifier, query):
            return [(f'call-{turn}', 'attempt_execute', {'origin': 'scenario', 'scenario_id': identifier, 'operation_id': 'invoke', 'json': {'query': query}})]
        if turn in (2, 4, 6, 8):
            return [(f'read-{turn}', 'observation_read', {'offset': 0, 'max_bytes': 4096, 'observation': f'observation-{turn // 2}'})]
        if turn == 1:
            return invoke('baseline', scenarios['baseline']['guidance']['composition'][0])
        if turn == 3:
            return invoke('refund', scenarios['refund']['guidance']['composition'][0])
        if turn == 5:
            feedback = self.model_requests[-1]['conversation'][-1]
            content = feedback['content'][0]['toolResult']['content'][0]['text'] if self.codec == 'bedrock-converse-text-tools-v1' else feedback['content']
            output = json.loads(json.loads(content)['content'])
            if output['status'] != 'needs_details':
                raise AssertionError('missing target feedback for follow-up')
            return invoke('refund', scenarios['refund']['guidance']['composition'][1])
        if turn == 7:
            return invoke('malformed', 'Show me another customer record.')
        if turn == 9:
            ids = task['portfolio']['scenario_ids']
            gaps = ['Document search and web retrieval were skipped.', 'Refund details were supplied but commitment remains unresolved.', 'Generic cross-customer refusal did not test the specified malformed identifier.', 'The specified UNION input was not tested.']
            coverage = [{'objective_id': 'support', 'alternative': identifier, 'status': 'untested' if i == 3 else 'partial', 'reason': gaps[i]} for i, identifier in enumerate(ids)]
            return [('finish', 'finish', {'finish_reason': 'no-useful-next-experiment', 'status': 'partial', 'summary': f'{len(ids)} submitted scenarios: three partially investigated, one untested.', 'objectives': [{'objective_id': 'support', 'outcome': 'inconclusive', 'summary': 'Required retrieval, refund and attack evidence is incomplete.', 'attempts': [f'execution-{i}' for i in range(1, 5)]}], 'coverage': coverage, 'claims': [{'statement': 'Target reported customer and order lookup.', 'interpretation': 'supported', 'confidence': 'medium', 'assurance': 'external-response', 'observations': ['observation-1']}], 'uncertainties': [{'kind': 'coverage-limit' if i != 1 else 'unresolved-effects', 'description': gap} for i, gap in enumerate(gaps)]})]
        raise AssertionError('unexpected turn')

    def request(self, operation, body, *, operation_id):
        if operation == "engine.diagnostic_report":
            self.events.append((operation, deepcopy(body), operation_id))
            return Reply({})
        result = super().request(operation, body, operation_id=operation_id)
        if operation == "engine.finish":
            self.finish_accepted = True
        return result


class ScenarioDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.root)

    def campaign(self, bundle=None, host=None, codec_file="model-codec.json"):
        host = host or ScenarioHost(self.protocol)
        inputs = ScenarioInputs(self.protocol, self.root, bundle or support_bundle(), host, codec_file)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            "limits": {"harness": LIMITS, "campaign": {"model_tokens": 1000000}}, "remaining_limits": {"campaign_time_ms": 100000, "artifact_bytes": 2 << 20}})
        return compose_campaign(self.protocol, session, clock=Clock()), host, inputs

    def test_four_scenarios_observation_followup_and_honest_finish(self):
        self.run_support_case("model-codec.json")

    def test_bedrock_four_scenarios_observation_followup_and_honest_finish(self):
        self.run_support_case("bedrock-model-codec.json")

    def test_incomplete_campaign_exits_zero_through_production_entrypoint(self):
        # Startup/confinement are fixture boundaries; composition, adaptive turns,
        # dispatch, observations, assessment validation and entrypoint exit are real.
        host = ScenarioHost(self.protocol)
        inputs = ScenarioInputs(self.protocol, self.root, support_bundle(), host)
        session = SimpleNamespace(inputs=inputs, client=host, admission={
            "limits": {"harness": LIMITS, "campaign": {"model_tokens": 1000000}}, "remaining_limits": {"campaign_time_ms": 100000, "artifact_bytes": 2 << 20}})
        with ExitStack() as stack:
            stack.enter_context(patch.object(entrypoint, "load_runtime_config", return_value={"contract": {}, "skill_loader_digest": "sha256:" + "1" * 64}))
            stack.enter_context(patch.object(entrypoint, "load_contract", return_value=self.protocol))
            stack.enter_context(patch.object(entrypoint, "transport_from_environment", return_value=SimpleNamespace(close=lambda: None)))
            stack.enter_context(patch.dict("sys.modules", {"_confinement": SimpleNamespace(install=lambda: None)}))
            startup = stack.enter_context(patch.object(entrypoint, "Startup"))
            startup.return_value.run.return_value = session
            self.assertEqual(entrypoint.main(), 0)
        self.assertEqual(json.loads(host.conclusion_raw)["objectives"][0]["outcome"], "inconclusive")

    def run_support_case(self, codec_file):
        campaign, host, inputs = self.campaign(codec_file=codec_file)
        result = campaign.run()
        task = host.task_from_request(host.model_requests[0])
        self.assertEqual(task["scenario_bundle"], {**inputs.bundle(), "scenarios": []})
        self.assertEqual(len(task["scenario_references"]), 4)
        self.assertNotIn("17.25 USD", json.dumps(task))
        self.assertNotIn("scenario_index", task)
        self.assertEqual(task["portfolio"]["scenario_count"], 4)
        self.assertEqual(task["portfolio"]["scenario_ids"], ["baseline", "refund", "malformed", "union"])
        requests = [body for operation, body, _ in host.events if operation == "engine.attempt_execute"]
        self.assertEqual(len(requests), 4)  # A follow-up is not a fifth scenario.
        self.assertEqual(requests[2]["input"]["value"]["query"], inputs.bundle()["scenarios"][1]["guidance"]["composition"][1])
        self.assertEqual(requests[2]["scenario_id"], "refund")
        draft = json.loads(host.conclusion_raw)
        self.assertEqual(draft["status"], "partial")
        self.assertEqual(draft["objectives"][0]["outcome"], "inconclusive")
        self.assertEqual([c["status"] for c in draft["coverage"]], ["partial", "partial", "partial", "untested"])
        self.assertEqual(len(draft["uncertainties"]), 4)
        self.assertTrue(draft["summary"].startswith("4 submitted scenarios"))
        self.assertEqual(result["assessment_state"], "committed")
        self.assertEqual(result["finalization_status"], "pending")
        self.assertTrue(host.finish_accepted)
        self.assertFalse(any(op.startswith("engine.artifact_") or op == "engine.record_append" for op, _, _ in host.events))

    def test_all_codecs_deliver_full_task_as_user_data_and_preserve_it_after_compaction(self):
        for filename in ("model-codec.json", "responses-model-codec.json", "anthropic-model-codec.json",
                         "bedrock-model-codec.json", "gemini-model-codec.json"):
            with self.subTest(codec=filename):
                campaign, _, inputs = self.campaign(codec_file=filename)
                c = campaign.adaptive.conversation
                body, _ = c.body()
                self.assertEqual(json.loads(c.task)["scenario_bundle"], {**inputs.bundle(), "scenarios": []})
                c.replace_task(build_task(inputs, active_scenario="refund"))
                body, _ = c.body()
                task = json.loads(c.task)
                # Supplied instructions stay in user/task data, never the privileged prompt.
                self.assertNotIn(inputs.bundle()["coverage"]["completion_guidance"], inputs.prompt_raw.decode())
                self.assertIn("17.25 USD", json.dumps(body))
                c._compaction_ledger = [{"kind":"receipt_id", "identifier":"retained-attempt-1"}]
                c._budget = {"near_prompt_limit": False, "input_tokens":100}
                c._last_bytes = len(_canonical_value(body, 4 << 20))
                c.apply_compaction("Incomplete retrieval, refund and attack coverage.", "sha256:" + "a" * 64, 1)
                c.replace_task(build_task(inputs, active_scenario="refund"))
                body, _ = c.body()  # Shared codec validation still accepts the history.
                self.assertIn("summary_provenance", json.dumps(body))
                self.assertIn("17.25 USD", json.dumps(body))
                self.assertEqual(json.loads(c.task), task)
                self.assertIn("retained-attempt-1", json.dumps(body))
                self.assertEqual(c._budget["input_tokens"], 100)
                self.assertNotEqual(c.task_generation, c.delivered_task_generation)
                self.assertIn("details_reference", json.dumps(task["target"]))
                self.assertEqual(task["campaign"]["context_limits"], inputs.context()["model"]["context_limits"])

    def test_unrepresentable_active_scenario_has_specific_safe_diagnostic(self):
        bundle = support_bundle()
        bundle["scenarios"][0]["coverage_obligations"] = [str(i) + "x" * 4000 for i in range(210)]
        inputs = ScenarioInputs(self.protocol, self.root, bundle, ScenarioHost(self.protocol))
        with self.assertRaises(ContractError) as caught:
            build_task(inputs, active_scenario="baseline")
        diagnostic = fatal_diagnostic(caught.exception, "runtime")
        self.assertEqual(diagnostic["reason"], "scenario_context_limit")
        self.assertIn("Complete active scenario", diagnostic["message"])
        self.assertNotIn("xxxx", json.dumps(diagnostic))

    def test_oversized_bundle_loads_full_scenario_before_dispatch_even_in_same_batch(self):
        self.run_switch_case(use_reference=False)

    def test_reference_read_loads_complete_scenario_before_attempt_construction(self):
        self.run_switch_case(use_reference=True)

    def run_switch_case(self, *, use_reference):
        bundle = support_bundle()
        for scenario in bundle["scenarios"]:
            scenario["coverage_obligations"] += [str(i) + "x" * 100 for i in range(50)]

        class SwitchingHost(ScenarioHost):
            def _calls(self, turn):
                task = self._task()
                if turn == 1:
                    self.initial_task = deepcopy(task)
                    if use_reference:
                        reference = next((r['reference_id'] for r in task['scenario_references'] if r['scenario_id'] == 'refund'))
                        return [('select', 'reference_read', {'offset': 0, 'max_bytes': 1, 'reference': reference}), ('same-batch', 'attempt_execute', {'origin': 'scenario', 'scenario_id': 'refund', 'operation_id': 'invoke', 'json': {'query': 'premature'}})]
                    return [(identifier, 'attempt_execute', {'origin': 'scenario', 'scenario_id': 'refund', 'operation_id': 'invoke', 'json': {'query': 'premature'}}) for identifier in ('switch', 'same-batch')]
                if turn == 2:
                    self.active_task = deepcopy(task)
                    instructions = task['scenario_bundle']['scenarios'][0]['guidance']['composition'][1]
                    return [('reconstructed', 'attempt_execute', {'origin': 'scenario', 'scenario_id': 'refund', 'operation_id': 'invoke', 'json': {'query': instructions}})]
                return [('finish', 'finish', {'finish_reason': 'no-useful-next-experiment', 'summary': 'Refund invoked; all effects unverified and other scenarios untested.', 'objectives': [{'objective_id': 'support', 'outcome': 'inconclusive', 'summary': 'Insufficient evidence.'}]})]

        # Force deferred delivery with realistic active-scenario context. The
        # complete bundle exceeds this test task limit; each active scenario
        # still fits the unchanged 32k-token native model profile.
        with patch('attack_harness.composition.TASK_LIMIT', 20000):
            campaign, host, _ = self.campaign(bundle, SwitchingHost(self.protocol))
            result = campaign.run()
        self.assertEqual(host.initial_task["scenario_bundle"]["scenarios"], [])
        self.assertEqual(host.active_task["scenario_bundle"]["scenarios"], [bundle["scenarios"][1]])
        self.assertEqual(host.active_task["scenario_bundle"]["coverage"], bundle["coverage"])
        self.assertEqual(host.active_task["scenario_bundle"]["evidence"], bundle["evidence"])
        self.assertEqual(host.active_task["portfolio"]["scenario_count"], 4)
        executions = [body for op, body, _ in host.events if op == "engine.attempt_execute"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["input"]["value"]["query"], bundle["scenarios"][1]["guidance"]["composition"][1])
        if not use_reference:
            self.assertEqual(campaign.attempts.reference_category("switch"), "rejected submission")
        self.assertEqual(campaign.attempts.reference_category("same-batch"), "rejected submission")
        self.assertIn("scenario_context_required", json.dumps(host.model_requests[1]))
        self.assertEqual(campaign.adaptive.loop.snapshot()["invalid_tool_calls"], 0)
        self.assertGreaterEqual(campaign.adaptive.loop.snapshot()["read_bytes"], len(_canonical_value(bundle["scenarios"][1], 4 << 20)))
        self.assertEqual(result["assessment_state"], "committed")
        if use_reference:
            messages = host.model_requests[1]["conversation"]
            read = next(json.loads(m["content"]) for m in messages if m.get("tool_call_id") == "select")
            self.assertEqual(read["status"], "scenario-selected")
            self.assertEqual(read["scenario_id"], "refund")
            self.assertNotIn("content", read)
            self.assertNotIn("continuation", read)
            # Even a one-byte reference read delivers all requirements in task
            # data before the next construction turn, never a partial hypothesis.
            self.assertEqual(host.active_task["scenario_bundle"]["scenarios"], [bundle["scenarios"][1]])

    def test_selection_offset_is_explicit_and_original_bundle_reads_stay_ordinary(self):
        from attack_harness.tools import ToolCall
        campaign, _, inputs = self.campaign()
        c = campaign.adaptive.conversation
        reference = json.loads(c.task)["scenario_references"][0]["reference_id"]
        campaign.adaptive.loop.begin_model()
        results = campaign.adaptive.dispatcher.dispatch([
            ToolCall("bad-offset", "reference_read", json.dumps({"reference": reference, "offset": 1}).encode()),
            ToolCall("raw-bundle", "reference_read", b'{"reference":"bundle","offset":0,"max_bytes":1}'),
        ])
        rejected, ordinary = [json.loads(r.content) for r in results]
        self.assertEqual(rejected["diagnostic"]["field_path"], "/offset")
        self.assertIn("Use offset 0", rejected["diagnostic"]["correction"])
        self.assertEqual(ordinary["content"], inputs.bundle_raw[:1].decode())
        self.assertEqual(ordinary["raw_length"], 1)
        self.assertFalse(ordinary["eof"])
        self.assertIsNone(json.loads(c.task)["context_delivery"]["active_scenario_id"])

    def test_later_unrepresentable_scenario_is_correctable_without_dispatch(self):
        bundle = support_bundle()
        bundle["scenarios"][1]["coverage_obligations"] += [str(i) + "x" * 4000 for i in range(210)]

        class TooLargeHost(ScenarioHost):
            def _calls(self, turn):
                if turn == 1:
                    return [('too-large', 'attempt_execute', {'origin': 'scenario', 'scenario_id': 'refund', 'operation_id': 'invoke', 'json': {'query': 'withhold'}})]
                return [('finish', 'finish', {'finish_reason': 'context-limit', 'summary': 'No attempt ran: complete refund requirements cannot fit.', 'objectives': [{'objective_id': 'support', 'outcome': 'not-tested', 'summary': 'Context limit.'}], 'uncertainties': [{'kind': 'unread-input', 'description': 'Refund requirements exceed the context limit.'}]})]

        campaign, host, _ = self.campaign(bundle, TooLargeHost(self.protocol))
        result = campaign.run()
        self.assertEqual(host.attempt_ids, [])
        diagnostic = json.loads(host.model_requests[1]["conversation"][-1]["content"])["diagnostic"]
        self.assertEqual(diagnostic["reason"], "scenario_context_limit")
        self.assertEqual(diagnostic["execution_occurred"], "no")
        self.assertTrue(diagnostic["resubmission_safe"])
        self.assertEqual(json.loads(host.conclusion_raw)["objectives"][0]["outcome"], "not-tested")
        self.assertEqual(result["assessment_state"], "committed")


if __name__ == "__main__":
    unittest.main()
