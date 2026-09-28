"""Receipt-scoped observation reads and bounded full-content verification."""

import base64
import binascii
import codecs
from dataclasses import dataclass
import hashlib

from operator_contracts import ContractError
from operator_contracts.startup import require


CHUNK_LIMIT = 256 << 10


class ObservationRejected(ContractError):
    def __init__(self, error):
        super().__init__("observation read rejected")
        self.error = error


@dataclass(frozen=True)
class ObservationChunk:
    receipt_id: str
    entry_id: str
    offset: int
    content: bytes
    eof: bool
    availability: str
    artifact: dict | None
    truncated: bool
    reason: str


@dataclass(frozen=True)
class ObservationContent:
    receipt_id: str
    entry_id: str
    content: bytes
    text: str | None
    artifact: dict
    truncated: bool
    reason: str


def _bytes(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ContractError("invalid observation content") from None
    require(base64.b64encode(raw).decode("ascii") == encoded)
    return raw


def _textual(media_type):
    return media_type.startswith("text/") or media_type in {
        "application/json", "application/yaml", "application/xml",
        "application/problem+json",
    }


class ObservationReader:
    def __init__(self, client):
        self.client = client
        self._metadata = {}

    def observed(self, receipt_id, entry_id):
        return (receipt_id, entry_id) in self._metadata

    def read(self, receipt_id, entry_id, offset, max_bytes=CHUNK_LIMIT):
        require(type(offset) is int and offset >= 0)
        require(type(max_bytes) is int and 0 < max_bytes <= CHUNK_LIMIT)
        reply = self.client.request("engine.observation_read", {
            "receipt_id": receipt_id,
            "entry_id": entry_id,
            "offset": offset,
            "max_bytes": max_bytes,
        }, operation_id=self.client.operation_id("observation-read"))
        if reply.error is not None:
            raise ObservationRejected(reply.error)
        result = reply.result
        content = _bytes(result["content"])
        require(result["receipt_id"] == receipt_id and result["entry_id"] == entry_id)
        require(result["offset"] == offset and result["raw_length"] == len(content))
        require(len(content) <= max_bytes)
        artifact = result.get("artifact")
        if result["availability"] == "available":
            require(artifact is not None)
            require(offset + len(content) <= artifact["size_bytes"])
            require(result["eof"] == (offset + len(content) == artifact["size_bytes"]))
        else:
            require(not content and not result["eof"] and artifact is None)
        metadata = (result["availability"], artifact, result["truncated"], result.get("reason", ""))
        key = (receipt_id, entry_id)
        previous = self._metadata.setdefault(key, metadata)
        require(previous == metadata)
        return ObservationChunk(receipt_id, entry_id, result["offset"], content,
                                result["eof"], result["availability"], artifact,
                                result["truncated"], result.get("reason", ""))

    def read_all(self, receipt_id, entry_id, *, maximum_bytes=16 << 20):
        require(type(maximum_bytes) is int and 0 <= maximum_bytes <= 1 << 30)
        parts = []
        offset = 0
        digest = hashlib.sha256()
        decoder = None
        text_parts = []
        artifact = None
        truncated = False
        reason = ""
        while True:
            remaining = maximum_bytes - offset
            require(remaining >= 0)
            chunk = self.read(receipt_id, entry_id, offset, min(CHUNK_LIMIT, max(1, remaining)))
            require(chunk.offset == offset)
            if chunk.availability != "available":
                require(not chunk.content and not chunk.eof and chunk.artifact is None)
                raise ContractError("observation content unavailable")
            require(chunk.artifact is not None)
            artifact = chunk.artifact
            require(artifact["size_bytes"] <= maximum_bytes)
            if decoder is None and _textual(artifact["media_type"]):
                decoder = codecs.getincrementaldecoder("utf-8")("strict")
            digest.update(chunk.content)
            parts.append(chunk.content)
            if decoder is not None:
                try:
                    text_parts.append(decoder.decode(chunk.content, final=chunk.eof))
                except UnicodeError:
                    raise ContractError("invalid observation text") from None
            offset += len(chunk.content)
            require(offset <= maximum_bytes)
            truncated, reason = chunk.truncated, chunk.reason
            if chunk.eof:
                break
            require(chunk.content)
        require(artifact is not None and offset == artifact["size_bytes"])
        require("sha256:" + digest.hexdigest() == artifact["digest"])
        return ObservationContent(receipt_id, entry_id, b"".join(parts),
                                  None if decoder is None else "".join(text_parts),
                                  artifact, truncated, reason)
