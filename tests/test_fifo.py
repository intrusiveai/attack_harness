import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from operator_contracts import Protocol, ContractError
from attack_harness.fifo import FIFO, LANES


class FIFOTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol=Protocol(source)
        cls.messages=json.loads((source/"fixtures/startup-example.json").read_text())

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.host={};self.now=0.
        for lane in LANES:
            os.mkfifo(self.root/lane,0o600)
            if lane.endswith("out"):self.host[lane]=os.open(self.root/lane,os.O_RDONLY|os.O_NONBLOCK)
        self.addCleanup(lambda:[os.close(fd) for fd in self.host.values()])
        self.peer=FIFO(self.protocol,self.root,clock=lambda:self.now);self.addCleanup(self.peer.close)

    def writers(self):
        for lane in ("ordinary-in","control-in"):
            self.host[lane]=os.open(self.root/lane,os.O_WRONLY|os.O_NONBLOCK)

    def bootstrap(self):
        self.writers()
        raw=json.dumps(self.messages[0]).encode()
        os.write(self.host["control-in"],self.protocol.encode_frame("control-in",raw))
        self.peer.pump();self.assertEqual(self.peer.take("control-in"),raw)

    def test_directional_handshake_and_framing(self):
        self.bootstrap()
        for lane,fd in self.peer.fds.items():
            self.assertEqual(fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE,os.O_RDONLY if lane.endswith("in") else os.O_WRONLY)
        raw=json.dumps(self.messages[1]).encode()
        self.peer.send("control-out",raw);self.peer.pump()
        self.assertEqual(os.read(self.host["control-out"],65536),self.protocol.encode_frame("control-out",raw))

    def test_initial_eof_allowed_but_established_eof_is_terminal(self):
        self.peer.pump()
        self.bootstrap()
        os.close(self.host.pop("ordinary-in"))
        with self.assertRaises(ContractError):self.peer.pump()
        with self.assertRaises(ContractError):self.peer.pump()

    def test_partial_frame_deadline_is_not_renewed(self):
        self.writers()
        os.write(self.host["control-in"],b"\0")
        self.peer.pump();self.now=4.9
        os.write(self.host["control-in"],b"\0");self.peer.pump();self.now=5.
        with self.assertRaises(ContractError):self.peer.pump()

    def test_oversized_prefix_rejected_without_body(self):
        self.writers();os.write(self.host["control-in"],((64<<10)+1).to_bytes(4,"big"))
        with self.assertRaises(ContractError):self.peer.pump()

    def test_fifo_replacement_is_terminal(self):
        os.unlink(self.root/"control-in");os.mkfifo(self.root/"control-in",0o600)
        with self.assertRaises(ContractError):self.peer.pump()

    def test_initial_rendezvous_expires(self):
        self.peer.pump();self.now=60.
        with self.assertRaises(ContractError):self.peer.pump()

    def test_unsent_queue_deadline_and_added_file_are_terminal(self):
        self.bootstrap();self.peer.send("control-out",json.dumps(self.messages[1]).encode())
        self.now=5.
        with self.assertRaises(ContractError):self.peer.pump()

    def test_added_directory_entry_is_rejected(self):
        (self.root/"unexpected").write_bytes(b"extra")
        with self.assertRaises(ContractError):self.peer.pump()


if __name__=="__main__":unittest.main()
