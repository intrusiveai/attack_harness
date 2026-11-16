"""First-attempt controlled calls using the approved shared model interface."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import Protocol
from attack_harness.composition import compose_campaign
from test_checkpoint_continuity import ContinuityHost
from test_instruction_boundary import CODECS
from test_scenario_delivery import ScenarioInputs
from scenario_loading_fixture import loading_bundle
from test_vertical_slice import Clock, LIMITS, Reply
import test_model_tools


class AlignedHost(ContinuityHost):
    def _calls(self, turn):
        if turn == 8:
            return [('finish','finish',dict(finish_reason='objectives-addressed',
                summary='Both supplied scenarios inspected; independent effects remain uncertain.',
                objectives=[dict(objective_id='support',outcome='inconclusive',summary='Only external evidence.',
                    observations=['observation-1','observation-2'])],
                claims=[dict(statement='The two responses were inspected.',interpretation='supported',
                    confidence='high',assurance='Observed responses',observations=['observation-1','observation-2'])],
                coverage=[dict(objective_id='support',status='tested',reason='Both operations ran.',attempts=['execution-1','execution-2'])],
                uncertainties=[dict(label='scope',kind='evidence-gap',description='Independent effects were not verified.')]))]
        calls=super()._calls(turn)
        for _,name,args in calls:
            if name=='record_progress':
                args['assessment']=dict(interpretation='supported',confidence='high',assurance='Observed response',summary='Baseline output inspected.')
        return calls


class ToolInterfaceWorkflowTest(unittest.TestCase):
    def test_first_attempt_acceptance_progress_switch_restore_and_finish_all_codecs(self):
        root=Path(os.environ['OPERATOR_CONTRACT_SOURCE']);protocol=Protocol(root)
        for codec in CODECS:
            with self.subTest(codec=codec):
                host=AlignedHost(protocol)
                bundle=loading_bundle();bundle['scenarios']=bundle['scenarios'][:2]
                inputs=ScenarioInputs(protocol,root,bundle,host,codec)
                session=SimpleNamespace(inputs=inputs,client=host,admission={
                    'limits':{'harness':dict(LIMITS,max_model_turns=40),'campaign':{'model_tokens':1000000}},
                    'remaining_limits':{'campaign_time_ms':100000,'artifact_bytes':2<<20}})
                campaign=compose_campaign(protocol,session,clock=Clock());host.conversation=campaign.adaptive.conversation
                result=campaign.run()
                self.assertEqual(result['assessment_state'],'committed')
                self.assertEqual(campaign.adaptive.loop.snapshot()['invalid_tool_calls'],0)
                self.assertEqual(len(host.attempt_ids),2)
                self.assertEqual(host.reads,2)
                self.assertGreater(host.checked_prefixes,0)
                progress=[body for op,body,_ in host.events if op=='engine.record_append']
                self.assertEqual(len(progress),1)
                self.assertEqual(progress[0]['record_kind'],'progress')
                self.assertNotIn('scenario_id',progress[0]['record'])
                self.assertEqual(progress[0]['record']['assessment']['interpretation'],'supported')
                self.assertEqual(len([1 for op,_,_ in host.events if op=='engine.restore_request']),1)
                self.assertEqual(len([1 for op,_,_ in host.events if op=='engine.finish']),1)


class CompletionFormTest(unittest.TestCase):
    def test_distinct_forms_dispatch_to_existing_finalizer(self):
        for name,extra,expected in (
            ('finish_unavailable',{'unavailable_reason':'invalid-call-limit'},'unavailable'),
            ('finish_artifact',{'artifact':'conclusion-1'},'committed')):
            with self.subTest(tool=name):
                fixture=test_model_tools.ModelToolsTest();fixture.setUpClass();fixture.setUp()
                original=fixture.host.request
                def request(op,body,*,operation_id):
                    if op!='engine.finish':return original(op,body,operation_id=operation_id)
                    fixture.host.events.append((op,deepcopy(body),operation_id))
                    return Reply(dict(status='accepted',stop_receipt='stop-1',execution_admission='closed',
                        assessment_state=expected,exit_required=True,exit_within_ms=5000,finalization_status='pending'))
                fixture.host.request=request
                if name=='finish_artifact':
                    fixture.model.register('artifact',dict(artifact_receipt='committed-conclusion',purpose='conclusion'),handle='conclusion-1',available=True)
                result=fixture.call(name,dict(finish_reason='harness-error',**extra))
                self.assertEqual(result['assessment_state'],expected)
                self.assertEqual(result['finalization_status'],'pending')
                self.assertEqual(len(fixture.host.events),1)
                self.assertEqual(fixture.host.events[0][0],'engine.finish')


class ObjectRootCorrectionTest(unittest.TestCase):
    def test_runtime_rejects_omitted_root_conditions_without_replaying_attempt(self):
        fixture=test_model_tools.ModelToolsTest();fixture.setUpClass();fixture.setUp()
        rejected=fixture.call('attempt_execute',dict(origin='scenario',operation_id='invoke',json={}))
        self.assertEqual(rejected['diagnostic']['execution_occurred'],'no')
        self.assertTrue(rejected['diagnostic']['resubmission_safe'])
        self.assertEqual(fixture.host.attempt_ids,[])
        executed=fixture.execute()
        observed=fixture.call('observation_read',{'observation':executed['observations'][0]['observation']})
        assessment=fixture.finish(observed['citation'])
        invalid=dict(assessment,status='completed',uncertainties=[{'kind':'coverage-limit','description':'Untested.'}])
        rejected=fixture.call('finish',invalid)
        self.assertIn('diagnostic',rejected)
        self.assertFalse(any(op=='engine.finish' for op,_,_ in fixture.host.events))
        accepted=fixture.call('finish',assessment)
        self.assertEqual(accepted['assessment_state'],'committed')
        self.assertEqual(len(fixture.host.attempt_ids),1)
        self.assertEqual(sum(op=='engine.finish' for op,_,_ in fixture.host.events),1)
