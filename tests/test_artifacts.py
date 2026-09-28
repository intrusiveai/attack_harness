import base64
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import raw_digest

from attack_harness.artifacts import ArtifactPublisher, PART_LIMIT


class ArtifactClient:
    def __init__(self):
        self.calls = []
        self.serial = 0
        self.uploads = {}

    def operation_id(self, purpose):
        self.serial += 1
        return f"{purpose}-{self.serial}"

    def request(self, operation, body, *, operation_id):
        self.calls.append((operation, deepcopy(body), operation_id))
        if operation == "engine.artifact_begin":
            upload = f"upload-{len(self.uploads) + 1}"
            self.uploads[upload] = {"content": bytearray(), "begin": deepcopy(body)}
            result = {"upload_id": upload, **deepcopy(body), "next_offset": 0}
        elif operation == "engine.artifact_put_part":
            data = base64.b64decode(body["content"], validate=True)
            target = self.uploads[body["upload_id"]]["content"]
            if body["offset"] != len(target):
                raise AssertionError("non-contiguous upload")
            target.extend(data)
            result = {"upload_id": body["upload_id"], "offset": body["offset"],
                      "raw_length": len(data), "next_offset": len(target)}
        else:
            upload = body["upload_id"]
            begin = self.uploads[upload]["begin"]
            result = {"upload_id": upload, "artifact_receipt": f"receipt-{upload}",
                      "purpose": begin["purpose"], "artifact": begin["artifact"]}
        return SimpleNamespace(result=result, error=None)


class ArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = Protocol(Path(os.environ["OPERATOR_CONTRACT_SOURCE"]))

    def test_tool_json_is_canonical_and_string_stays_a_string(self):
        client = ArtifactClient()
        publisher = ArtifactPublisher(self.protocol, client)
        artifact = publisher.publish_tool({
            "purpose": "payload",
            "media_type": "application/json",
            "content": {"encoding": "json", "value": {"z": 1, "a": "value"}},
        })
        self.assertEqual(publisher.content(artifact.receipt_id), b'{"a":"value","z":1}')
        self.assertEqual(artifact.canonicalization, "jcs-v1")

        string = publisher.publish_tool({
            "purpose": "carrier",
            "media_type": "application/json",
            "content": {"encoding": "json", "value": "payload"},
        })
        self.assertEqual(publisher.content(string.receipt_id), b'"payload"')

    def test_upload_parts_are_bounded_ordered_and_commit_is_last(self):
        client = ArtifactClient()
        publisher = ArtifactPublisher(self.protocol, client)
        content = b"x" * (PART_LIMIT + 7)
        artifact = publisher.publish("supporting-data", "application/octet-stream", content)
        calls = [name for name, _, _ in client.calls]
        self.assertEqual(calls, ["engine.artifact_begin", "engine.artifact_put_part",
                                "engine.artifact_put_part", "engine.artifact_commit"])
        parts = [base64.b64decode(body["content"]) for name, body, _ in client.calls
                 if name == "engine.artifact_put_part"]
        self.assertEqual([len(part) for part in parts], [PART_LIMIT, 7])
        self.assertEqual(artifact.digest, raw_digest(content))
        self.assertEqual(publisher.content(artifact.receipt_id), content)

    def test_empty_artifact_and_explicit_unavailable_cache(self):
        client = ArtifactClient()
        publisher = ArtifactPublisher(self.protocol, client, maximum_cache_bytes=0)
        artifact = publisher.publish("payload", "application/octet-stream", b"")
        self.assertEqual([name for name, _, _ in client.calls],
                         ["engine.artifact_begin", "engine.artifact_commit"])
        self.assertTrue(artifact.retained)
        self.assertEqual(publisher.content(artifact.receipt_id), b"")

        artifact = publisher.publish("payload", "application/octet-stream", b"x")
        self.assertFalse(artifact.retained)
        with self.assertRaisesRegex(ContractError, "ARTIFACT_UNAVAILABLE"):
            publisher.content(artifact.receipt_id)

    def test_invalid_encoding_and_false_canonical_claim_fail_before_upload(self):
        client = ArtifactClient()
        publisher = ArtifactPublisher(self.protocol, client)
        with self.assertRaises(ContractError):
            publisher.publish_tool({
                "purpose": "payload", "media_type": "application/octet-stream",
                "content": {"encoding": "base64", "data": "YR=="},
            })
        with self.assertRaises(ContractError):
            publisher.publish("payload", "application/json", b'{"z":1, "a":2}',
                              canonicalization="jcs-v1")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
