import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from build import publish_candidate as release
from build.inspect_oci import ALLOWED_ENV, ENTRYPOINT, inspect
from build.inspect_stopped_image import _local_image_id
from build.prepare_release import COMPATIBILITY_PATH, compatibility


SOURCE = "a" * 40
MERGE = "b" * 40
BRANCH = "candidate-v1.2.3"


def make_archive(directory, platform, mutate_files=None):
    """Small OCI fixture exercising the actual inspector and publication path."""
    blobs = {}

    def blob(value, media_type):
        raw = value if isinstance(value, bytes) else json.dumps(value, separators=(",", ":")).encode()
        digest = release.digest(raw)
        blobs["blobs/sha256/" + digest[7:]] = raw
        return {"mediaType": media_type, "digest": digest, "size": len(raw)}

    config = blob({"os": "linux", "architecture": platform.split("/")[1],
                   "created": "1970-01-01T00:00:00Z", "history": [],
                   "rootfs": {"diff_ids": ["sha256:" + "c" * 64]},
                   "config": {"User": "65532:65532", "Entrypoint": ENTRYPOINT,
                              "WorkingDir": "/run/operator/work", "Env": ALLOWED_ENV,
                              "Labels": {"org.opencontainers.image.source": "https://github.com/" + release.REPOSITORY}}},
                  "application/vnd.oci.image.config.v1+json")
    pin = json.loads(Path("build/contract-lock.json").read_bytes())["package"]
    pin = {key: pin[key] for key in ("package_version", "package_digest")}
    resources = {"prompt": ("share/default-system-prompt.txt", b"test prompt"),
                 "skill_loader": ("lib/attack_harness/skill_loader.py", b"# loader\n"),
                 "tool_catalog": ("share/tool-catalog.json", b'{}')}
    embedded = {"api_version": "operator.dev/engine-manifest/v1alpha1", "contract": pin,
                "platform": platform, "runtime_profile": "operator-container/v1",
                "entrypoint": ENTRYPOINT, "transports": ["fifo", "spool"],
                **{key: {"size_bytes": len(raw), "digest": release.digest(raw)}
                   for key, (_, raw) in resources.items()}}
    files = {"opt/operator/engine/" + name: raw for name, raw in resources.values()}
    files["opt/operator/engine/share/engine-manifest.json"] = json.dumps(embedded).encode()
    files[COMPATIBILITY_PATH] = json.dumps(compatibility(pin, platform), sort_keys=True, separators=(",", ":")).encode()
    if mutate_files:
        mutate_files(files)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, raw in files.items():
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(raw), 0o444
            tar.addfile(entry, io.BytesIO(raw))
    layer = blob(buffer.getvalue(), "application/vnd.oci.image.layer.v1.tar")
    manifest = blob({"schemaVersion": 2, "config": config, "layers": [layer]},
                    "application/vnd.oci.image.manifest.v1+json")
    manifest["platform"] = {"os": "linux", "architecture": platform.split("/")[1]}
    statements = []
    for predicate in ("https://spdx.dev/Document", "https://slsa.dev/provenance/v0.2"):
        statement = blob({"predicateType": predicate}, "application/vnd.in-toto+json")
        statement["annotations"] = {"in-toto.io/predicate-type": predicate}
        statements.append(statement)
    attestation = blob({"schemaVersion": 2, "layers": statements}, "application/vnd.oci.image.manifest.v1+json")
    attestation["platform"] = {"os": "unknown", "architecture": "unknown"}
    attestation["annotations"] = {"vnd.docker.reference.type": "attestation-manifest",
                                   "vnd.docker.reference.digest": manifest["digest"]}
    index = blob({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                  "manifests": [manifest, attestation]}, "application/vnd.oci.image.index.v1+json")
    blobs["index.json"] = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [index]}).encode()
    blobs["oci-layout"] = b'{"imageLayoutVersion":"1.0.0"}'
    prefix = directory / ("attack-harness-" + platform.replace("/", "-"))
    archive = Path(str(prefix) + ".oci.tar")
    with tarfile.open(archive, "w") as output:
        for name, raw in blobs.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            output.addfile(entry, io.BytesIO(raw))
    report = inspect(archive, platform, Path("build/contract-lock.json"))
    release.write_json(Path(str(prefix) + ".build-report.json"), report)
    release.write_json(Path(str(prefix) + ".inspection-report.json"), {
        "status": "passed", "native_platform": True, "platform": platform, "oci_config_digest": config["digest"],
        "layer_digests": [layer["digest"]], "operator_stopped_image_inspection": "passed",
        "inspection_container_cleanup": "passed", "operator_version": "0.1.0",
        "operator_local_compatibility": "passed", "compatibility_digest": report["compatibility"]["digest"],
        "operator_commit": Path("build/operator-runtime-commit.txt").read_text().strip()})
    release.write_json(Path(str(prefix) + ".rebuild-comparison.json"), {
        "platform": platform, "runtime_identity": "identical",
        "runtime_comparisons": {"image_digest": True, "manifest_digest": True, "layer_digests": True}})


class FakeRegistry:
    def __init__(self):
        self.images = {}
        self.copies = []

    def raw(self, reference):
        return self.images[reference]

    def copy(self, source, tag):
        self.copies.append((source, tag))
        if source.startswith("oci-archive:"):
            with tarfile.open(source.removeprefix("oci-archive:")) as archive:
                root = json.load(archive.extractfile("index.json"))
                raw = archive.extractfile("blobs/sha256/" + root["manifests"][0]["digest"][7:]).read()
        else:
            raw = self.raw(source.removeprefix("docker://"))
        self.images[release.IMAGE + ":" + tag] = raw
        self.images[release.IMAGE + "@" + release.digest(raw)] = raw

    def combine(self, references, tag, source, version, evidence_tag):
        manifests = [m for reference in references for m in json.loads(self.raw(reference))["manifests"]]
        raw = json.dumps({"manifests": manifests, "annotations": {
            "org.opencontainers.image.revision": source, "org.opencontainers.image.version": version,
            "ai.intrusive.evidence-tag": evidence_tag}}).encode()
        self.images[release.IMAGE + ":" + tag] = raw
        self.images[release.IMAGE + "@" + release.digest(raw)] = raw
        return raw


class FakeGitHub:
    def __init__(self):
        self.refs = {BRANCH: SOURCE, "main": MERGE}
        self.tags, self.releases, self.dispatches = {}, {}, []
        self.tree = {SOURCE: "tree", MERGE: "tree"}
        self.pr = {"number": 42, "merged": True, "merge_commit_sha": MERGE,
                   "html_url": "https://github.com/" + release.REPOSITORY + "/pull/42",
                   "body": "QA results for this candidate: fixture campaign passed.",
                   "base": {"ref": "main"}, "head": {"ref": BRANCH, "sha": SOURCE,
                   "repo": {"full_name": release.REPOSITORY}}}
        self.jobs = [{"name": "native-platform (" + p + ")", "conclusion": "success"} for p in release.PLATFORMS]

    def api(self, path, method="GET", data=None, missing=False):
        if path.startswith("git/ref/heads/"):
            value = self.refs.get(path.removeprefix("git/ref/heads/"))
            return {"object": {"sha": value}} if value else None
        if path.startswith("git/ref/tags/"):
            value = self.tags.get(path.removeprefix("git/ref/tags/"))
            return {"object": {"sha": value}} if value else None
        if path.startswith("git/commits/"):
            return {"tree": {"sha": self.tree[path.removeprefix("git/commits/")]}}
        if path == "pulls/42":
            return self.pr
        if path.endswith("/dispatches"):
            self.dispatches.append({"workflow": path.split("/")[2], **data})
            return None
        if path == "actions/runs/123":
            return {"head_sha": SOURCE, "head_branch": BRANCH, "path": ".github/workflows/verify.yml", "event": "push"}
        if path == "actions/runs/123/attempts/1/jobs?per_page=100":
            return {"jobs": self.jobs}
        if path == "actions/runs/123/attempts/2/jobs?per_page=100":
            return {"jobs": []}
        raise AssertionError(path)

    def release(self, tag):
        return self.releases.get(tag)

    def download_entry(self, tag, directory):
        return json.loads(self.releases[tag]["files"]["release-index-entry.json"])

    def create_release(self, tag, source, metadata, files, prerelease):
        self.tags[tag] = source
        result = {"draft": False, "body": release.MARKER + "\n" + json.dumps(metadata),
                  "html_url": "https://github.com/" + release.REPOSITORY + "/releases/tag/" + tag,
                  "prerelease": prerelease, "files": {p.name: p.read_bytes() for p in files}}
        self.releases[tag] = result
        return result


class DockerIdentityTest(unittest.TestCase):
    @patch("build.inspect_stopped_image.subprocess.run")
    def test_classic_and_containerd_ids_are_independently_resolved(self, run):
        config, manifest = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        run.return_value = subprocess.CompletedProcess([], 0, config + "\n")
        self.assertEqual(_local_image_id("docker", "linux/arm64", manifest, config), config)
        run.side_effect = [subprocess.CompletedProcess([], 1, ""),
                           subprocess.CompletedProcess([], 0, manifest + "\n")]
        self.assertEqual(_local_image_id("docker", "linux/arm64", manifest, config), manifest)

    @patch("build.inspect_stopped_image.subprocess.run")
    def test_unknown_or_missing_image_identity_fails(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "sha256:" + "f" * 64)
        with self.assertRaisesRegex(ValueError, "unexpected image identity"):
            _local_image_id("docker", "linux/arm64", "sha256:" + "a" * 64, "sha256:" + "b" * 64)
        run.return_value = subprocess.CompletedProcess([], 1, "")
        with self.assertRaisesRegex(ValueError, "cannot resolve"):
            _local_image_id("docker", "linux/arm64", "sha256:" + "a" * 64, "sha256:" + "b" * 64)


class CandidateWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.github, self.registry = FakeGitHub(), FakeRegistry()
        for platform in release.PLATFORMS:
            make_archive(self.directory, platform)

    def publish(self, run="123.1", source=SOURCE):
        return release.publish(self.github, self.registry, self.directory, BRANCH, source, run, "success")

    def test_push_and_merge_into_candidate_publish_but_pr_does_not(self):
        for event in ({}, {"before": "c" * 40, "after": SOURCE}):
            self.assertEqual(release.context(event, "push", "refs/heads/" + BRANCH, SOURCE, release.REPOSITORY)["mode"], "publish")
        event = {"action": "synchronize", "pull_request": self.github.pr}
        self.assertEqual(release.context(event, "pull_request", "refs/pull/42/merge", SOURCE, release.REPOSITORY)["mode"], "verify")
        event["action"] = "closed"
        self.assertEqual(release.context(event, "pull_request", "refs/heads/main", MERGE, release.REPOSITORY)["mode"], "promote")
        self.github.pr["base"]["ref"] = BRANCH
        self.assertEqual(release.context(event, "pull_request", "refs/heads/" + BRANCH, MERGE, release.REPOSITORY)["mode"], "ignore")

    def test_closed_unmerged_fork_deleted_and_main_never_publish(self):
        for merged, repo in ((False, release.REPOSITORY), (True, "elsewhere/fork")):
            pr = copy.deepcopy(self.github.pr)
            pr["merged"], pr["head"]["repo"]["full_name"] = merged, repo
            self.assertEqual(release.context({"action": "closed", "pull_request": pr}, "pull_request", "", SOURCE, release.REPOSITORY)["mode"], "ignore")
        self.assertEqual(release.context({"deleted": True}, "push", "refs/heads/" + BRANCH, SOURCE, release.REPOSITORY)["mode"], "ignore")
        self.assertEqual(release.context({}, "push", "refs/heads/main", SOURCE, release.REPOSITORY)["mode"], "verify")

    @patch("urllib.request.urlopen", side_effect=AssertionError("compatibility API must not be queried"))
    def test_complete_candidate_and_promotion_preserves_bytes_without_records(self, remote):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        candidate = self.registry.raw(release.IMAGE + ":v1.2.3")
        self.assertNotIn(release.IMAGE + ":latest", self.registry.images)
        self.assertEqual(self.github.dispatches, [
            {"workflow": "publish-catalog.yml", "ref": tag}])
        candidate_entry = json.loads(release.catalog_context(
            self.github, self.registry, tag, SOURCE, self.directory)["entry_json"])
        self.assertEqual(candidate_entry["tags"], ["rc"])
        self.assertEqual(candidate_entry["image"], release.IMAGE + ":" + tag)
        package_version = json.loads(Path("build/contract-lock.json").read_bytes())["package"]["package_version"]
        self.assertEqual(candidate_entry["contract_package_version"], package_version)
        evidence = json.loads(self.github.releases[tag]["files"]["candidate.json"])
        self.assertTrue(all("record" not in p for p in evidence["platforms"]))
        release.promote(self.github, self.registry, 42, self.directory)
        snapshot = self.github.releases["v1.2.3"]["body"]
        self.github.pr["body"] = "Later edits must not change the retained QA sign-off."
        release.promote(self.github, self.registry, 42, self.directory)
        self.assertEqual(self.github.releases["v1.2.3"]["body"], snapshot)
        final_entry = json.loads(release.catalog_context(
            self.github, self.registry, "v1.2.3", SOURCE, self.directory)["entry_json"])
        remote.assert_not_called()
        self.assertEqual(self.registry.raw(release.IMAGE + ":latest"), candidate)
        self.assertEqual(self.github.tags["v1.2.3"], SOURCE)
        final = json.loads(self.github.releases["v1.2.3"]["files"]["release-index-entry.json"])
        self.assertEqual(final["tags"], ["release"])
        self.assertEqual(final["digest"], release.digest(candidate))
        self.assertEqual(final_entry, final)
        self.assertEqual(candidate_entry["digest"], final_entry["digest"])
        self.assertEqual(candidate_entry["contract_package_version"], final_entry["contract_package_version"])
        self.assertEqual(self.github.dispatches[-1], {"workflow": "publish-catalog.yml", "ref": "v1.2.3"})
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.publish("124.1")

    def test_generated_candidate_and_promotion_match_local_publisher_contract(self):
        """Pass real source-pipeline outputs through the bundled Go entry points."""
        publisher = Path(__file__).resolve().parents[2] / "tools/release-publisher"

        def run(command, *arguments):
            result = subprocess.run(
                ["go", "run", "./cmd/" + command, *map(str, arguments)],
                cwd=publisher, capture_output=True, text=True,
                env=dict(os.environ, GOWORK="off", GOPROXY="off", GOTOOLCHAIN="local"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.publish()
        tag = "v1.2.3-candidate.123.1"
        entry = self.directory / "entry.json"
        catalog = self.directory / "catalog.json"
        entry.write_text(release.catalog_context(
            self.github, self.registry, tag, SOURCE, self.directory)["entry_json"])
        run("catalog-publisher", "catalog", "merge", "--product", "attack_harness",
            "--entry", entry, "--output", catalog)
        candidate = json.loads(catalog.read_bytes())["releases"][0]
        self.assertEqual(candidate["tags"], ["rc"])
        self.assertEqual(candidate["contract_package_version"],
                         json.loads(Path("build/contract-lock.json").read_bytes())["package"]["package_version"])
        release.promote(self.github, self.registry, 42, self.directory)
        entry.write_text(release.catalog_context(
            self.github, self.registry, "v1.2.3", SOURCE, self.directory)["entry_json"])
        run("catalog-publisher", "catalog", "merge", "--product", "attack_harness",
            "--entry", entry, "--current", catalog, "--output", catalog)
        final, retained_candidate = json.loads(catalog.read_bytes())["releases"]
        self.assertEqual(final["tags"], ["release"])
        self.assertEqual(final["digest"], candidate["digest"])
        self.assertEqual(final["contract_package_version"], candidate["contract_package_version"])
        self.assertEqual(final["digest"], release.digest(self.registry.raw(release.IMAGE + ":latest")))
        self.assertEqual(retained_candidate, dict(candidate, latest=False))
        self.assertEqual(final["image"], release.IMAGE + ":v1.2.3")

    def test_stale_build_preserves_immutable_evidence_without_moving_version(self):
        self.publish()
        original = self.registry.raw(release.IMAGE + ":v1.2.3")
        self.github.refs[BRANCH] = "c" * 40
        self.assertIn("superseded", self.publish("124.1"))
        self.assertEqual(self.registry.raw(release.IMAGE + ":v1.2.3"), original)
        self.assertIn("v1.2.3-candidate.124.1", self.github.releases)

    def test_missing_or_invalid_contract_version_never_uploads(self):
        reports, files = release.check_reports(self.directory)
        for version in (None, "", "v0.2.1", "0.2", "01.2.3", "0.2.1-rc.1", "0.2.1+build",
                        "0.2.1\n", " 0.2.1", "^0.2.1", 21, "1" * 125 + ".0.0"):
            for platform in range(2):
                with self.subTest(version=version, platform=platform):
                    invalid = copy.deepcopy(reports)
                    if version is None:
                        invalid[platform]["contract"].pop("package_version")
                    else:
                        invalid[platform]["contract"]["package_version"] = version
                    with patch.object(release, "check_reports", return_value=(invalid, files)):
                        with self.assertRaisesRegex(ValueError, "contract_package_version"):
                            self.publish()
                    self.assertEqual(self.registry.copies, [])
                    self.assertEqual(self.github.releases, {})
                    self.assertEqual(self.github.dispatches, [])

    def test_cross_platform_contract_disagreement_never_uploads(self):
        reports, files = release.check_reports(self.directory)
        reports[1]["contract"]["package_version"] = "99.0.0"
        compatibility = reports[1]["compatibility"]
        compatibility["record"]["contract_package_version"] = "99.0.0"
        compatibility["raw"] = json.dumps(compatibility["record"])
        compatibility["digest"] = release.digest(compatibility["raw"].encode())
        with patch.object(release, "check_reports", return_value=(reports, files)):
            with self.assertRaisesRegex(ValueError, "platform contracts differ"):
                self.publish()
        self.assertEqual(self.registry.copies, [])

    def test_build_report_contract_must_describe_the_image(self):
        for platform in release.PLATFORMS:
            path = self.directory / ("attack-harness-" + platform.replace("/", "-") + ".build-report.json")
            original = json.loads(path.read_bytes())
            invalid = copy.deepcopy(original)
            invalid["contract"]["package_version"] = "99.0.0"
            release.write_json(path, invalid)
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "archive differs"):
                self.publish()
            self.assertEqual(self.registry.copies, [])
            release.write_json(path, original)

    def test_promotion_and_catalog_use_retained_contract_not_current_checkout(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        original = json.loads(self.github.releases[tag]["files"]["release-index-entry.json"])
        read_bytes = Path.read_bytes

        def read(path):
            if path == Path("build/contract-lock.json"):
                raise AssertionError("released metadata must not come from the current checkout")
            return read_bytes(path)

        with patch.object(Path, "read_bytes", read):
            release.promote(self.github, self.registry, 42, self.directory)
            final = json.loads(release.catalog_context(
                self.github, self.registry, "v1.2.3", SOURCE, self.directory)["entry_json"])
        self.assertEqual(final["contract_package_version"], original["contract_package_version"])
        self.assertEqual(final["digest"], original["digest"])

    def test_catalog_and_promotion_reject_changed_candidate_contract(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        assets = self.github.releases[tag]["files"]
        original = json.loads(assets["release-index-entry.json"])
        for version in (None, "99.0.0"):
            changed = dict(original)
            if version is None:
                changed.pop("contract_package_version")
            else:
                changed["contract_package_version"] = version
            assets["release-index-entry.json"] = json.dumps(changed).encode()
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "catalog entry differs"):
                    release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)
                with self.assertRaisesRegex(ValueError, "candidate catalog entry differs"):
                    release.promote(self.github, self.registry, 42, self.directory)
                self.assertNotIn("v1.2.3", self.github.releases)
                self.assertNotIn(release.IMAGE + ":latest", self.registry.images)

    def test_retained_contract_must_match_embedded_compatibility(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        candidate = self.github.releases[tag]
        evidence = json.loads(candidate["body"].removeprefix(release.MARKER + "\n"))
        for platform in evidence["platforms"]:
            platform["contract"]["package_version"] = "99.0.0"
        candidate["body"] = release.MARKER + "\n" + json.dumps(evidence)
        with self.assertRaisesRegex(ValueError, "differs from embedded compatibility"):
            release.promote(self.github, self.registry, 42, self.directory)
        with self.assertRaisesRegex(ValueError, "differs from embedded compatibility"):
            release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)
        self.assertNotIn(release.IMAGE + ":latest", self.registry.images)

    def test_new_head_replaces_version_and_requires_matching_merge(self):
        self.publish()
        self.github.refs[BRANCH] = "c" * 40
        self.publish("124.1", "c" * 40)
        with self.assertRaisesRegex(ValueError, "merged candidate head"):
            release.promote(self.github, self.registry, 42, self.directory)

    def test_merge_tree_change_and_stale_promotion_fail(self):
        self.publish()
        self.github.tree[MERGE] = "different"
        with self.assertRaisesRegex(ValueError, "merge changed"):
            release.promote(self.github, self.registry, 42, self.directory)
        self.github.tree[MERGE] = "tree"
        self.github.refs["main"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "main has advanced"):
            release.promote(self.github, self.registry, 42, self.directory)
        self.assertNotIn(release.IMAGE + ":latest", self.registry.images)

    def test_failed_build_or_different_inspection_never_publishes(self):
        with self.assertRaisesRegex(ValueError, "must succeed"):
            release.publish(self.github, self.registry, self.directory, BRANCH, SOURCE, "123.1", "failure")
        path = self.directory / "attack-harness-linux-amd64.inspection-report.json"
        inspection = json.loads(path.read_bytes())
        inspection["oci_config_digest"] = "sha256:" + "f" * 64
        release.write_json(path, inspection)
        with self.assertRaisesRegex(ValueError, "inspection does not match"):
            self.publish()
        self.assertEqual(self.registry.copies, [])

    def test_runtime_pin_can_differ_from_contract_source(self):
        contract_commit = json.loads(Path("build/contract-lock.json").read_bytes())["source"]["commit"]
        runtime_commit = Path("build/operator-runtime-commit.txt").read_text().strip()
        self.assertNotEqual(runtime_commit, contract_commit)
        self.publish()
        self.assertIn(release.IMAGE + ":v1.2.3", self.registry.images)
        self.assertEqual(self.github.dispatches, [
            {"workflow": "publish-catalog.yml", "ref": "v1.2.3-candidate.123.1"}])

    def test_unpinned_inspector_never_publishes_even_at_contract_source(self):
        contract_commit = json.loads(Path("build/contract-lock.json").read_bytes())["source"]["commit"]
        for platform in release.PLATFORMS:
            path = self.directory / ("attack-harness-" + platform.replace("/", "-") + ".inspection-report.json")
            original = json.loads(path.read_bytes())
            for commit in (contract_commit, "f" * 40, "main", ""):
                with self.subTest(platform=platform, commit=commit):
                    release.write_json(path, {**original, "operator_commit": commit})
                    with self.assertRaisesRegex(ValueError, "unpinned Operator runtime"):
                        self.publish()
                    self.assertEqual(self.registry.copies, [])
                    self.assertEqual(self.github.releases, {})
                    self.assertEqual(self.github.dispatches, [])
            release.write_json(path, original)

    def test_invalid_runtime_pin_fails_before_publication(self):
        for commit in ("", "main", "052781a", "f" * 41):
            with self.subTest(commit=commit), patch.object(Path, "read_text", return_value=commit):
                with self.assertRaisesRegex(ValueError, "invalid pinned Operator runtime commit"):
                    self.publish()
                self.assertEqual(self.registry.copies, [])
                self.assertEqual(self.github.releases, {})
                self.assertEqual(self.github.dispatches, [])

    def test_oci_inspection_uses_actual_embedded_bytes(self):
        def change_record(files, **changes):
            record = json.loads(files[COMPATIBILITY_PATH])
            files[COMPATIBILITY_PATH] = json.dumps({**record, **changes}).encode()

        for mutation in (
            lambda files: files.pop(COMPATIBILITY_PATH),
            lambda files: files.update({COMPATIBILITY_PATH: b"{"}),
            lambda files: files.update({COMPATIBILITY_PATH: b" " * ((64 << 10) + 1)}),
            lambda files: change_record(files, platform="linux/arm64"),
            lambda files: change_record(files, contract_package_version="0.0.3"),
            lambda files: change_record(files, image_digest="sha256:" + "a" * 64),
            lambda files: files.update({"opt/operator/engine/share/default-system-prompt.txt": b"changed"}),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                make_archive(self.directory, "linux/amd64", mutation)

    def test_stopped_inspection_must_match_embedded_compatibility_digest(self):
        path = self.directory / "attack-harness-linux-amd64.inspection-report.json"
        inspection = json.loads(path.read_bytes())
        inspection["compatibility_digest"] = "sha256:" + "f" * 64
        release.write_json(path, inspection)
        with self.assertRaisesRegex(ValueError, "inspection does not match"):
            self.publish()
        self.assertEqual(self.registry.copies, [])

    def test_cross_platform_inspection_does_not_satisfy_native_build_gate(self):
        path = self.directory / "attack-harness-linux-amd64.inspection-report.json"
        inspection = json.loads(path.read_bytes())
        inspection["native_platform"] = False
        release.write_json(path, inspection)
        with self.assertRaisesRegex(ValueError, "inspection does not match"):
            self.publish()
        self.assertEqual(self.registry.copies, [])

    def test_catalog_and_promotion_recheck_real_build_results(self):
        self.publish()
        self.github.jobs[1]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "did not both succeed"):
            release.catalog_context(self.github, self.registry, "v1.2.3-candidate.123.1", SOURCE, self.directory)
        with self.assertRaisesRegex(ValueError, "did not both succeed"):
            release.promote(self.github, self.registry, 42, self.directory)
        self.assertNotIn(release.IMAGE + ":latest", self.registry.images)

    def test_catalog_rejects_wrong_source_or_incomplete_platform_evidence(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        with self.assertRaisesRegex(ValueError, "source differs"):
            release.catalog_context(self.github, self.registry, tag, "f" * 40, self.directory)
        candidate = self.github.releases[tag]
        evidence = json.loads(candidate["body"].removeprefix(release.MARKER + "\n"))
        evidence["platforms"].pop()
        candidate["body"] = release.MARKER + "\n" + json.dumps(evidence)
        with self.assertRaisesRegex(ValueError, "requires both platforms"):
            release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)
        with self.assertRaisesRegex(ValueError, "requires both platforms"):
            release.promote(self.github, self.registry, 42, self.directory)

    def test_failed_publication_retry_reuses_successful_build_jobs(self):
        self.publish("123.2")
        result = release.catalog_context(self.github, self.registry, "v1.2.3-candidate.123.2", SOURCE, self.directory)
        self.assertEqual(json.loads(result["entry_json"])["tags"], ["rc"])

    def test_delayed_candidate_catalog_keeps_immutable_identity_after_new_build(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        first = release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)
        self.github.refs[BRANCH] = "c" * 40
        self.publish("124.1", "c" * 40)
        self.assertEqual(release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory), first)

    def test_catalog_rejects_altered_stage_digest_or_image(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        files = self.github.releases[tag]["files"]
        original = json.loads(files["release-index-entry.json"])
        for key, value in (("tags", ["release"]), ("digest", "sha256:" + "f" * 64),
                           ("image", release.IMAGE + ":latest")):
            changed = {**original, key: value}
            files["release-index-entry.json"] = json.dumps(changed).encode()
            with self.assertRaisesRegex(ValueError, "lifecycle stage"):
                release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)

    def test_catalog_rejects_moved_image_tag(self):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        self.registry.images[release.IMAGE + ":" + tag] = b"{}"
        with self.assertRaisesRegex(ValueError, "public image tag differs"):
            release.catalog_context(self.github, self.registry, tag, SOURCE, self.directory)

    def test_final_catalog_requires_matching_merged_pr_and_candidate_bytes(self):
        self.publish()
        release.promote(self.github, self.registry, 42, self.directory)
        self.github.pr["merged"] = False
        with self.assertRaisesRegex(ValueError, "QA sign-off"):
            release.catalog_context(self.github, self.registry, "v1.2.3", SOURCE, self.directory)
        self.github.pr["merged"] = True
        final = self.github.releases["v1.2.3"]
        evidence = json.loads(final["body"].removeprefix(release.MARKER + "\n"))
        evidence["index_digest"] = "sha256:" + "f" * 64
        final["body"] = release.MARKER + "\n" + json.dumps(evidence)
        with self.assertRaisesRegex(ValueError, "promotion changed"):
            release.catalog_context(self.github, self.registry, "v1.2.3", SOURCE, self.directory)

    @patch("urllib.request.urlopen", side_effect=AssertionError("compatibility API must not be queried"))
    def test_historical_candidate_records_do_not_require_remote_verification(self, remote):
        self.publish()
        tag = "v1.2.3-candidate.123.1"
        candidate = self.github.releases[tag]
        evidence = json.loads(candidate["body"].removeprefix(release.MARKER + "\n"))
        for platform in evidence["platforms"]:
            platform["record"] = {"image_digest": platform["image_digest"]}
        candidate["body"] = release.MARKER + "\n" + json.dumps(evidence)
        release.promote(self.github, self.registry, 42, self.directory)
        release.catalog_context(self.github, self.registry, "v1.2.3", SOURCE, self.directory)
        remote.assert_not_called()

    def test_unsafe_versions_are_rejected(self):
        for branch in ("candidate-v1.2", "candidate-v01.2.3", "candidate-v1.2.3\n", "candidate-v1.2.3;echo bad", "feature-v1.2.3", "candidate-v1.2.3-01", "candidate-v1.2.3-rc..1"):
            with self.assertRaises(ValueError):
                release.version_for(branch)


if __name__ == "__main__":
    unittest.main()
