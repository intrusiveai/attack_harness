"""Publish inspected OCI bytes and promote a merged candidate without rebuilding."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from build.inspect_oci import inspect


REPOSITORY = "intrusiveai/attack_harness"
IMAGE = "ghcr.io/" + REPOSITORY
PLATFORMS = ("linux/amd64", "linux/arm64")
MARKER = "<!-- attack-harness-candidate/v1 -->"
QA_PENDING = ["native-runtime", "live-provider-target-integration", "full-host-matrix"]
RECORD_FIELDS = ("api_version", "image_digest", "minimum_operator_version",
                 "contract_package_version", "contract_package_digest", "runtime_profile", "platform")


def version_for(branch):
    version = branch.removeprefix("candidate-")
    if not branch.startswith("candidate-") or not re.fullmatch(
            r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("expected candidate-vMAJOR.MINOR.PATCH (optional prerelease suffix)")
    if len(version) > 64:
        raise ValueError("candidate version is too long for registry tags")
    if "-" in version:
        for identifier in version.split("-", 1)[1].split("."):
            if not identifier or (identifier.isdigit() and len(identifier) > 1 and identifier[0] == "0"):
                raise ValueError("invalid SemVer prerelease identifier")
    return version


def context(event, name, ref, sha, repository):
    result = dict(mode="verify", version="", branch="", source=sha, pr="")
    if name == "pull_request" and event["action"] == "closed":
        result["mode"] = "ignore"
        pr = event["pull_request"]
        if (pr["merged"] and pr["base"]["ref"] == "main"
                and pr["head"]["ref"].startswith("candidate-v")
                and pr["head"]["repo"]["full_name"] == repository == REPOSITORY):
            result.update(mode="promote", version=version_for(pr["head"]["ref"]),
                          branch=pr["head"]["ref"], source=pr["head"]["sha"], pr=str(pr["number"]))
    elif name in ("push", "workflow_dispatch") and ref.startswith("refs/heads/candidate-v"):
        if event.get("deleted"):
            result["mode"] = "ignore"
        elif repository == REPOSITORY:
            branch = ref.removeprefix("refs/heads/")
            result.update(mode="publish", version=version_for(branch), branch=branch)
    return result


def run(*command):
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


class GitHub:
    def api(self, path, method="GET", data=None, missing=False):
        command = ["gh", "api", f"repos/{REPOSITORY}/{path}", "--method", method]
        if data is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True)
        if result.returncode:
            if missing and "(HTTP 404)" in result.stderr:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed: {result.stderr}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def release(self, tag):
        return self.api("releases/tags/" + tag, missing=True)

    def create_release(self, tag, source, metadata, files, prerelease):
        body = MARKER + "\n" + json.dumps(metadata)
        ref = self.api("git/ref/tags/" + tag, missing=True)
        if ref:
            if ref["object"]["sha"] != source:
                raise ValueError("existing release tag points to different source")
        else:
            self.api("git/refs", "POST", {"ref": "refs/tags/" + tag, "sha": source})
        release = self.release(tag)
        if release and release.get("body") != body:
            raise ValueError("refusing to replace different release evidence")
        if not release:
            release = self.api("releases", "POST", {
                "tag_name": tag, "name": "Attack Harness " + tag, "body": body,
                "draft": True, "prerelease": prerelease, "make_latest": "false"})
        if release["draft"]:
            run("gh", "release", "upload", tag, *map(str, files), "--clobber", "--repo", REPOSITORY)
            assets = self.api(f"releases/{release['id']}/assets?per_page=100")
            actual = {a["name"]: a.get("digest") for a in assets if a["state"] == "uploaded"}
            if actual != {f.name: digest(f.read_bytes()) for f in files}:
                raise ValueError("uploaded evidence does not match local bytes")
            release = self.api(f"releases/{release['id']}", "PATCH", {
                "draft": False, "prerelease": prerelease, "make_latest": "false"})
        return release


class Registry:
    def raw(self, reference):
        return run("skopeo", "inspect", "--raw", "docker://" + reference)

    def copy(self, source, tag):
        run("skopeo", "copy", "--all", "--preserve-digests", source, "docker://" + IMAGE + ":" + tag)

    def combine(self, references, tag, source, version, evidence_tag):
        run("docker", "buildx", "imagetools", "create", "--tag", IMAGE + ":" + tag,
            "--annotation", "index:org.opencontainers.image.revision=" + source,
            "--annotation", "index:org.opencontainers.image.version=" + version,
            "--annotation", "index:ai.intrusive.evidence-tag=" + evidence_tag, *references)
        return self.raw(IMAGE + ":" + tag)


def check_reports(directory):
    """Re-inspect the archives that will be uploaded; bind the other gates to them."""
    reports, files = [], []
    for platform in PLATFORMS:
        prefix = directory / ("attack-harness-" + platform.replace("/", "-"))
        archive = Path(str(prefix) + ".oci.tar")
        paths = [Path(str(prefix) + suffix) for suffix in
                 (".build-report.json", ".inspection-report.json", ".rebuild-comparison.json")]
        report, inspection, rebuild = [json.loads(p.read_bytes()) for p in paths]
        if report != inspect(archive, platform, Path("build/contract-lock.json")):
            raise ValueError("archive differs from its build report")
        if (inspection["status"] != "passed" or inspection["platform"] != platform
                or inspection["oci_config_digest"] != report["oci"]["image_digest"]
                or inspection["layer_digests"] != report["oci"]["layer_digests"]
                or inspection["operator_stopped_image_inspection"] != "passed"
                or inspection["inspection_container_cleanup"] != "passed"):
            raise ValueError("stopped-image inspection does not match the published bytes")
        if (rebuild["platform"] != platform or rebuild["runtime_identity"] != "identical"
                or rebuild["runtime_comparisons"] != {
                    "image_digest": True, "manifest_digest": True, "layer_digests": True}):
            raise ValueError("runtime reproducibility gate failed")
        if inspection["operator_commit"] != json.loads(Path("build/contract-lock.json").read_bytes())["source"]["commit"]:
            raise ValueError("inspection used an unpinned Operator")
        record = dict(report["compatibility_candidate"])
        record["minimum_operator_version"] = inspection["operator_version"]
        report["approval_record"] = {field: record[field] for field in RECORD_FIELDS}
        reports.append(report)
        files.extend(paths)
    if reports[0]["contract"] != reports[1]["contract"]:
        raise ValueError("platform contracts differ")
    return reports, files


def catalog_entry(version, image_digest, promoted=False):
    return {"version": version, "latest": True, "image": IMAGE + ":" + version,
            "tags": ["release"] if promoted else ["rc"], "digest": image_digest}


def publish(github, registry, directory, branch, source, run_id, gate_status):
    version = version_for(branch)
    if not re.fullmatch(r"[0-9a-f]{40}", source) or not re.fullmatch(r"[0-9]+\.[0-9]+", run_id):
        raise ValueError("invalid source or run identity")
    qualification_status = "passed" if gate_status == "success" else "failed"
    if qualification_status != "passed":
        raise ValueError("both native build jobs must succeed before candidate approval")
    if github.api("git/ref/tags/" + version, missing=True):
        raise ValueError("version has been frozen for promotion; use a new candidate version")
    reports, files = check_reports(directory)
    tag = version + "-candidate." + run_id
    references = []
    for report in reports:
        platform_tag = tag + "-" + report["platform"].replace("/", "-")
        archive = directory / report["archive"]["path"]
        registry.copy("oci-archive:" + str(archive), platform_tag)
        if digest(registry.raw(IMAGE + ":" + platform_tag)) != report["oci"]["index_digest"]:
            raise ValueError("registry changed the inspected platform index")
        references.append(IMAGE + "@" + report["oci"]["index_digest"])
    raw = registry.combine(references, tag, source, version, tag)
    index = json.loads(raw)
    expected = {r["oci"][key] for r in reports for key in ("manifest_digest", "attestation_manifest_digest")}
    if {m["digest"] for m in index["manifests"]} != expected or len(index["manifests"]) != 4:
        raise ValueError("combined index did not preserve both platforms and attestations")
    image_digest = digest(raw)
    evidence = {"source_commit": source, "version": version, "index_digest": image_digest,
                "evidence_tag": tag, "qualification_status": qualification_status,
                "qualification_policy": "candidate-qa/v1", "qa_pending": QA_PENDING,
                "build_run_id": run_id.split(".")[0], "build_run_attempt": run_id.split(".")[1],
                "platforms": [{"platform": r["platform"], **r["oci"],
                               "record": r["approval_record"]} for r in reports]}
    handoff, record = directory / "release-index-entry.json", directory / "candidate.json"
    write_json(handoff, catalog_entry(version, image_digest))
    write_json(record, evidence)
    github.create_release(tag, source, evidence, files + [handoff, record], prerelease=True)
    # workflow_dispatch runs even with GITHUB_TOKEN; tag-push events do not.
    github.api("actions/workflows/approve-candidate.yml/dispatches", "POST", {"ref": tag})
    # Keep every run's immutable evidence; only the current branch head moves the rolling tag.
    branch_ref = github.api("git/ref/heads/" + branch, missing=True)
    if branch_ref is None:
        raise ValueError("candidate branch was deleted before publication; restore it and rerun")
    if branch_ref["object"]["sha"] != source:
        return "superseded; immutable candidate published without moving version tag"
    registry.copy("docker://" + IMAGE + "@" + image_digest, version)
    if digest(registry.raw(IMAGE + ":" + version)) != image_digest:
        raise ValueError("version tag differs from the published candidate")
    return "candidate published; approval workflow dispatched at " + tag


def promote(github, registry, number, directory):
    pr = github.api("pulls/" + str(number))
    if (not pr["merged"] or pr["base"]["ref"] != "main"
            or pr["head"]["repo"]["full_name"] != REPOSITORY):
        raise ValueError("promotion requires a merged same-repository candidate PR into main")
    version, source = version_for(pr["head"]["ref"]), pr["head"]["sha"]
    raw = registry.raw(IMAGE + ":" + version)
    annotations = json.loads(raw).get("annotations", {})
    if annotations.get("org.opencontainers.image.revision") != source or annotations.get("org.opencontainers.image.version") != version:
        raise ValueError("version tag was not built from the merged candidate head; finish its build and rerun")
    tag = annotations.get("ai.intrusive.evidence-tag", "")
    if not re.fullmatch(re.escape(version) + r"-candidate\.[0-9]+\.[0-9]+", tag):
        raise ValueError("candidate has no valid evidence tag")
    release = github.release(tag)
    if not release or release["draft"] or not release["body"].startswith(MARKER + "\n"):
        raise ValueError("candidate evidence is missing or incomplete")
    evidence = json.loads(release["body"].removeprefix(MARKER + "\n"))
    image_digest = digest(raw)
    if (evidence["source_commit"] != source or evidence["index_digest"] != image_digest
            or evidence["version"] != version or evidence["evidence_tag"] != tag
            or github.api("git/ref/tags/" + tag)["object"]["sha"] != source):
        raise ValueError("candidate evidence identity mismatch")
    source_tree = github.api("git/commits/" + source)["tree"]["sha"]
    merge_tree = github.api("git/commits/" + pr["merge_commit_sha"])["tree"]["sha"]
    if source_tree != merge_tree:
        raise ValueError("merge changed the candidate tree; merge main into the candidate and rebuild first")
    # An old promotion rerun must not roll latest back after a subsequent main merge.
    if github.api("git/ref/heads/main")["object"]["sha"] != pr["merge_commit_sha"]:
        raise ValueError("main has advanced; refusing stale promotion")
    verify_approvals(evidence)
    directory.mkdir(parents=True, exist_ok=True)
    handoff, record = directory / "release-index-entry.json", directory / "candidate.json"
    write_json(handoff, catalog_entry(version, image_digest, promoted=True))
    write_json(record, evidence)
    # The stable tag freezes this version before latest changes, including across retries.
    github.create_release(version, source, evidence, [handoff, record], prerelease=False)
    registry.copy("docker://" + IMAGE + "@" + image_digest, "latest")
    if digest(registry.raw(IMAGE + ":latest")) != image_digest:
        raise ValueError("latest does not resolve to the candidate index")
    return "approved candidate promoted to latest without rebuilding"


def verify_approvals(evidence):
    if len(evidence["platforms"]) != 2 or {p["platform"] for p in evidence["platforms"]} != set(PLATFORMS):
        raise ValueError("approval requires both platforms")
    for platform in evidence["platforms"]:
        record = platform["record"]
        if (list(record) != list(RECORD_FIELDS) or record["platform"] != platform["platform"]
                or record["image_digest"] != platform["image_digest"]
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["image_digest"])):
            raise ValueError("approval record differs from platform identity")
        canonical = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        url = "https://releases.intrusive.ai/sha256/" + record["image_digest"].removeprefix("sha256:")
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.read(65537) != canonical:
                raise ValueError("published approval differs from the candidate record")


def approval_context(github, tag, source, directory):
    """Verify the completed build jobs before handing records to the service."""
    release = github.release(tag)
    if not release or release["draft"] or not release["body"].startswith(MARKER + "\n"):
        raise ValueError("approval requires public candidate evidence")
    evidence = json.loads(release["body"].removeprefix(MARKER + "\n"))
    version = evidence["version"]
    version_for("candidate-" + version)
    run_id, attempt = evidence["build_run_id"], evidence["build_run_attempt"]
    if (not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9]+", attempt)
            or tag != version + "-candidate." + run_id + "." + attempt
            or evidence["source_commit"] != source or evidence["evidence_tag"] != tag
            or evidence["qualification_policy"] != "candidate-qa/v1"
            or evidence["qualification_status"] != "passed"):
        raise ValueError("invalid candidate qualification identity")
    build_run = github.api("actions/runs/" + run_id)
    if (build_run["head_sha"] != source or build_run["head_branch"] != "candidate-" + version
            or build_run["path"] != ".github/workflows/verify.yml"
            or build_run["event"] not in ("push", "workflow_dispatch")):
        raise ValueError("evidence does not identify a candidate build workflow")
    # Rerun-failed-jobs retains successful matrix jobs from earlier attempts.
    # Use the newest execution of each build job at or before this publication.
    gate_jobs = {}
    for number in range(int(attempt), 0, -1):
        jobs = github.api(f"actions/runs/{run_id}/attempts/{number}/jobs?per_page=100")["jobs"]
        for job in jobs:
            if job["name"].startswith("native-platform ("):
                gate_jobs.setdefault(job["name"], job)
        if len(gate_jobs) >= 2:
            break
    gates = list(gate_jobs.values())
    if len(gates) != 2 or any(job["conclusion"] != "success" for job in gates):
        raise ValueError("candidate build gates did not both succeed")
    if len(evidence["platforms"]) != 2 or {p["platform"] for p in evidence["platforms"]} != set(PLATFORMS):
        raise ValueError("candidate evidence requires both platforms")
    directory.mkdir(parents=True, exist_ok=True)
    matrix = []
    for platform in evidence["platforms"]:
        record = platform["record"]
        if (list(record) != list(RECORD_FIELDS) or record["platform"] != platform["platform"]
                or record["image_digest"] != platform["image_digest"]):
            raise ValueError("approval record does not match platform evidence")
        canonical = json.dumps(record, separators=(",", ":"))
        write_json(directory / (platform["platform"].replace("/", "-") + ".json"), record)
        matrix.append({"platform": platform["platform"], "record_json": canonical,
                       "image_config_digest": platform["image_digest"],
                       "platform_manifest_digest": platform["manifest_digest"]})
    return {"matrix": json.dumps({"include": matrix}, separators=(",", ":")),
            "qualification_status": "passed" if all(job["conclusion"] == "success" for job in gates) else "failed",
            "evidence_url": release["html_url"], "index_digest": evidence["index_digest"],
            "image_reference": IMAGE + ":" + tag}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("context", "publish", "promote", "approval-context"))
    parser.add_argument("--directory", type=Path, default=Path("dist/publication"))
    parser.add_argument("--branch")
    parser.add_argument("--source")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--gate-status")
    args = parser.parse_args()
    if args.operation == "context":
        result = context(json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
                         os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"],
                         os.environ["GITHUB_SHA"], os.environ["GITHUB_REPOSITORY"])
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key, value in result.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("invalid workflow output")
                output.write(f"{key}={value}\n")
        return
    if os.environ["GITHUB_REPOSITORY"] != REPOSITORY:
        raise ValueError("publication is restricted to the canonical repository")
    if args.operation == "approval-context":
        if not os.environ["GITHUB_REF"].startswith("refs/tags/v"):
            raise ValueError("approval must run from a candidate tag")
        result = approval_context(GitHub(), os.environ["GITHUB_REF_NAME"],
                                  os.environ["GITHUB_SHA"], args.directory)
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key, value in result.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("invalid workflow output")
                output.write(f"{key}={value}\n")
        return
    if args.operation == "publish":
        if not args.branch or not args.source:
            parser.error("publish requires --branch and --source")
        result = publish(GitHub(), Registry(), args.directory, args.branch, args.source,
                         os.environ["GITHUB_RUN_ID"] + "." + os.environ["GITHUB_RUN_ATTEMPT"], args.gate_status)
    else:
        if not args.pr or args.pr < 1:
            parser.error("promote requires --pr")
        result = promote(GitHub(), Registry(), args.pr, args.directory)
    print(result)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(result + "\n")


if __name__ == "__main__":
    main()
