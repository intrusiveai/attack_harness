import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.loop import HarnessLoop

from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.artifacts import ArtifactPublisher
from attack_harness.attempts import AttemptExecutor
from attack_harness.conclusion import ConclusionFinalizer
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.runtime import RuntimeStopped
from attack_harness.tools import Dispatcher


LIMITS = {
    "max_model_turns":20,"max_tool_calls":100,"max_tool_calls_per_response":16,
    "max_invalid_tool_calls":5,"max_consecutive_invalid_tool_calls":3,
    "max_read_bytes":1<<20,"max_no_progress_turns":10,
}


class Reply:
    error=None
    def __init__(self,result):self.result=deepcopy(result)


class Inputs:
    def __init__(self,bundle):self._bundle=deepcopy(bundle)
    def bundle(self):return deepcopy(self._bundle)
    def conclusion_binding(self,revision):
        return {
            "campaign_id":"campaign-1","launch_id":"launch-1","run_revision":revision,
            "input_tree_digest":"sha256:"+"1"*64,
            "engine_context_digest":"sha256:"+"2"*64,
            "prompt_digest":"sha256:"+"3"*64,
            "skill_set_digest":"sha256:"+"4"*64,
            "image_digest":"sha256:"+"5"*64,
            "release_record_digest":"sha256:"+"6"*64,
            "contract_package_digest":"sha256:"+"7"*64,
            "contract_package_version":"0.0.0",
        }
    def entry(self,_identifier):raise AssertionError("no input reference expected")


class Clock:
    def __init__(self):self.now=1000
    def __call__(self):self.now+=1;return self.now


class ScriptedHost:
    campaign_id="campaign-1";launch_id="launch-1";run_revision=1
    def __init__(self,protocol,payloads,observations):
        self.protocol=protocol;self.payloads=payloads;self.observations=observations
        self.operations=frozenset({
            "engine.model_generate","engine.artifact_begin","engine.artifact_put_part",
            "engine.artifact_commit","engine.attempt_execute","engine.observation_read",
            "engine.record_append","engine.request_stop",
        })
        self.serial=0;self.model_turn=0;self.uploads={};self.attempt_ids=[]
        self.events=[];self.model_requests=[];self.conclusion_raw=None

    def operation_id(self,purpose):
        self.serial+=1;return f"{purpose}-{self.serial}"

    def _checked(self,operation,result):
        schema=next(item["result_schema"] for item in self.protocol.operations()
                    if item["name"]==operation)
        self.protocol._catalog.validate_value(schema,result)
        return Reply(result)

    @staticmethod
    def _model_result(turn,calls):
        return {
            "codec_id":"openai-chat-text-tools-v1",
            "profile_id":"vertical-slice-profile",
            "profile_digest":"sha256:"+"9"*64,
            "receipt_id":f"model-receipt-{turn}",
            "response":{
                "id":f"chatcmpl-{turn}","object":"chat.completion","created":turn,
                "model":"fixture-model-2026","choices":[{"index":0,
                    "message":{"role":"assistant","content":None,"refusal":None,
                               "annotations":[],"tool_calls":[{
                        "id":identifier,"type":"function","function":{
                            "name":name,"arguments":json.dumps(arguments,separators=(",",":"))}
                    } for identifier,name,arguments in calls]},
                    "finish_reason":"tool_calls","logprobs":None}],
                "usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120,
                    "prompt_tokens_details":{"cached_tokens":0,"audio_tokens":0},
                    "completion_tokens_details":{"reasoning_tokens":0,"audio_tokens":0,
                        "accepted_prediction_tokens":0,"rejected_prediction_tokens":0}},
                "service_tier":"default","system_fingerprint":None,
            },
        }

    def _attempt(self,descriptor,generation,parent=None):
        value={
            "origin":"scenario","scenario_id":"scenario-marker",
            "thread_id":"thread-marker","generation":generation,
            "payload":descriptor,"pre_actions":[],
            "invocation":{"operation_id":"invoke","input_source":"payload",
                          "media_type":"application/json"},
            "cleanup":{"delete_actions_after_observation":True},
            "strategy_provenance_ref":"record-1",
            "rationale":"Change only the benign marker instruction after observed output.",
        }
        if parent is not None:value["parent_attempt_id"]=parent
        return value

    def _draft(self):
        attempts=["attempt-receipt-1","attempt-receipt-2"]
        observation={"attempt_receipt_id":"attempt-receipt-2","entry_id":"target-output",
                     "range":{"offset":0,"length":len(self.observations[1])}}
        return {
            "status":"completed","finish_reason":"objectives-addressed",
            "summary":"A refined benign input produced the marker in permitted output.",
            "objectives":[{"objective_id":"objective-marker","outcome":"supported",
                "summary":"Two serial variants were observed.",
                "attempt_receipt_refs":attempts,"record_refs":["record-1","record-2"]}],
            "hypotheses":[{"hypothesis_id":"hypothesis-marker",
                "objective_refs":["objective-marker"],
                "provenance":{"origin":"scenario","scenario_id":"scenario-marker"},
                "outcome":"supported","summary":"The changed instruction influenced output.",
                "attempt_receipt_refs":attempts,"record_refs":["record-1"]}],
            "claims":[{"claim_id":"claim-marker",
                "statement":"The second target output contains the benign marker.",
                "interpretation":"supported","confidence":"medium",
                "assurance":"external-response","attempt_receipt_refs":[attempts[1]],
                "observation_refs":[observation],"uncertainty_refs":["gap-internal"]}],
            "coverage":[{"objective_id":"objective-marker","hypothesis_id":"hypothesis-marker",
                "status":"tested","reason":"Baseline and one changed variant completed.",
                "attempt_receipt_refs":attempts}],
            "uncertainties":[{"gap_id":"gap-internal","kind":"evidence-gap",
                "description":"No independent internal-effect evidence was available.",
                "observation_refs":[],"input_refs":[],"record_refs":[]}],
            "record_refs":["record-1","record-2"],
        }

    def _calls(self,turn):
        descriptor=lambda raw:{"digest":raw_digest(raw),"size_bytes":len(raw),
            "media_type":"application/json","canonicalization":"jcs-v1"}
        publish=lambda value:{"purpose":"payload","media_type":"application/json",
                              "content":{"encoding":"json","value":value}}
        if turn==1:
            record={"record_kind":"hypothesis","record":{
                "hypothesis_id":"hypothesis-marker","objective_refs":["objective-marker"],
                "provenance":{"origin":"scenario","scenario_id":"scenario-marker"},
                "statement":"A changed benign instruction may influence the target output.",
                "assumptions":["Only external response evidence is available."],
                "predicted_observations":["The marker appears in permitted output."],
                "record_refs":[]}}
            return [("hypothesis","record_append",record),
                    ("payload-1","artifact_publish",publish({"query":"baseline"})),
                    ("attempt-1","attempt_execute",self._attempt(descriptor(self.payloads[0]),1))]
        if turn==2:
            return [("observe-1","observation_read",{
                "receipt_id":"attempt-receipt-1","entry_id":"target-output",
                "offset":0,"max_bytes":4096})]
        if turn==3:
            return [("payload-2","artifact_publish",publish({"query":"return MARKER"})),
                    ("attempt-2","attempt_execute",self._attempt(
                        descriptor(self.payloads[1]),2,self.attempt_ids[0]))]
        if turn==4:
            coverage={"record_kind":"coverage","record":{"entries":[{
                "objective_id":"objective-marker","hypothesis_id":"hypothesis-marker",
                "status":"tested","reason":"Two completed variants were compared.",
                "attempt_receipt_refs":["attempt-receipt-1","attempt-receipt-2"]}],
                "record_refs":["record-1"]}}
            return [("observe-2","observation_read",{
                "receipt_id":"attempt-receipt-2","entry_id":"target-output",
                "offset":0,"max_bytes":4096}),
                    ("coverage","record_append",coverage)]
        if turn==5:return [("finish","request_stop",self._draft())]
        raise AssertionError("unexpected model turn")

    def request(self,operation,body,*,operation_id):
        self.events.append((operation,deepcopy(body),operation_id))
        if operation=="engine.model_generate":
            self.model_turn+=1;self.model_requests.append(deepcopy(body))
            return self._checked(operation,self._model_result(
                self.model_turn,self._calls(self.model_turn)))
        if operation=="engine.artifact_begin":
            upload=f"upload-{len(self.uploads)+1}"
            self.uploads[upload]={"begin":deepcopy(body),"content":bytearray()}
            return self._checked(operation,{"upload_id":upload,**deepcopy(body),"next_offset":0})
        if operation=="engine.artifact_put_part":
            content=base64.b64decode(body["content"],validate=True)
            target=self.uploads[body["upload_id"]]["content"]
            if body["offset"]!=len(target):raise AssertionError("non-contiguous upload")
            target.extend(content)
            return self._checked(operation,{"upload_id":body["upload_id"],
                "offset":body["offset"],"raw_length":len(content),"next_offset":len(target)})
        if operation=="engine.artifact_commit":
            upload=self.uploads[body["upload_id"]];begin=upload["begin"]
            content=bytes(upload["content"])
            if raw_digest(content)!=begin["artifact"]["digest"]:raise AssertionError("digest")
            receipt=f"artifact-{len([e for e in self.events if e[0]=='engine.artifact_commit'])}"
            if begin["purpose"]=="conclusion":self.conclusion_raw=content
            return self._checked(operation,{"upload_id":body["upload_id"],
                "artifact_receipt":receipt,"purpose":begin["purpose"],
                "artifact":deepcopy(begin["artifact"])})
        if operation=="engine.attempt_execute":
            index=len(self.attempt_ids);self.attempt_ids.append(body["attempt_id"])
            receipt=f"attempt-receipt-{index+1}";content=self.observations[index]
            artifact={"digest":raw_digest(content),"size_bytes":len(content),
                      "media_type":"application/json"}
            result={"api_version":"operator.dev/engine-attempt-result/v1alpha2",
                "kind":"EngineAttemptResult","request_id":body["request_id"],
                "attempt_id":body["attempt_id"],"receipt_id":receipt,"status":"completed",
                "stage":"complete","target_contact":"attempted","invocation_state":"succeeded",
                "cleanup_state":"not-needed","retry_disposition":"do-not-retry","errors":[],
                "feedback":{"profile":"black-box","collection_state":"complete",
                    "boundary":"invocation-completed","categories":[
                        {"kind":"target_output","state":"available"},
                        {"kind":"operation_error","state":"empty"},
                        {"kind":"injection_delivery","state":"empty"},
                        {"kind":"oracle_outcome","state":"empty"}],
                    "entries":[{"entry_id":"target-output","kind":"target_output",
                        "visibility":"harness_visible","source":"synthetic-target",
                        "assurance":"external-response","availability":"available",
                        "artifact":artifact,"truncated":False}]}}
            return self._checked(operation,result)
        if operation=="engine.observation_read":
            index=int(body["receipt_id"].rsplit("-",1)[1])-1;content=self.observations[index]
            result={"receipt_id":body["receipt_id"],"entry_id":body["entry_id"],
                "availability":"available","offset":body["offset"],
                "content":base64.b64encode(content).decode(),"raw_length":len(content),
                "eof":True,"truncated":False,"artifact":{
                    "digest":raw_digest(content),"size_bytes":len(content),
                    "media_type":"application/json"}}
            return self._checked(operation,result)
        if operation=="engine.record_append":
            count=len([event for event in self.events if event[0]==operation])
            return self._checked(operation,{"receipt_id":f"record-{count}",
                "record_kind":body["record_kind"],"assertion_origin":"harness",
                "attribution":{"campaign_id":self.campaign_id,"launch_id":self.launch_id,
                               "run_revision":self.run_revision}})
        if operation=="engine.request_stop":
            return self._checked(operation,{"status":"accepted","stop_receipt":"stop-1",
                "execution_admission":"closed","conclusion_state":body["conclusion"]["state"],
                "exit_required":True,"exit_within_ms":5000,"finalization_status":"pending"})
        raise AssertionError(operation)

    def fail(self,reason,*,receipt=None):raise RuntimeStopped(reason,receipt=receipt)


class VerticalSliceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol=Protocol(cls.root)

    def test_marker_feedback_drives_child_attempt_and_bound_conclusion(self):
        bundle=json.loads((self.root/"fixtures/scenario-bundle-scenarios.json").read_text())
        context=json.loads((self.root/"fixtures/engine-context-example.json").read_text())
        payloads=[_canonical_value({"query":"baseline"},1<<20),
                  _canonical_value({"query":"return MARKER"},1<<20)]
        observations=[b'{"answer":"ordinary"}',b'{"answer":"MARKER"}']
        client=ScriptedHost(self.protocol,payloads,observations)
        inputs=Inputs(bundle);loop=HarnessLoop(LIMITS);artifacts=ArtifactPublisher(self.protocol,client)
        observation_reader=ObservationReader(client)
        attempts=AttemptExecutor(self.protocol,client,artifacts,context,bundle,loop)
        records=set();clock=Clock()
        finalizer=ConclusionFinalizer(self.protocol,client,inputs,loop,artifacts,
            attempts=attempts,observations=observation_reader,record_receipts=records,
            campaign_deadline_ms=100000,artifact_remaining=2<<20,clock=clock)
        handlers=FixedHandlers(self.protocol,inputs,client,loop,artifacts=artifacts,
            observations=observation_reader,attempts=attempts,finalizer=finalizer,
            record_receipts=records)
        dispatcher=Dispatcher(self.protocol,loop,handlers.handlers(),
                              raw_handlers=handlers.raw_handlers())
        tools=self.protocol.model_tools("openai-chat-text-tools-v1",sorted(client.operations))
        policy={"codec_id":"openai-chat-text-tools-v1",
            "profile_id":"vertical-slice-profile","profile_digest":"sha256:"+"9"*64,
            "request_model":"fixture-model","response_models":["fixture-model-2026"],
            "instruction_role":"developer","prompt":"Fixed vertical-slice prompt.\n",
            "max_completion_tokens":4096,"tools":json.loads(tools)}
        policy_raw=_canonical_value(policy,4<<20)
        conversation=NativeConversation(self.protocol,policy_raw,"Run the marker scenario.")
        result=AdaptiveHarness(self.protocol,client,loop,dispatcher,conversation,finalizer).run()

        self.assertEqual(result["stop_receipt"],"stop-1")
        self.assertEqual(len(client.attempt_ids),2)
        self.assertNotEqual(client.attempt_ids[0],client.attempt_ids[1])
        attempts_sent=[body for operation,body,_ in client.events
                       if operation=="engine.attempt_execute"]
        self.assertEqual(attempts_sent[1]["parent_attempt_id"],attempts_sent[0]["attempt_id"])
        self.assertEqual(attempts_sent[1]["generation"],2)
        committed=[bytes(value["content"]) for value in client.uploads.values()
                   if value["begin"]["purpose"]=="payload"]
        self.assertEqual(committed,payloads)
        turn3=json.dumps(client.model_requests[2],separators=(",",":"))
        self.assertIn(base64.b64encode(observations[0]).decode(),turn3)
        conclusion=self.protocol.validate_conclusion(client.conclusion_raw)
        self.assertEqual(conclusion["claims"][0]["observation_refs"][0]
                         ["attempt_receipt_id"],"attempt-receipt-2")
        tail=[operation for operation,_,_ in client.events[-5:]]
        self.assertEqual(tail,["engine.artifact_begin","engine.artifact_put_part",
            "engine.artifact_commit","engine.record_append","engine.request_stop"])


if __name__=="__main__":unittest.main()
