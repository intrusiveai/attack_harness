"""Exact instruction-only skill consumption; never discovers or executes code."""
from dataclasses import dataclass
from types import MappingProxyType

from operator_contracts import ContractError
from operator_contracts.canonical import _object_digest, canonical_digest, raw_digest
from operator_contracts.startup import require

from .files import Directory


@dataclass(frozen=True)
class Skill:
    skill_id: str
    bundle_digest: str
    name: str
    description: str
    instructions: str
    files: MappingProxyType


def load_skills(protocol, selection_raw, manifests, loader_digest,
                root="/run/operator/customer-skills", *, tick=lambda: None):
    selection=protocol.validate_skill_set(selection_raw)
    require(selection["loader_digest"]==loader_digest)
    require(selection["loading_digest"]==_object_digest({k:v for k,v in selection.items() if k!="loading_digest"},65536))
    require(len(selection["skills"])==len(manifests))
    entries=[];metadata=[]
    for selected,raw in zip(selection["skills"],manifests):
        tick()
        m=protocol.validate_skill_manifest(raw)
        require(m["skill_id"]==selected["skill_id"])
        require(len(raw)==selected["manifest"]["size_bytes"] and raw_digest(raw)==selected["manifest"]["digest"])
        require(canonical_digest(raw,2<<20)==selected["manifest"]["object_digest"])
        require(selected["bundle_digest"]==selected["manifest"]["object_digest"])
        metadata.append(m)
        for entry in m["files"]:
            entries.append({**entry,"path":m["skill_id"]+"/"+entry["path"]})
    with Directory(root,tick=tick) as directory:
        files=directory.inventory(sorted(entries,key=lambda e:e["path"]),maximum_files=16384,maximum_bytes=64<<20)
    result=[]
    for selected,m in zip(selection["skills"],metadata):
        content={}
        for entry in m["files"]:
            tick();raw=files[m["skill_id"]+"/"+entry["path"]]
            try:text=raw.decode("utf-8",errors="strict")
            except UnicodeError:raise ContractError("invalid skill text") from None
            require("\0" not in text and "\r" not in text)
            content[entry["path"]]=raw
        instructions=content["SKILL.md"].decode("utf-8")
        require(bool(instructions.strip()))
        result.append(Skill(m["skill_id"],selected["bundle_digest"],m["name"],m["description"],instructions,MappingProxyType(content)))
    return tuple(result)
