"""Exercise Operator's stopped-image inspection against a matched candidate."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile


def _read_member(archive, members, name, maximum):
    member = members.get(name)
    if member is None or not member.isreg() or member.size < 1 or member.size > maximum:
        raise ValueError(f"missing or invalid Docker archive member: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"unreadable Docker archive member: {name}")
    body = stream.read(maximum + 1)
    if len(body) != member.size:
        raise ValueError(f"short Docker archive member: {name}")
    expected = Path(name).name
    if len(expected) == 64 and hashlib.sha256(body).hexdigest() != expected:
        raise ValueError(f"Docker archive blob digest mismatch: {name}")
    return body


def _candidate(archive_path, build_report):
    with tarfile.open(archive_path, "r:*") as archive:
        members = {}
        for member in archive:
            if member.name in members or not (member.isdir() or member.isreg()):
                raise ValueError("Docker archive has duplicate or unsafe members")
            members[member.name] = member
        index = json.loads(_read_member(archive, members, "index.json", 1 << 20))
        if index.get("schemaVersion") != 2 or len(index.get("manifests", ())) != 1:
            raise ValueError("Docker archive must contain one image manifest")
        descriptor = index["manifests"][0]
        manifest_digest = descriptor.get("digest", "")
        if not manifest_digest.startswith("sha256:"):
            raise ValueError("Docker archive manifest has no digest")
        manifest_name = "blobs/sha256/" + manifest_digest.removeprefix("sha256:")
        manifest = json.loads(_read_member(archive, members, manifest_name, 1 << 20))
        config_digest = manifest.get("config", {}).get("digest")
        layers = [item.get("digest") for item in manifest.get("layers", ())]
        expected = build_report["oci"]
        if config_digest != expected["image_digest"] or layers != expected["layer_digests"]:
            raise ValueError("inspection image content differs from attested OCI image")
        _read_member(archive, members,
                     "blobs/sha256/" + config_digest.removeprefix("sha256:"), 4 << 20)
        for digest in set(layers):
            _read_member(archive, members,
                         "blobs/sha256/" + digest.removeprefix("sha256:"), 256 << 20)
        return manifest_digest, config_digest, layers


def _host_platform():
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = {"x86_64": "amd64", "amd64": "amd64",
                    "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system not in ("linux", "darwin") or architecture is None:
        raise ValueError("unsupported Operator host platform")
    return f"{system}/{architecture}"


def inspect(args):
    docker = shutil.which("docker")
    go = shutil.which("go")
    if docker is None or go is None:
        raise ValueError("Docker and Go are required for stopped-image inspection")
    report = json.loads(args.build_report.read_bytes())
    if report.get("platform") != args.platform or report.get("status") != "built-not-qualified":
        raise ValueError("build report does not identify the requested candidate")
    selector, config_digest, layers = _candidate(args.archive, report)
    subprocess.run([docker, "image", "load", "--platform", args.platform,
                    "--input", str(args.archive)], check=True)
    endpoint = json.loads(subprocess.run(
        [docker, "context", "inspect", "--format",
         "{{json .Endpoints.docker.Host}}"], check=True, capture_output=True,
        text=True).stdout)
    operator_root = args.operator_root.resolve()
    backing = (args.source_root / "build/operator_stopped_image_test.go").resolve()
    target = operator_root / "internal/dockercontrol/candidate_stopped_image_test.go"
    with tempfile.TemporaryDirectory(prefix="attack-harness-operator-overlay-") as directory:
        overlay = Path(directory) / "overlay.json"
        overlay.write_text(json.dumps({"Replace": {str(target): str(backing)}}),
                           encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "ATTACK_HARNESS_DOCKER": docker,
            "ATTACK_HARNESS_DOCKER_ENDPOINT": endpoint,
            "ATTACK_HARNESS_IMAGE_SELECTOR": selector,
            "ATTACK_HARNESS_HOST_PLATFORM": _host_platform(),
        })
        subprocess.run([go, "test", "-overlay", str(overlay),
                        "./internal/dockercontrol", "-run",
                        "^TestCandidateStoppedImageInspection$", "-count=1", "-v"],
                       cwd=operator_root, env=environment, check=True)
    operator_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=operator_root, check=True,
        capture_output=True, text=True).stdout.strip()
    result = {
        "api_version": "intrusive.ai/stopped-image-inspection/v1alpha1",
        "status": "passed",
        "platform": args.platform,
        "host_platform": _host_platform(),
        "operator_commit": operator_commit,
        "docker_image_id": selector,
        "oci_config_digest": config_digest,
        "layer_digests": layers,
        "operator_stopped_image_inspection": "passed",
        "inspection_container_cleanup": "passed",
    }
    args.output.write_bytes(json.dumps(result, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    print(json.dumps(result, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--operator-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", type=Path, required=True)
    inspect(parser.parse_args())


if __name__ == "__main__":
    main()
