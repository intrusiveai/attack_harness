"""Run controlled integration against an exact Operator revision.

Keep the default contract source pin; an explicitly selected newer host must have
identical contracts/schemas. Test-only Go overlays replace its obsolete terminal
assessment fixture and add fatal-exit cases through a separate Python adapter.
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
    parser.add_argument("--run", default=".")
    parser.add_argument("--operator-commit", help="Explicit host runtime revision; shared contract must remain identical")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    operator = args.operator_root.resolve()
    lock = json.loads((root / "build/contract-lock.json").read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=operator, text=True).strip()
    if commit != (args.operator_commit or lock["source"]["commit"]):
        raise SystemExit("integration requires the exact selected Operator commit")
    subprocess.run(["git", "diff", "--exit-code", lock["source"]["commit"], commit,
        "--", "contracts", "schemas"], cwd=operator, check=True, stdout=subprocess.DEVNULL)
    original = operator / "internal/preparation/conclusion_diagnostic_process_test.go"
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
        # The fixture kills on FIFO EOF before Python finishes flushing stderr.
        # Give this deliberate fatal-exit fixture the same bounded exit window.
        marker = "if service.StopAccepted() {"
        if source.count(marker) != 1:
            raise SystemExit("Operator process exit fixture changed; review the grace window")
        source = source.replace(marker,
            'if service.StopAccepted() || os.Getenv("HARNESS_TEST_EXIT_MODE") == "runtime-fatal" {')
        helper_copy.write_text(source)
        overlay.write_text(json.dumps({"Replace": {
            str(original): str(replacement), str(helper): str(helper_copy),
            str(operator / "internal/preparation/harness_exit_process_test.go"):
                str(root / "build/operator_exit_test.go"),
        }}))
        environment = dict(os.environ, OPERATOR_TEST_HARNESS_SOURCE=str(root),
            OPERATOR_TEST_PYTHON=str(args.python.absolute()), OPERATOR_HARNESS_INTEGRATION="1",
            OPERATOR_PYTHON_PEER_TEST="1", PYTHONDONTWRITEBYTECODE="1")
        subprocess.run(["go", "test", "-overlay", str(overlay), "-count=1", "-timeout", "10m",
            "-v", "-run", args.run, "./internal/preparation", "./internal/transport"],
            cwd=operator, env=environment, check=True)


if __name__ == "__main__":
    main()
