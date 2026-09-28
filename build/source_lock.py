"""Create or verify the content identity of every runtime build input."""

import argparse
import hashlib
import json
from pathlib import Path


FIXED = (
    ".dockerignore", "Dockerfile", "bootstrap.py", "requirements-runtime.lock",
    "assets/default-system-prompt.txt", "build/compile_native.py",
    "build/contract-lock.json", "build/prepare_release.py",
    "native/confinement.c", "native/live_allowlist.h",
)


def inventory(root):
    names = list(FIXED)
    names.extend(path.relative_to(root).as_posix()
                 for directory in ("src/attack_harness", "tests")
                 for path in sorted((root / directory).glob("*.py")))
    if names != sorted(set(names)):
        names = sorted(set(names))
    entries = []
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing regular build input: {name}")
        raw = path.read_bytes()
        entries.append({"path":name,"size_bytes":len(raw),
                        "digest":"sha256:"+hashlib.sha256(raw).hexdigest()})
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "api_version":"intrusive.ai/attack-harness-source-lock/v1alpha1",
        "scope":"runtime-build-inputs",
        "file_count":len(entries),
        "content_digest":"sha256:"+hashlib.sha256(canonical).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    actual = inventory(args.root.resolve())
    encoded = json.dumps(actual, indent=2, sort_keys=True).encode() + b"\n"
    if args.write:
        args.lock.write_bytes(encoded)
    elif args.lock.read_bytes() != encoded:
        raise SystemExit("runtime source lock drift")
    print(actual["content_digest"])


if __name__ == "__main__":
    main()
