from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.loop import HarnessLoop

from attack_harness.adaptive import AdaptiveHarness, NativeConversation
from attack_harness.tools import Dispatcher, HandlerResult


LIMITS = {
    "max_model_turns": 20,
    "max_tool_calls": 100,
    "max_tool_calls_per_response": 16,
    "max_invalid_tool_calls": 5,
    "max_consecutive_invalid_tool_calls": 3,
    "max_read_bytes": 1 << 20,
    "max_no_progress_turns": 2,
}


class Reply:
    error = None

    def __init__(self, result):
        self.result = deepcopy(result)


class Client:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []
        self.index = 0

    def operation_id(self, purpose):
        self.index += 1
        return f"{purpose}-{self.index}"

    def request(self, operation, body, *, operation_id):
        self.requests.append(deepcopy(body))
        return Reply(self.results.pop(0))

    def fail(self, reason, *, receipt=None):
        from attack_harness.runtime import RuntimeStopped
        raise RuntimeStopped(reason, receipt=receipt)


class Finalizer:
    pending = False

    def __init__(self):
        self.reason = None

    def finish_unavailable(self, reason):
        self.reason = reason
        return {"status": "accepted", "conclusion_state": "unavailable"}


class AdaptiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["OPERATOR_CONTRACT_SOURCE"])
        cls.protocol = Protocol(cls.root)

    def cases(self, filename):
        return json.loads((self.root / "fixtures" / filename).read_text())

    def test_all_installed_codecs_build_bound_initial_requests(self):
        files = ["model-codec.json", "responses-model-codec.json",
                 "anthropic-model-codec.json", "bedrock-model-codec.json",
                 "gemini-model-codec.json"]
        for filename in files:
            with self.subTest(filename=filename):
                case = next(item for item in self.cases(filename)
                            if item["mode"] == "context" and item["valid"])
                policy_raw = _canonical_value(case["policy"], 4 << 20)
                conversation = NativeConversation(self.protocol, policy_raw,
                                                  "Inspect the admitted target.")
                _, request_raw = conversation.body()
                self.protocol.validate_model_request(policy_raw, request_raw)

    def test_tool_continuation_is_native_and_text_exhaustion_finalizes(self):
        cases = self.cases("model-codec.json")
        tool_case = next(item for item in cases if item["name"] == "multiple native tools")
        text_case = next(item for item in cases
                         if item["name"] == "native text and usage preserved")
        policy_raw = _canonical_value(tool_case["policy"], 4 << 20)
        conversation = NativeConversation(self.protocol, policy_raw, "Inspect the target.")
        loop = HarnessLoop(LIMITS)
        observed = []

        def snapshots(arguments):
            observed.append(arguments)
            return HandlerResult({"status": "ok", "snapshots": []})

        dispatcher = Dispatcher(self.protocol, loop, {"snapshot_list": snapshots})
        client = Client([tool_case["result"], text_case["result"]])
        finalizer = Finalizer()
        result = AdaptiveHarness(self.protocol, client, loop, dispatcher,
                                 conversation, finalizer).run()
        self.assertEqual(result["conclusion_state"], "unavailable")
        self.assertEqual(len(observed), 2)
        self.assertEqual(len(client.requests), 2)
        messages = client.requests[1]["request"]["messages"]
        self.assertEqual(messages[-3]["role"], "assistant")
        self.assertEqual([item["role"] for item in messages[-2:]], ["tool", "tool"])
        self.assertEqual(finalizer.reason, "local-error")
        self.assertEqual(loop.snapshot()["model_turns"], 2)


if __name__ == "__main__":
    unittest.main()
