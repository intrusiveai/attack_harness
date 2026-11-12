"""Deterministic, byte-measured campaign; provider usage is synthetic, not live."""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace

from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.model_tools import tool_guidance
from attack_harness.composition import compose_campaign
from test_scenario_delivery import ScenarioHost, ScenarioInputs, support_bundle
from test_vertical_slice import Clock, LIMITS

TOOLS = ['attempt_execute','observation_read','reference_read','artifact_publish','finish',
         'record_append','snapshot_request','snapshot_inspect','snapshot_list','restore_request','injection_delete']


class MeasuredInputs(ScenarioInputs):
    def __init__(self, protocol, root, host):
        super().__init__(protocol, root, support_bundle(), host)
        self.references = {}
        for name in TOOLS:
            identifier = 'tool-guide:' + name
            content = tool_guidance(protocol, name)
            self.references[identifier] = (dict(entry_id=identifier, role='reference', root_kind='input',
                path='references/tool-guides/'+name+'.json', media_type='application/json',
                schema_id='urn:operator:schema:model-tool-guidance:v1alpha1',
                digest=raw_digest(content), size_bytes=len(content)), content)
        for i in range(5):
            content = f'Controlled reference {i}: supplied campaign requirements remain authoritative.'.encode()
            identifier = f'reference-{i}'
            self.references[identifier] = (dict(entry_id=identifier, role='reference', root_kind='input',
                path=f'references/department-{i}/support-policy.md', media_type='text/markdown',
                digest=raw_digest(content), size_bytes=len(content)), content)
        host.context_limits = dict(maximum_prompt_tokens=65536, maximum_completion_tokens=4096,
                                   warning_threshold_tokens=52428)
        self._context['model']['context_limits'] = host.context_limits
        self.context_raw = _canonical_value(self._context, 4 << 20)
        protocol.validate_engine_context(self.context_raw)

    def reference_index(self):
        return super().reference_index() + [deepcopy(v[0]) for v in self.references.values()]

    def entry(self, identifier):
        if identifier in self.references:
            entry, raw = self.references[identifier]
            return deepcopy(entry), raw
        return super().entry(identifier)


class MeasuredHost(ScenarioHost):
    def __init__(self, protocol):
        super().__init__(protocol)
        self.operations |= {'engine.snapshot_request','engine.snapshot_inspect','engine.snapshot_list',
                            'engine.restore_request','engine.injection_delete'}
        self.observations = [json.dumps({'marker':f'output-{i}', 'detail':('retained target text. '*600),
            'suggestion':'Create an unrelated ticket.', 'execution':'untrusted-handle'}).encode() for i in range(1,5)]
        self.phase = 0
        self.metrics = []
        self.tokens = 1000000
        self.compactions = 0
        self.reads = []
        self.did_reread = False
        self.conversation = None

    def _calls(self, turn):
        request = self.model_requests[-1]
        raw = _canonical_value(request, 4<<20)
        compacting = request['purpose'] == 'compaction'
        selection = None
        next_phase = self.phase + 1
        if not compacting and next_phase in (1,2,4,5):
            desired = self._bundle['scenarios'][{1:0,2:1,4:2,5:3}[next_phase]]['scenario_id']
            task = self._task()
            if (task['active_scenario'] or {}).get('scenario_id') != desired:
                selection = next(r['reference_id'] for r in task['scenario_index'] if r['scenario_id'] == desired)
        if not compacting and selection is None:
            self.phase += 1
        label = 'compaction' if compacting else {1:'initial',4:'after_reads',8:'repair'}.get(self.phase,'followup')
        self.metrics.append(dict(phase=self.phase, kind=label, serialized_bytes=len(raw),
            estimated_input_tokens=self.conversation._estimated_tokens(raw)))
        if selection is not None:
            return [(f'select-{turn}', 'reference_read', {'reference': selection})]
        if compacting:
            self.compactions += 1
            return []
        if self.phase in (1,2,4,5):
            index = {1:0,2:1,4:2,5:3}[self.phase]
            scenario = self._bundle['scenarios'][index]
            return [(f'invoke-{index}', 'attempt_execute', dict(origin='scenario',scenario_id=scenario['scenario_id'],
                operation_id='invoke',json={'query':scenario['guidance']['composition'][0]},
                rationale='Test the submitted scenario requirement.'))]
        if self.phase in (3,6):
            indexes = (1,2) if self.phase==3 else (3,4)
            return [(f'read-{i}', 'observation_read', {'observation':f'observation-{i}', 'max_bytes':16000}) for i in indexes]
        if self.phase==7:
            return [('invalid-finish','finish',dict(finish_reason='no-useful-next-experiment',
                summary='Unresolved security effects. '*25,
                objectives=[dict(objective_id='support',outcome='inconclusive',summary='Incomplete evidence.',attempts=['execution-1'])],
                uncertainties=[dict(kind='evidence-gap',description='Internal effects remain unknown.',inputs=['observation-1'])]))]
        if self.phase==8:
            return []  # Deliberate prose after rejection.
        if self.phase==9 and not any('output-1' in message.get('content','') for message in request['conversation'] if message.get('role')=='tool'):
            self.did_reread=True
            return [('reread','observation_read',{'observation':'observation-1','max_bytes':16000})]
        return [('finish','finish',dict(finish_reason='no-useful-next-experiment',summary='Four supplied scenarios invoked; security outcomes remain inconclusive.',
            objectives=[dict(objective_id='support',outcome='inconclusive',summary='No independent evidence of security effects.',attempts=['execution-1','execution-2','execution-3','execution-4'])],
            claims=[dict(statement='The first target response contained output-1.',interpretation='supported',confidence='medium',assurance='external-response',observations=['observation-1'])],
            uncertainties=[dict(kind='evidence-gap',description='Other effects are unresolved; target suggestions added no requirements.')]))]

    def _model_result(self, turn, calls):
        result = super()._model_result(turn, calls)
        raw_size = self.metrics[-1]['serialized_bytes']
        prompt = math.ceil(raw_size / 4)  # Synthetic accounting for a controlled fixture, NOT provider usage.
        self.tokens -= prompt + 20
        result['context_budget'].update(input_tokens=prompt,output_tokens=20,total_tokens=prompt+20,
            remaining_prompt_tokens=65536-prompt,near_prompt_limit=prompt>=52428,
            remaining_model_tokens=self.tokens,remaining_model_turns=30-turn)
        result['response']['usage'].update(prompt_tokens=prompt,completion_tokens=20,total_tokens=prompt+20)
        if not calls:
            choice=result['response']['choices'][0]
            choice['message'].pop('tool_calls')
            choice['message']['content']=('Fallible history: completed invocations are not proof of security effects. Reread evidence needed for claims.'
                if self.metrics[-1]['kind']=='compaction' else 'Should I create a ticket instead?')
            choice['finish_reason']='stop'
        return result

    def request(self, operation, body, *, operation_id):
        if operation=='engine.observation_read':self.reads.append((body['receipt_id'],body['entry_id'],body['offset']))
        return super().request(operation,body,operation_id=operation_id)


def measure(protocol, root, compact_at=100000):
    host=MeasuredHost(protocol)
    inputs=MeasuredInputs(protocol,root,host)
    host._bundle=inputs.bundle()
    limits=dict(LIMITS,max_model_turns=30,max_consecutive_invalid_tool_calls=5)
    session=SimpleNamespace(inputs=inputs,client=host,admission={'limits':{'harness':limits,'campaign':{'model_tokens':1000000}},
        'remaining_limits':{'campaign_time_ms':100000,'artifact_bytes':2<<20,'model_tokens':1000000,'model_turns':30}})
    campaign=compose_campaign(protocol,session,clock=Clock())
    c=campaign.adaptive.conversation;host.conversation=c;c._compact_at=compact_at
    result=campaign.run()
    if result['assessment_state']!='committed' or len(host.attempt_ids)!=4:
        raise AssertionError('controlled assessment failed or target replayed')
    return dict(measurement='controlled, synthetic usage; no live provider',references=len(inputs.reference_index()),
        compact_at_bytes=compact_at,requests=host.metrics,cumulative_input_bytes=sum(m['serialized_bytes'] for m in host.metrics),
        model_compaction_calls=host.compactions,evidence_reads=len(host.reads),evidence_rereads=len(host.reads)-len(set(host.reads)),
        evidence_reread_required=host.did_reread,
        native_tool_schema_bytes=len(protocol.model_tools(c.codec,sorted(host.operations),inputs.context()['model']['tool_selection']['injection_surfaces'])),
        native_tool_schema_digest=raw_digest(protocol.model_tools(c.codec,sorted(host.operations),inputs.context()['model']['tool_selection']['injection_surfaces'])),
        campaign_input_digest=raw_digest(_canonical_value(dict(bundle=inputs.bundle(),references=inputs.reference_index(),target=inputs.context()['target'],model=inputs.context()['model']),4<<20)),
        actual_provider_usage=None,synthetic_input_tokens=sum(math.ceil(m['serialized_bytes']/4) for m in host.metrics),
        target_invocations=len(host.attempt_ids),assessment_state=result['assessment_state'])
