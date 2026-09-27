"""Test-only peer for Go/Python transport interoperability; no confinement claim."""
import base64
import json
from pathlib import Path
import sys
import time

from operator_contracts import Protocol
from attack_harness.spool import Spool, POLL_SECONDS
from attack_harness.fifo import FIFO


def main():
    root,schemas=map(Path,sys.argv[1:3])
    fifo=len(sys.argv)>3 and sys.argv[3]=="fifo"
    protocol=Protocol(schemas)
    transcript=json.loads((schemas/"fixtures/startup-example.json").read_text())
    for message in ([] if fifo else transcript[:2]):
        message["body"]["host_platform"]="darwin/arm64"
        message["body"]["transport"]="spool"
    frames={}
    for case in json.loads((schemas/"fixtures/transport-codec.json").read_text()):
        if case["mode"]=="frames" and case["valid"] and case["lane"] not in frames:
            frames[case["lane"]]=base64.b64decode(case["frames_base64"][0])
    peer=(FIFO if fifo else Spool)(protocol,root)
    deadline=time.monotonic()+15
    def receive(lane):
        while time.monotonic()<deadline:
            peer.pump()
            message=peer.take(lane)
            if message is not None:return message
            time.sleep(POLL_SECONDS)
        raise RuntimeError("test peer deadline")
    try:
        for index in (0,2,4):
            actual=receive("control-in")
            if json.loads(actual)!=transcript[index]:raise RuntimeError("different host startup")
            if index==0 and fifo:
                peer.pin_descriptors()
                if list(peer.fds.values())!=[3,4,5,6]:raise RuntimeError("descriptor handoff mismatch")
            if index<4:peer.send("control-out",json.dumps(transcript[index+1]).encode())
        peer.send("ordinary-out",frames["ordinary-out"])
        actual=receive("ordinary-in")
        if json.loads(actual)!=json.loads(frames["ordinary-in"]):raise RuntimeError("different host response")
        peer.pump()
        print("transport complete")
    finally:peer.close()


if __name__=="__main__":main()
