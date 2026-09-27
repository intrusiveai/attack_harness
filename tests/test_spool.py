import json
import os
from pathlib import Path
import tempfile
import unittest

from operator_contracts import Protocol, ContractError
from operator_contracts.transport import spool_message_name
from attack_harness.spool import Spool, LANES


class SpoolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol=Protocol(source)
        cls.startup=json.loads((source/"fixtures/startup-example.json").read_text())
        for message in cls.startup[:2]:
            message["body"]["host_platform"]="darwin/arm64"
            message["body"]["transport"]="spool"

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for lane in LANES:(self.root/lane).mkdir()
        self.now=0.
        self.peer=Spool(self.protocol,self.root,clock=lambda:self.now)
        self.addCleanup(self.peer.close)

    def put(self,lane,message):
        raw=json.dumps(message,separators=(",",":")).encode()
        path=self.root/lane/spool_message_name(message["seq"])
        path.write_bytes(raw)
        return raw

    def bootstrap(self):
        raw=self.put("control-in",self.startup[0]);self.peer.pump()
        self.assertEqual(self.peer.take("control-in"),raw)
        return raw

    def ack(self,control=None,ordinary=None):
        (self.root/"control-in/consumed.json").write_text(json.dumps({"api_version":"operator.dev/engine-spool-ack/v1alpha1","launch_id":"launch-1","control_seq":control,"ordinary_seq":ordinary}))

    def test_capture_ack_producer_cleanup_and_continued_sequence(self):
        self.bootstrap()
        ack=json.loads((self.root/"control-out/consumed.json").read_bytes())
        self.assertEqual(ack["control_seq"],0)
        raw=json.dumps(self.startup[1]).encode()
        self.peer.send("control-out",raw);self.peer.pump()
        path=self.root/"control-out"/spool_message_name(0)
        self.assertEqual(path.read_bytes(),raw)
        self.ack(control=0);self.peer.pump();self.assertFalse(path.exists())
        (self.root/"control-in"/spool_message_name(0)).unlink()
        raw=self.put("control-in",self.startup[2]);self.peer.pump()
        self.assertEqual(self.peer.take("control-in"),raw)
        self.peer.pump();self.assertIsNone(self.peer.take("control-in"))

    def test_ack_deadline_does_not_renew_on_progress(self):
        self.bootstrap();self.peer.send("control-out",json.dumps(self.startup[1]).encode());self.peer.pump()
        self.now=4.99;self.peer.pump()
        self.now=5.;self.ack(control=0)
        with self.assertRaises(ContractError):self.peer.pump()
        self.assertTrue(self.peer.closed)

    def test_gap_and_changed_consumed_file_are_terminal(self):
        self.bootstrap()
        (self.root/"control-in"/spool_message_name(0)).write_bytes(b"changed")
        with self.assertRaises(ContractError):self.peer.pump()

    def test_sequence_gap_rejected_before_unbounded_work(self):
        message=dict(self.startup[0],seq=9007199254740991)
        self.put("control-in",message)
        with self.assertRaises(ContractError):self.peer.pump()

    def test_temporary_files_expire_and_oversized_files_fail(self):
        path=self.root/"ordinary-in"/spool_message_name(0,True)
        path.write_bytes(b"partial");self.peer.pump();self.now=5.
        with self.assertRaises(ContractError):self.peer.pump()

    def test_unexpected_file_type_fails(self):
        os.symlink("/etc/passwd",self.root/"control-in"/spool_message_name(0))
        with self.assertRaises(ContractError):self.peer.pump()

    def test_replaced_lane_fails(self):
        os.rename(self.root/"control-in",self.root/"old")
        (self.root/"control-in").mkdir()
        with self.assertRaises(ContractError):self.peer.pump()

    def test_full_receiver_has_nonrenewing_deadline(self):
        self.bootstrap()
        (self.root/"control-in"/spool_message_name(0)).unlink()
        for seq in range(1,17):self.put("control-in",dict(self.startup[2],seq=seq))
        self.peer.pump()
        for seq in range(1,17):(self.root/"control-in"/spool_message_name(seq)).unlink()
        self.put("control-in",dict(self.startup[2],seq=17))
        self.peer.pump();self.now=4.9;self.peer.pump();self.now=5.
        with self.assertRaises(ContractError):self.peer.pump()

    def test_reopen_guest_output_is_rejected(self):
        self.bootstrap()
        with self.assertRaises(ContractError):Spool(self.protocol,self.root)

    def test_oversized_sparse_ready_file_is_not_read(self):
        path=self.root/"control-in"/spool_message_name(0)
        with path.open("wb") as f:f.truncate((64<<10)+1)
        with self.assertRaises(ContractError):self.peer.pump()

    def test_wrong_ack_cannot_delete_unacknowledged_message(self):
        self.bootstrap();self.peer.send("control-out",json.dumps(self.startup[1]).encode());self.peer.pump()
        self.ack(control=1)
        with self.assertRaises(ContractError):self.peer.pump()
        self.assertTrue((self.root/"control-out"/spool_message_name(0)).exists())


if __name__=="__main__":unittest.main()
