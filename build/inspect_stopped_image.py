"""Exercise Operator's stopped-image inspection against a matched candidate."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
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


def _local_image_id(docker, platform, manifest_digest, config_digest):
    # Classic Docker exposes the config ID; containerd-backed Docker can expose
    # the single-image manifest ID. Preserve the daemon's independently resolved
    # identity, while checking the archive's config/layers separately above.
    for selector in (config_digest, manifest_digest):
        result = subprocess.run(
            [docker, "image", "inspect", "--platform", platform, "--format",
             "{{.Id}}", "--", selector], capture_output=True, text=True)
        if result.returncode == 0:
            image_id = result.stdout.strip()
            if image_id not in (config_digest, manifest_digest):
                raise ValueError("Docker resolved an unexpected image identity")
            return image_id
    raise ValueError("Docker cannot resolve the loaded inspection image")


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
    selector = _local_image_id(docker, args.platform, selector, config_digest)
    endpoint = json.loads(subprocess.run(
        [docker, "context", "inspect", "--format",
         "{{json .Endpoints.docker.Host}}"], check=True, capture_output=True,
        text=True).stdout)
    operator_root = args.operator_root.resolve()
    host_platform = _host_platform()
    native_platform = host_platform.split("/")[1] == args.platform.split("/")[1]
    if not native_platform and not args.allow_cross_platform_inspection:
        raise ValueError("non-native stopped inspection requires --allow-cross-platform-inspection")
    inspection_host = host_platform.split("/")[0] + "/" + args.platform.split("/")[1]
    backing = (args.source_root / "build/operator_stopped_image_test.go").resolve()
    target = operator_root / "internal/dockercontrol/candidate_stopped_image_test.go"
    with tempfile.TemporaryDirectory(prefix="attack-harness-operator-overlay-") as directory:
        overlay = Path(directory) / "overlay.json"
        overlay.write_text(json.dumps({"Replace": {str(target): str(backing)}}),
                           encoding="utf-8")
        expected = Path(directory) / "compatibility.json"
        raw = report["compatibility"]["raw"].encode("utf-8")
        if "sha256:" + hashlib.sha256(raw).hexdigest() != report["compatibility"]["digest"]:
            raise ValueError("build report compatibility bytes differ from their digest")
        expected.write_bytes(raw)
        environment = os.environ.copy()
        environment.update({
            "ATTACK_HARNESS_DOCKER": docker,
            "ATTACK_HARNESS_DOCKER_ENDPOINT": endpoint,
            "ATTACK_HARNESS_IMAGE_SELECTOR": selector,
            "ATTACK_HARNESS_HOST_PLATFORM": inspection_host,
            "ATTACK_HARNESS_EXPECTED_COMPATIBILITY": str(expected),
            "ATTACK_HARNESS_CONTRACT_ROOT": str((args.source_root / "build/context/contracts").resolve()),
            "ATTACK_HARNESS_CONTRACT_VERSION": report["contract"]["package_version"],
            "ATTACK_HARNESS_CONTRACT_DIGEST": report["contract"]["package_digest"],
        })
        subprocess.run([go, "test", "-overlay", str(overlay),
                        "./internal/dockercontrol", "-run",
                        "^TestCandidateStoppedImageInspection$", "-count=1", "-v"],
                       cwd=operator_root, env=environment, check=True)
    operator_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=operator_root, check=True,
        capture_output=True, text=True).stdout.strip()
    version_match = re.search(r'^var operatorVersion = "([^"]+)"$',
                              (operator_root / "cmd/operatorctl/worker.go").read_text(), re.MULTILINE)
    if version_match is None or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version_match[1]):
        raise ValueError("pinned Operator source must identify a stable version")
    result = {
        "api_version": "intrusive.ai/stopped-image-inspection/v1alpha1",
        "status": "passed",
        "platform": args.platform,
        "host_platform": host_platform,
        "inspection_host_platform": inspection_host,
        "native_platform": native_platform,
        "operator_commit": operator_commit,
        "operator_version": version_match[1],
        "docker_image_id": selector,
        "oci_config_digest": config_digest,
        "layer_digests": layers,
        "compatibility_digest": report["compatibility"]["digest"],
        "operator_local_compatibility": "passed",
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
    parser.add_argument("--allow-cross-platform-inspection", action="store_true",
                        help="inspect foreign-architecture files without claiming native runtime qualification")
    inspect(parser.parse_args())


if __name__ == "__main__":
    main()
