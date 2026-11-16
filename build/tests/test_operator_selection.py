"""Selected validator identity is checked before importing counterpart code."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class OperatorSelectionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.harness = Path(directory.name)
        (self.harness / "build").mkdir()
        self.document = b'{"info":{"version":"1.2.3"}}'
        identity = {"package_version": "1.2.3", "package_digest":
                    "sha256:" + hashlib.sha256(self.document).hexdigest()}
        (self.harness / "build/contract-lock.json").write_text(json.dumps({"package": identity}))
        for name in ("Makefile", "build/verify_integration.py"):
            (self.harness / name).write_bytes((ROOT / name).read_bytes())

    def selected(self, mutate=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "schemas").mkdir()
        raw = self.document
        if mutate:
            raw = mutate(raw)
        (root / "schemas/asyncapi.json").write_bytes(raw)
        return root

    def check(self, operator):
        return subprocess.run([sys.executable, "build/verify_integration.py",
            "--operator-root", str(operator), "--python", sys.executable,
            "--check-contract-only"], cwd=self.harness, capture_output=True, text=True)

    def test_approved_bytes_need_no_git_revision_or_integration_runtime(self):
        result = self.check(self.selected())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selected Operator interface verified", result.stdout)

    def test_changed_bytes_with_same_version_fail(self):
        result = self.check(self.selected(lambda raw: raw + b" "))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected:", result.stderr)
        self.assertIn("Observed:", result.stderr)
        self.assertIn("exact document hash", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_make_test_rejects_wrong_version_before_unit_tests(self):
        def change(raw):
            value = json.loads(raw)
            value["info"]["version"] = "0.0.0"
            return json.dumps(value).encode()
        operator = self.selected(change)
        result = subprocess.run(["make", "test", "OPERATOR_ROOT=" + str(operator),
            "PYTHON=" + sys.executable], cwd=self.harness, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Selected Operator interface does not match", result.stderr)
        self.assertIn('"package_version": "0.0.0"', result.stderr)
        self.assertNotIn("unittest discover", result.stdout)
        self.assertNotIn("AttributeError", result.stderr)
