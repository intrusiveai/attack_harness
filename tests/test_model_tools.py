"""Runtime handles, shared normalization, evidence retention and call recovery."""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.loop import HarnessLoop
from attack_harness.artifacts import ArtifactPublisher
from attack_harness.attempts import AttemptExecutor
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.runtime import RuntimeStopped
from attack_harness.tools import Dispatcher, ToolCall
from test_vertical_slice import ScriptedHost, Inputs, LIMITS, Clock, Reply


class Host(ScriptedHost):
    def __init__(self, protocol):
        super().__init__(protocol, [], [b'{"answer":"MARKER"}'] * 4)
        self.operations |= {"engine.snapshot_request", "engine.snapshot_list", "engine.snapshot_inspect",
                            "engine.restore_request", "engine.injection_delete"}
        self.reject_selection = False
        self.error = None
        self.snapshot = dict(campaign_id=self.campaign_id, source_session="session-raw", checkpoint_id="checkpoint-raw",
            label="before", description="baseline", created_at="2026-11-05T00:00:00Z", status="ready", canonical_size_bytes=1)

    def request(self, operation, body, *, operation_id):
        if self.error and operation == "engine.finish":
            r = Reply({}); r.error = self.error
            return r
        if operation == "engine.diagnostic_report" and body.get("observation_selections") and self.reject_selection:
            r = Reply({}); r.error = dict(code="POLICY_DENIED", message="Retention failed.", effect_state="none", disposition="correct-and-resubmit")
            return r
        if operation == "engine.observation_read":
            index = int(body["receipt_id"].rsplit("-", 1)[1]) - 1
            content = self.observations[index]; offset = body["offset"]
            # Keep the full metadata but return only the requested bytes.
            result = super().request(operation, body, operation_id=operation_id).result
            part = content[offset:offset + body["max_bytes"]]
            result.update(content=base64.b64encode(part).decode(), raw_length=len(part), eof=offset + len(part) == len(content))
            return Reply(result)
        if operation in ("engine.snapshot_request", "engine.snapshot_inspect", "engine.snapshot_list"):
            self.events.append((operation, deepcopy(body), operation_id))
            return Reply(dict(snapshots=[self.snapshot], offset=0, total=1) if operation.endswith("list") else dict(snapshot=self.snapshot))
        if operation == "engine.restore_request":
            self.events.append((operation, deepcopy(body), operation_id)); self.run_revision += 1
            return Reply(dict(previous_run_revision=self.run_revision - 1, run_revision=self.run_revision,
                              transition_receipt="restore-raw", harness_disposition="continue"))
        if operation == "engine.injection_delete":
            self.events.append((operation, deepcopy(body), operation_id))
            return Reply(dict(receipt_id="delete-raw", **body, outcome="deleted"))
        result = super().request(operation, body, operation_id=operation_id)
        if operation == "engine.attempt_execute" and body.get("retain_injections"):
            result.result["cleanup_state"] = "not-requested"
        return result


class ModelToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.source)

    def setUp(self):
        self.host = Host(self.protocol)
        self.loop = HarnessLoop(dict(LIMITS, max_invalid_tool_calls=20, max_consecutive_invalid_tool_calls=10))
        self.inputs = Inputs({"scenarios": [{"scenario_id": "configuration"}]})
        artifacts = ArtifactPublisher(self.protocol, self.host)
        observations = ObservationReader(self.host)
        attempts = AttemptExecutor(self.protocol, self.host, artifacts, {}, self.inputs.bundle(), self.loop)
        finalizer = ConclusionFinalizer(self.protocol, self.host, self.inputs, self.loop, artifacts,
            attempts=attempts, observations=observations, campaign_deadline_ms=100000,
            artifact_remaining=1 << 20, clock=Clock())
        self.handlers = FixedHandlers(self.protocol, self.inputs, self.host, self.loop,
            artifacts=artifacts, observations=observations, attempts=attempts, finalizer=finalizer)
        self.dispatcher = Dispatcher(self.protocol, self.loop, {}, raw_handlers=self.handlers.raw_handlers())
        self.model = self.handlers.model_tools
        self.serial = 0

    def call(self, name, arguments, identifier=None):
        self.serial += 1
        self.loop.begin_model()
        call = ToolCall(identifier or f"call-{self.serial}", name,
            arguments if isinstance(arguments, bytes) else json.dumps(arguments).encode())
        result = self.dispatcher.dispatch([call])[0]
        return json.loads(result.content)

    def execute(self):
        return self.call("attempt_execute", dict(origin="scenario", scenario_id="configuration", operation_id="invoke", json={"query": "marker"}))

    def finish(self, observation):
        return dict(finish_reason="objectives-addressed", summary="Marker observed.",
            objectives=[dict(objective_id="objective-marker", outcome="supported", summary="Observed.", observations=[observation])],
            claims=[dict(statement="Marker returned.", interpretation="supported", assurance="external-response", confidence="high", observations=[observation])])

    def test_four_attempt_qa_finish_derives_claim_receipts_and_retains_selections(self):
        handles = []
        for _ in range(4):
            result = self.execute()
            self.assertNotIn("receipt_id", result)
            observed = self.call("observation_read", {"observation": result["observations"][0]["observation"]})
            handles.append(observed["citation"])
        bad = self.call("finish", b'{"finish_reason":"objectives-addressed","summary":"one","summary":"two","objectives":[]}')
        self.assertEqual(bad["diagnostic"]["field_path"], "/summary")
        draft = self.finish(handles[0])
        draft["claims"] *= 4
        draft["claims"] = [dict(c, observations=[h]) for c, h in zip(draft["claims"], handles)]
        result = self.call("finish", draft, "finish-good")
        self.assertEqual(result["assessment_state"], "committed")
        self.assertEqual(len(self.host.attempt_ids), 4)
        assessment = json.loads(self.host.conclusion_raw)
        for i, claim in enumerate(assessment["claims"], 1):
            self.assertEqual(claim["attempt_receipt_refs"], [f"attempt-receipt-{i}"])
        operations = [op for op, _, _ in self.host.events]
        self.assertEqual(operations[-2:], ["engine.diagnostic_report", "engine.finish"])
        self.assertNotIn("stopping", self.host.events[-2][1])
        same = self.model.dispatch(ToolCall("finish-good", "finish", json.dumps(draft).encode()))
        self.assertEqual(same.value, result)
        self.assertEqual([op for op, _, _ in self.host.events].count("engine.finish"), 1)

    def test_pagination_instructions_are_executable_and_bound_to_readable_extent(self):
        whole = self.execute()['observations'][0]['observation']
        first = self.call('observation_read', dict(observation=whole, max_bytes=4))
        self.assertEqual(first['readable_observation'], whole)
        self.assertNotEqual(first['citation'], whole)
        self.assertFalse(self.model.resources[whole]['inspected'])
        rejected = self.call('finish', self.finish(whole))
        self.assertEqual(rejected['diagnostic']['reason'], 'evidence_not_inspected')
        self.assertIn(first['citation'], rejected['diagnostic']['correction'])
        next_read = first['continuation']
        self.assertEqual(next_read, dict(tool='observation_read', arguments=dict(observation=whole, offset=4, max_bytes=4)))
        second = self.call(next_read['tool'], next_read['arguments'])
        self.assertEqual(second['offset'], 4)
        bounded = self.call('observation_read', dict(observation=first['citation'], offset=0, max_bytes=2))
        last = self.call(bounded['continuation']['tool'], bounded['continuation']['arguments'])
        self.assertEqual(last['offset'] + last['raw_length'], 4)
        self.assertNotIn('continuation', last)
        self.assertFalse(last['eof'])  # End of permitted range, not end of entry.
        while 'continuation' in second:
            second = self.call(second['continuation']['tool'], second['continuation']['arguments'])
        self.assertTrue(second['eof'])
        self.assertFalse(self.model.resources[whole]['inspected'])
        self.assertEqual(self.call('finish', self.finish(first['citation']))['assessment_state'], 'committed')

    def test_finish_structural_errors_preserve_specific_shared_corrections(self):
        for changes, path, correction in (
            ({'observations': []}, '', 'Unsupported fields'),
            ({'uncertainties': [{'kind': 'invented', 'description': 'gap'}]}, '/uncertainties/0/kind', 'evidence-gap'),
            ({'uncertainties': ['gap']}, '/uncertainties/0', 'object'),
        ):
            with self.subTest(path=path):
                result = self.call('finish', dict(finish_reason='budget-limit', summary='Not tested.', objectives=[], **changes))
                self.assertEqual(result['diagnostic']['field_path'], path)
                self.assertIn(correction, result['diagnostic']['correction'])
                self.assertEqual(result['diagnostic']['execution_occurred'], 'no')
                self.assertTrue(result['diagnostic']['resubmission_safe'])
        self.assertFalse(any(op == 'engine.finish' for op, _, _ in self.host.events))

    def test_unsupported_claim_names_and_purposes_survive_immediate_response(self):
        claim=dict(statement='A limited observation.',interpretation='inconclusive',confidence='low',assurance='direct-observation',references=['invented'])
        rejected=self.call('finish',dict(finish_reason='budget-limit',summary='Not tested.',objectives=[],claims=[claim]))
        d=rejected['diagnostic']
        self.assertEqual(d['field_path'],'/claims/0')
        self.assertEqual(d['unsupported_fields']['names'],['references'])
        self.assertIn('Inspected observation citation handles',d['correction'])
        self.assertIn('Required.',d['correction'])
        self.assertFalse(any(op=='engine.finish' for op,_,_ in self.host.events))
        claim['observations']=claim.pop('references')
        rejected=self.call('finish',dict(finish_reason='budget-limit',summary='Not tested.',objectives=[],claims=[claim]))
        self.assertEqual(rejected['diagnostic']['reason'],'unknown_handle')
        self.assertFalse(any(op=='engine.finish' for op,_,_ in self.host.events))

    def test_wrong_kind_unread_and_partial_evidence_are_correctable(self):
        result = self.execute(); whole = result["observations"][0]["observation"]
        for handle, reason in ((whole, "evidence_not_inspected"), (result["execution"], "wrong_handle_kind"), ("invented", "unknown_handle")):
            rejected = self.call("finish", self.finish(handle))
            self.assertEqual(rejected["diagnostic"]["reason"], reason)
            self.assertEqual(rejected["diagnostic"]["field_path"], "/objectives/0/observations/0")
        part = self.call("observation_read", dict(observation=whole, offset=2, max_bytes=4))
        self.assertNotEqual(part["citation"], whole)
        self.assertFalse(self.model.resources[whole]["inspected"])
        extent = self.model.resources[part["citation"]]["value"]["range"]
        self.assertEqual(extent, dict(offset=2, length=4))
        rejected = self.call("observation_read", dict(observation=part["citation"]))
        self.assertEqual(rejected["diagnostic"]["reason"], "range_exceeded")
        reread = self.call("observation_read", dict(observation=part["citation"], offset=2, max_bytes=100))
        self.assertEqual(reread["raw_length"], 4)
        self.assertEqual(reread["citation"], part["citation"])
        self.assertEqual(self.call("finish", self.finish(part["citation"]))["assessment_state"], "committed")

    def test_selection_retention_failure_prevents_assessment_submission(self):
        whole = self.execute()["observations"][0]["observation"]
        self.call("observation_read", dict(observation=whole))
        self.host.reject_selection = True
        self.assertEqual(self.call("finish", self.finish(whole))["status"], "error")
        self.assertFalse(any(op == "engine.finish" for op, _, _ in self.host.events))

    def test_host_error_path_maps_to_model_handle_without_replacing_cause(self):
        whole = self.execute()["observations"][0]["observation"]
        self.call("observation_read", dict(observation=whole))
        self.host.error = dict(code="POLICY_DENIED", effect_state="none", disposition="correct-and-resubmit", message="Denied.",
            diagnostic=dict(source="operator", stage="references", reason="invalid_attempt", field_path="/assessment/claims/0/attempt_receipt_refs/0"))
        result = self.call("finish", self.finish(whole))
        self.assertEqual(result["diagnostic"]["field_path"], "/claims/0/observations/0")
        self.assertEqual(result["diagnostic"]["reason"], "invalid_attempt")
        self.assertEqual(result["diagnostic"]["source"], "operator")

    def test_duplicate_calls_do_not_repeat_host_effects_and_conflicts_are_explicit(self):
        body = dict(origin="exploratory", operation_id="invoke", json={"query": "one"})
        first = self.call("attempt_execute", body, "same")
        self.assertEqual(self.call("attempt_execute", body, "same"), first)
        result = self.call("attempt_execute", dict(body, json={"query": "two"}), "same")
        self.assertEqual(result["diagnostic"]["reason"], "call_identity_conflict")
        self.assertEqual(len(self.host.attempt_ids), 1)

    def test_restore_revalidates_known_injections_through_current_host_binding(self):
        self.host.snapshot["parent"] = dict(source_session="session-raw", checkpoint_id="earlier-checkpoint")
        snapshot = self.call("snapshot_request", {})
        self.assertIsInstance(snapshot["snapshot"], str)
        self.assertIsInstance(snapshot["parent"], str)
        self.assertEqual(self.call("snapshot_inspect", {"snapshot": snapshot["snapshot"]})["snapshot"], snapshot["snapshot"])
        listed = self.call("snapshot_list", {"session": snapshot["session"]})
        self.assertEqual(listed["snapshots"][0]["snapshot"], snapshot["snapshot"])
        injection = self.model.register("injection", dict(attempt_receipt_id="receipt", action_id="action"), live=True)
        self.assertEqual(self.call("injection_delete", {"injection": injection})["outcome"], "deleted")
        self.assertFalse(self.model.resources[injection]["live"])
        restored = self.call("restore_request", {"snapshot": snapshot["snapshot"]})
        self.assertEqual(restored["run_revision"], 2)
        self.assertTrue(self.model.resources[injection]["live"])
        self.assertEqual(self.call("injection_delete", {"injection": injection})["outcome"], "deleted")
        deletions = [event for event in self.host.events if event[0] == "engine.injection_delete"]
        self.assertEqual(len(deletions), 2)
        self.assertNotEqual(deletions[0][2], deletions[1][2])
        self.assertEqual(self.call("injection_delete", {"injection": "unknown"})["diagnostic"]["reason"], "unknown_handle")

    def test_historical_records_and_local_forward_hypotheses(self):
        hypothesis = self.call("record_append", dict(kind="hypothesis", origin="exploratory", statement="Could a marker appear?"))
        self.assertIn("hypothesis", hypothesis)
        draft = dict(finish_reason="budget-limit", summary="Untested.", objectives=[], hypotheses=[
            dict(label="child", parent="parent", origin="exploratory", outcome="not-tested", summary="Child untested."),
            dict(label="parent", parent=hypothesis["hypothesis"], origin="exploratory", outcome="not-tested", summary="Parent untested.")])
        result = self.call("finish", draft)
        self.assertEqual(result["assessment_state"], "committed")
        actual = json.loads(self.host.conclusion_raw)["hypotheses"]
        self.assertEqual(actual[0]["provenance"]["parent_hypothesis_id"], actual[1]["hypothesis_id"])

    def test_shared_normalization_fixtures_remain_exact(self):
        for case in json.loads((self.source / "fixtures/tool-normalization.json").read_text()):
            with self.subTest(case=case["name"]):
                raw = json.dumps(case["arguments"]).encode()
                if "reason" in case:
                    with self.assertRaises(ContractError) as caught:
                        self.protocol.normalize_tool_arguments(case["tool"], raw, case["context"])
                    self.assertEqual((caught.exception.reason, caught.exception.field_path), (case["reason"], case["path"]))
                else:
                    self.assertEqual(self.protocol.normalize_tool_arguments(case["tool"], raw, case["context"]), case["expected"])



    def test_host_reference_correction_uses_model_fields_in_every_layer(self):
        value = dict(instance_path="/record/attempt_receipt_id",
            message="Invalid reference. Field: /record/attempt_receipt_id.",
            diagnostic=dict(field_path="/record/attempt_receipt_id",
                correction="Use the returned execution handle. Field: /record/attempt_receipt_id.",
                execution_occurred="no", resubmission_safe=True))
        shown = self.model._remap(value, {"/record/attempt_receipt_id":"/attempt"})
        self.assertEqual(shown["instance_path"], "/attempt")
        self.assertEqual(shown["diagnostic"]["field_path"], "/attempt")
        self.assertNotIn("attempt_receipt_id", json.dumps(shown))
        self.assertIn("returned execution handle", shown["diagnostic"]["correction"])
        self.assertEqual(value["instance_path"], "/record/attempt_receipt_id")

    def test_uncertainty_label_repair_preserves_completed_execution(self):
        attempt=self.call('attempt_execute',dict(origin='scenario',scenario_id='configuration',operation_id='invoke',json={'prompt':'test'}))
        observation=attempt['observations'][0]['observation']
        inspected=self.call('observation_read',dict(observation=observation))
        claim=dict(statement='Limited conclusion.',interpretation='inconclusive',assurance='refund-behavior',confidence='low',observations=[inspected['citation']],uncertainties=['Explanation instead of a label. '*6])
        draft=dict(finish_reason='no-useful-next-experiment',summary='Limited.',objectives=[],claims=[claim],uncertainties=[dict(label='limited-feedback',kind='unavailable-feedback',description='Limited feedback.')])
        rejected=self.call('finish',draft)
        diagnostic=rejected['diagnostic']
        self.assertEqual(diagnostic['field_path'],'/claims/0/uncertainties/0')
        self.assertIn('top-level uncertainties',diagnostic['correction'])
        self.assertIn('128',diagnostic['correction'])
        self.assertIn('constraint',diagnostic)
        self.assertEqual(diagnostic['execution_occurred'],'no')
        self.assertTrue(diagnostic['resubmission_safe'])
        claim['uncertainties']=['limited-feedback']
        self.assertEqual(self.call('finish',draft)['status'],'accepted')
        self.assertEqual(len([e for e in self.host.events if e[0]=='engine.attempt_execute']),1)

    def test_internal_resolution_is_terminal_not_a_model_repair(self):
        self.model.resources['bad-artifact']=dict(kind='artifact',campaign_id=self.host.campaign_id,value={'purpose':'payload'},available=True,inspected=False,live=True)
        with self.assertRaises(RuntimeStopped):
            self.call('attempt_execute',dict(origin='exploratory',operation_id='invoke',artifact='bad-artifact'))
        self.assertFalse(any(e[0]=='engine.attempt_execute' for e in self.host.events))

if __name__ == "__main__": unittest.main()
