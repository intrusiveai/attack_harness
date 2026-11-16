"""Consume Operator-owned direct-target schemas without choosing a destination."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from operator_contracts import ContractError, Protocol
from test_attempts import Client


class HTTPContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(source)
        cls.fixture = json.loads((source / 'fixtures/http-capability-chain.json').read_text())

    def test_direct_target_capability_fixture_and_obsolete_identifiers(self):
        public = self.fixture['public']
        schema = 'urn:operator:schema:target-capability-manifest:v1alpha1'
        self.protocol._catalog.validate_value(schema, public)
        self.assertEqual(public['source']['adapter'], 'http/v1')
        self.assertEqual(public['capabilities']['adapter'], 'http/v1')
        self.assertNotIn(self.fixture['mapping']['origin'], json.dumps(public))
        self.assertEqual(public['capabilities']['features'], [])
        self.assertEqual(public['capabilities']['actions'], [])
        for fields in [('source',), ('capabilities',), ('source', 'capabilities')]:
            with self.subTest(fields=fields):
                changed = deepcopy(public)
                for field in fields:
                    changed[field]['adapter'] = 'https/v1'
                with self.assertRaises(ContractError):
                    self.protocol._catalog.validate_value(schema, changed)

    def test_direct_target_timeout_retains_execution_outcome(self):
        result = Client('failed').request('engine.attempt_execute', {}, operation_id='attempt-1').result
        result['status'] = 'unknown'
        result['invocation_state'] = 'unknown'
        result['retry_disposition'] = 'host-reconciliation-required'
        result['timeout'] = {
            'native_operation': 'http.invoke', 'attempt_allowance_ms': 30000,
            'elapsed_ms': 30001, 'deadline_source': 'attempt',
            'observation_collection': 'not-started',
        }
        schema = 'urn:operator:schema:engine-attempt-result:v1alpha2'
        self.protocol._catalog.validate_value(schema, result)
        result['timeout']['native_operation'] = 'https.invoke'
        with self.assertRaises(ContractError):
            self.protocol._catalog.validate_value(schema, result)


if __name__ == '__main__':
    unittest.main()
