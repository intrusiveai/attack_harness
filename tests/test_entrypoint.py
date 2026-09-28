import json
from pathlib import Path
import tempfile
import unittest

from operator_contracts import ContractError

from attack_harness.entrypoint import load_runtime_config


class EntrypointTest(unittest.TestCase):
    def test_fixed_release_config_is_closed_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            value={"contract":{"package_version":"1.2.3",
                    "package_digest":"sha256:"+"1"*64},
                   "skill_loader_digest":"sha256:"+"2"*64}
            path=root/"runtime-config.json"
            path.write_text(json.dumps(value,separators=(",",":")))
            path.chmod(0o444);root.chmod(0o555)
            try:self.assertEqual(load_runtime_config(root),value)
            finally:root.chmod(0o700)

    def test_release_config_cannot_select_paths_or_extra_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/"runtime-config.json"
            path.write_text(json.dumps({"contract":{"package_version":"1.2.3",
                "package_digest":"sha256:"+"1"*64},"skill_loader_digest":"sha256:"+"2"*64,
                "contract_path":"/untrusted"}))
            path.chmod(0o444);root.chmod(0o555)
            try:
                with self.assertRaises(ContractError):load_runtime_config(root)
            finally:root.chmod(0o700)


if __name__=="__main__":unittest.main()
