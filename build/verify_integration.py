"""Run pinned Operator integration with the simple-workflow process fixture.

The pin still contains a legacy test that expects invalid finish to terminate.
Replace only that test source through Go's overlay; never edit the contract or
runtime checkout. Remove the overlay when Operator incorporates this fixture.
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
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    operator = args.operator_root.resolve()
    lock = json.loads((root / "build/contract-lock.json").read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=operator, text=True).strip()
    if commit != lock["source"]["commit"]:
        raise SystemExit("integration requires the pinned Operator commit")
    original = operator / "internal/preparation/conclusion_diagnostic_process_test.go"
    replacement = root / "build/operator_simple_campaign_test.go"
    with tempfile.TemporaryDirectory(prefix="harness-integration-") as directory:
        overlay = Path(directory) / "overlay.json"
        overlay.write_text(json.dumps({"Replace": {str(original): str(replacement)}}))
        environment = dict(os.environ, OPERATOR_TEST_HARNESS_SOURCE=str(root),
            OPERATOR_TEST_PYTHON=str(args.python.absolute()), OPERATOR_HARNESS_INTEGRATION="1",
            OPERATOR_PYTHON_PEER_TEST="1", PYTHONDONTWRITEBYTECODE="1")
        subprocess.run(["go", "test", "-overlay", str(overlay), "-count=1", "-timeout", "10m",
            "-v", "-run", args.run, "./internal/preparation", "./internal/transport"],
            cwd=operator, env=environment, check=True)


if __name__ == "__main__":
    main()
