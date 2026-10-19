"""Test-only fault adapter around Operator's real-process launch fixture."""
import errno
import json
import os
from pathlib import Path
import runpy
import sys

config = json.loads(Path(sys.argv[1]).read_text())
sys.path[:0] = [config['harness'] + '/src', config['package'] + '/source/contracts/python']
from attack_harness.composition import Campaign

original = Campaign.run
mode = os.environ.get('HARNESS_TEST_EXIT_MODE', '')


def controlled_run(self):
    if mode == 'runtime-fatal':
        raise OSError(errno.EIO, 'synthetic-secret https://secret.invalid/ prompt=response')
    result = original(self)
    if mode == 'post-finish-fatal':
        raise OSError(errno.EIO, 'synthetic-secret https://secret.invalid/ prompt=response')
    if mode == 'healthy-unwind':
        self.adaptive.client.tick()
        self.adaptive.client.close()
    return result


Campaign.run = controlled_run
runpy.run_path(sys.argv[2], run_name='__main__')
