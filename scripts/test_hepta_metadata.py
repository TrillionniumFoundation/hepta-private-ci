import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

from hepta_metadata import (
    AUTHORITY_KEYS,
    authority_fixture,
    has_deny_all_authority,
    has_schema_version,
)


class SharedMetadataTests(unittest.TestCase):
    def test_authority_fixture_is_canonical_deny_all(self):
        fixture = authority_fixture()
        self.assertEqual(list(fixture), AUTHORITY_KEYS)
        self.assertTrue(fixture)
        self.assertTrue(all(value is False for value in fixture.values()))

    def test_schema_version_check_is_shape_safe(self):
        self.assertTrue(has_schema_version({"schemaVersion": 3}, 3))
        self.assertFalse(has_schema_version({"schemaVersion": "3"}, 3))
        self.assertFalse(has_schema_version(None, 3))

    def test_authority_predicate_preserves_exact_boolean_semantics(self):
        reordered = dict(reversed(list(authority_fixture().items())))
        self.assertTrue(has_deny_all_authority(reordered))
        for invalid in (True, 0, 0.0, None, "", "false", [], {}):
            with self.subTest(value=invalid, kind=type(invalid).__name__):
                flags = authority_fixture()
                flags["runtimeAuthority"] = invalid
                self.assertFalse(has_deny_all_authority(flags))
        for flags in (None, [], {}, {**authority_fixture(), "other": False}):
            self.assertFalse(has_deny_all_authority(flags))
        missing = authority_fixture()
        del missing["release"]
        self.assertFalse(has_deny_all_authority(missing))

    def test_schema_version_rejects_boolean_and_float_aliases(self):
        for value in (True, 1.0, False, 0.0):
            with self.subTest(value=value, kind=type(value).__name__):
                self.assertFalse(
                    has_schema_version({"schemaVersion": value}, int(value))
                )

    def test_global_gate_rejects_nonboolean_denial(self):
        module = self.global_verifier()
        original_load = module.load

        def load(path):
            value = original_load(path)
            if path == "docs/CURRENT.json":
                value["authorityFlags"]["runtimeAuthority"] = 0
            return value

        with mock.patch.object(module, "load", side_effect=load):
            with self.assertRaisesRegex(SystemExit, "authority"):
                with contextlib.redirect_stdout(io.StringIO()):
                    module.verify()

    def test_global_gate_accepts_reordered_deny_all_metadata(self):
        module = self.global_verifier()
        original_load = module.load

        def load(path):
            value = original_load(path)
            if path == "docs/CURRENT.json":
                flags = value["authorityFlags"]
                value["authorityFlags"] = dict(reversed(list(flags.items())))
            return value

        with mock.patch.object(module, "load", side_effect=load):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.verify(), 0)

    @staticmethod
    def global_verifier():
        path = Path(__file__).with_name("hepta-docs.py")
        spec = importlib.util.spec_from_file_location("hepta_docs_metadata_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
