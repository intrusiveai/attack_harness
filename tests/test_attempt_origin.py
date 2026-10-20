"""Consume Operator origin fixtures through the actual Harness dispatch path."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from operator_contracts import Protocol
from operator_contracts.loop import HarnessLoop
from attack_harness.attempts import AttemptExecutor
from attack_harness.tools import Dispatcher, ToolCall
from test_attempts import Client, LIMITS, Reply


class AttemptOriginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(source)
        cls.fixture = json.loads((source / 'fixtures/attempt-origin.json').read_text())

    def handler(self, client=None):
        client = client or Client()
        loop = HarnessLoop(LIMITS)
        bundle = {'scenarios': [{'scenario_id': name} for name in self.fixture['scenarios']]}
        executor = AttemptExecutor(self.protocol, client, None, {}, bundle, loop)
        dispatcher = Dispatcher(self.protocol, loop, {}, raw_handlers={'attempt_execute': executor})
        return client, loop, executor, dispatcher

    def body(self, origin):
        return {**deepcopy(origin), 'operation_id': 'invoke',
                'input': {'encoding': 'json', 'value': {'prompt': 'Reply exactly QA_CONFIG_OK. Do not call tools.'}}}

    def dispatch(self, loop, dispatcher, body, call_id='invoke'):
        loop.begin_model()
        return dispatcher.dispatch([ToolCall(call_id, 'attempt_execute', json.dumps(body).encode(), batch_id=call_id)])[0]

    def test_shared_fixtures_preserve_origin_or_reject_without_dispatch(self):
        for case in self.fixture['cases']:
            with self.subTest(case=case['name']):
                client, loop, executor, dispatcher = self.handler()
                body = self.body(case['body'])
                result = self.dispatch(loop, dispatcher, body)
                value = json.loads(result.content)
                if case.get('valid'):
                    self.assertEqual(result.outcome, 'success')
                    self.assertEqual(client.requests[0][1], body)
                    self.assertEqual(len(client.requests), 1)
                else:
                    self.assertEqual(result.outcome, 'invalid')
                    self.assertEqual(value['code'], 'INVALID_ARGUMENTS')
                    self.assertEqual(value['effect_state'], 'none')
                    self.assertEqual(value['disposition'], 'correct-and-resubmit')
                    d = value['diagnostic']
                    self.assertEqual((d['reason'], d['field_path']), (case['reason'], case['path']))
                    self.assertTrue(d['message'] and d['correction'])
                    self.assertEqual(d['execution_occurred'], 'no')
                    self.assertTrue(d['resubmission_safe'])
                    self.assertEqual(client.requests, [])
                    self.assertEqual(client.index, 0)
                    self.assertFalse(executor.receipts)
                    self.assertEqual(executor.reference_category('invoke'), 'rejected submission')

    def test_missing_origin_is_correctable_without_defaulting_the_only_scenario(self):
        client, loop, executor, dispatcher = self.handler()
        body = self.body({'scenario_id': 'configuration'})
        rejected = self.dispatch(loop, dispatcher, body, 'bad')
        self.assertEqual(json.loads(rejected.content)['diagnostic']['field_path'], '/origin')
        self.assertEqual(client.requests, [])
        body['origin'] = 'scenario'
        accepted = self.dispatch(loop, dispatcher, body, 'corrected')
        self.assertEqual(accepted.outcome, 'success')
        self.assertEqual(client.requests[0][1], body)
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(executor.reference_category('bad') == 'execution receipt')

    def test_authoritative_host_error_is_preserved_and_correction_gets_new_identity(self):
        error = {'code': 'INVALID_ARGUMENTS', 'message': 'Select a scenario from the submitted bundle.',
                 'effect_state': 'none', 'disposition': 'correct-and-resubmit', 'diagnostic': {
                     'source': 'operator', 'stage': 'arguments', 'reason': 'unknown_scenario',
                     'field_path': '/scenario_id', 'message': 'Unknown scenario.',
                     'correction': 'Select a submitted scenario.', 'execution_occurred': 'no', 'resubmission_safe': True}}
        class RejectOnce(Client):
            def request(self, operation, body, *, operation_id):
                if not self.requests:
                    self.requests.append((operation, body, operation_id))
                    return Reply(error=deepcopy(error))
                return super().request(operation, body, operation_id=operation_id)
        client, loop, executor, dispatcher = self.handler(RejectOnce())
        body = self.body({'origin': 'scenario', 'scenario_id': 'configuration'})
        rejected = self.dispatch(loop, dispatcher, body, 'first')
        self.assertEqual(json.loads(rejected.content), {'status': 'error', **error})
        self.assertFalse(executor.receipts)
        self.assertEqual(self.dispatch(loop, dispatcher, body, 'corrected').outcome, 'success')
        self.assertNotEqual(client.requests[0][2], client.requests[1][2])
        self.assertEqual(executor.receipts, {'receipt-1'})

    def test_all_five_provider_projections_require_origin_and_describe_the_choice(self):
        codecs = ('openai-chat-text-tools-v1', 'openai-responses-text-tools-v1',
                  'anthropic-messages-text-tools-v1', 'bedrock-converse-text-tools-v1', 'gemini-text-tools-v1')
        for codec in codecs:
            with self.subTest(codec=codec):
                tools = json.loads(self.protocol.model_tools(codec, ['engine.attempt_execute']))
                if codec.startswith('openai-chat'):
                    tool = tools[0]['function']; schema = tool['parameters']
                elif codec.startswith('anthropic'):
                    tool = tools[0]; schema = tool['input_schema']
                elif codec.startswith('bedrock'):
                    tool = tools[0]['toolSpec']; schema = tool['inputSchema']['json']
                elif codec.startswith('gemini'):
                    tool = tools[0]['functionDeclarations'][0]; schema = tool['parametersJsonSchema']
                else:
                    tool = tools[0]; schema = tool['parameters']
                self.assertEqual(tool['name'], 'attempt_execute')
                self.assertIn('origin', schema['required'])
                self.assertIn('scenario', tool['description'])
                self.assertIn('exploratory', tool['description'])
                Draft202012Validator.check_schema(schema)
                validator = Draft202012Validator(schema)
                for origin in ({'origin': 'scenario', 'scenario_id': 'configuration'}, {'origin': 'exploratory'}):
                    validator.validate(self.body(origin))
                self.assertFalse(validator.is_valid(self.body({})))

    def test_trusted_prompt_example_is_valid_and_does_not_infer_origin(self):
        prompt = (Path(__file__).resolve().parents[1] / 'assets/default-system-prompt.txt').read_text()
        example = next(line.removeprefix('Example: ') for line in prompt.splitlines() if line.startswith('Example: '))
        arguments = self.protocol.validate_tool_arguments('attempt_execute', example.encode())
        self.assertEqual((arguments['origin'], arguments['scenario_id']), ('scenario', 'configuration'))
        self.assertIn('linking their evidence to an objective at finish does not change origin', prompt)


if __name__ == '__main__': unittest.main()
