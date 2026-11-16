"""Offline contract loading from a release-selected, independently pinned tree."""

from operator_contracts import Protocol, ContractError
from operator_contracts.canonical import raw_digest
from operator_contracts.package import PACKAGE_MANIFEST_LIMIT, PACKAGE_FILE_LIMIT
from operator_contracts.startup import require, inventory_paths

from .files import Directory


def load_contract(directory, expected, *, tick=lambda: None):
    """Only release-owned configuration supplies ``directory`` and ``expected``.

    Approve the exact interface bytes, then verify the separate distribution inventory.
    All schemas are data, loaded offline; no package file becomes Python code.
    """
    require(type(expected) is dict and set(expected) == {"package_version", "package_digest"})
    with Directory(directory, readonly=False, tick=tick) as root:
        raw = root.read("package.json", PACKAGE_MANIFEST_LIMIT)
        document = root.read("asyncapi.json", PACKAGE_FILE_LIMIT)
        bootstrap = Protocol.from_interface(document, expected)
        m = bootstrap.validate_package_manifest(raw)
        entries = m.get("files")
        require(type(entries) is list and len(entries) <= 4096)
        for entry in entries:
            require(type(entry) is dict and set(entry) == {"path", "size_bytes", "digest"})
            require(type(entry["path"]) is str and type(entry["digest"]) is str)
            require(type(entry["size_bytes"]) is int and 0 <= entry["size_bytes"] <= PACKAGE_FILE_LIMIT)
            require(entry["path"].split("/", 1)[0] != "package.json")
        inventory_paths(entries)
        inventory = sorted(entries + [{"path": "package.json", "size_bytes": len(raw), "digest": raw_digest(raw)}], key=lambda e:e["path"])
        content = root.inventory(inventory, maximum_files=4097, maximum_bytes=(128 << 20) + PACKAGE_MANIFEST_LIMIT)
    require(content.pop("package.json") == raw)
    try:
        require(content["asyncapi.json"] == document)
        return bootstrap.load_verified_protocol(raw, content, expected)
    except (KeyError, TypeError, ValueError):
        raise ContractError("invalid installed contract package") from None
