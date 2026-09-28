"""Deterministic artifact encoding, upload, commit, and bounded byte retention."""

import base64
import binascii
from dataclasses import dataclass

from operator_contracts import ContractError
from operator_contracts.canonical import _canonical_value, canonicalize, raw_digest
from operator_contracts.startup import require
from operator_contracts.validation import ORDINARY_LIMIT


ARTIFACT_LIMIT = 16 << 20
CONCLUSION_LIMIT = 1 << 20
PART_LIMIT = 256 << 10


class ArtifactRejected(ContractError):
    def __init__(self, error):
        super().__init__("artifact operation rejected")
        self.error = error


@dataclass(frozen=True)
class CommittedArtifact:
    receipt_id: str
    purpose: str
    digest: str
    size_bytes: int
    media_type: str
    canonicalization: str
    retained: bool

    def descriptor(self):
        return {
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "canonicalization": self.canonicalization,
        }


def _decode_base64(value):
    require(type(value) is str)
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ContractError("invalid artifact content") from None
    require(base64.b64encode(raw).decode("ascii") == value)
    return raw


class ArtifactPublisher:
    """Wrap the three host artifact operations without retrying any of them."""

    def __init__(self, protocol, client, *, maximum_cache_bytes=128 << 20):
        require(type(maximum_cache_bytes) is int and 0 <= maximum_cache_bytes <= 1 << 30)
        self.protocol = protocol
        self.client = client
        self.maximum_cache_bytes = maximum_cache_bytes
        self._cache_bytes = 0
        self._artifacts = {}
        self._content = {}

    @staticmethod
    def encode(content):
        """Return ``(bytes, canonicalization)`` for validated model content."""
        require(type(content) is dict and type(content.get("encoding")) is str)
        encoding = content["encoding"]
        if encoding == "utf8":
            require(set(content) == {"encoding", "text"} and type(content["text"]) is str)
            return content["text"].encode("utf-8"), "raw"
        if encoding == "base64":
            require(set(content) == {"encoding", "data"})
            return _decode_base64(content["data"]), "raw"
        if encoding == "json":
            require(set(content) == {"encoding", "value"})
            return _canonical_value(content["value"], ARTIFACT_LIMIT), "jcs-v1"
        raise ContractError("invalid artifact content")

    def publish_tool(self, arguments):
        raw = _canonical_value(arguments, ORDINARY_LIMIT)
        value = self.protocol.validate_tool_arguments("artifact_publish", raw)
        content, canonicalization = self.encode(value["content"])
        return self.publish(value["purpose"], value["media_type"], content,
                            canonicalization=canonicalization)

    def _request(self, operation, body, purpose):
        operation_id = self.client.operation_id(f"{purpose}-{operation.removeprefix('engine.').replace('_', '-')}")
        reply = self.client.request(operation, body, operation_id=operation_id)
        if reply.error is not None:
            raise ArtifactRejected(reply.error)
        return reply.result

    def publish(self, purpose, media_type, content, *, canonicalization="raw"):
        require(purpose in ("payload", "carrier", "conclusion", "supporting-data"))
        require(type(media_type) is str and type(content) is bytes)
        maximum = CONCLUSION_LIMIT if purpose == "conclusion" else ARTIFACT_LIMIT
        require(len(content) <= maximum)
        require(canonicalization in ("raw", "jcs-v1"))
        require(canonicalization != "jcs-v1" or media_type == "application/json")
        if canonicalization == "jcs-v1":
            # Canonicalize validates strict JSON and proves the supplied bytes do
            # not merely claim a canonical form.
            require(canonicalize(content, maximum) == content)

        descriptor = {
            "digest": raw_digest(content),
            "size_bytes": len(content),
            "media_type": media_type,
            "canonicalization": canonicalization,
        }
        begin = self._request("engine.artifact_begin", {
            "purpose": purpose,
            "artifact": descriptor,
        }, purpose)
        upload_id = begin["upload_id"]
        offset = 0
        while offset < len(content):
            part = content[offset:offset + PART_LIMIT]
            result = self._request("engine.artifact_put_part", {
                "upload_id": upload_id,
                "offset": offset,
                "content": base64.b64encode(part).decode("ascii"),
            }, purpose)
            require(result["next_offset"] == offset + len(part))
            offset = result["next_offset"]
        committed = self._request("engine.artifact_commit", {"upload_id": upload_id}, purpose)
        require(committed["purpose"] == purpose and committed["artifact"] == descriptor)
        receipt_id = committed["artifact_receipt"]
        require(receipt_id not in self._artifacts)
        retained = len(content) <= self.maximum_cache_bytes - self._cache_bytes
        artifact = CommittedArtifact(receipt_id, purpose, retained=retained, **descriptor)
        self._artifacts[receipt_id] = artifact
        if retained:
            self._content[receipt_id] = content
            self._cache_bytes += len(content)
        return artifact

    def artifact(self, receipt_id):
        require(receipt_id in self._artifacts)
        return self._artifacts[receipt_id]

    def content(self, receipt_id):
        """Return exact committed bytes or explicitly fail when not retained."""
        require(receipt_id in self._artifacts)
        if receipt_id not in self._content:
            raise ContractError("ARTIFACT_UNAVAILABLE")
        return self._content[receipt_id]
