#!/usr/bin/env python3
"""Strict native qualification from an importable multiprocessing entry point."""

import os
from pathlib import Path
import signal
import unittest

import trusted_executor


def main() -> int:
    trusted_executor._require_procfs_namespace()
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise SystemExit("Linux pidfd process containment is required")
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"))
    if not suite.countTestCases():
        raise SystemExit("Native OS evidence qualification requires tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        raise SystemExit("Native OS evidence qualification cannot skip tests")
    return 0 if result.wasSuccessful() else 1


# A spawned bundle-inspection worker imports this file as __mp_main__. Running
# the suite there would recursively launch workers. A stdin main is also invalid:
# spawn cannot reload <stdin> as a source file.
if __name__ == "__main__":
    raise SystemExit(main())
