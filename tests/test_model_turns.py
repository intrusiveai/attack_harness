import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.validation import decode, ORDINARY_LIMIT

from attack_harness.model_turns import native_batch
from attack_harness.tools import ToolResult


CASES = (
    ("model-codec.json", "multiple native tools"),
    ("responses-model-codec.json", "responses: parallel call batch"),
    ("anthropic-model-codec.json", "anthropic: multiple tools"),
    ("bedrock-model-codec.json", "bedrock: multiple tools"),
    ("gemini-model-codec.json", "gemini: multiple same-name tools without IDs"),
)


class ModelTurnsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.source)

    def fixture(self, filename, name):
        cases = decode((self.source / "fixtures" / filename).read_bytes(), ORDINARY_LIMIT)
        case = next(item for item in cases if item["name"] == name)
        return tuple(_canonical_value(case[key], ORDINARY_LIMIT)
                     for key in ("policy", "request", "result"))

    def test_all_installed_codecs_extract_and_continue_native_batches(self):
        for filename, name in CASES:
            with self.subTest(filename=filename):
                batch = native_batch(self.protocol, *self.fixture(filename, name))
                self.assertEqual(batch.disposition, "tool-calls")
                self.assertEqual(len(batch.calls), 2)
                self.assertEqual([call.name for call in batch.calls],
                                 ["snapshot_list", "snapshot_list"])
                results = [ToolResult(call.call_id, call.name, '{"status":"ok"}', "success")
                           for call in batch.calls]
                continuation = batch.continuation(results)
                self.assertIsInstance(continuation, bytes)
                self.assertGreater(len(continuation), 10)

    def test_unknown_usage_never_exposes_calls(self):
        cases = json.loads((self.source / "fixtures/model-codec.json").read_text())
        case = next(item for item in cases if item["name"] == "missing usage is explicit unknown")
        with self.assertRaisesRegex(ContractError, "usage unknown"):
            native_batch(self.protocol, *(_canonical_value(case[key], ORDINARY_LIMIT)
                                           for key in ("policy", "request", "result")))

    def test_uncorrelated_exchange_never_exposes_calls(self):
        cases = decode((self.source / "fixtures/model-codec.json").read_bytes(), ORDINARY_LIMIT)
        case = next(item for item in cases if item["name"] == "multiple native tools")
        case["request"]["request"]["model"] = "changed-model"
        with self.assertRaises(ContractError):
            native_batch(self.protocol, *(_canonical_value(case[key], ORDINARY_LIMIT)
                                           for key in ("policy", "request", "result")))

    def test_text_has_no_calls_and_mismatched_results_cannot_continue(self):
        cases = json.loads((self.source / "fixtures/model-codec.json").read_text())
        case = next(item for item in cases if item["name"] == "native text and usage preserved")
        batch = native_batch(self.protocol, *(_canonical_value(case[key], ORDINARY_LIMIT)
                                               for key in ("policy", "request", "result")))
        self.assertEqual(batch.disposition, "text")
        self.assertEqual(batch.calls, ())

        tool_batch = native_batch(self.protocol, *self.fixture(*CASES[0]))
        wrong = [ToolResult("wrong", "snapshot_list", "{}", "success") for _ in tool_batch.calls]
        with self.assertRaises(ContractError):
            tool_batch.continuation(wrong)


if __name__ == "__main__":
    unittest.main()
