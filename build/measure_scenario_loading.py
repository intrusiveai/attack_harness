"""Reproduce complete controlled-sequence input sizes against selected Harness sources.

Run with PYTHONPATH=<selected checkout>/src:<Operator>/contracts/python:tests.
No model network calls; synthetic accounting is never measured provider usage.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from operator_contracts import Protocol
from scenario_loading_fixture import run_loading, loading_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract-source', type=Path, default=Path(os.environ.get('OPERATOR_CONTRACT_SOURCE', '../operator_sandbox/schemas')))
    parser.add_argument('--prompt', type=Path, default=Path('assets/default-system-prompt.txt'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = Protocol(args.contract_source)
    results = []
    for count in (4, 8):
        bundle = loading_bundle()
        if count == 8:
            bundle['scenarios'] += [dict(deepcopy(s), scenario_id=s['scenario_id']+'-additional') for s in bundle['scenarios']]
            bundle['coverage']['completion_guidance'] = 'Account for all eight scenarios and their required actions; report unmet requirements.'
            for scenario in bundle['scenarios']:
                scenario['coverage_obligations'].extend(['Document the inspected evidence and its limits for requirement '+str(i)+'.' for i in range(8)])
        for trimmed in (False, True):
            campaign, host, inputs, result = run_loading(protocol, args.contract_source, trim=trimmed, bundle=bundle, prompt=args.prompt.read_bytes())
            if result['assessment_state'] != 'committed' or len(host.attempt_ids) != 2 or host.run_revision != 2:
                raise AssertionError('Controlled campaign did not finish its two executions and restore.')
            fixed = len(args.prompt.read_bytes()) + len(protocol.model_tools(host.codec, sorted(host.operations),
                inputs.context()['model']['tool_selection']['injection_surfaces']))
            totals = [size + fixed for size in host.metrics]
            results.append(dict(scenarios=count, forced_trimming=trimmed,
                bundle_digest='sha256:'+hashlib.sha256(inputs.bundle_raw).hexdigest(),
                initial_conversation_bytes=host.metrics[0], cumulative_conversation_bytes=sum(host.metrics),
                fixed_prompt_and_schema_bytes=fixed,
                cumulative_input_bytes_including_fixed=sum(totals),
                input_estimate_bytes_divided_by_four=sum(math.ceil(n/4) for n in totals),
                per_request_conversation_bytes=host.metrics,
                per_request_task_bytes=[len(json.dumps(r['conversation'][0], separators=(',', ':')).encode()) for r in host.model_requests],
                per_request_history_bytes=[len(json.dumps(r['conversation'][1:], separators=(',', ':')).encode()) for r in host.model_requests],
                conversation_checkpoints=getattr(campaign.adaptive.conversation, '_checkpoint_number', 0),
                model_requests=len(host.metrics),
                scenario_selection_requests=host.selection_requests, target_invocations=len(host.attempt_ids),
                restores=host.run_revision-1, evidence_reads=host.reads, evidence_rereads=host.reads-2,
                model_compaction_calls=len(campaign.adaptive.conversation._compactions),
                assessment_state=result['assessment_state'], actual_provider_usage=None))
    args.output.write_text(json.dumps(dict(method='Controlled model/target; bytes measured, bytes/4 is an estimate, provider usage unavailable.', cases=results), indent=2)+'\n')


if __name__ == '__main__':
    main()
