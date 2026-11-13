"""Run controlled integration against an implementation of the approved interface.

The host must implement the independently approved interface. Test-only Go overlays add Harness workflow and
fatal-exit cases through a separate Python adapter. Run cross-component tests here;
Operator-only unit/service tests belong to Operator CI. Use --run . for the full packages.
No production fault switches, contract changes, or checkout edits are required.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--run", default="^Test(Python|Harness)",
        help="Go test expression; defaults to cross-component tests (use . for full host packages)")
    parser.add_argument("--check-contract-only", action="store_true",
                        help="check selected Operator interface identity without running integration")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    operator = args.operator_root.resolve()
    lock = json.loads((root / "build/contract-lock.json").read_text())
    # Source revision is provenance, never a compatibility prerequisite.
    import hashlib
    document = (operator / "schemas/asyncapi.json").read_bytes()
    identity = {"package_version": json.loads(document)["info"]["version"],
                "package_digest": "sha256:" + hashlib.sha256(document).hexdigest()}
    if identity != lock["package"]:
        raise SystemExit(
            "Selected Operator interface does not match the Harness contract lock.\n"
            + "Expected: " + json.dumps(lock["package"], sort_keys=True) + "\n"
            + "Observed: " + json.dumps(identity, sort_keys=True) + "\n"
            + "Select Operator validators implementing the approved version and exact document hash before running tests.")
    if args.check_contract_only:
        print("Selected Operator interface verified: " + json.dumps(identity, sort_keys=True))
        return
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=operator, text=True).strip()
    print("Integration Operator provenance: " + commit, flush=True)
    original = operator / "internal/preparation/harness_simple_campaign_test.go"
    replacement = root / "build/operator_simple_campaign_test.go"
    with tempfile.TemporaryDirectory(prefix="harness-integration-") as directory:
        overlay = Path(directory) / "overlay.json"
        helper = operator / "internal/preparation/python_process_test.go"
        helper_copy = Path(directory) / helper.name
        old = 'filepath.Join(operator, "internal/preparation/testdata/harness_process.py"), config'
        new = json.dumps(str(root / "build/operator_exit_adapter.py")) + ', config, filepath.Join(operator, "internal/preparation/testdata/harness_process.py")'
        source = helper.read_text()
        if source.count(old) != 1:
            raise SystemExit("Operator process fixture changed; review the test adapter")
        source = source.replace(old, new)
        # Honor each controlled case's selected profile instead of the helper's
        # fixed 10k-token profile. Production admission still validates both.
        source = source.replace('MaximumPromptTokens: 10000}',
                                'MaximumPromptTokens: cfg.Model.Settings().MaximumPromptTokens}')
        # The fixture kills on FIFO EOF before Python finishes flushing stderr.
        # Give this deliberate fatal-exit fixture the same bounded exit window.
        marker = "if service.StopAccepted() {"
        if source.count(marker) != 1:
            raise SystemExit("Operator process exit fixture changed; review the grace window")
        source = source.replace(marker,
            'if service.StopAccepted() || os.Getenv("HARNESS_TEST_EXIT_MODE") == "runtime-fatal" {')
        source = source.replace('"reference_handles"', '"scenario_index"')
        helper_copy.write_text(source)
        origin = operator / 'internal/preparation/python_origin_test.go'
        origin_copy = Path(directory) / origin.name
        origin_source = origin.read_text()
        if origin_source.count('observed["observation"]') != 1:
            raise SystemExit('Operator origin fixture changed; review inspected citation selection')
        origin_copy.write_text(origin_source.replace('observed["observation"]', 'observed["citation"]'))
        campaign = operator / "internal/preparation/python_campaign_test.go"
        campaign_copy = Path(directory) / campaign.name
        source = campaign.read_text()
        old_identity = 'attempts[0]["attempt_id"] == attempts[1]["attempt_id"]'
        if source.count(old_identity) != 1:
            raise SystemExit("Operator campaign fixture changed; review model handle identity assertion")
        # The model now receives an execution handle, not internal bookkeeping.
        # Test-only adapters consume the current presentation; canonical evidence
        # bytes and Operator sources remain unchanged.
        source = source.replace('task["reference_handles"].([]any)',
            'task["campaign"].(map[string]any)["references"].([]any)')
        source = source.replace('e["role"] == "reference"', 'e["reference"] != nil').replace('e["entry_id"]', 'e["reference"]')
        source = source.replace('text, ok := value["content"].(string)',
            'if value["encoding"] == "json" { return json.Marshal(value["content"]) }; text, ok := value["content"].(string)')
        campaign_copy.write_text(source.replace(old_identity,
            'attempts[0]["execution"] == attempts[1]["execution"]'))
        scenario_overlays = {}
        for name in ("python_restore_test.go", "python_postgresql_test.go", "python_attempt_timeout_test.go", "unsupported_fields_process_test.go"):
            original_test = operator / "internal/preparation" / name
            text = original_test.read_text()
            if name == "python_restore_test.go":
                text = text.replace('processResponse([]any{modelCall("record",',
                    'processResponse([]any{mustScenarioSelection(q), modelCall("record",')
            elif name == "python_postgresql_test.go":
                text = text.replace('_, ok := v["content"].(string)', '_, ok := v["content"]')
                text = text.replace('_, ok := observed["content"].(string)', '_, ok := observed["content"]')
                text = text.replace('processResponse([]any{call("snapshot",',
                    'processResponse([]any{mustScenarioSelection(q), call("snapshot",')
            elif name == "unsupported_fields_process_test.go":
                text = text.replace('reply: func(turn int, q map[string]any) ([]byte, error) {',
                    'reply: func(turn int, q map[string]any) ([]byte, error) { if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil { return response, err };')
            else:
                text = text.replace('if turn != 1 {',
                    'if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil { return response, err }; if turn != 1 {')
                text = text.replace('len(r.provider.requests) != 1', 'len(r.provider.requests) != 2')
            copied = Path(directory) / name
            copied.write_text(text)
            scenario_overlays[str(original_test)] = str(copied)
        text = origin_copy.read_text().replace('reply := func(turn int, q map[string]any) ([]byte, error) {',
            'reply := func(turn int, q map[string]any) ([]byte, error) { if mode != "exploratory" { if response, err := scenarioSelectionTurn(&turn, q); response != nil || err != nil { return response, err } };')
        origin_copy.write_text(text)
        text = campaign_copy.read_text().replace('calls := []any{}',
            'calls := []any{}; if turn == 1 && origin == "scenario" { calls = append(calls, mustScenarioSelection(q)) }')
        campaign_copy.write_text(text)
        overlay.write_text(json.dumps({"Replace": {
            **scenario_overlays,
            str(operator / "internal/preparation/harness_scenario_loading_test.go"):
                str(root / "build/operator_scenario_loading_test.go"),
            str(original): str(replacement), str(helper): str(helper_copy),
            str(operator / "internal/preparation/harness_evidence_budget_test.go"):
                str(root / "build/operator_evidence_budget_test.go"),
            str(campaign): str(campaign_copy),
            str(origin): str(origin_copy),
            str(operator / "internal/preparation/python_context_test.go"):
                str(root / "build/operator_context_test.go"),
            str(operator / "internal/preparation/python_history_test.go"):
                str(root / "build/operator_history_test.go"),
            str(operator / "internal/preparation/conclusion_diagnostic_process_test.go"):
                str(root / "build/operator_conclusion_diagnostic_test.go"),
            str(operator / "internal/preparation/harness_exit_process_test.go"):
                str(root / "build/operator_exit_test.go"),
        }}))
        environment = dict(os.environ, OPERATOR_TEST_HARNESS_SOURCE=str(root),
            OPERATOR_TEST_PYTHON=str(args.python.absolute()), OPERATOR_HARNESS_INTEGRATION="1",
            OPERATOR_PYTHON_PEER_TEST="1", PYTHONDONTWRITEBYTECODE="1")
        subprocess.run(["go", "test", "-overlay", str(overlay), "-count=1", "-timeout", "20m",
            "-v", "-run", args.run, "./internal/preparation", "./internal/transport"],
            cwd=operator, env=environment, check=True)


if __name__ == "__main__":
    main()
