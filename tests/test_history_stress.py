"""Bounded stress histories across every supported native model codec."""
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value, raw_digest
from attack_harness.adaptive import NativeConversation


class HistoryStressTest(unittest.TestCase):
    def test_repeated_large_histories_compact_without_losing_task_or_provenance(self):
        root = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        protocol = Protocol(root)
        for filename in ("model-codec.json", "responses-model-codec.json",
                         "anthropic-model-codec.json", "bedrock-model-codec.json",
                         "gemini-model-codec.json"):
            with self.subTest(codec=filename):
                cases = json.loads((root / "fixtures" / filename).read_text())
                case = next(c for c in cases if c["mode"] == "context" and c["valid"])
                policy = _canonical_value(case["policy"], 4 << 20)
                conversation = NativeConversation(protocol, policy,
                    "Required objective and immutable reference handles.", compact_at=512 << 10)
                for generation in range(1, 4):
                    for index in range(200):
                        text = f"Retained segment {generation}/{index}: " + "x" * 3000
                        if conversation.codec == "gemini-text-tools-v1":
                            segment = [{"role":"user", "parts":[{"text":text}]}]
                        elif conversation.codec == "bedrock-converse-text-tools-v1":
                            segment = [{"role":"user", "content":[{"text":text}]}]
                        else:
                            segment = [{"role":"user", "content":text}]
                        conversation.extend(_canonical_value(segment, 4 << 20))
                    self.assertTrue(conversation.needs_compaction())
                    _, before = conversation.body()
                    self.assertGreater(len(before), 512 << 10)
                    body, raw, digest, omitted = conversation.compaction_body()
                    self.assertEqual(omitted, 200)
                    history = conversation._request[conversation._history_field()]
                    if conversation.codec == "openai-chat-text-tools-v1":
                        history = history[1:]
                    self.assertEqual(digest, raw_digest(_canonical_value(history, 4 << 20)))
                    protocol.validate_model_request(policy, raw)
                    request = body["request"]
                    if conversation.codec == "bedrock-converse-text-tools-v1":
                        self.assertNotIn("toolConfig", request)
                    elif conversation.codec == "gemini-text-tools-v1":
                        self.assertEqual(request["toolConfig"]["functionCallingConfig"]["mode"], "NONE")
                    elif conversation.codec == "anthropic-messages-text-tools-v1":
                        self.assertEqual(request["tool_choice"], {"type":"none"})
                    else:
                        self.assertEqual(request["tool_choice"], "none")
                    conversation.apply_compaction("Prior observations remain uncertain.", digest, omitted)
                    _, after = conversation.body()
                    self.assertLess(len(after), 64 << 10)
                    self.assertIn(b"Required objective and immutable reference handles.", after)
                    self.assertIn(b"model-generated-not-evidence", after)
                    self.assertIn(digest.encode(), after)
                    self.assertEqual(conversation._compactions[-1]["generation"], generation)
                    self.assertFalse(conversation.needs_compaction())


if __name__ == "__main__":
    unittest.main()
