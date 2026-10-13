"""Run the publisher scripts with real record validation and simulated GHCR/AWS.

OCI and HTTPS protocol validation have separate Go tests. These tests exercise
the workflow handoff, including pending QA, without publishing anything remotely.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PublisherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / "releasectl"
        subprocess.run(["go", "build", "-o", str(cls.binary), "./cmd/release-publisher"], cwd=ROOT, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.path = Path(self.work.name)
        self.raw = (ROOT / "testdata/records/valid-amd64.json").read_text()
        self.env = dict(os.environ, PATH=f"{self.path}:{os.environ['PATH']}",
                        TEST_BINARY=str(self.binary), TEST_STORE=str(self.path / "object"),
                        TEST_TRACE=str(self.path / "trace"), RECORD_JSON=self.raw,
                        IMAGE_REFERENCE="ghcr.io/intrusiveai/attack_harness:v1.0.0-rc.1",
                        PLATFORM="linux/amd64", IMAGE_CONFIG_DIGEST=json.loads(self.raw)["image_digest"],
                        PLATFORM_MANIFEST_DIGEST="sha256:" + "b" * 64, INDEX_DIGEST="",
                        EVIDENCE_URL="https://github.com/intrusiveai/attack_harness/actions/runs/123",
                        SOURCE_COMMIT="a" * 40, CONTENT_BUCKET="fixture", CLOUDFRONT_DISTRIBUTION_ID="fixture")
        self.record = self.path / "record.json"
        self.stub("go", '''#!/usr/bin/env bash
set -eu
shift 2 # go run ./cmd/release-publisher
if [[ "$1 $2" == 'record validate' ]]; then exec "$TEST_BINARY" "$@"; fi
printf '%s\\n' "$*" >> "$TEST_TRACE"
if [[ "$1 $2" == 'image verify' ]]; then exit "${TEST_IMAGE_FAILURE:-0}"; fi
if [[ "$1 $2" == 'remote verify' ]]; then
  cmp "$TEST_STORE" "$6"
  exit "${TEST_REMOTE_FAILURE:-0}"
fi
exit 99
''')
        self.stub("curl", '''#!/usr/bin/env bash
printf 'public evidence\\n' >> "$TEST_TRACE"
exit "${TEST_EVIDENCE_FAILURE:-0}"
''')
        self.stub("aws", '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
store = pathlib.Path(os.environ['TEST_STORE'])
with open(os.environ['TEST_TRACE'], 'a') as trace:
    trace.write(' '.join(args) + '\\n')
def opt(name): return args[args.index(name) + 1]
if args[:2] == ['s3api', 'put-object']:
    assert opt('--if-none-match') == '*'
    assert opt('--key').startswith('sha256/')
    assert opt('--content-type') == 'application/json'
    assert opt('--cache-control') == 'public,max-age=31536000,immutable'
    try:
        with store.open('xb') as dest:
            dest.write(pathlib.Path(opt('--body')).read_bytes())
    except FileExistsError:
        print('PreconditionFailed', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({'ChecksumSHA256': 'fixture', 'VersionId': 'fixture'}))
elif args[:2] == ['s3api', 'get-object']:
    pathlib.Path(args[-1]).write_bytes(store.read_bytes())
    print('{}')
elif args[:2] == ['s3api', 'head-object']:
    print(json.dumps({'ContentType': 'application/json', 'CacheControl': 'public,max-age=31536000,immutable'}))
elif args[:2] == ['cloudfront', 'create-invalidation']:
    assert opt('--paths') == '/sha256/' + json.loads(store.read_bytes())['image_digest'][7:]
    print('{}')
else:
    sys.exit(99)
''')

    def stub(self, name, content):
        path = self.path / name
        path.write_text(content)
        path.chmod(0o755)

    def run_script(self, name, success=True):
        result = subprocess.run(["bash", str(ROOT / "scripts" / name), str(self.record)],
                                cwd=ROOT, env=self.env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, "invalid publication succeeded")
        return result

    def test_candidate_publication_before_qualification_is_idempotent(self):
        self.env["QUALIFICATION_STATUS"] = "pending"
        self.run_script("prepare-record.sh")
        self.assertEqual(self.record.read_text(), self.raw)
        self.run_script("publish-record.sh")
        self.run_script("publish-record.sh")
        self.assertEqual(Path(self.env["TEST_STORE"]).read_text(), self.raw)
        trace = Path(self.env["TEST_TRACE"]).read_text()
        self.assertIn("image verify --reference ghcr.io/intrusiveai/attack_harness:v1.0.0-rc.1", trace)
        self.assertIn("public evidence", trace)
        self.assertIn("remote verify", trace)
        self.assertEqual(trace.count("cloudfront create-invalidation"), 1)
        # Compatibility changes under the same image ID are still forbidden.
        self.record.write_text(self.raw.replace('"minimum_operator_version":"0.1.0"',
                                                '"minimum_operator_version":"0.2.0"'))
        result = self.run_script("publish-record.sh", success=False)
        self.assertIn("immutable conflict", result.stderr)
        self.assertEqual(Path(self.env["TEST_STORE"]).read_text(), self.raw)

    def test_rejects_invalid_candidate_inputs_before_publication(self):
        cases = [
            {"IMAGE_CONFIG_DIGEST": "sha256:" + "c" * 64},
            {"PLATFORM": "linux/arm64"},
            {"IMAGE_REFERENCE": "ghcr.io/other/attack_harness:v1.0.0-rc.1"},
            {"TEST_IMAGE_FAILURE": "1"},
            {"EVIDENCE_URL": ""},
            {"EVIDENCE_URL": "https://github.com/other/attack_harness/actions/runs/123"},
            {"TEST_EVIDENCE_FAILURE": "22"},
            {"SOURCE_COMMIT": "not-a-commit"},
            {"RECORD_JSON": self.raw.replace('"platform":', '"tags":["release"],"platform":')},
        ]
        original = self.env.copy()
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.env = dict(original, **overrides)
                self.run_script("prepare-record.sh", success=False)
                self.assertFalse(Path(self.env["TEST_STORE"]).exists())

    def test_requires_successful_public_readback(self):
        self.run_script("prepare-record.sh")
        self.env["TEST_REMOTE_FAILURE"] = "1"
        self.run_script("publish-record.sh", success=False)


if __name__ == "__main__":
    unittest.main()
