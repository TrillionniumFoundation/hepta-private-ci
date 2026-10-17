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

DOC_SPEC = importlib.util.spec_from_file_location(
    "documentation_gate",
    ROOT / "scripts" / "check_platform_types_documentation_contract.py",
)
assert DOC_SPEC is not None and DOC_SPEC.loader is not None
DOC_MODULE = importlib.util.module_from_spec(DOC_SPEC)
DOC_SPEC.loader.exec_module(DOC_MODULE)


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

    def test_does_not_cross_constructor_argument_or_later_statement(self) -> None:
        source = """
        let digest = Digest32::of_bytes(
            format!("domain:{value}").as_bytes(),
        );
        let raw = value.as_str().as_bytes();
        """
        self.assertIsNone(MODULE.REMOVED_DIGEST_BYTES.search(source))

    def test_rejects_direct_chain_with_nested_argument_call(self) -> None:
        source = "Digest32::of_bytes(material.as_bytes()).as_bytes()"
        self.assertIsNotNone(MODULE.REMOVED_DIGEST_BYTES.search(source))

    def test_rejects_removed_receiver_with_whitespace(self) -> None:
        source = "Digest32::from_array ( [0; 32] )\n .as_bytes ( )"
        self.assertIsNotNone(MODULE.REMOVED_DIGEST_BYTES.search(source))


class DocumentationAuthorityTests(unittest.TestCase):
    INTRODUCTION = (
        "# Supporting technical guide\n\n"
        "Start with [spec](./SPEC_V2.md), "
        "[status](./IMPLEMENTATION_STATUS.md), and "
        "[migration](./MIGRATION_V1_TO_V2.md).\n"
    )

    def test_accepts_current_navigation_with_later_historical_context(self) -> None:
        source = (
            self.INTRODUCTION + "\n## Metrics\nCURRENT_IMPLEMENTATION.md is archived.\n"
        )
        errors: list[str] = []
        DOC_MODULE.validate_technical_authority(source, errors)
        self.assertEqual(errors, [])

    def test_rejects_archived_current_state_redirect_even_with_current_links(
        self,
    ) -> None:
        source = (
            self.INTRODUCTION
            + "Start with `CURRENT_IMPLEMENTATION.md` for current state.\n"
        )
        errors: list[str] = []
        DOC_MODULE.validate_technical_authority(source, errors)
        self.assertTrue(
            any("archived CURRENT_IMPLEMENTATION.md" in error for error in errors)
        )

    def test_rejects_missing_current_migration_entry(self) -> None:
        source = self.INTRODUCTION.replace(
            "[migration](./MIGRATION_V1_TO_V2.md)", "old migration"
        )
        errors: list[str] = []
        DOC_MODULE.validate_technical_authority(source, errors)
        self.assertTrue(
            any("exactly the three current entries" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
