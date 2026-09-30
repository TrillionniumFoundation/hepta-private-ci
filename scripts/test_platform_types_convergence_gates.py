#!/usr/bin/env python3
"""Unit tests for the lightweight platform.types convergence gates."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_platform_types_legacy_api_usage.py"
SPEC = importlib.util.spec_from_file_location("legacy_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LegacyApiPatternTests(unittest.TestCase):
    def test_rejects_removed_digest_receiver(self) -> None:
        source = "Ok(*Digest32::of_bytes(material.as_bytes()).as_bytes())"
        self.assertIsNotNone(MODULE.REMOVED_DIGEST_BYTES.search(source))

    def test_accepts_current_borrowed_array_receiver(self) -> None:
        source = "Ok(*Digest32::of_bytes(material.as_bytes()).as_array())"
        self.assertIsNone(MODULE.REMOVED_DIGEST_BYTES.search(source))

    def test_does_not_reject_input_string_as_bytes(self) -> None:
        source = "let digest = Digest32::of_bytes(material.as_bytes());"
        self.assertIsNone(MODULE.REMOVED_DIGEST_BYTES.search(source))


if __name__ == "__main__":
    unittest.main()
