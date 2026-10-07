import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build.prepare_release import CODECS, _descriptor, _tool_catalog, _write_json, prepare, verify


class FakeProtocol:
    def package_identity(self):
        return {"package_version": "v0.0.3", "package_digest": "sha256:" + "a" * 64}

    def operations(self):
        return [{"name":"engine.z"},{"name":"engine.a"}]

    def model_tools(self,codec,operations):
        if operations != ["engine.a","engine.z"]:raise AssertionError("not sorted")
        return json.dumps([{"codec":codec}],separators=(",",":")).encode()


class ReleaseBuildTest(unittest.TestCase):
    def test_release_manifest_uses_operator_package_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, contract, output = root / "source", root / "contract", root / "output"
            runtime = source / "src/attack_harness"
            runtime.mkdir(parents=True)
            (source / "bootstrap.py").write_text("# bootstrap\n")
            (runtime / "skill_loader.py").write_text("# loader\n")
            python = contract / "source/contracts/python/operator_contracts"
            python.mkdir(parents=True)
            for name in ["__init__"] + [f"module_{index}" for index in range(9)]:
                (python / f"{name}.py").write_text("# contract fixture\n")
            pin = FakeProtocol().package_identity()
            _write_json(contract / "package.json", {"package_version": pin["package_version"]})
            lock, prompt = root / "lock.json", root / "prompt.txt"
            _write_json(lock, {"package": pin})
            prompt.write_text("test prompt")
            (output / "opt/operator/engine/lib").mkdir(parents=True)
            with patch("build.prepare_release.check_contract", return_value=(FakeProtocol(), {"files": []})):
                prepare(source, contract, output, "linux/arm64", prompt, lock)
                path = output / "opt/operator/engine/share/engine-manifest.json"
                manifest = json.loads(path.read_bytes())
                self.assertEqual(manifest["contract"], pin)
                verify(output, contract, lock, require_native=False)
                manifest["contract"] = {"version": pin["package_version"], "digest": pin["package_digest"]}
                _write_json(path, manifest)
                with self.assertRaisesRegex(ValueError, "runtime configuration identity mismatch"):
                    verify(output, contract, lock, require_native=False)

    def test_tool_catalog_is_complete_and_deterministic(self):
        catalog=_tool_catalog(FakeProtocol())
        self.assertEqual(tuple(catalog["codecs"]),CODECS)
        self.assertEqual(catalog["codecs"][CODECS[0]],[{"codec":CODECS[0]}])

    def test_descriptors_bind_canonical_generated_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"value.json"
            _write_json(path,{"z":1,"a":"value"})
            self.assertEqual(path.read_bytes(),b'{"a":"value","z":1}')
            self.assertEqual(_descriptor(path),{
                "size_bytes":19,
                "digest":"sha256:5aaca98f7ea3b0364fe69ff79e271b638a88fad50ad5482ac2829be070200775",
            })


if __name__=="__main__":unittest.main()
