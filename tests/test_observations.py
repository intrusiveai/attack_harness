import base64
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest

from operator_contracts import ContractError

from attack_harness.observations import ObservationReader


class ObservationClient:
    def __init__(self, content, media_type="text/plain", *, digest=None, available=True):
        self.content = content
        self.media_type = media_type
        self.digest = digest or "sha256:" + hashlib.sha256(content).hexdigest()
        self.available = available
        self.calls = []
        self.serial = 0
        self.mutate_metadata = False

    def operation_id(self, purpose):
        self.serial += 1
        return f"{purpose}-{self.serial}"

    def request(self, operation, body, *, operation_id):
        self.calls.append((operation, deepcopy(body), operation_id))
        if not self.available:
            result = {"receipt_id": body["receipt_id"], "entry_id": body["entry_id"],
                      "offset": body["offset"], "availability": "unavailable",
                      "reason": "content_evicted", "content": "", "raw_length": 0,
                      "eof": False, "truncated": False}
            return SimpleNamespace(result=result, error=None)
        start = body["offset"]
        count = min(body["max_bytes"], 3)
        part = self.content[start:start + count]
        artifact = {"digest": self.digest, "size_bytes": len(self.content),
                    "media_type": self.media_type}
        if self.mutate_metadata and start:
            artifact["media_type"] = "application/octet-stream"
        result = {"receipt_id": body["receipt_id"], "entry_id": body["entry_id"],
                  "offset": start, "availability": "available",
                  "content": base64.b64encode(part).decode("ascii"),
                  "raw_length": len(part), "eof": start + len(part) == len(self.content),
                  "truncated": False, "artifact": artifact}
        return SimpleNamespace(result=result, error=None)


class ObservationTest(unittest.TestCase):
    def test_chunk_assembly_digest_and_incremental_utf8(self):
        raw = "A€U0001f680Z".encode()
        client = ObservationClient(raw)
        content = ObservationReader(client).read_all("receipt-1", "entry-1")
        self.assertEqual(content.content, raw)
        self.assertEqual(content.text, "A€U0001f680Z")
        self.assertGreater(len(client.calls), 1)
        offsets = [body["offset"] for _, body, _ in client.calls]
        self.assertEqual(offsets, sorted(set(offsets)))

    def test_binary_remains_opaque_and_empty_is_available(self):
        binary = ObservationReader(ObservationClient(b"\xff\x00", "application/octet-stream"))
        self.assertIsNone(binary.read_all("receipt-1", "entry-1").text)
        empty = ObservationReader(ObservationClient(b""))
        result = empty.read_all("receipt-2", "entry-2")
        self.assertEqual(result.content, b"")
        self.assertEqual(result.text, "")

    def test_unavailable_inconsistent_and_corrupt_content_remain_explicit(self):
        unavailable = ObservationReader(ObservationClient(b"", available=False))
        chunk = unavailable.read("receipt-1", "entry-1", 0)
        self.assertEqual(chunk.availability, "unavailable")
        with self.assertRaisesRegex(ContractError, "unavailable"):
            unavailable.read_all("receipt-1", "entry-1")

        changed_client = ObservationClient(b"abcdef")
        changed_client.mutate_metadata = True
        with self.assertRaises(ContractError):
            ObservationReader(changed_client).read_all("receipt-2", "entry-2")

        corrupt = ObservationReader(ObservationClient(b"abc", digest="sha256:" + "0" * 64))
        with self.assertRaises(ContractError):
            corrupt.read_all("receipt-3", "entry-3")

    def test_maximum_is_checked_from_authenticated_descriptor(self):
        reader = ObservationReader(ObservationClient(b"abcd"))
        with self.assertRaises(ContractError):
            reader.read_all("receipt-1", "entry-1", maximum_bytes=3)


if __name__ == "__main__":
    unittest.main()
