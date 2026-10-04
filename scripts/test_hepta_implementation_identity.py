"""Canonical migration integrity, using the existing real-Git fixture.

The old suite exercised a removed source_objects_v1 policy, a permissive
historical-only verifier and unsupported scoped verify/generate signatures.
Source/checkout mutation coverage lives in test_hepta_implementation_maps and
source_identity; these tests retain the additional migration safety properties.
No test is skipped and no historical-only verification fallback is restored.
"""

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

import test_hepta_implementation_maps as fixtures


class MigrationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = self.fixture.root
        self.subject = fixtures.maps

    def migrate_row(self, row):
        return self.subject.migrate_map(
            row,
            self.fixture.modules[0],
            {"alpha": "test-lane"},
            self.subject.current_source_base(),
        )

    def test_non_boolean_claims_rejected_before_coercion(self):
        original = self.fixture.rows["alpha"]
        for key in self.subject.BOOLEAN_CLAIMS:
            for value in ("false", "true", 0, 1, None, [], {"value": False}):
                for container in (None, "claimBoundary", "completion"):
                    with self.subTest(key=key, value=value, container=container):
                        row = copy.deepcopy(original)
                        target = (
                            row if container is None else row.setdefault(container, {})
                        )
                        target[key] = value
                        with self.assertRaisesRegex(ValueError, "must be boolean"):
                            self.migrate_row(row)

    def test_verification_rejects_non_boolean_claims(self):
        self.fixture.rows["alpha"]["claimBoundary"]["productExecutionProved"] = "false"
        self.fixture.change_maps()
        with self.assertRaisesRegex(SystemExit, "must be boolean"):
            self.fixture.verify()

    def test_unchanged_typed_execution_claim_is_not_recertified(self):
        row = self.fixture.rows["alpha"]
        row["claimBoundary"]["productExecutionProved"] = True
        migrated = self.migrate_row(row)
        self.assertIs(migrated["claimBoundary"]["productExecutionProved"], True)
        self.assertFalse(migrated["claimBoundary"]["nativeSourceMappingComplete"])

    def test_source_change_cannot_launder_execution_claim(self):
        self.fixture.rows["alpha"]["claimBoundary"]["productExecutionProved"] = True
        self.fixture.change_maps()
        self.fixture.write(
            "src/alpha/lib.rs", "pub fn calculate() { let changed = 1; }\n"
        )
        self.fixture.commit("changed source after execution claim")
        path = self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "mapped source/evidence changed"):
            self.subject.migrate(["alpha"])
        self.assertEqual(path.read_bytes(), before)

    def test_caller_test_and_delegate_are_independently_bound(self):
        row = self.fixture.rows["alpha"]
        self.fixture.write("delegate/lib.rs", "pub fn delegate() {}\n")
        row["operations"][0]["tests"] = ["tests/native.rs::qualified"]
        row["operations"][0]["delegatedCallees"] = [{"sourcePath": "delegate/lib.rs"}]
        row["productCallers"] = [{"sourcePath": "host/caller.rs"}]
        row["sourceBase"] = self.fixture.commit("delegate source")
        self.fixture.change_maps()
        self.fixture.verify()
        for path in ("tests/native.rs", "delegate/lib.rs", "host/caller.rs"):
            with self.subTest(path=path):
                original = (self.root / path).read_text()
                self.fixture.write(path, original + "// semantic source change\n")
                self.fixture.commit("change bound evidence")
                with self.assertRaisesRegex(
                    SystemExit, "mapped source/evidence changed"
                ):
                    self.fixture.verify()
                self.fixture.write(path, original)
                self.fixture.commit("restore bytes")
                self.fixture.verify()

    def test_conflicting_evidence_aliases_reject(self):
        row = self.fixture.rows["alpha"]
        row["operations"][0]["delegatedCallees"] = [
            {
                "path": "tests/native.rs",
                "sourcePath": "host/caller.rs",
            }
        ]
        self.fixture.change_maps()
        with self.assertRaisesRegex(SystemExit, "conflicting evidence paths"):
            self.fixture.verify()

    def test_symlink_map_is_not_read_or_written(self):
        path = self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        target = self.root / "outside-map.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        self.fixture.commit("symlink map")
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.subject.migrate(["alpha"])
        self.assertEqual(target.read_bytes(), before)

    def test_empty_selection_rejects_before_writing(self):
        before = (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty module selection"):
            self.subject.migrate([])
        self.assertEqual(
            (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(),
            before,
        )

    def test_malformed_operation_is_a_bounded_error(self):
        row = self.fixture.rows["alpha"]
        row["operations"] = [True]
        with self.assertRaisesRegex(ValueError, "invalid operation"):
            self.migrate_row(row)
        self.fixture.change_maps()
        with self.assertRaises(SystemExit):
            self.fixture.verify()

    def test_duplicate_json_key_is_rejected(self):
        self.fixture.write(
            "docs/modules/alpha/IMPLEMENTATION_MAP.json",
            '{"module":"alpha","module":"beta"}',
        )
        self.fixture.commit("duplicate keys")
        with self.assertRaisesRegex(SystemExit, "duplicate JSON key"):
            self.fixture.verify()

    def test_repeatable_module_option_uses_canonical_migration(self):
        with patch(
            "sys.argv",
            [
                "hepta-implementation-maps.py",
                "migrate",
                "--module",
                "alpha",
                "--module",
                "alpha",
            ],
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.subject.main()
        self.assertEqual(
            json.loads(output.getvalue())["maps"],
            ["docs/modules/alpha/IMPLEMENTATION_MAP.json"],
        )

    def test_strict_alias_cannot_enable_historical_only_pass(self):
        self.fixture.write("src/alpha/lib.rs", "pub fn changed() {}\n")
        self.fixture.commit("stale source")
        for strict in (True, False):
            with self.subTest(strict=strict), self.assertRaises(SystemExit):
                self.subject.verify(require_current_source=strict)


if __name__ == "__main__":
    unittest.main()
