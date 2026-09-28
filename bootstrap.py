"""Literal isolated-mode bootstrap installed at /opt/operator/engine/bootstrap.py."""

import sys

sys.path.insert(0,"/opt/operator/engine/lib")

from attack_harness.entrypoint import main

raise SystemExit(main())
