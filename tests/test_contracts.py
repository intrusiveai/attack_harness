import os
import json
from pathlib import Path
import tempfile
import unittest

from operator_contracts import Protocol, ContractError
from attack_harness.contracts import load_contract


class ContractLoaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol=Protocol(source)
        cls.files={p.name:p.read_bytes() for p in source.glob("*.schema.json")}
        cls.files.update({name:(source/name).read_bytes() for name in ("catalog.json","operations.json","asyncapi.json")})
        profiles={"jcs-v1":"semantics/digests.md","manifest-paths-v1":"semantics/paths.md","harness-loop-v1":"semantics/limits.md"}
        cls.files.update({name:b"Test-only semantic profile.\n" for name in profiles.values()})
        cls.manifest,cls.pin=cls.protocol.build_package_manifest("0.9.0",cls.files,profiles)

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        for name,raw in {**self.files,"package.json":self.manifest}.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o644)

    def test_independent_pin_and_frozen_offline_resources(self):
        loaded=load_contract(self.root,self.pin)
        self.assertEqual(loaded.package_identity(),self.pin)
        before=loaded.registry_digests()
        (self.root/"catalog.json").write_bytes(b"changed after load")
        self.assertEqual(loaded.registry_digests(),before)
        with self.assertRaises(ContractError):load_contract(self.root,self.pin)

    def test_pin_failure_precedes_payload_read(self):
        (self.root/"catalog.json").unlink()
        with self.assertRaises(ContractError):load_contract(self.root,{**self.pin,"package_digest":"sha256:"+"0"*64})

    def test_exact_document_bytes_and_version_are_required(self):
        path = self.root / 'asyncapi.json'
        path.write_bytes(path.read_bytes().rstrip(b'\n'))
        with self.assertRaises(ContractError):
            load_contract(self.root, self.pin)
        path.write_bytes(self.files['asyncapi.json'])
        with self.assertRaises(ContractError):
            load_contract(self.root, dict(self.pin, package_version='0.6.1'))

    def test_distribution_change_keeps_identity_but_requires_valid_inventory(self):
        files = dict(self.files, **{'source/implementation.py': b'# implementation-only change\n'})
        manifest = json.loads(self.manifest)
        profiles = {p['profile_id']: p['path'] for p in manifest['semantic_profiles']}
        raw, pin = self.protocol.build_package_manifest('0.9.0', files, profiles)
        self.assertEqual(pin, self.pin)
        self.assertNotEqual(raw, self.manifest)
        (self.root / 'source').mkdir()
        implementation = self.root / 'source/implementation.py'
        implementation.write_bytes(files['source/implementation.py'])
        (self.root / 'package.json').write_bytes(raw)
        self.assertEqual(load_contract(self.root, self.pin).package_identity(), pin)
        implementation.write_bytes(b'# unrecorded corruption\n')
        with self.assertRaises(ContractError):
            load_contract(self.root, self.pin)

    def test_extra_file_and_manifest_replacement_rejected(self):
        (self.root/"surprise.py").write_bytes(b"raise Exception('must never execute')")
        with self.assertRaises(ContractError):load_contract(self.root,self.pin)
        (self.root/"surprise.py").unlink()
        (self.root/"package.json").unlink()
        os.symlink("catalog.json",self.root/"package.json")
        with self.assertRaises(ContractError):load_contract(self.root,self.pin)


if __name__=="__main__":unittest.main()
