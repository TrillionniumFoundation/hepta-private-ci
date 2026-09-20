"""Behavioral regressions for semantic readiness checks, not prose quotas."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).with_name("hepta-readiness.py")
SPEC = importlib.util.spec_from_file_location("readiness_semantics_under_test", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("readiness verifier could not be loaded")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ReadinessSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "guide.md"
        self.row = {
            "id": "RDY-TEST",
            "path": "guide.md",
            "requiredSections": ["## Interface"],
            "protocols": ["FixtureProtocolV1"],
            "gapIds": ["GAP-TEST"],
        }
        self.text = (
            "# Bounded fixture\n\n## Interface\n"
            "FixtureProtocolV1 consumes the existing owner fact.\n\n"
            "## Appendix A. Closed gap and protocol mapping\n"
            "GAP-TEST -> FixtureProtocolV1.\n"
        )
        self.path.write_text(self.text, encoding="utf-8")

    def verify(self, protocols=None, gaps=None):
        with patch.object(VERIFIER, "ROOT", self.root):
            VERIFIER.validate_markdown_document(
                self.row,
                {"FixtureProtocolV1"} if protocols is None else protocols,
                {"GAP-TEST"} if gaps is None else gaps,
            )

    def test_concise_contract_guide_is_not_rejected_by_arbitrary_size(self):
        self.assertLess(len(self.text), 5000)
        self.verify()

    def test_explicit_follow_up_marker_is_not_a_fabricated_closure(self):
        self.path.write_text(self.text + "\nTODO: independent operational acceptance.\n")
        self.verify()

    def test_missing_required_contract_section_still_rejects(self):
        self.path.write_text(self.text.replace("## Interface", "## Notes"))
        with self.assertRaisesRegex(SystemExit, "sections"):
            self.verify()

    def test_unknown_or_uncited_protocol_and_gap_still_reject(self):
        for protocols, gaps, message in [
            (set(), {"GAP-TEST"}, "unknown protocol"),
            ({"FixtureProtocolV1"}, set(), "unknown gap"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(SystemExit, message):
                    self.verify(protocols, gaps)
        for omitted, message in [
            ("FixtureProtocolV1", "protocol not cited"),
            ("GAP-TEST", "gap not cited"),
        ]:
            self.path.write_text(self.text.replace(omitted, "omitted"))
            with self.subTest(omitted=omitted):
                with self.assertRaisesRegex(SystemExit, message):
                    self.verify()

    def test_module_guide_edit_needs_no_prose_digest_or_section_inventory(self):
        self.path.write_text("# Owner guide\n\nAn explanation with a revised heading.\n")
        VERIFIER.validate_module_guide(self.path, "fixture.module")

    def test_empty_or_missing_module_guide_still_rejects(self):
        self.path.write_text(" \n")
        with self.assertRaisesRegex(SystemExit, "empty module guide"):
            VERIFIER.validate_module_guide(self.path, "fixture.module")
        self.path.unlink()
        with self.assertRaisesRegex(SystemExit, "module guide missing"):
            VERIFIER.validate_module_guide(self.path, "fixture.module")

    def test_authority_metadata_accepts_key_permutation_not_key_substitution(self):
        flags = dict.fromkeys(reversed(VERIFIER.AUTHORITY_KEYS), False)
        VERIFIER.false_authority(flags, "fixture")
        flags["unknown"] = flags.pop("merge")
        with self.assertRaisesRegex(SystemExit, "key closure"):
            VERIFIER.false_authority(flags, "fixture")

    def test_falsey_non_boolean_and_positive_authority_still_reject(self):
        for value in [True, 0, "", None, [], {}]:
            flags = dict.fromkeys(VERIFIER.AUTHORITY_KEYS, False)
            flags["merge"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(SystemExit, "authority"):
                    VERIFIER.false_authority(flags, "fixture")


if __name__ == "__main__":
    unittest.main()
