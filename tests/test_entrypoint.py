import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from operator_contracts import ContractError

from attack_harness.entrypoint import load_runtime_config, main


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

    def test_native_import_failure_closes_transport_without_traceback(self):
        transport=Mock()
        original_import=__import__
        def controlled_import(name,*args,**kwargs):
            if name=="_confinement":raise ImportError("unavailable")
            return original_import(name,*args,**kwargs)
        with patch("attack_harness.entrypoint.load_runtime_config",
                   return_value={"contract":{},"skill_loader_digest":"sha256:"+"1"*64}), \
             patch("attack_harness.entrypoint.load_contract",return_value=object()), \
             patch("attack_harness.entrypoint.transport_from_environment",
                   return_value=transport), \
             patch("builtins.__import__",side_effect=controlled_import):
            self.assertEqual(main(),1)
        transport.close.assert_called_once_with()


if __name__=="__main__":unittest.main()
