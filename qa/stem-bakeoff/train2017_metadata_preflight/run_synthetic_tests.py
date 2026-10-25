#!/usr/bin/env python3
"""Fail on absent/skipped tests; never run the original-metadata CLI."""

from pathlib import Path
import sys
import unittest


def offline(event, _args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("synthetic test runner forbids networking")


if __name__ == "__main__":
    sys.addaudithook(offline)
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).parent), pattern="test_*.py"
    )
    if suite.countTestCases() != 10:
        raise RuntimeError("expected all 10 synthetic test methods")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
