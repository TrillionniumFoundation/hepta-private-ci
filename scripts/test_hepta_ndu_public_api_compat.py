#!/usr/bin/env python3
"""Adversarial tests for the utility.ndu public API compatibility gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-ndu-public-api-compat.py"
SPEC = importlib.util.spec_from_file_location("hepta_ndu_public_api_compat", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load public API compatibility gate")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicApiCompatibilityTests(unittest.TestCase):
    def test_repository_baseline_passes(self) -> None:
        completed = subprocess.run(
            ["python3", str(SCRIPT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_private_removed_and_reordered_fields_are_detected(self) -> None:
        source = """
pub struct ReceiptV1 {
    pub alpha: u64,
    pub beta: u64,
}
"""
        self.assertEqual(
            MODULE.extract_public_fields(source, "ReceiptV1"),
            ["alpha", "beta"],
        )
        self.assertNotEqual(
            MODULE.extract_public_fields(
                source.replace("pub beta", "beta"), "ReceiptV1"
            ),
            ["alpha", "beta"],
        )
        self.assertNotEqual(
            MODULE.extract_public_fields(
                source.replace("pub alpha: u64,\n    pub beta", "pub beta: u64,\n    pub alpha"),
                "ReceiptV1",
            ),
            ["alpha", "beta"],
        )

    def test_unterminated_or_missing_struct_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.extract_public_fields("pub struct ReceiptV1 {", "ReceiptV1")
        with self.assertRaises(ValueError):
            MODULE.extract_public_fields("pub struct Other {}", "ReceiptV1")


if __name__ == "__main__":
    unittest.main()
