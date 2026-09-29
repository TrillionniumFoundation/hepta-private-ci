#!/usr/bin/env python3
"""Tests for the Cargo lockfile integrity verifier."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_cargo_lock.py")
SPEC = importlib.util.spec_from_file_location("verify_cargo_lock", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CargoLockVerifierTests(unittest.TestCase):
    def test_current_lockfile_has_expected_shape(self) -> None:
        count = MODULE.verify_lockfile(MODULE.DEFAULT_LOCKFILE)
        self.assertGreaterEqual(count, len(MODULE.REQUIRED_PACKAGES))

    def test_python_310_fallback_parses_current_lockfile(self) -> None:
        document = MODULE.DEFAULT_LOCKFILE.read_text(encoding="utf-8")
        parsed = MODULE.parse_cargo_lock_subset(
            document, source=str(MODULE.DEFAULT_LOCKFILE)
        )
        packages = parsed.get("package")
        self.assertIsInstance(packages, list)
        self.assertGreaterEqual(len(packages), len(MODULE.REQUIRED_PACKAGES))

    def test_truncation_marker_is_rejected_as_invalid_toml(self) -> None:
        document = MODULE.DEFAULT_LOCKFILE.read_text(encoding="utf-8")
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.validate_lock_document(
                "Warning: truncated output (original token count: 103930)\n" + document
            )

    def test_fallback_rejects_truncated_array(self) -> None:
        with self.assertRaisesRegex(
            MODULE.VerificationFailure, "truncated multiline array"
        ):
            MODULE.parse_cargo_lock_subset(
                'version = 4\n[[package]]\nname = "x"\nversion = "1"\ndependencies = [\n "y",\n',
                source="truncated.lock",
            )

    def test_dependency_count_can_change_but_duplicate_identity_is_rejected(self) -> None:
        document = MODULE.DEFAULT_LOCKFILE.read_text(encoding="utf-8")
        self.assertGreater(
            MODULE.validate_lock_document(
                document
                + '\n[[package]]\nname = "synthetic-extra"\nversion = "0.0.0"\n'
            ),
            len(MODULE.REQUIRED_PACKAGES),
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "duplicate package identity"):
            MODULE.validate_lock_document(
                document
                + '\n[[package]]\nname = "codex-hepta-types"\nversion = "0.0.0"\n'
            )

    def test_missing_required_package_is_rejected(self) -> None:
        document = MODULE.DEFAULT_LOCKFILE.read_text(encoding="utf-8")
        with self.assertRaisesRegex(
            MODULE.VerificationFailure, "missing required packages"
        ):
            MODULE.validate_lock_document(
                document.replace(
                    'name = "codex-hepta-ndu"',
                    'name = "codex-hepta-ndu-missing"',
                    1,
                )
            )


if __name__ == "__main__":
    unittest.main()
