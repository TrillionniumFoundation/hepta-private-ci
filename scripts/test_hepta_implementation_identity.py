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
import subprocess
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
            row, self.fixture.modules[0], {"alpha": "test-lane"},
            self.subject.current_source_base(),
        )

    def test_non_boolean_claims_rejected_before_coercion(self):
        original = self.fixture.rows["alpha"]
        for key in self.subject.BOOLEAN_CLAIMS:
            for value in ("false", "true", 0, 1, None, [], {"value": False}):
                for container in (None, "claimBoundary", "completion"):
                    with self.subTest(key=key, value=value, container=container):
                        row = copy.deepcopy(original)
                        target = row if container is None else row.setdefault(container, {})
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
        self.fixture.write("src/alpha/lib.rs", "pub fn calculate() { let changed = 1; }\n")
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
                with self.assertRaisesRegex(SystemExit, "mapped source/evidence changed"):
                    self.fixture.verify()
                self.fixture.write(path, original)
                self.fixture.commit("restore bytes")
                self.fixture.verify()

    def test_conflicting_evidence_aliases_reject(self):
        row = self.fixture.rows["alpha"]
        row["operations"][0]["delegatedCallees"] = [{
            "path": "tests/native.rs", "sourcePath": "host/caller.rs",
        }]
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
        self.assertEqual((self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(), before)

    def test_malformed_operation_is_a_bounded_error(self):
        row = self.fixture.rows["alpha"]
        row["operations"] = [True]
        with self.assertRaisesRegex(ValueError, "invalid operation"):
            self.migrate_row(row)
        self.fixture.change_maps()
        with self.assertRaises(SystemExit):
            self.fixture.verify()

    def test_duplicate_json_key_is_rejected(self):
        self.fixture.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", '{"module":"alpha","module":"beta"}')
        self.fixture.commit("duplicate keys")
        with self.assertRaisesRegex(SystemExit, "duplicate JSON key"):
            self.fixture.verify()

    def test_repeatable_module_option_uses_canonical_migration(self):
        with patch("sys.argv", ["hepta-implementation-maps.py", "migrate",
                                "--module", "alpha", "--module", "alpha"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.subject.main()
        self.assertEqual(json.loads(output.getvalue())["maps"], ["docs/modules/alpha/IMPLEMENTATION_MAP.json"])

    def test_strict_alias_cannot_enable_historical_only_pass(self):
        self.fixture.write("src/alpha/lib.rs", "pub fn changed() {}\n")
        self.fixture.commit("stale source")
        for strict in (True, False):
            with self.subTest(strict=strict), self.assertRaises(SystemExit):
                self.subject.verify(require_current_source=strict)


class HistoricalObjectAvailabilityTests(unittest.TestCase):
    """Missing objects are not proof that a historical path was absent."""

    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = self.fixture.root
        self.subject = fixtures.maps

    def prepare_history(self, extra_path=None):
        self.fixture.write("src/beta/lib.rs", "pub fn old_beta() {}\n")
        if extra_path is not None:
            self.fixture.write(extra_path, "old witness\n")
        anchor = self.fixture.commit("distinct historical evidence")
        for row in self.fixture.rows.values():
            row["sourceBase"] = dict(anchor)
        if extra_path is not None:
            row = self.fixture.rows["beta"]
            row["observedAtHead"] = dict(anchor)
            row["observedSourcePaths"] = ["src/beta", extra_path]
        self.fixture.write("src/alpha/lib.rs", "pub fn current_alpha() {}\n")
        self.fixture.write("src/beta/lib.rs", "pub fn current_beta() {}\n")
        if extra_path is not None:
            self.fixture.write(extra_path, "current witness\n")
        self.fixture.commit("available current source")
        self.fixture.change_maps()
        return anchor

    def remove_object(self, anchor, suffix):
        oid = self.fixture.git("rev-parse", anchor["commit"] + suffix)
        # Objects belong only to this disposable fixture, never a shared clone.
        path = self.root / ".git" / "objects" / oid[:2] / oid[2:]
        self.assertTrue(path.is_file())
        path.unlink()
        return oid

    def assert_hard_unavailable(self, anchor, paths):
        with self.assertRaisesRegex(ValueError, "historical.*unavailable") as error:
            self.subject.require_tracked_paths(anchor["commit"], paths, historical=True)
        self.assertNotIsInstance(error.exception, self.subject.SourceDrift)

    def assert_migration_writes_nothing(self):
        before = {
            path: path.read_bytes()
            for path in self.root.glob("docs/modules/*/IMPLEMENTATION_MAP.json")
        }
        with self.assertRaisesRegex(ValueError, "historical.*unavailable") as error:
            with contextlib.redirect_stdout(io.StringIO()):
                self.subject.migrate(["alpha", "beta"])
        self.assertNotIsInstance(error.exception, self.subject.SourceDrift)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_missing_historical_blob_is_hard_error_and_strict_failure(self):
        anchor = self.prepare_history()
        self.remove_object(anchor, ":src/beta/lib.rs")
        self.assert_hard_unavailable(anchor, ["src/beta/lib.rs"])
        with self.assertRaisesRegex(SystemExit, "historical.*unavailable"):
            self.subject.verify(require_current_source=True)

    def test_missing_historical_blob_stops_multi_module_migration_before_writes(self):
        anchor = self.prepare_history()
        self.remove_object(anchor, ":src/beta/lib.rs")
        self.assert_migration_writes_nothing()

    def test_missing_historical_subtree_is_hard_error_and_never_rebound(self):
        anchor = self.prepare_history()
        self.remove_object(anchor, ":src/beta")
        self.assert_hard_unavailable(anchor, ["src/beta"])
        self.assert_hard_unavailable(anchor, ["src/beta/lib.rs"])
        with self.assertRaisesRegex(SystemExit, "historical.*unavailable"):
            self.subject.verify(require_current_source=True)
        self.assert_migration_writes_nothing()

    def test_missing_historical_root_is_hard_error_and_never_rebound(self):
        anchor = self.prepare_history()
        self.remove_object(anchor, "^{tree}")
        self.assert_hard_unavailable(anchor, ["src/beta/lib.rs"])
        # The source identity guard rejects a missing root even before the
        # path queries; retain that earlier hard failure instead of rebinding.
        with self.assertRaisesRegex(SystemExit, "rev-parse"):
            self.subject.verify(require_current_source=True)
        before = {
            path: path.read_bytes()
            for path in self.root.glob("docs/modules/*/IMPLEMENTATION_MAP.json")
        }
        with self.assertRaises(subprocess.CalledProcessError):
            self.subject.migrate(["alpha", "beta"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_proven_historical_absence_remains_explicit_source_refresh(self):
        path = "src/beta/added.rs"
        anchor = self.prepare_history()
        self.fixture.write(path, "pub fn added() {}\n")
        self.fixture.rows["beta"]["operations"][0]["sourcePath"] = path
        self.fixture.change_maps()
        with self.assertRaisesRegex(self.subject.SourceDrift, "absent at historical"):
            self.subject.require_tracked_paths(
                anchor["commit"], [path], historical=True
            )
        with self.assertRaisesRegex(SystemExit, "absent at historical"):
            self.subject.verify(require_current_source=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.subject.migrate(["alpha", "beta"])
        self.fixture.commit("explicit refreshed source observation")
        self.fixture.verify()

    def test_available_changed_blob_remains_drift_and_can_be_explicitly_refreshed(self):
        anchor = self.prepare_history()
        self.subject.require_tracked_paths(
            anchor["commit"], ["src/beta/lib.rs"], historical=True
        )
        with self.assertRaisesRegex(SystemExit, "changed after source observation"):
            self.subject.verify(require_current_source=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.subject.migrate(["alpha", "beta"])
        self.fixture.commit("explicit refreshed available observation")
        self.fixture.verify()

    def test_missing_historical_blob_with_literal_tab_and_newline_paths(self):
        path = "witness[1]\tline\nending.txt"
        anchor = self.prepare_history(extra_path=path)
        self.remove_object(anchor, ":" + path)
        self.assert_hard_unavailable(anchor, [path])
        with self.assertRaisesRegex(SystemExit, "historical.*unavailable"):
            self.subject.verify(require_current_source=True)
        self.assert_migration_writes_nothing()

    def test_missing_historical_blob_with_literal_tab_path(self):
        path = "witness[1]\tending.txt"
        anchor = self.prepare_history(extra_path=path)
        self.remove_object(anchor, ":" + path)
        self.assert_hard_unavailable(anchor, [path])
        self.assert_migration_writes_nothing()

    def test_literal_carriage_return_parent_preserves_absence_and_unavailability(self):
        path = "witness\rdir/old.txt"
        anchor = self.prepare_history(extra_path=path)
        with self.assertRaisesRegex(self.subject.SourceDrift, "absent at historical"):
            self.subject.require_tracked_paths(
                anchor["commit"], ["witness\rdir/absent.txt"], historical=True
            )
        self.remove_object(anchor, ":" + path)
        self.assert_hard_unavailable(anchor, [path])
        self.assert_migration_writes_nothing()

    def test_proven_absence_does_not_hide_later_unavailable_object(self):
        anchor = self.prepare_history()
        self.remove_object(anchor, ":src/beta/lib.rs")
        self.assert_hard_unavailable(anchor, ["src/beta/absent.rs", "src/beta/lib.rs"])

    def test_absent_parent_is_distinct_from_unavailable_parent_tree(self):
        anchor = self.prepare_history()
        with self.assertRaisesRegex(self.subject.SourceDrift, "absent at historical"):
            self.subject.require_tracked_paths(
                anchor["commit"], ["never-present/subtree/file.rs"], historical=True
            )
        self.remove_object(anchor, ":src")
        self.assert_hard_unavailable(anchor, ["src/never-present/file.rs"])

    def assert_observation_order_fails_closed(self, *, unavailable_first):
        anchor = self.prepare_history()
        row = self.fixture.rows["beta"]
        first, second = anchor, self.fixture.anchor
        if not unavailable_first:
            first, second = second, first
        row["sourceBase"] = dict(first)
        row["observedAtHead"] = dict(second)
        row["observedSourcePaths"] = ["src/beta"]
        self.fixture.change_maps()
        self.remove_object(anchor, ":src/beta/lib.rs")
        with self.assertRaisesRegex(SystemExit, "historical.*unavailable"):
            self.subject.verify(require_current_source=True)
        self.assert_migration_writes_nothing()

    def test_changed_first_observation_cannot_hide_unavailable_second_observation(self):
        self.assert_observation_order_fails_closed(unavailable_first=False)

    def test_unavailable_first_observation_is_not_refreshable_second_drift(self):
        self.assert_observation_order_fails_closed(unavailable_first=True)

    def test_absent_first_observation_cannot_hide_unavailable_second_observation(self):
        path = "witness.txt"
        anchor = self.prepare_history(extra_path=path)
        row = self.fixture.rows["beta"]
        row["sourceBase"] = dict(self.fixture.anchor)
        row["operations"][0]["sourcePath"] = path
        self.fixture.change_maps()
        self.remove_object(anchor, ":" + path)
        with self.assertRaisesRegex(SystemExit, "historical.*unavailable"):
            self.subject.verify(require_current_source=True)
        self.assert_migration_writes_nothing()


if __name__ == "__main__":
    unittest.main()
