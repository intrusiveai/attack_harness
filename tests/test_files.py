import os
from pathlib import Path
import tempfile
import unittest

from operator_contracts import ContractError
from operator_contracts.canonical import raw_digest
from attack_harness.files import Directory


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, raw=b"safe data"):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o444)
        return {"path":name, "size_bytes":len(raw), "digest":raw_digest(raw)}

    def readonly(self):
        for path in self.root.rglob("*"):
            if path.is_dir():path.chmod(0o555)
        self.root.chmod(0o555)
        def writable():
            self.root.chmod(0o700)
            for path in self.root.rglob("*"):
                if path.is_dir():path.chmod(0o700)
        self.addCleanup(writable)

    def test_exact_inventory_and_bounded_control_ticks(self):
        entries=[self.write("a.txt",b"a"*200000),self.write("nested/b.txt",b"b")]
        self.readonly()
        ticks=[]
        with Directory(self.root,tick=lambda:ticks.append(True)) as d:
            files=d.inventory(entries)
            self.assertEqual(files["nested/b.txt"],b"b")
            self.assertGreater(len(ticks),8)
            with self.assertRaises(ContractError):d.read("a.txt",1024)
            with self.assertRaises(ContractError):d.read("nested/b.txt",1,digest=raw_digest(b"x"))
            for name in ("../escape","/absolute","nested/../a.txt","a//b","a\\b"):
                with self.assertRaises(ContractError):d.read(name,100)
        with self.assertRaises(ContractError):d.read("a.txt",200000)

    def test_links_special_files_and_extras_rejected(self):
        self.write("actual")
        os.symlink("actual",self.root/"link")
        os.link(self.root/"actual",self.root/"hardlink")
        os.mkfifo(self.root/"pipe",0o444)
        with Directory(self.root,readonly=False) as d:
            for name in ("actual","link","hardlink","pipe"):
                with self.assertRaises(ContractError):d.read(name,100)
            with self.assertRaises(ContractError):d.inventory([])

    def test_missing_and_empty_extra_directories_fail(self):
        entry=self.write("file")
        (self.root/"extra").mkdir()
        with Directory(self.root,readonly=False) as d:
            with self.assertRaises(ContractError):d.inventory([entry])
        (self.root/"extra").rmdir()
        (self.root/"file").unlink()
        with Directory(self.root,readonly=False) as d:
            with self.assertRaises(ContractError):d.inventory([entry])

    def test_replacement_during_read_and_control_stop(self):
        self.write("data",b"original")
        calls=0
        def mutate():
            nonlocal calls
            calls+=1
            if calls==2:
                (self.root/"new").write_bytes(b"changed!")
                (self.root/"new").chmod(0o444)
                os.replace(self.root/"new",self.root/"data")
        with Directory(self.root,readonly=False,tick=mutate) as d:
            with self.assertRaises(ContractError):d.read("data",100)
        def stop():raise ContractError("host closed")
        with Directory(self.root,readonly=False,tick=stop) as d:
            with self.assertRaisesRegex(ContractError,"host closed"):d.read("data",100)


if __name__=="__main__":unittest.main()
