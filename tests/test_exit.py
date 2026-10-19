"""Production entrypoint and runtime exit semantics; no live model calls."""
from contextlib import ExitStack
import errno
import io
import json
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from operator_contracts import ContractError, Protocol
from operator_contracts.canonical import _canonical_value
from operator_contracts.validation import ORDINARY_LIMIT
from attack_harness import entrypoint
from attack_harness.diagnostics import fatal_diagnostic
from attack_harness.runtime import OrdinaryClient, RuntimeStopped
from attack_harness.fifo import FIFO, LANES
from attack_harness.startup import Startup
from test_runtime import FakeTransport


SECRET = 'synthetic-secret https://secret.invalid/ prompt=response config=private'


class ExitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ['OPERATOR_CONTRACT_SOURCE'])
        cls.protocol = Protocol(source)
        cls.fixtures = {c['name']: c for c in json.loads(
            (source / 'fixtures/ordinary-protocol.json').read_text())}

    def setUp(self):
        self.transport = FakeTransport(self.protocol, self.respond)
        self.client = OrdinaryClient(self.protocol, self.transport, {
            'campaign_id': 'campaign-1', 'launch_id': 'launch-1', 'run_revision': 3,
            'operations': sorted(o['name'] for o in self.protocol.operations())})
        self.output = io.StringIO()

    def respond(self, raw):
        request = self.protocol.validate_request(raw)
        name = 'finish response' if request['operation'] == 'engine.finish' else 'diagnostic report response'
        response = dict(self.fixtures[name]['response'])
        for key in ('campaign_id', 'launch_id', 'run_revision', 'call_id', 'operation_id', 'operation'):
            response[key] = request[key]
        response['seq'] = len(self.transport.sent) - 1
        return _canonical_value(response, ORDINARY_LIMIT)

    def finish(self):
        self.client.request('engine.finish', self.fixtures['finish response']['request']['body'])

    def run_main(self, run, *, bootstrap_error=None, sink=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(entrypoint, 'load_runtime_config', return_value={
                'contract': {}, 'skill_loader_digest': 'sha256:' + '1' * 64}))
            stack.enter_context(patch.object(entrypoint, 'load_contract', return_value=self.protocol))
            stack.enter_context(patch.object(entrypoint, 'transport_from_environment', return_value=self.transport))
            stack.enter_context(patch.dict('sys.modules', {'_confinement': types.SimpleNamespace(install=lambda: None)}))
            startup = stack.enter_context(patch.object(entrypoint, 'Startup'))
            startup.return_value.run.return_value = types.SimpleNamespace(client=self.client)
            startup.return_value.run.side_effect = bootstrap_error
            stack.enter_context(patch.object(entrypoint, 'compose_campaign', return_value=types.SimpleNamespace(run=run)))
            stack.enter_context(patch('sys.stderr', sink if sink is not None else self.output))
            return entrypoint.main()

    def diagnostic(self):
        raw = self.output.getvalue()
        self.assertLessEqual(len(raw.encode()), 1025)
        self.assertEqual(len(raw.splitlines()), 1)
        self.assertNotIn(SECRET, raw)
        self.assertNotIn('https://', raw)
        self.assertNotIn('Traceback', raw)
        return json.loads(raw)

    def test_accepted_finish_ticks_and_redundant_close_are_healthy(self):
        def run():
            self.finish()
            self.client.tick()
            self.client.close()
        self.assertEqual(self.run_main(run), 0)
        self.assertEqual(self.output.getvalue(), '')
        self.assertEqual(len(self.transport.sent), 1)
        self.assertTrue(self.client.finish_accepted)

    def test_post_finish_fatal_is_nonzero_without_another_operation(self):
        def run():
            self.finish()
            raise OSError(errno.EIO, SECRET)
        self.assertEqual(self.run_main(run), 1)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.diagnostic(), {'stage': 'runtime', 'reason': 'io-error',
            'exception': 'OSError', 'message': os.strerror(errno.EIO)})

    def test_actual_close_failure_after_acceptance_still_fails(self):
        with patch.object(self.transport, 'close', side_effect=OSError(errno.EIO, SECRET)):
            self.assertEqual(self.run_main(self.finish), 1)
        self.assertTrue(self.client.finish_accepted)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.diagnostic()['reason'], 'io-error')
        with self.assertRaises(RuntimeStopped):
            self.client.tick()

    def test_runtime_fatal_reports_once_on_healthy_channel_then_exits(self):
        def run():
            raise RuntimeError(SECRET)
        self.assertEqual(self.run_main(run), 1)
        diagnostic = self.diagnostic()
        self.assertEqual(diagnostic['reason'], 'runtime-error')
        self.assertIn('omitted', diagnostic['message'])
        requests = [self.protocol.validate_request(raw) for _, raw in self.transport.sent]
        self.assertEqual([r['operation'] for r in requests], ['engine.diagnostic_report'])
        self.assertEqual(requests[0]['timeout_ms'], 1000)
        self.assertNotIn(SECRET, json.dumps(requests))
        self.assertTrue(self.transport.closed)

    def test_runtime_stopped_and_bootstrap_causes_survive_close_failure(self):
        primary = OSError(errno.EACCES, SECRET)
        wrapped = RuntimeStopped('protocol-error')
        wrapped.__cause__ = primary
        with patch.object(self.transport, 'close', side_effect=ValueError(SECRET)):
            self.assertEqual(self.run_main(lambda: None, bootstrap_error=wrapped), 1)
        diagnostic = self.diagnostic()
        self.assertEqual(diagnostic['stage'], 'bootstrap')
        self.assertEqual(diagnostic['exception'], 'PermissionError')
        self.assertEqual(diagnostic['reason'], 'io-error')
        self.assertEqual(diagnostic['wrapper_reason'], 'protocol-error')
        self.assertIn('secondary_close_error:untrusted', diagnostic['omissions'])
        self.assertEqual(self.transport.sent, [])

    def test_prebootstrap_configuration_failure_retains_stage_and_flushes(self):
        class Sink(io.StringIO):
            flushed = False
            def flush(self):
                self.flushed = True
        sink = Sink()
        with patch.object(entrypoint, 'load_runtime_config', side_effect=ValueError(SECRET)), patch('sys.stderr', sink):
            self.assertEqual(entrypoint.main(), 1)
        self.assertTrue(sink.flushed)
        self.output = sink
        self.assertEqual(self.diagnostic()['stage'], 'configuration')

    def test_stopped_reason_and_failed_diagnostic_sink_do_not_change_exit(self):
        def run():
            self.client.fail('deadline-exceeded')
        self.assertEqual(self.run_main(run), 1)
        self.assertEqual(self.diagnostic()['reason'], 'deadline-exceeded')
        class BrokenSink:
            def write(self, _): raise OSError(errno.EPIPE, SECRET)
            def flush(self): raise OSError(errno.EPIPE, SECRET)
        self.assertEqual(self.run_main(run, sink=BrokenSink()), 1)
        self.assertEqual(self.transport.sent, [])

    def test_failed_report_and_flush_preserve_primary_failure(self):
        def run():
            raise RuntimeError(SECRET)
        class BrokenFlush(io.StringIO):
            def flush(self): raise OSError(errno.EPIPE, SECRET)
        sink = BrokenFlush()
        with patch.object(self.transport, 'pump', side_effect=OSError(errno.EIO, SECRET)):
            self.assertEqual(self.run_main(run, sink=sink), 1)
        self.output = sink
        self.assertEqual(self.diagnostic()['reason'], 'runtime-error')
        self.assertEqual(len(self.transport.sent), 1)

    def test_new_work_after_finish_is_a_failure_without_sending(self):
        def run():
            self.finish()
            self.client.request('engine.finish', self.fixtures['finish response']['request']['body'])
        self.assertEqual(self.run_main(run), 1)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.diagnostic()['stage'], 'runtime')

    def test_fifo_handoff_cleanup_does_not_replace_original_cause(self):
        peer = FIFO.__new__(FIFO)
        peer.closed = peer.pinned = False
        peer.root = 9
        peer.fds = dict(zip(LANES, range(3, 7)))
        primary = OSError(errno.EIO, SECRET)
        with patch('attack_harness.fifo.fcntl.fcntl', side_effect=[70, 71, primary]), \
             patch.object(peer, 'close', side_effect=OSError(errno.EACCES, SECRET)), \
             patch('attack_harness.fifo.os.close', side_effect=OSError(errno.EBADF, SECRET)):
            with self.assertRaises(ContractError) as caught:
                peer.pin_descriptors()
        self.assertIs(caught.exception.__cause__, primary)

    def test_fifo_handoff_cleanup_failure_after_success_is_fatal(self):
        peer = FIFO.__new__(FIFO)
        peer.closed = peer.pinned = False
        peer.root = 9
        peer.fds = dict(zip(LANES, range(3, 7)))
        failure = OSError(errno.EIO, SECRET)
        with patch('attack_harness.fifo.fcntl.fcntl', side_effect=range(70, 75)), \
             patch('attack_harness.fifo.os.dup2'), \
             patch('attack_harness.fifo.os.close', side_effect=[None] * 5 + [failure] * 4):
            with self.assertRaises(OSError) as caught:
                peer.pin_descriptors()
        self.assertTrue(peer.pinned)
        self.assertIs(caught.exception, failure)

    def test_incomplete_run_never_becomes_success(self):
        self.assertEqual(self.run_main(lambda: None), 1)
        self.assertEqual(self.diagnostic()['reason'], 'incomplete-execution')
        self.assertFalse(self.client.finish_accepted)

    def test_transport_and_startup_wrappers_keep_original_io_cause(self):
        for operation in (self.client.tick, Startup(self.protocol, self.transport, 'fifo', '', lambda: None)._pump):
            with self.subTest(operation=operation), patch.object(self.transport, 'pump', side_effect=OSError(errno.EIO, SECRET)), \
                 patch.object(self.transport, 'close', side_effect=ValueError(SECRET)):
                with self.assertRaises(RuntimeStopped) as caught:
                    operation()
                self.assertEqual(caught.exception.__cause__.errno, errno.EIO)
                self.assertEqual(fatal_diagnostic(caught.exception, 'runtime')['message'], os.strerror(errno.EIO))

    def test_untrusted_message_and_reason_are_explicitly_omitted(self):
        error = ContractError(SECRET * 10000)
        error.reason = [SECRET]
        diagnostic = fatal_diagnostic(error, 'runtime')
        self.assertNotIn(SECRET, json.dumps(diagnostic))
        self.assertEqual(diagnostic['omissions'], ['reason:untrusted', 'message:untrusted-or-unavailable'])


if __name__ == '__main__':
    unittest.main()
