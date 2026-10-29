"""Exercise Operator's database fixtures through Harness dispatch and feedback."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from operator_contracts import Protocol
from operator_contracts.loop import HarnessLoop
from attack_harness.attempts import AttemptExecutor
from attack_harness.handlers import FixedHandlers
from attack_harness.observations import ObservationReader
from attack_harness.tools import Dispatcher, ToolCall
from build.prepare_release import CODECS
from test_attempts import Client, LIMITS, Reply
from test_observations import ObservationClient


class DatabaseContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(source)
        fixtures = json.loads((source / 'fixtures/model-tools.json').read_text())
        cls.cases = [case for case in fixtures if case['name'].startswith('database ')]
        if not cls.cases or not any(case['valid'] for case in cls.cases):
            raise AssertionError('The locked package must contain database fixtures')

    def executor(self, client=None):
        client = client or Client()
        loop = HarnessLoop(LIMITS)
        executor = AttemptExecutor(self.protocol, client, None, {}, {'scenarios': []}, loop)
        dispatcher = Dispatcher(self.protocol, loop, {}, raw_handlers={'attempt_execute': executor})
        return client, loop, executor, dispatcher

    def test_shared_database_cases_dispatch_once_or_reject_before_host_contact(self):
        for case in self.cases:
            with self.subTest(case=case['name']):
                client, loop, executor, dispatcher = self.executor()
                call = ToolCall('database-call', 'attempt_execute', json.dumps(case['arguments']).encode(), batch_id='batch-1')
                loop.begin_model()
                result = dispatcher.dispatch([call])[0]
                self.assertEqual(result.outcome, 'success' if case['valid'] else 'invalid')
                if case['valid']:
                    self.assertEqual(client.requests[0][1], case['arguments'])
                    executor(call)
                    self.assertEqual(len(client.requests), 1)
                    self.assertEqual(executor.receipts, {'receipt-1'})
                else:
                    self.assertEqual(client.requests, [])
                    error = json.loads(result.content)
                    self.assertEqual(error['effect_state'], 'none')
                    self.assertTrue(error['diagnostic']['resubmission_safe'])

    def test_all_provider_projections_accept_the_same_database_requests(self):
        for codec in CODECS:
            tools = json.loads(self.protocol.model_tools(codec, ['engine.attempt_execute', 'engine.injection_delete']))
            if codec.startswith('openai-chat'):
                schema = tools[0]['function']['parameters']
            elif codec.startswith('anthropic'):
                schema = tools[0]['input_schema']
            elif codec.startswith('bedrock'):
                schema = tools[0]['toolSpec']['inputSchema']['json']
            elif codec.startswith('gemini'):
                schema = tools[0]['functionDeclarations'][0]['parametersJsonSchema']
            else:
                schema = tools[0]['parameters']
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            for case in self.cases:
                with self.subTest(codec=codec, case=case['name']):
                    self.assertEqual(validator.is_valid(case['arguments']), case['valid'])

    def test_injection_fields_are_absent_without_the_admitted_injection_capability(self):
        tools = json.loads(self.protocol.model_tools('openai-chat-text-tools-v1', ['engine.attempt_execute']))
        schema = tools[0]['function']['parameters']
        for field in ('pre_actions', 'injection_input', 'retain_injections'):
            self.assertNotIn(field, schema['properties'])
        body = next(case['arguments'] for case in self.cases if case['valid'])
        self.assertFalse(Draft202012Validator(schema).is_valid(body))

    def test_state_selector_keeps_composite_json_key_and_host_policy_rejection(self):
        body = deepcopy(next(case['arguments'] for case in self.cases if case['valid']))
        parameters = body['pre_actions'][0]['parameters']
        parameters.update(surface='environment_state', mode='fidelity',
            selector={'service': 'database', 'collection': 'documents',
                      'key': '{"tenant":"one", "id":7}'},
            placement={'operation': 'replace', 'pointer': '/body'})
        error = {'code': 'POLICY_DENIED', 'message': 'Database field is not writable.',
                 'effect_state': 'none', 'disposition': 'correct-and-resubmit'}
        class Denied(Client):
            def request(self, operation, body, *, operation_id):
                self.requests.append((operation, body, operation_id))
                return Reply(error=deepcopy(error))
        client, loop, executor, dispatcher = self.executor(Denied())
        loop.begin_model()
        result = dispatcher.dispatch([ToolCall('state', 'attempt_execute', json.dumps(body).encode())])[0]
        self.assertEqual(result.outcome, 'preflight-rejected')
        self.assertEqual(client.requests[0][1], body)
        self.assertEqual(json.loads(result.content), {'status': 'error', **error})
        self.assertFalse(executor.receipts)
        self.assertFalse(executor.dispatched)

    def test_live_database_oracle_bytes_are_preserved_across_reads(self):
        content = b'{"detector_id":"opaque-1","detector_kind":"database_query_match","fired":true}'
        client = ObservationClient(content, 'application/json')
        reader = ObservationReader(client)
        first = reader.read_all('old-receipt', 'oracle-entry')
        self.assertEqual(first.content, content)
        self.assertEqual(reader.read_all('old-receipt', 'oracle-entry'), first)
        # A changed source cannot silently replace a retained receipt's identity.
        client.digest = 'sha256:' + '0' * 64
        from operator_contracts import ContractError
        with self.assertRaises(ContractError):
            reader.read_all('old-receipt', 'oracle-entry')

    def test_unavailable_oracle_reason_reaches_model_without_becoming_negative(self):
        class Unavailable(ObservationClient):
            def request(self, operation, body, *, operation_id):
                reply = super().request(operation, body, operation_id=operation_id)
                reply.result['reason'] = 'oracle_evaluation_unavailable'
                return reply
        client = Unavailable(b'', available=False)
        loop = HarnessLoop(LIMITS)
        handlers = FixedHandlers(self.protocol, None, client, loop)
        result = handlers.observation_read({'receipt_id': 'receipt', 'entry_id': 'oracle', 'offset': 0, 'max_bytes': 256})
        self.assertEqual(result.value['availability'], 'unavailable')
        self.assertEqual(result.value['reason'], 'oracle_evaluation_unavailable')
        self.assertIsNone(result.value['artifact'])
        self.assertEqual(base64.b64decode(result.value['content']), b'')
        self.assertNotIn('fired', result.value)


if __name__ == '__main__': unittest.main()
