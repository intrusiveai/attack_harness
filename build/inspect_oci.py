"""Validate one-platform OCI output and emit a non-approval build report."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

if __package__:
    from .prepare_release import COMPATIBILITY_PATH, validate_compatibility
else:
    from prepare_release import COMPATIBILITY_PATH, validate_compatibility


DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
ENTRYPOINT = ["/usr/bin/python3", "-I", "-S", "-B",
              "/opt/operator/engine/bootstrap.py"]
ALLOWED_ENV = [
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
    "LANG=C.UTF-8",
]
RELEASE_FILES = {
    COMPATIBILITY_PATH: 64 << 10,
    "opt/operator/engine/share/engine-manifest.json": 64 << 10,
    "opt/operator/engine/share/default-system-prompt.txt": 1 << 20,
    "opt/operator/engine/lib/attack_harness/skill_loader.py": 1 << 20,
    "opt/operator/engine/share/tool-catalog.json": 1 << 20,
}


class OCI:
    def __init__(self, archive):
        self.tar = tarfile.open(archive, "r:*")
        self.members = {}
        for member in self.tar:
            if member.name in self.members or not (member.isdir() or member.isreg()):
                raise ValueError("OCI archive has duplicate or unsafe members")
            self.members[member.name] = member

    def close(self):
        self.tar.close()

    def read(self, name, maximum=256 << 20):
        member = self.members.get(name)
        if member is None or not member.isreg() or member.size > maximum:
            raise ValueError(f"missing or oversized OCI member: {name}")
        stream = self.tar.extractfile(member)
        if stream is None:
            raise ValueError(f"unreadable OCI member: {name}")
        raw = stream.read(maximum + 1)
        if len(raw) != member.size:
            raise ValueError(f"short OCI member: {name}")
        return raw

    def blob(self, descriptor, maximum=256 << 20):
        match = DIGEST.fullmatch(descriptor.get("digest", ""))
        if match is None or type(descriptor.get("size")) is not int:
            raise ValueError("invalid OCI descriptor")
        raw = self.read("blobs/sha256/" + match.group(1), maximum)
        if len(raw) != descriptor["size"] or hashlib.sha256(raw).hexdigest() != match.group(1):
            raise ValueError("OCI descriptor identity mismatch")
        return raw

    def document(self, descriptor, maximum=16 << 20):
        value = json.loads(self.blob(descriptor, maximum))
        if type(value) is not dict:
            raise ValueError("OCI document is not an object")
        return value


def _file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
            size += len(block)
    return size, "sha256:" + digest.hexdigest()


def _embedded_files(oci, layers):
    """Read fixed files from the final layer view, without extracting host paths."""
    files = {}
    for layer in layers:
        with tarfile.open(fileobj=io.BytesIO(oci.blob(layer)), mode="r|*") as archive:
            seen = set()
            for member in archive:
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                parent, _, base = name.rpartition("/")
                if base.startswith(".wh."):
                    removed = parent if base == ".wh..wh..opq" else (parent + "/" + base[4:]).lstrip("/")
                    files = {key: value for key, value in files.items()
                             if key != removed and not key.startswith(removed + "/")}
                    continue
                if name not in RELEASE_FILES:
                    if any(key.startswith(name.rstrip("/") + "/") for key in RELEASE_FILES) and not member.isdir():
                        raise ValueError("embedded release parent is not a directory")
                    continue
                if name in seen or not member.isreg() or member.issparse() or member.pax_headers.get("linkpath"):
                    raise ValueError("embedded release file is not one regular file")
                seen.add(name)
                if member.size < 1 or member.size > RELEASE_FILES[name]:
                    raise ValueError("missing or oversized embedded release file")
                if name == COMPATIBILITY_PATH and (member.mode != 0o444 or member.uid != 0 or member.gid != 0):
                    raise ValueError("compatibility file is not immutable and root-owned")
                raw = archive.extractfile(member).read(RELEASE_FILES[name] + 1)
                if len(raw) != member.size:
                    raise ValueError("short embedded release file")
                files[name] = raw
    if set(files) != set(RELEASE_FILES):
        raise ValueError("image lacks required embedded release files")
    return files


def inspect(archive, platform, contract_lock):
    os_name, architecture = platform.split("/", 1)
    if os_name != "linux" or architecture not in ("amd64", "arm64"):
        raise ValueError("unsupported release platform")
    oci = OCI(archive)
    try:
        layout = json.loads(oci.read("oci-layout", 1024))
        root = json.loads(oci.read("index.json", 1 << 20))
        if layout != {"imageLayoutVersion": "1.0.0"} or \
                root.get("mediaType") != "application/vnd.oci.image.index.v1+json" or \
                len(root.get("manifests", ())) != 1:
            raise ValueError("invalid OCI layout root")
        release_index_descriptor = root["manifests"][0]
        release_index = oci.document(release_index_descriptor)
        images = [item for item in release_index.get("manifests", ())
                  if item.get("platform") == {"os":os_name,"architecture":architecture}]
        attestations = [item for item in release_index.get("manifests", ())
                        if item.get("annotations", {}).get(
                            "vnd.docker.reference.type") == "attestation-manifest"]
        if len(images) != 1 or len(attestations) != 1 or \
                attestations[0]["annotations"].get("vnd.docker.reference.digest") != images[0]["digest"]:
            raise ValueError("OCI index lacks one image and its attestations")
        image_descriptor = images[0]
        image_manifest = oci.document(image_descriptor)
        config_descriptor = image_manifest.get("config", {})
        config = oci.document(config_descriptor, 4 << 20)
        if config.get("os") != os_name or config.get("architecture") != architecture:
            raise ValueError("OCI configuration platform mismatch")
        process = config.get("config", {})
        if process.get("Labels", {}).get("org.opencontainers.image.source") != "https://github.com/intrusiveai/attack_harness":
            raise ValueError("OCI image lacks the canonical source label")
        if process.get("User") != "65532:65532" or \
                process.get("Entrypoint") != ENTRYPOINT or \
                process.get("WorkingDir") != "/run/operator/work" or \
                process.get("Env") != ALLOWED_ENV or \
                any(key in process for key in ("Cmd", "Volumes", "ExposedPorts", "Healthcheck")):
            raise ValueError("OCI process metadata is not the fixed runtime profile")
        if config.get("created") != "1970-01-01T00:00:00Z" or \
                any(item.get("created") != "1970-01-01T00:00:00Z"
                    for item in config.get("history", ())):
            raise ValueError("OCI timestamps were not normalized")
        layers = image_manifest.get("layers", ())
        diff_ids = config.get("rootfs", {}).get("diff_ids", ())
        if not layers or len(layers) != len(diff_ids):
            raise ValueError("OCI layer/config identity mismatch")
        files = _embedded_files(oci, layers)
        lock = json.loads(contract_lock.read_bytes())
        pin = {key: lock["package"][key] for key in ("package_version", "package_digest")}
        compatibility_raw = files[COMPATIBILITY_PATH]
        compatibility_record = validate_compatibility(compatibility_raw, pin, platform)
        embedded = json.loads(files["opt/operator/engine/share/engine-manifest.json"])
        if (embedded["contract"] != pin or embedded["platform"] != platform
                or embedded["runtime_profile"] != compatibility_record["runtime_profile"]
                or embedded["entrypoint"] != ENTRYPOINT or embedded["transports"] != ["fifo", "spool"]):
            raise ValueError("embedded manifest and compatibility disagree")
        for field, name in (("prompt", "share/default-system-prompt.txt"),
                            ("skill_loader", "lib/attack_harness/skill_loader.py"),
                            ("tool_catalog", "share/tool-catalog.json")):
            raw = files["opt/operator/engine/" + name]
            if embedded[field] != {"size_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}:
                raise ValueError("embedded resource digest mismatch: " + field)
        attestation = oci.document(attestations[0])
        predicates = []
        for layer in attestation.get("layers", ()):
            if layer.get("mediaType") != "application/vnd.in-toto+json":
                raise ValueError("unexpected attestation media type")
            oci.blob(layer, 32 << 20)
            predicates.append(layer.get("annotations", {}).get("in-toto.io/predicate-type"))
        if sorted(predicates) != sorted(("https://spdx.dev/Document",
                                         "https://slsa.dev/provenance/v0.2")):
            raise ValueError("OCI output lacks pinned SBOM and provenance attestations")
    finally:
        oci.close()

    size, archive_digest = _file_digest(archive)
    image_digest = config_descriptor["digest"]
    return {
        "api_version":"intrusive.ai/attack-harness-build-report/v1alpha1",
        "status":"built-not-qualified",
        "platform":platform,
        "archive":{"path":archive.name,"size_bytes":size,"digest":archive_digest},
        "oci":{
            "index_digest":release_index_descriptor["digest"],
            "manifest_digest":image_descriptor["digest"],
            "image_digest":image_digest,
            "layer_digests":[item["digest"] for item in layers],
            "attestation_manifest_digest":attestations[0]["digest"],
            "predicate_types":sorted(predicates),
        },
        "contract":lock["package"],
        "contract_source":lock["source"],
        "compatibility":{
            "path":"/" + COMPATIBILITY_PATH,
            "size_bytes":len(compatibility_raw),
            "digest":"sha256:" + hashlib.sha256(compatibility_raw).hexdigest(),
            "raw":compatibility_raw.decode("utf-8"),
            "record":compatibility_record,
        },
        "acceptance":{
            "builder_tests":"passed",
            "embedded_release_verification":"passed",
            "native_host_qualification":"not-run",
            "provider_target_integration":"not-run",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--contract-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.archive, args.platform, args.contract_lock)
    args.output.write_bytes(json.dumps(report, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
