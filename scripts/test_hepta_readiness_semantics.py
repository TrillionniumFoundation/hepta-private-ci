"""Behavioral regressions for semantic readiness checks, not prose quotas."""

from __future__ import annotations

import importlib.util
import json
import itertools
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


    def test_field_schema_object_key_order_is_not_semantic(self):
        schemas = [
            {"name": "id", "type": "u64", "required": True},
            {"name": "label", "type": "utf8", "required": True, "maxBytes": 32},
            {"type": "enum", "maxBytes": 32, "values": ["first", "second"]},
            {"type": "bounded_array", "maxBytes": 64, "minItems": 0,
             "maxItems": 4, "uniqueItems": False, "items": {"type": "u64"}},
            {"type": "bounded_fixed_point_vector", "maxBytes": 64, "scale": "Q24",
             "minItems": 1, "maxItems": 4, "items": {"type": "i64"}},
            {"type": "bounded_object", "maxBytes": 64, "minProperties": 1,
             "maxProperties": 1, "additionalProperties": False,
             "properties": [{"required": True, "type": "u64", "name": "id"}]},
        ]
        for schema in schemas:
            for keys in itertools.permutations(schema):
                with self.subTest(schema=schema["type"], keys=keys):
                    VERIFIER.validate_schema_node(
                        {key: schema[key] for key in keys}, 128, "fixture",
                        named="name" in schema,
                    )

    def test_field_schema_still_rejects_missing_and_unknown_keys(self):
        schema = {"name": "id", "type": "utf8", "required": True, "maxBytes": 32}
        for key in schema:
            invalid = {k: v for k, v in schema.items() if k != key}
            with self.subTest(missing=key), self.assertRaises(SystemExit):
                VERIFIER.validate_schema_node(invalid, 128, "fixture", named=True)
        with self.assertRaisesRegex(SystemExit, "key closure"):
            VERIFIER.validate_schema_node(schema | {"extra": False}, 128, "fixture", named=True)

    def test_json_duplicate_schema_keys_are_not_collapsed(self):
        with self.assertRaises(VERIFIER.DuplicateKey):
            json.loads('{"type":"u64","type":"bool"}', object_pairs_hook=VERIFIER.pairs)


if __name__ == "__main__":
    unittest.main()
