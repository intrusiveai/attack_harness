import json
from pathlib import Path
import tempfile
import unittest

from build.prepare_release import CODECS, _descriptor, _tool_catalog, _write_json


class FakeProtocol:
    def operations(self):
        return [{"name":"engine.z"},{"name":"engine.a"}]

    def model_tools(self,codec,operations):
        if operations != ["engine.a","engine.z"]:raise AssertionError("not sorted")
        return json.dumps([{"codec":codec}],separators=(",",":")).encode()


class ReleaseBuildTest(unittest.TestCase):
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
