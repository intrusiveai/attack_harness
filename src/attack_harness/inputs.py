"""Immutable initialized input capture, followed by actual admission validation."""
from copy import deepcopy
from types import MappingProxyType

from operator_contracts.canonical import canonical_digest
from operator_contracts.inputs import descriptor, validate_prompt
from operator_contracts.schema_ids import SCENARIO_BUNDLE_SCHEMA
from operator_contracts.startup import require

from .files import Directory
from .skill_loader import load_skills


class Inputs:
    def __init__(self, protocol, prefix, loader_digest, *,
                 manifests_root="/run/operator/manifests", input_root="/run/operator/input",
                 skills_root="/run/operator/customer-skills", tick=lambda: None):
        # The bootstrap controller calls only after irreversible confinement and
        # receipt of initialize. This object alone grants no execution admission.
        require(len(prefix)==3 and all(type(raw) is bytes for raw in prefix) and protocol.package_identity() is not None)
        self._protocol=protocol;self._prefix=tuple(prefix);self._admitted=False
        messages=[protocol.validate_control(direction,raw) for direction,raw in zip(("host","guest","host"),prefix)]
        require([m["kind"] for m in messages]==["bootstrap","confinement_ready","initialize"])
        require([m["seq"] for m in messages]==[0,0,1])
        bootstrap,ready,initialize=messages
        for m in messages[1:]:require(all(m[k]==bootstrap[k] for k in ("campaign_id","launch_id","run_revision")))
        require(ready["body"]=={k:v for k,v in bootstrap["body"].items() if k!="timeout_ms"})
        pin=protocol.package_identity();contract=bootstrap["body"]["contract"]
        require(contract["version"]==pin["package_version"] and contract["digest"]==pin["package_digest"])
        require(all(contract[k]==v for k,v in protocol.registry_digests().items()))
        body=initialize["body"]
        with Directory(manifests_root,tick=tick) as directory:
            def read_manifest(name,meta,limit):
                require(meta["size_bytes"]<=limit)
                raw=directory.read(name,limit,size=meta["size_bytes"],digest=meta["digest"])
                require(canonical_digest(raw,limit)==meta["object_digest"])
                return raw
            tree=read_manifest("input-tree.json",body["input_tree"],8<<20)
            selection=read_manifest("skill-set.json",body["skill_set"],64<<10)
            selected=protocol.validate_skill_set(selection)
            inventory=[{"path":name,**descriptor(raw)} for name,raw in (("input-tree.json",tree),("skill-set.json",selection))]
            manifests=[]
            for item in selected["skills"]:
                name=f'skills/{item["manifest"]["slot"]:04d}.json'
                raw=read_manifest(name,item["manifest"],2<<20)
                manifests.append(raw);inventory.append({"path":name,**descriptor(raw)})
            frozen=directory.inventory(sorted(inventory,key=lambda e:e["path"]),maximum_bytes=40<<20)
            require(frozen["input-tree.json"]==tree and frozen["skill-set.json"]==selection)
        protocol.validate_manifest_set(tree,selection,manifests)
        self.tree,self.selection,self.manifests=tree,selection,tuple(manifests)
        inventory=protocol.validate_input_tree(tree)["entries"]
        with Directory(input_root,tick=tick) as directory:
            files=directory.inventory(inventory,maximum_bytes=64<<20)
        self.files=MappingProxyType({entry["entry_id"]:files[entry["path"]] for entry in inventory})
        self._entries={entry["entry_id"]:deepcopy(entry) for entry in inventory}
        core={entry["role"]:entry for entry in inventory if entry["role"]!="reference"}
        self.context_raw=self.files[core["engine-context"]["entry_id"]]
        self.bundle_raw=self.files[core["scenario-bundle"]["entry_id"]]
        self.prompt_raw=self.files[core["system-prompt"]["entry_id"]]
        self._context=protocol.validate_engine_context(self.context_raw)
        self._bundle=protocol._catalog.validate(SCENARIO_BUNDLE_SCHEMA,self.bundle_raw)
        validate_prompt(self.prompt_raw)
        c=self._context;binding=body["binding"]
        require(canonical_digest(self.context_raw,64<<20)==body["engine_context_object_digest"])
        require(core["engine-context"]["digest"]==binding["engine_context_digest"])
        require(core["system-prompt"]["digest"]==binding["prompt_digest"])
        require(all(c[k]==bootstrap[k] for k in ("campaign_id","launch_id","run_revision")))
        require(c["contract"]==contract and c["release"]==bootstrap["body"]["release"] and c["skills"]==selected)
        require(binding["contract_package_version"]==contract["version"] and binding["contract_package_digest"]==contract["digest"])
        require(binding["image_digest"]==c["release"]["image_digest"] and binding["release_record_digest"]==c["release"]["release_record_digest"])
        require(c["scenario_bundle"]==core["scenario-bundle"] and c["prompt"]["entry_id"]==core["system-prompt"]["entry_id"])
        require(c["prompt"]["provenance"]["effective"]==descriptor(self.prompt_raw))
        require(c["references"]==[e for e in inventory if e["role"]=="reference"])
        self.skills=load_skills(protocol,selection,manifests,loader_digest,skills_root,tick=tick)

    def initialized_body(self):
        body=deepcopy(self._protocol.validate_control("host",self._prefix[2])["body"])
        del body["timeout_ms"]
        body["contract"]=deepcopy(self._context["contract"])
        return body

    def admit(self,initialized,admission):
        require(not self._admitted)
        self._protocol.validate_launch_identities([*self._prefix,initialized,admission],self.tree,self.selection,list(self.manifests),self.context_raw,self.bundle_raw,self.prompt_raw)
        self._admitted=True
        return deepcopy(self._protocol.validate_control("host",admission)["body"])

    def context(self):
        require(self._admitted)
        return deepcopy(self._context)

    def bundle(self):
        require(self._admitted)
        return deepcopy(self._bundle)

    def conclusion_binding(self, run_revision):
        """Return the verified startup identity binding at the final revision."""
        require(self._admitted and type(run_revision) is int and run_revision >= 0)
        binding = self.initialized_body()["binding"]
        binding["run_revision"] = run_revision
        return binding

    def entry(self,identifier):
        require(self._admitted and identifier in self._entries)
        return deepcopy(self._entries[identifier]),self.files[identifier]
