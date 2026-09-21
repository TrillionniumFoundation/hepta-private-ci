"""Exercise map identity against real Git commits, trees and dirty worktrees."""

import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "implementation_maps", Path(__file__).with_name("hepta-implementation-maps.py")
)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patched = patch.object(subject, "ROOT", self.root)
        patched.start()
        self.addCleanup(patched.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("owner/src/lib.rs", "pub fn run() {}\n")
        self.write("tests/product.rs", "fn product_test() {}\n")
        self.write("host/caller.rs", "fn call() { run() }\n")
        self.write("delegate/src/lib.rs", "pub fn delegated() {}\n")
        self.commit()
        self.module = {
            "id": "example.owner",
            "rootBindings": [{"path": "owner"}],
            "owner": "example",
            "deputy": "reviewer",
            "technicalDocument": "docs/modules/example.owner/TECHNICAL.md",
        }
        self.row = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceBase": subject.current_source_base(),
            "module": "example.owner",
            "laneId": "owner-lane",
            "declaredRoots": ["owner"],
            "resolvedRoots": ["owner"],
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productCallerState": "not_composed",
            "operations": [{
                "operation": "run", "nativeSymbol": "run",
                "sourcePath": "owner/src/lib.rs",
                "tests": ["tests/product.rs::product_test"],
                "delegatedCallees": [{"sourcePath": "delegate/src/lib.rs"}],
            }],
            "productCallers": [{"sourcePath": "host/caller.rs"}],
            "claimBoundary": {"productExecutionProved": False},
        }

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True,
            text=True, capture_output=True,
        ).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def bind_objects(self):
        self.row["sourceIdentityPolicy"] = "source_objects_v1"
        self.row["sourceObjects"] = subject.current_source_objects(self.row)

    def bind_observation(self):
        self.row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        self.row["observedAtHead"] = subject.current_source_base()
        self.row["sourceBase"] = subject.current_source_base()
        self.row["observedSourcePaths"] = subject.tracked_source_paths(self.row)

    def rejected(self):
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            subject.verify_source_identity(self.row)

    def test_exact_objects_bind_owner_test_delegate_and_caller(self):
        self.bind_objects()
        self.assertEqual(subject.tracked_source_paths(self.row), [
            "delegate/src/lib.rs", "host/caller.rs", "owner",
            "owner/src/lib.rs", "tests/product.rs",
        ])
        self.assertTrue(subject.verify_source_identity(self.row))

    def test_document_only_commit_does_not_need_map_rebinding(self):
        self.bind_objects()
        self.write("docs/explanation.md", "Reworded explanation.\n")
        self.commit()
        self.assertTrue(subject.verify_source_identity(self.row))

    def test_owner_source_change_rejects_stale_object(self):
        self.bind_objects()
        self.write("owner/src/lib.rs", "pub fn changed() {}\n")
        self.commit()
        self.rejected()

    def test_test_change_outside_owner_is_bound(self):
        self.bind_objects()
        self.write("tests/product.rs", "fn changed_test() {}\n")
        self.commit()
        self.rejected()

    def test_delegated_implementation_change_is_bound(self):
        self.bind_objects()
        self.write("delegate/src/lib.rs", "pub fn changed_delegate() {}\n")
        self.commit()
        self.rejected()

    def test_caller_change_is_bound(self):
        self.bind_objects()
        self.write("host/caller.rs", "fn changed_caller() {}\n")
        self.commit()
        self.rejected()

    def test_resolved_alias_target_cannot_be_omitted(self):
        self.write("actual/src/lib.rs", "pub fn implementation() {}\n")
        self.commit()
        self.bind_objects()
        self.row["resolvedRoots"] = ["actual"]
        self.rejected()

    def test_unchanged_directory_tree_covers_child_objects(self):
        self.bind_objects()
        self.row["sourceObjects"] = [
            item for item in self.row["sourceObjects"]
            if item["path"] != "owner/src/lib.rs"
        ]
        self.assertTrue(subject.verify_source_identity(self.row))

    def test_partial_file_witness_cannot_cover_an_owner_tree(self):
        self.bind_objects()
        self.row["sourceObjects"] = [
            item for item in self.row["sourceObjects"] if item["path"] != "owner"
        ]
        self.rejected()

    def test_worktree_source_change_rejected_without_new_commit(self):
        self.bind_objects()
        self.write("owner/src/lib.rs", "dirty\n")
        self.rejected()

    def test_index_change_rejected_even_after_worktree_restored(self):
        self.bind_objects()
        self.write("owner/src/lib.rs", "staged\n")
        self.git("add", "owner/src/lib.rs")
        self.write("owner/src/lib.rs", "pub fn run() {}\n")
        self.rejected()

    def test_untracked_file_below_bound_root_rejected(self):
        self.bind_objects()
        self.write("owner/src/extra.rs", "not in HEAD\n")
        self.rejected()

    def test_duplicate_source_object_rejected(self):
        self.bind_objects()
        self.row["sourceObjects"].append(self.row["sourceObjects"][0])
        self.rejected()

    def test_invalid_paths_rejected(self):
        for path in ("../outside", "/tmp/outside", "owner/../host", "owner\\src", "owner//src"):
            with self.subTest(path=path):
                self.row["resolvedRoots"] = [path]
                self.rejected()

    def test_symlink_binding_rejected(self):
        (self.root / "link").symlink_to(self.root / "owner", target_is_directory=True)
        self.row["resolvedRoots"] = ["link"]
        self.rejected()

    def test_recursive_map_source_binding_rejected(self):
        for path in ("docs", "docs/modules/example.owner/IMPLEMENTATION_MAP.json"):
            with self.subTest(path=path):
                self.row["resolvedRoots"] = [path]
                self.rejected()

    def test_observed_source_survives_later_document_commit(self):
        self.bind_observation()
        self.write("docs/explanation.md", "Changed navigation.\n")
        self.commit()
        self.assertTrue(subject.verify_source_identity(self.row))

    def test_observation_checks_tests_not_just_owner_roots(self):
        self.bind_observation()
        self.write("tests/product.rs", "changed\n")
        self.commit()
        self.rejected()

    def test_observation_cannot_omit_caller_or_test_paths(self):
        self.bind_observation()
        self.row["observedSourcePaths"] = ["owner"]
        self.rejected()

    def test_observation_rejects_forged_tree(self):
        self.bind_observation()
        self.row["observedAtHead"]["tree"] = "a" * 40
        self.rejected()

    def test_observation_must_be_an_ancestor_not_sibling(self):
        base = self.git("rev-parse", "HEAD")
        self.write("docs/side.md", "side branch\n")
        self.commit()
        self.bind_observation()
        self.git("reset", "--hard", base)
        self.write("docs/main.md", "other branch\n")
        self.commit()
        self.rejected()

    def test_observation_paths_cannot_include_the_map(self):
        self.write("docs/modules/example.owner/IMPLEMENTATION_MAP.json", "{}\n")
        self.commit()
        self.bind_observation()
        self.row["observedSourcePaths"].append("docs")
        self.rejected()

    def test_unknown_policy_and_invalid_sha_fail_closed(self):
        for field, value in (("sourceIdentityPolicy", "trust_me"), ("sourceBase", {"commit": True, "tree": "b" * 40})):
            with self.subTest(field=field):
                row = copy.deepcopy(self.row)
                row[field] = value
                with self.assertRaises(ValueError):
                    subject.verify_source_identity(row)

    def test_source_object_policy_requires_objects(self):
        self.row["sourceIdentityPolicy"] = "source_objects_v1"
        self.rejected()

    def test_exact_candidate_policy_is_an_explicit_witness(self):
        self.row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        self.assertTrue(subject.verify_source_identity(self.row))

    def test_candidate_policy_cannot_float_after_source_change(self):
        self.row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        self.write("owner/src/lib.rs", "changed\n")
        self.commit()
        self.rejected()

    def test_legacy_baseline_does_not_prove_current_source(self):
        self.write("owner/src/lib.rs", "changed\n")
        self.commit()
        self.assertFalse(subject.verify_source_identity(self.row))

    def registry(self):
        self.write("docs/modules/MODULES.json", json.dumps({"modules": [self.module]}))
        self.write("docs/readiness/READINESS.json", json.dumps({
            "implementationLanes": [{"id": "owner-lane", "modules": [self.module["id"]]}],
        }))
        self.write("docs/modules/example.owner/IMPLEMENTATION_MAP.json", json.dumps(self.row))

    def report(self, strict=False):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            subject.verify(require_current_source=strict)
        return json.loads(stream.getvalue())

    def test_all_legacy_maps_are_explicitly_historical_only(self):
        self.registry()
        result = self.report()
        self.assertEqual(result["historicalOnlyModules"], ["example.owner"])
        self.assertEqual(result["sourceWitnessedModules"], [])
        self.assertFalse(result["productionImplementationProved"])

    def test_strict_mode_rejects_uniformly_stale_maps(self):
        self.write("owner/src/lib.rs", "changed\n")
        self.commit()
        self.registry()
        with self.assertRaisesRegex(SystemExit, "current source witness required"):
            self.report(strict=True)

    def test_all_maps_can_migrate_without_a_leftover_legacy_batch(self):
        self.bind_objects()
        self.registry()
        self.assertEqual(self.report(strict=True)["historicalOnlyModules"], [])

    def test_composed_map_cannot_rely_on_historical_baseline(self):
        self.row["productCallerState"] = "composed"
        self.registry()
        with self.assertRaisesRegex(SystemExit, "current source witness required"):
            self.report()

    def test_positive_execution_claim_cannot_rely_on_historical_baseline(self):
        self.row["claimBoundary"]["productExecutionProved"] = True
        self.registry()
        with self.assertRaisesRegex(SystemExit, "current source witness required"):
            self.report()

    def test_duplicate_json_key_rejected(self):
        self.registry()
        path = "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        self.write(path, '{"module":"example.owner","module":"other"}')
        with self.assertRaisesRegex(SystemExit, "duplicate binding key"):
            self.report()

    def test_bad_operation_record_is_a_bounded_validation_error(self):
        self.row["operations"] = [True]
        self.registry()
        with self.assertRaisesRegex(SystemExit, "invalid operation"):
            self.report()

    def test_file_presence_does_not_generate_complete_api_claim(self):
        self.write("qualification/module-execution-dossiers/detail/example.owner.md",
                   "**Implemented entrypoints:** `run` in [../../../owner/src/lib.rs]\n")
        result = subject.map_for(self.module, subject.current_source_base(), {"example.owner": "owner-lane"})
        self.assertTrue(result["claimBoundary"]["listedEntrypointsPresent"])
        self.assertFalse(result["claimBoundary"]["nativeSourceMappingComplete"])

    def test_migration_does_not_upgrade_missing_completeness(self):
        result = subject.migrate_map(self.row, self.module, {"example.owner": "owner-lane"}, subject.current_source_base())
        self.assertTrue(result["claimBoundary"]["listedEntrypointsPresent"])
        self.assertFalse(result["claimBoundary"]["nativeSourceMappingComplete"])


    def migrated_row(self):
        return subject.migrate_map(
            self.row, self.module, {"example.owner": "owner-lane"},
            subject.current_source_base(),
        )

    def test_schema_migration_cannot_rebind_changed_source_to_old_execution(self):
        for changed in (
            "owner/src/lib.rs", "tests/product.rs", "host/caller.rs",
            "delegate/src/lib.rs",
        ):
            with self.subTest(changed=changed):
                self.bind_objects()
                self.row["claimBoundary"]["productExecutionProved"] = True
                witness = copy.deepcopy(self.row["sourceObjects"])
                self.write(changed, "changed since witnessed execution\n")
                self.commit()
                migrated = self.migrated_row()
                self.assertEqual(migrated["sourceObjects"], witness)
                with self.assertRaisesRegex(ValueError, "stale source object"):
                    subject.verify_source_identity(migrated)
                # A new test iteration must create a genuinely different commit.
                self.write(changed, "restored for next case\n")
                self.commit()

    def test_schema_migration_preserves_additional_evidence_inputs(self):
        self.write("build-policy.txt", "reviewed policy\n")
        self.commit()
        self.bind_objects()
        self.row["sourceObjects"].append({
            "path": "build-policy.txt",
            "object": self.git("rev-parse", "HEAD:build-policy.txt"),
        })
        witness = copy.deepcopy(self.row["sourceObjects"])
        self.assertEqual(self.migrated_row()["sourceObjects"], witness)

    def test_schema_migration_preserves_exact_observation(self):
        self.bind_observation()
        self.write("owner/src/lib.rs", "changed since observation\n")
        self.commit()
        migrated = self.migrated_row()
        self.assertEqual(migrated["observedAtHead"], self.row["observedAtHead"])
        with self.assertRaisesRegex(ValueError, "source drift"):
            subject.verify_source_identity(migrated)

    def test_document_only_migration_keeps_witness_valid(self):
        self.bind_objects()
        self.write("docs/explanation.md", "Documentation only.\n")
        self.commit()
        before = copy.deepcopy(self.row)
        migrated = self.migrated_row()
        self.assertEqual(self.row, before)
        self.assertEqual(migrated["sourceObjects"], before["sourceObjects"])
        self.assertTrue(subject.verify_source_identity(migrated))

    def test_migration_rejects_non_boolean_execution_claims(self):
        original = copy.deepcopy(self.row)
        for value in ("false", "true", 0, 1, None, [], {"value": False}):
            for container in ("top", "claimBoundary", "completion"):
                with self.subTest(value=value, container=container):
                    self.row = copy.deepcopy(original)
                    record = self.row if container == "top" else self.row.setdefault(container, {})
                    record["productExecutionProved"] = value
                    with self.assertRaisesRegex(ValueError, "must be boolean"):
                        self.migrated_row()
        self.row = original

    def test_migration_rejects_non_boolean_production_implementation(self):
        self.row["productionImplementation"] = "false"
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            self.migrated_row()

    def test_verify_rejects_non_boolean_claim_instead_of_ignoring_it(self):
        self.row["claimBoundary"]["productExecutionProved"] = "true"
        self.registry()
        with self.assertRaisesRegex(SystemExit, "must be boolean"):
            self.report()

    def test_verify_rejects_integer_execution_claim(self):
        self.row["claimBoundary"]["productExecutionProved"] = 1
        self.registry()
        with self.assertRaisesRegex(SystemExit, "must be boolean"):
            self.report()

    def test_typed_true_claim_is_preserved_not_recertified(self):
        self.bind_objects()
        self.row["claimBoundary"]["productExecutionProved"] = True
        migrated = self.migrated_row()
        self.assertIs(migrated["claimBoundary"]["productExecutionProved"], True)
        self.assertEqual(migrated["sourceObjects"], self.row["sourceObjects"])

    def second_module(self, *, valid_map=True):
        self.registry()
        other = copy.deepcopy(self.module)
        other["id"] = "second.owner"
        other["technicalDocument"] = "docs/modules/second.owner/TECHNICAL.md"
        self.write("docs/modules/MODULES.json", json.dumps({"modules": [self.module, other]}))
        self.write("docs/readiness/READINESS.json", json.dumps({
            "implementationLanes": [{
                "id": "owner-lane", "modules": [self.module["id"], other["id"]],
            }],
        }))
        second = copy.deepcopy(self.row)
        second["module"] = other["id"]
        self.write(
            "docs/modules/second.owner/IMPLEMENTATION_MAP.json",
            json.dumps(second) if valid_map else "invalid unrelated JSON\n",
        )
        return "docs/modules/second.owner/IMPLEMENTATION_MAP.json"

    def call_scoped(self, function, module_ids, **kwargs):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            function(module_ids=module_ids, **kwargs)
        return json.loads(stream.getvalue())

    def test_scoped_verify_does_not_parse_unrelated_maps(self):
        self.second_module(valid_map=False)
        result = self.call_scoped(subject.verify, ["example.owner"])
        self.assertEqual(result["selectedModules"], ["example.owner"])
        self.assertEqual(result["moduleSelection"], "explicit")
        self.assertEqual(result["modules"], 1)
        self.assertFalse(result["productionImplementationProved"])

    def test_default_verify_still_checks_all_registered_maps(self):
        self.second_module(valid_map=False)
        with self.assertRaisesRegex(SystemExit, "second.owner: invalid JSON"):
            self.report()

    def test_scoped_strict_verify_still_rejects_historical_only_map(self):
        self.registry()
        with self.assertRaisesRegex(SystemExit, "current source witness required"):
            self.call_scoped(subject.verify, ["example.owner"], require_current_source=True)

    def test_scoped_migrate_does_not_read_or_write_unrelated_map(self):
        other_path = self.second_module(valid_map=False)
        original = (self.root / other_path).read_bytes()
        result = self.call_scoped(subject.migrate, ["example.owner"])
        self.assertEqual(result["maps"], ["docs/modules/example.owner/IMPLEMENTATION_MAP.json"])
        self.assertEqual((self.root / other_path).read_bytes(), original)

    def test_repeated_migration_is_a_noop(self):
        self.registry()
        self.call_scoped(subject.migrate, ["example.owner"])
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        before = path.stat().st_mtime_ns
        result = self.call_scoped(subject.migrate, ["example.owner"])
        self.assertEqual(result["migrated"], 0)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_migration_prevalidates_all_targets_before_first_write(self):
        self.second_module(valid_map=False)
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                subject.migrate()
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_module_is_rejected_before_any_write(self):
        self.registry()
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "unknown module"):
            subject.migrate(module_ids=["example.owner", "typo.owner"])
        self.assertEqual(path.read_bytes(), before)

    def test_empty_explicit_module_selection_is_not_success(self):
        self.registry()
        with self.assertRaisesRegex(ValueError, "empty module selection"):
            subject.verify(module_ids=[])

    def test_duplicate_module_requests_are_deduplicated(self):
        self.registry()
        result = self.call_scoped(subject.migrate, ["example.owner", "example.owner"])
        self.assertEqual(result["migrated"], 1)

    def test_duplicate_registry_identity_fails_before_migration(self):
        self.registry()
        self.write("docs/modules/MODULES.json", json.dumps({
            "modules": [self.module, self.module],
        }))
        with self.assertRaisesRegex(ValueError, "duplicate module"):
            subject.migrate()

    def test_scoped_generate_creates_only_selected_missing_map(self):
        other_path = self.second_module()
        first_path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        first_path.unlink()
        (self.root / other_path).unlink()
        result = self.call_scoped(subject.generate, ["example.owner"])
        self.assertEqual(result["generated"], 1)
        self.assertTrue(first_path.is_file())
        self.assertFalse((self.root / other_path).exists())

    def test_generate_never_overwrites_an_existing_witness(self):
        self.bind_objects()
        self.registry()
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        result = self.call_scoped(subject.generate, ["example.owner"])
        self.assertEqual(result["generated"], 0)
        self.assertEqual(path.read_bytes(), before)

    def test_map_identity_mismatch_is_not_silently_migrated(self):
        self.registry()
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        wrong = copy.deepcopy(self.row)
        wrong["module"] = "second.owner"
        path.write_text(json.dumps(wrong))
        with self.assertRaisesRegex(ValueError, "map identity mismatch"):
            subject.migrate(module_ids=["example.owner"])
        self.assertEqual(json.loads(path.read_text())["module"], "second.owner")

    def test_missing_selected_map_is_not_reported_as_success(self):
        self.registry()
        (self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing map"):
            subject.migrate(module_ids=["example.owner"])

    def test_symlink_map_cannot_be_migrated(self):
        self.registry()
        path = self.root / "docs/modules/example.owner/IMPLEMENTATION_MAP.json"
        text = path.read_text()
        path.unlink()
        target = self.root / "outside-map.json"
        target.write_text(text)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink source path"):
            subject.migrate(module_ids=["example.owner"])
        self.assertEqual(target.read_text(), text)

    def test_cli_module_option_is_repeatable_and_explicit(self):
        self.second_module()
        with patch("sys.argv", ["hepta-implementation-maps.py", "verify",
                                "--module", "example.owner", "--module", "second.owner"]):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                subject.main()
        result = json.loads(stream.getvalue())
        self.assertEqual(result["selectedModules"], ["example.owner", "second.owner"])
        self.assertEqual(result["moduleSelection"], "explicit")

    def test_unscoped_report_explicitly_names_global_scope(self):
        self.registry()
        result = self.report()
        self.assertEqual(result["moduleSelection"], "all_registered")
        self.assertEqual(result["selectedModules"], ["example.owner"])


if __name__ == "__main__":
    unittest.main()
