"""Measure the same controlled workflow against selected sources, without model calls.

Select sources/tests with PYTHONPATH; use --source-root for the matching prompt.
Optional --archive reconstructs the supplied eight-scenario initial/active task
using its verified bundle and target capability data. It does not replay its model.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from operator_contracts.target_context import compact_target_context
from attack_harness.composition import build_task
from scenario_loading_fixture import run_loading, loading_bundle


def size(value):
    return len(_canonical_value(value, 64 << 20))


def parts(request, host):
    task = host.task_from_request(request)
    return dict(task_bytes=size(task), history_bytes=size(request['conversation'][1:]),
                conversation_bytes=size(request['conversation']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, default=Path('.'))
    p.add_argument('--contract-source', type=Path, default=Path('../operator_sandbox/schemas'))
    p.add_argument('--archive', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--request-output', type=Path)
    args = p.parse_args()
    protocol = Protocol(args.contract_source)
    prompt = (args.source_root / 'assets/default-system-prompt.txt').read_bytes()
    bundle = loading_bundle()
    bundle['scenarios'] += [dict(deepcopy(s), scenario_id=s['scenario_id']+'-additional') for s in bundle['scenarios']]
    bundle['coverage']['completion_guidance'] = 'Account for all eight scenarios and their required actions; report unmet requirements.'
    campaign, host, inputs, result = run_loading(protocol, args.contract_source,
        'bedrock-model-codec.json', trim=True, bundle=bundle, prompt=prompt)
    assert result['assessment_state'] == 'committed' and len(host.attempt_ids) == 2 and host.run_revision == 2
    tools = json.loads(protocol.model_tools(host.codec, sorted(host.operations),
        inputs.context()['model']['tool_selection']['injection_surfaces']))
    # Native Bedrock envelope; same frozen declarations and system prompt that
    # Operator installs. Real Operator request injection is exercised separately.
    requests = [dict(system=[{'text': prompt.decode()}], messages=r['conversation'],
                     toolConfig={'tools':tools}, inferenceConfig={'maxTokens':host.context_limits['maximum_completion_tokens']})
                for r in host.model_requests]
    metrics = [dict(**parts(r, host), provider_request_bytes=size(q)) for r, q in zip(host.model_requests, requests)]
    result = dict(method='Controlled Bedrock reconstruction; serialized UTF-8 bytes, not actual token usage.',
        bundle_digest=raw_digest(inputs.bundle_raw), system_prompt_bytes=len(prompt), tool_definitions_bytes=size(tools),
        model_requests=len(requests), target_invocations=len(host.attempt_ids), evidence_reads=host.reads,
        evidence_rereads=host.reads-2, model_compactions=len(campaign.adaptive.conversation._compactions),
        per_request=metrics, cumulative_provider_request_bytes=sum(size(r) for r in requests),
        token_estimate_bytes_divided_by_four=sum(math.ceil(size(r)/4) for r in requests), actual_provider_usage=None)
    if args.archive:
        # Read-only reconstruction. Source files remain outside the repository.
        from test_scenario_delivery import ScenarioInputs, ScenarioHost
        archive = args.archive
        source_bundle = json.loads((archive/'operator/run/input/scenario-bundle.json').read_bytes())
        target = json.loads((archive/'operator/run/input/capabilities.json').read_bytes())
        # Locate the first archived provider request for the transcript's campaign.
        journal = archive / 'operator/state/campaigns/campaign-59e19304e39b80b00bace74ca59b8afb/journals/0000000000000001/content'
        original = json.loads((journal / 'event-0000000000000058-00.bin').read_bytes())
        original_task = json.loads(original['messages'][0]['content'][0]['text'])
        archived = ScenarioInputs(protocol, args.contract_source, source_bundle, ScenarioHost(protocol), 'bedrock-model-codec.json')
        archived._context.update(original_task['campaign'])
        archived._context['target'] = target
        _, archived.details = compact_target_context(protocol, _canonical_value(target, 4 << 20))
        initial = json.loads(build_task(archived))
        active = json.loads(build_task(archived, active_scenario=source_bundle['scenarios'][0]['scenario_id']))
        result['archive_reconstruction'] = dict(bundle_digest=raw_digest(archived.bundle_raw),
            scenario_count=len(source_bundle['scenarios']), initial_task_bytes=size(initial), active_task_bytes=size(active),
            archived_initial_task_bytes=size(original_task), archived_tool_definitions_bytes=size(original['toolConfig']['tools']),
            archived_system_prompt_bytes=len(original['system'][0]['text'].encode()),
            archived_initial_request_bytes=size(original))
        if args.request_output:
            q = deepcopy(original);q['system']=[{'text':prompt.decode()}];q['messages']=[{'role':'user','content':[{'text':_canonical_value(active,4<<20).decode()}]}]
            args.request_output.write_text(json.dumps(q,indent=2)+'\n')
    elif args.request_output:
        args.request_output.write_text(json.dumps(requests,indent=2)+'\n')
    args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
