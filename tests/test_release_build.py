import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build.prepare_release import (CODECS, COMPATIBILITY_PATH, _descriptor, _tool_catalog,
                                   _write_json, prepare, validate_compatibility, verify)


class FakeProtocol:
    def package_identity(self):
        return {"package_version": "0.0.5", "package_digest": "sha256:" + "a" * 64}

    def operations(self):
        return [{"name": "engine.z"}, {"name": "engine.a"}]

    def model_tools(self, codec, operations):
        if operations != ["engine.a", "engine.z"]:
            raise AssertionError("not sorted")
        return json.dumps([{"codec": codec}], separators=(",", ":")).encode()


class ReleaseBuildTest(unittest.TestCase):
    def release(self, platform="linux/arm64"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
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
        mocked = patch("build.prepare_release.check_contract", return_value=(FakeProtocol(), {"files": []}))
        mocked.start()
        self.addCleanup(mocked.stop)
        prepare(source, contract, output, platform, prompt, lock)
        return output, contract, lock

    def test_both_platforms_have_reproducible_immutable_compatibility(self):
        for platform in ("linux/amd64", "linux/arm64"):
            with self.subTest(platform=platform):
                output, contract, lock = self.release(platform)
                again, _, _ = self.release(platform)
                path = output / COMPATIBILITY_PATH
                raw = path.read_bytes()
                self.assertEqual(raw, (again / COMPATIBILITY_PATH).read_bytes())
                self.assertEqual(path.stat().st_mode & 0o777, 0o444)
                record = validate_compatibility(raw, FakeProtocol().package_identity(), platform)
                self.assertEqual(record["platform"], platform)
                self.assertEqual(set(record), {"api_version", "minimum_operator_version", "contract_package_version",
                                               "contract_package_digest", "runtime_profile", "platform"})
                manifest = json.loads((path.parent / "engine-manifest.json").read_bytes())
                self.assertEqual(manifest["contract"], FakeProtocol().package_identity())
                verify(output, contract, lock, require_native=False)
                manifest["contract"] = {"version": "0.0.5", "digest": "sha256:" + "a" * 64}
                _write_json(path.parent / "engine-manifest.json", manifest)
                with self.assertRaisesRegex(ValueError, "runtime configuration identity mismatch"):
                    verify(output, contract, lock, require_native=False)

    def test_invalid_or_incompatible_compatibility_fails_closed(self):
        output, contract, lock = self.release()
        path = output / COMPATIBILITY_PATH
        raw = path.read_bytes()
        record = json.loads(raw)
        invalid = [b"", b"{}", b"{", b"\xff", b" " * ((64 << 10) + 1), raw + b"{}",
                   b'{"platform":"linux/arm64",' + raw[1:]]
        for field, value in (("image_digest", "sha256:" + "b" * 64),
                             ("contract_package_version", "0.0.3"),
                             ("contract_package_digest", "sha256:" + "b" * 64),
                             ("runtime_profile", "other"), ("platform", "linux/amd64"),
                             ("minimum_operator_version", "999.0.0"),
                             ("minimum_operator_version", "0.1.0-rc.1"),
                             ("minimum_operator_version", "01.0.0"),
                             ("minimum_operator_version", 1)):
            invalid.append(json.dumps({**record, field: value}).encode())
        path.chmod(0o644)
        for value in invalid:
            with self.subTest(value=value[:100]):
                path.write_bytes(value)
                path.chmod(0o444)
                with self.assertRaises(ValueError):
                    verify(output, contract, lock, require_native=False)
                path.chmod(0o644)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            verify(output, contract, lock, require_native=False)
        target = output / "record.json"
        target.write_bytes(raw)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular file"):
            verify(output, contract, lock, require_native=False)

    def test_compatibility_digest_binds_raw_bytes_not_reserialized_json(self):
        output, _, _ = self.release()
        path = output / COMPATIBILITY_PATH
        raw = path.read_bytes()
        record = validate_compatibility(raw + b"\n", FakeProtocol().package_identity(), "linux/arm64")
        self.assertEqual(record, json.loads(raw))
        self.assertEqual(_descriptor(path)["digest"], "sha256:" + hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(hashlib.sha256(raw).digest(), hashlib.sha256(raw + b"\n").digest())

    def test_resources_and_tool_catalog_still_fail_closed(self):
        output, contract, lock = self.release()
        engine = output / "opt/operator/engine"
        for name in ("share/default-system-prompt.txt", "lib/attack_harness/skill_loader.py", "share/tool-catalog.json"):
            path = engine / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                verify(output, contract, lock, require_native=False)
            path.write_bytes(original)
        path = engine / "share/tool-catalog.json"
        _write_json(path, {"api_version": "operator.dev/model-tool-catalog/v1alpha1", "codecs": {}})
        manifest_path = engine / "share/engine-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["tool_catalog"] = _descriptor(path)
        _write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "tool catalog drift"):
            verify(output, contract, lock, require_native=False)

    def test_tool_catalog_is_complete_and_deterministic(self):
        catalog = _tool_catalog(FakeProtocol())
        self.assertEqual(tuple(catalog["codecs"]), CODECS)
        self.assertEqual(catalog["codecs"][CODECS[0]], [{"codec": CODECS[0]}])

    def test_descriptors_bind_canonical_generated_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "value.json"
            _write_json(path, {"z": 1, "a": "value"})
            self.assertEqual(path.read_bytes(), b'{"a":"value","z":1}')
            self.assertEqual(_descriptor(path), {
                "size_bytes": 19,
                "digest": "sha256:5aaca98f7ea3b0364fe69ff79e271b638a88fad50ad5482ac2829be070200775",
            })


if __name__ == "__main__":
    unittest.main()
