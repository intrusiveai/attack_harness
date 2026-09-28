"""Build and verify the deterministic application release tree.

This script runs only in the release builder.  It treats the published contract
package as data, verifies it against the repository lock, and copies only fixed
application code plus manifest-declared contract bytes into the runtime tree.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat


CODECS = (
    "anthropic-messages-text-tools-v1",
    "bedrock-converse-text-tools-v1",
    "gemini-text-tools-v1",
    "openai-chat-text-tools-v1",
    "openai-responses-text-tools-v1",
)
ENTRYPOINT = ["/usr/bin/python3", "-I", "-S", "-B",
              "/opt/operator/engine/bootstrap.py"]
PLATFORMS = ("linux/amd64", "linux/arm64")


def _read_json(path, maximum):
    raw = path.read_bytes()
    if not raw or len(raw) > maximum:
        raise ValueError(f"invalid bounded JSON: {path}")
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError(f"invalid JSON object: {path}")
    return value


def _write_json(path, value):
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8"))


def _digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _descriptor(path):
    raw = path.read_bytes()
    return {"size_bytes": len(raw), "digest": _digest(raw)}


def _copy_file(source, destination):
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"release input is not one regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1 << 20)
    os.chmod(destination, 0o644)


def _locked_protocol(contract_root, lock):
    from attack_harness.contracts import load_contract

    expected = {key: lock["package"][key]
                for key in ("package_version", "package_digest")}
    protocol = load_contract(contract_root, expected)
    if protocol.registry_digests() != {
        "catalog_digest": lock["package"]["catalog_digest"],
        "operations_digest": lock["package"]["operations_digest"],
    }:
        raise ValueError("contract registry does not match contract lock")
    manifest = _read_json(contract_root / "package.json", 8 << 20)
    if len(manifest["files"]) != lock["package"]["file_count"]:
        raise ValueError("contract file count does not match contract lock")
    if sum(item["size_bytes"] for item in manifest["files"]) != lock["package"]["content_bytes"]:
        raise ValueError("contract content size does not match contract lock")
    return protocol, manifest


def _tool_catalog(protocol):
    operations = sorted(item["name"] for item in protocol.operations())
    return {
        "api_version": "operator.dev/model-tool-catalog/v1alpha1",
        "codecs": {codec: json.loads(protocol.model_tools(codec, operations))
                   for codec in CODECS},
    }


def check_contract(contract_root, lock_path):
    lock = _read_json(lock_path, 64 << 10)
    if set(lock) != {"api_version", "source", "package", "publisher"} or \
            lock["api_version"] != "operator.dev/harness-contract-lock/v1alpha1":
        raise ValueError("invalid contract lock")
    return _locked_protocol(contract_root, lock)


def prepare(source_root, contract_root, output_root, platform, prompt_path,
            lock_path):
    if platform not in PLATFORMS:
        raise ValueError("unsupported release platform")
    protocol, manifest = check_contract(contract_root, lock_path)
    engine = output_root / "opt/operator/engine"
    library = engine / "lib"
    if not library.is_dir():
        raise ValueError("dependency installer must create the release library first")
    for name in ("attack_harness", "operator_contracts"):
        if (library / name).exists():
            raise ValueError(f"release package already exists: {name}")

    _copy_file(source_root / "bootstrap.py", engine / "bootstrap.py")
    for source in sorted((source_root / "src/attack_harness").iterdir()):
        if source.is_file() and source.suffix == ".py":
            _copy_file(source, library / "attack_harness" / source.name)

    contract_python = contract_root / "source/contracts/python/operator_contracts"
    copied = 0
    for source in sorted(contract_python.iterdir()):
        if source.is_file() and source.suffix == ".py":
            _copy_file(source, library / "operator_contracts" / source.name)
            copied += 1
    if copied < 10 or not (library / "operator_contracts/__init__.py").is_file():
        raise ValueError("published contract package lacks its Python runtime")

    schemas = engine / "share/schemas"
    for item in manifest["files"]:
        _copy_file(contract_root / item["path"], schemas / item["path"])
    _copy_file(contract_root / "package.json", schemas / "package.json")

    share = engine / "share"
    _copy_file(prompt_path, share / "default-system-prompt.txt")
    _write_json(share / "tool-catalog.json", _tool_catalog(protocol))
    loader = library / "attack_harness/skill_loader.py"
    runtime_config = {
        "contract": {key: _read_json(contract_root / "package.json", 8 << 20)[
            "package_version"] if key == "package_version" else
            _read_json(lock_path, 64 << 10)["package"]["package_digest"]
                     for key in ("package_version", "package_digest")},
        "skill_loader_digest": _descriptor(loader)["digest"],
    }
    _write_json(share / "runtime-config.json", runtime_config)
    engine_manifest = {
        "api_version": "operator.dev/engine-manifest/v1alpha1",
        "contract": {
            "version": runtime_config["contract"]["package_version"],
            "digest": runtime_config["contract"]["package_digest"],
        },
        "runtime_profile": "operator-container/v1",
        "platform": platform,
        "entrypoint": ENTRYPOINT,
        "transports": ["fifo", "spool"],
        "prompt": _descriptor(share / "default-system-prompt.txt"),
        "skill_loader": _descriptor(loader),
        "tool_catalog": _descriptor(share / "tool-catalog.json"),
    }
    _write_json(share / "engine-manifest.json", engine_manifest)
    licenses = engine / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    (licenses / "README.txt").write_text(
        "Python distribution license texts are retained in lib/*.dist-info/licenses.\n"
        "Shared-contract source licenses and notices are retained in share/schemas.\n",
        encoding="utf-8")
    for relative in ("run/operator/input", "run/operator/customer-skills",
                     "run/operator/manifests", "run/operator/ipc",
                     "run/operator/spool", "run/operator/work"):
        (output_root / relative).mkdir(parents=True, exist_ok=True)
    verify(output_root, contract_root, lock_path, require_native=False)


def verify(output_root, contract_root, lock_path, *, require_native=True):
    protocol, _ = check_contract(contract_root, lock_path)
    engine = output_root / "opt/operator/engine"
    share, library = engine / "share", engine / "lib"
    manifest = _read_json(share / "engine-manifest.json", 64 << 10)
    if set(manifest) != {"api_version", "contract", "runtime_profile", "platform",
                        "entrypoint", "transports", "prompt", "skill_loader",
                        "tool_catalog"}:
        raise ValueError("embedded manifest is not closed")
    if manifest["api_version"] != "operator.dev/engine-manifest/v1alpha1" or \
            manifest["runtime_profile"] != "operator-container/v1" or \
            manifest["platform"] not in PLATFORMS or \
            manifest["entrypoint"] != ENTRYPOINT or \
            manifest["transports"] != ["fifo", "spool"]:
        raise ValueError("embedded manifest has incompatible fixed fields")
    paths = {
        "prompt": share / "default-system-prompt.txt",
        "skill_loader": library / "attack_harness/skill_loader.py",
        "tool_catalog": share / "tool-catalog.json",
    }
    for key, path in paths.items():
        if manifest[key] != _descriptor(path):
            raise ValueError(f"embedded {key} identity mismatch")
    if _read_json(paths["tool_catalog"], 1 << 20) != _tool_catalog(protocol):
        raise ValueError("embedded tool catalog drift")
    runtime = _read_json(share / "runtime-config.json", 64 << 10)
    pin = protocol.package_identity()
    if runtime != {"contract": pin,
                   "skill_loader_digest": manifest["skill_loader"]["digest"]} or \
            manifest["contract"] != {"version": pin["package_version"],
                                      "digest": pin["package_digest"]}:
        raise ValueError("runtime configuration identity mismatch")
    if require_native and not (library / "_confinement.abi3.so").is_file():
        raise ValueError("native confinement module is absent")
    for path in output_root.rglob("*"):
        if path.is_symlink() or path.name == "__pycache__" or path.suffix == ".pyc":
            raise ValueError(f"undeclared runtime file type: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--contract-package", type=Path, required=True)
    parser.add_argument("--contract-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--platform", choices=PLATFORMS)
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--check-contract", action="store_true")
    args = parser.parse_args()
    if args.check_contract:
        check_contract(args.contract_package, args.contract_lock)
    elif args.verify:
        if args.output is None:
            parser.error("--verify requires --output")
        verify(args.output, args.contract_package, args.contract_lock)
    else:
        if None in (args.source_root, args.output, args.platform, args.prompt):
            parser.error("preparation requires source, output, platform and prompt")
        prepare(args.source_root, args.contract_package, args.output, args.platform,
                args.prompt, args.contract_lock)


if __name__ == "__main__":
    main()
