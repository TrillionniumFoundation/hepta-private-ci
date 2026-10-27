"""Reject source mutations even when a generator emits legitimate schema data."""

import unittest

import ndu_protocol_fixture_candidate as protocol
import test_ndu_dependency_candidate as fixtures


class ProtocolFixtureScopeTests(unittest.TestCase):
    setUp = fixtures.CandidateBindingTests.setUp
    seal = fixtures.CandidateBindingTests.seal
    runner = fixtures.CandidateBindingTests.runner
    restore = fixtures.CandidateBindingTests.restore

    def test_generated_schema_is_allowed_but_source_edit_is_rejected(self):
        runner = self.runner()
        candidate = self.restore(runner)
        name = protocol.SCHEMA_ROOT + "json/v2/Generated.json"
        path = self.root / name
        path.parent.mkdir(parents=True)
        path.write_text('{"type":"object"}\n')
        self.assertEqual(protocol.verify_scope(runner, candidate), [name])
        source = self.root / "codex-rs/app-server-protocol/src/lib.rs"
        source.parent.mkdir(parents=True)
        source.write_text("// unapproved change\n")
        with self.assertRaisesRegex(ValueError, "Only generated schema"):
            protocol.verify_scope(runner, candidate)

    def test_verified_schema_bytes_cannot_change_during_regression(self):
        runner = self.runner()
        candidate = self.restore(runner)
        name = protocol.SCHEMA_ROOT + "json/v2/Generated.json"
        path = self.root / name
        path.parent.mkdir(parents=True)
        path.write_text('{"type":"object"}\n')
        sealed = protocol.describe(self.root, (name,))
        protocol.verify_scope(runner, candidate, sealed)
        path.write_text('{"type":"string"}\n')
        with self.assertRaisesRegex(ValueError, "schema bytes"):
            protocol.verify_scope(runner, candidate, sealed)

    def test_schema_paths_cannot_escape_or_hide_code(self):
        for name in (
            "/" + protocol.SCHEMA_ROOT + "json/x.json",
            protocol.SCHEMA_ROOT + "../src/generated.rs",
            protocol.SCHEMA_ROOT + "json/../../../../Cargo.toml",
            protocol.SCHEMA_ROOT + "generate.py",
        ):
            with self.subTest(path=name):
                self.assertFalse(protocol.schema_path(name))


if __name__ == "__main__":
    unittest.main()
