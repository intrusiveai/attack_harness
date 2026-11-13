"""Offline comparison of pinned catalogs and controlled ordinary request histories."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def argument_shape(value):
    """Count submitted fields/container levels, excluding intrinsic target data."""
    if isinstance(value, dict):
        children = [argument_shape(v) for k, v in value.items() if k not in ("json", "value", "content")]
        return dict(fields=len(value) + sum(c["fields"] for c in children),
                    nesting=1 + max((c["nesting"] for c in children), default=0))
    if isinstance(value, list):
        children = [argument_shape(v) for v in value]
        return dict(fields=sum(c["fields"] for c in children),
                    nesting=1 + max((c["nesting"] for c in children), default=0))
    return dict(fields=0, nesting=0)


def native_group(codec, group, suffix=""):
    """Transcode recorded controlled Chat tool groups, retaining arguments/results."""
    calls = deepcopy(group[0]["tool_calls"])
    results = deepcopy(group[1:])
    for call in calls: call["id"] += suffix
    for result in results: result["tool_call_id"] += suffix
    if codec.startswith("openai-chat"):
        return [dict(group[0], tool_calls=calls), *results]
    if codec.startswith("openai-responses"):
        return [dict(type="function_call", call_id=c["id"], **c["function"]) for c in calls] + [
            dict(type="function_call_output", call_id=r["tool_call_id"], output=r["content"]) for r in results]
    if codec.startswith("anthropic"):
        return [dict(role="assistant", content=[dict(type="tool_use", id=c["id"],
            name=c["function"]["name"], input=json.loads(c["function"]["arguments"])) for c in calls]),
            dict(role="user", content=[dict(type="tool_result", tool_use_id=r["tool_call_id"], content=r["content"]) for r in results])]
    if codec.startswith("bedrock"):
        return [dict(role="assistant", content=[dict(toolUse=dict(toolUseId=c["id"],
            name=c["function"]["name"], input=json.loads(c["function"]["arguments"]))) for c in calls]),
            dict(role="user", content=[dict(toolResult=dict(toolUseId=r["tool_call_id"], content=[dict(text=r["content"])])) for r in results])]
    names = {c["id"]: c["function"]["name"] for c in calls}
    return [dict(role="model", parts=[dict(functionCall=dict(name=c["function"]["name"],
        args=json.loads(c["function"]["arguments"]))) for c in calls]),
        dict(role="user", parts=[dict(functionResponse=dict(name=names[r["tool_call_id"]],
            response=dict(output=r["content"]))) for r in results])]


def sample(harness, operator):
    sys.path[:0] = [str(harness / "src"), str(harness / "tests"), str(operator / "contracts/python")]
    os.environ["OPERATOR_CONTRACT_SOURCE"] = str(operator / "schemas")
    from operator_contracts import Protocol
    from test_simple_campaign import SimpleCampaignTest
    from attack_harness.adaptive import NativeConversation
    protocol = Protocol(operator / "schemas")
    prompt_bytes = len((harness / "assets/default-system-prompt.txt").read_bytes())
    codecs = ("openai-chat-text-tools-v1", "openai-responses-text-tools-v1",
              "anthropic-messages-text-tools-v1", "bedrock-converse-text-tools-v1", "gemini-text-tools-v1")
    surfaces = ["database_response", "environment_state", "mcp_tool_result", "model_response", "model_tool_result", "service_response"]
    operations = sorted(item["name"] for item in protocol.operations())
    ordinary = ["engine.attempt_execute", "engine.finish", "engine.observation_read"]
    configs = {"full": (operations, surfaces), "no-setup": (operations, []), "ordinary": (ordinary, [])}
    configs.update({surface: (operations, [surface]) for surface in surfaces})
    configs["database-pair"] = (operations, surfaces[:2])
    fixtures = ("model-codec.json", "responses-model-codec.json", "anthropic-model-codec.json",
                "bedrock-model-codec.json", "gemini-model-codec.json")
    policies = {codec: deepcopy(next(c["policy"] for c in json.loads(
        (operator / "schemas/fixtures" / filename).read_text()) if c["mode"] == "context" and c["valid"]))
        for codec, filename in zip(codecs, fixtures)}
    task = (operator / "schemas/fixtures/scenario-bundle-scenarios.json").read_text()
    prompt = (harness / "assets/default-system-prompt.txt").read_text()
    def conversation(codec, tools):
        policy = dict(policies[codec], tools=tools, prompt=prompt)
        return NativeConversation(protocol, encoded(policy), task)
    catalogs = {}
    for codec in codecs:
        for label, (ops, selected) in configs.items():
            raw = protocol.model_tools(codec, ops, selected)
            tools = json.loads(raw)
            if codec.startswith("gemini"): tools = tools[0]["functionDeclarations"]
            details = {}
            for tool in tools:
                tool = tool.get("function", tool.get("toolSpec", tool))
                schema = tool.get("parameters", tool.get("parametersJsonSchema", tool.get("input_schema", tool.get("inputSchema", {}).get("json"))))
                details[tool["name"]] = dict(bytes=len(encoded(tool)), schema_bytes=len(encoded(schema)),
                    description_bytes=len(tool["description"].encode()), required=schema.get("required", []))
            catalogs[codec + "/" + label] = dict(catalog_bytes=len(raw),
                prompt_and_catalog_bytes=prompt_bytes + len(raw), estimated_tokens=(prompt_bytes + len(raw) + 1) // 2,
                initial_request_bytes=len(conversation(codec, json.loads(raw)).body()[1]),
                tools=details)
    SimpleCampaignTest.setUpClass()
    test = SimpleCampaignTest("test_basic_direct_workflow_has_three_host_calls")
    host, _, history, result = test.run_campaign("direct")
    lengths = [len(encoded(request)) for request in host.model_requests]
    submitted = [call for turn in range(1, len(lengths) + 1) for call in host._calls(turn)]
    shapes = {name: argument_shape(args) for _, name, args in submitted}
    # Equivalent serialized advanced setup and partial-read continuations. Their
    # dispatch semantics are exercised separately by the shared/runtime suites.
    setup = next(c["arguments"] for c in json.loads((operator / "schemas/fixtures/model-tools.json").read_text())
                 if c["name"].startswith("database ") and c["valid"])
    advanced = deepcopy(history._groups[:2])
    advanced[0][0]["tool_calls"][0]["function"]["arguments"] = encoded(setup).decode()
    read_call = advanced[1][0]["tool_calls"][0]["function"]
    read = dict(json.loads(read_call["arguments"]), offset=0, max_bytes=8)
    read_call["arguments"] = encoded(read).decode()
    for name, args in (("attempt_execute", setup), ("observation_read", read)):
        protocol.validate_tool_arguments(name, encoded(args))
    partial = json.loads(advanced[1][1]["content"])
    partial.update(content=partial["content"][:8], raw_length=8, eof=False, next_offset=8)
    if "observation" in partial: partial["observation"] = "observation-range-1"
    advanced[1][1]["content"] = encoded(partial).decode()
    workflows = {}
    for codec in codecs:
        tools = json.loads(protocol.model_tools(codec, operations, surfaces))
        flow = conversation(codec, tools)
        sizes = [len(flow.body()[1])]
        for group in history._groups:
            flow.extend(encoded(native_group(codec, group)))
            sizes.append(len(flow.body()[1]))
        advanced_flow = conversation(codec, tools)
        advanced_sizes = [len(advanced_flow.body()[1])]
        for group in advanced:
            advanced_flow.extend(encoded(native_group(codec, group)))
            advanced_sizes.append(len(advanced_flow.body()[1]))
        stress = conversation(codec, tools)
        compactions, peaks = [], []
        # Repeat execute/read history with distinct call identities. This measures
        # serialization/compaction only, never re-executes a target or a finish.
        for turn in range(60):
            stress.extend(encoded(native_group(codec, history._groups[turn % 2], f"-{turn}")))
            peaks.append(len(stress.body()[1]))
            if stress.needs_compaction():
                _, _, digest, count = stress.compaction_body()
                stress.apply_compaction("Retained observations remain evidence; reread them when needed.", digest, count)
                compactions.append(turn + 1)
        workflows[codec] = dict(request_bytes=sizes, total_request_bytes=sum(sizes),
            peak_request_bytes=max(sizes), estimated_input_tokens=sum((n + 1) // 2 for n in sizes),
            model_turns=len(sizes), tool_calls=len(submitted), retries=0,
            advanced_setup_partial_read_bytes=advanced_sizes,
            stress=dict(tool_groups=60, compaction_after_groups=compactions, peak_bytes=max(peaks)))
    return dict(catalogs=catalogs, prompt_bytes=prompt_bytes,
        contract_lock=json.loads((harness / "build/contract-lock.json").read_text()),
        source_lock=json.loads((harness / "build/source-lock.json").read_text()),
        ordinary_submitted_shape=shapes, serialized_workflows=workflows,
        controlled_openai_workflow=dict(request_bytes=lengths, peak_request_bytes=max(lengths),
            total_request_bytes=sum(lengths), model_turns=len(lengths), assessment_state=result["assessment_state"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--operator", type=Path, required=True)
    parser.add_argument("--baseline-harness", type=Path)
    parser.add_argument("--baseline-operator", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(sample(args.harness.resolve(), args.operator.resolve())))
        return
    if not args.baseline_harness or not args.baseline_operator or not args.output:
        parser.error("baseline paths and output are required")
    def run(harness, operator):
        return json.loads(subprocess.check_output([sys.executable, __file__, "--sample",
            "--harness", str(harness.resolve()), "--operator", str(operator.resolve())],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), text=True))
    baseline = run(args.baseline_harness, args.baseline_operator)
    current = run(args.harness, args.operator)
    violations = []
    for name, after in current["catalogs"].items():
        before = baseline["catalogs"][name]
        for metric in ("catalog_bytes", "prompt_and_catalog_bytes", "estimated_tokens", "initial_request_bytes"):
            if after[metric] > before[metric]: violations.append(name + ":" + metric)
    for metric in ("model_turns", "peak_request_bytes", "total_request_bytes"):
        if current["controlled_openai_workflow"][metric] > baseline["controlled_openai_workflow"][metric]:
            violations.append("controlled_openai_workflow:" + metric)
    for codec, after in current["serialized_workflows"].items():
        before = baseline["serialized_workflows"][codec]
        for metric in ("total_request_bytes", "peak_request_bytes", "estimated_input_tokens", "model_turns", "tool_calls"):
            if after[metric] > before[metric]: violations.append(codec + ":" + metric)
        if len(after["stress"]["compaction_after_groups"]) > len(before["stress"]["compaction_after_groups"]):
            violations.append(codec + ":more_compactions")
        if after["stress"]["compaction_after_groups"] and (not before["stress"]["compaction_after_groups"] or
                after["stress"]["compaction_after_groups"][0] < before["stress"]["compaction_after_groups"][0]):
            violations.append(codec + ":earlier_compaction")
        if any(a > b for a, b in zip(after["advanced_setup_partial_read_bytes"], before["advanced_setup_partial_read_bytes"])):
            violations.append(codec + ":advanced_setup_partial_read_growth")
    report = dict(method="canonical UTF-8 JSON bytes; token estimates use ceil(bytes/2), the existing cold-start Harness heuristic, not provider admission or tokenizer counts",
        baseline=baseline, current=current, growth_violations=violations,
        limits="Controlled OpenAI runtime history replayed into all five validated native request formats; advanced setup/partial-read and stress serialization fixtures are separate from runtime qualification. No paid/live model evaluation; estimates do not establish provider token usage.")
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"growth_violations": violations, "output": str(args.output)}))
    if violations: raise SystemExit(1)


if __name__ == "__main__": main()
