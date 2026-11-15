"""Regression coverage for accidental premature production/retirement claims."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_migration_invariants import CAPABILITIES, validate


def incomplete():
    migration = {
        "schema": "codex.hia.migration.v1",
        "whole_codex_rewritten": False,
        "production_dispatch_migrated": False,
        "toolchain": {"complete_compiler_runtime_qualified": False},
        "current_qualification": {"template_performance_closed": False},
        "capabilities": [
            {"id": name, "migration_status": "pending", "production_dispatch_migrated": False}
            for name in sorted(CAPABILITIES)
        ],
        "candidate_modules": [
            {"id": "sample", "source_path": "codex-rs/sample.rs",
             "retire_legacy": False, "production_dispatch_migrated": False}
        ],
        "retirement": {"ready": False, "approved_paths": []},
    }
    verification = {
        "schema": "codex.hia.component-verification.v2",
        "whole_codex_rewritten": False,
        "production_dispatch_migrated": False,
        "legacy_source_retired": False,
    }
    return migration, verification


class RetirementGateTest(unittest.TestCase):
    def test_partial_migration_is_valid_but_not_qualified(self):
        migration, verification = incomplete()
        self.assertEqual(validate(migration, verification), [])

    def test_missing_capability_is_not_equivalent_to_completion(self):
        migration, verification = incomplete()
        migration["capabilities"].pop()
        self.assertIn("missing original capability", "\n".join(validate(migration, verification)))

    def test_false_global_completion_is_rejected(self):
        migration, verification = incomplete()
        migration["whole_codex_rewritten"] = verification["whole_codex_rewritten"] = True
        self.assertIn("whole-product rewrite claimed", "\n".join(validate(migration, verification)))

    def test_dispatch_cannot_exceed_capability_closure(self):
        migration, verification = incomplete()
        migration["production_dispatch_migrated"] = verification["production_dispatch_migrated"] = True
        self.assertIn("default production dispatch claimed", "\n".join(validate(migration, verification)))

    def test_false_retirement_ready_is_rejected(self):
        migration, verification = incomplete()
        migration["retirement"]["ready"] = True
        self.assertIn("retirement ready without", "\n".join(validate(migration, verification)))

    def test_unapproved_component_retirement_is_rejected(self):
        migration, verification = incomplete()
        migration["candidate_modules"][0]["retire_legacy"] = True
        self.assertIn("retire_legacy without", "\n".join(validate(migration, verification)))

    def test_approved_path_requires_independent_source_and_platform_evidence(self):
        migration, verification = incomplete()
        migration["retirement"]["approved_paths"] = ["codex-rs/sample.rs"]
        errors = "\n".join(validate(migration, verification))
        self.assertIn("per_path_qualification", errors)
        self.assertIn("immutable source-tree", errors)
        self.assertIn("executed platform", errors)

    def test_verified_components_do_not_imply_retirement(self):
        migration, verification = incomplete()
        migration["candidate_modules"][0]["production_dispatch_migrated"] = True
        self.assertEqual(validate(migration, verification), [])

    def test_global_flags_without_per_path_evidence_cannot_mark_retirement_ready(self):
        migration, verification = incomplete()
        for item in migration["capabilities"]:
            item["migration_status"] = "fully_qualified"
            item["production_dispatch_migrated"] = True
        migration["whole_codex_rewritten"] = verification["whole_codex_rewritten"] = True
        migration["production_dispatch_migrated"] = verification["production_dispatch_migrated"] = True
        migration["toolchain"]["complete_compiler_runtime_qualified"] = True
        migration["current_qualification"]["template_performance_closed"] = True
        migration["retirement"]["ready"] = True
        self.assertIn("retirement ready without approved source paths",
                      "\n".join(validate(migration, verification)))
        migration["retirement"]["approved_paths"] = ["codex-rs/sample.rs"]
        migration["retirement"]["per_path_qualification"] = [{
            "path": "codex-rs/sample.rs",
            "source_tree": "a" * 40, "qualification_sha256": "b" * 64,
            "verified_platforms": ["linux-x86_64-gnu"],
        }]
        migration["candidate_modules"][0]["retire_legacy"] = True
        migration["candidate_modules"][0]["production_dispatch_migrated"] = True
        # Valid declarations are consistency checks, never executed qualification.
        self.assertEqual(validate(migration, verification), [])

    def test_approved_source_cannot_escape_checkout_or_target_git_metadata(self):
        migration, verification = incomplete()
        for path in ("../outside", "/absolute", "codex-rs/../outside",
                     ".git/config", "a\\\\b", "codex-rs//sample.rs"):
            with self.subTest(path=path):
                migration["retirement"]["approved_paths"] = [path]
                self.assertIn("unsafe approved source path",
                              "\n".join(validate(migration, verification)))

    def test_claimed_retirement_requires_an_explicit_module(self):
        migration, verification = incomplete()
        verification["legacy_source_retired"] = True
        self.assertIn("without a retired candidate module",
                      "\n".join(validate(migration, verification)))

    def test_platform_proof_names_must_be_nonempty_unique_strings(self):
        migration, verification = incomplete()
        migration["retirement"]["approved_paths"] = ["codex-rs/sample.rs"]
        migration["retirement"]["per_path_qualification"] = [{
            "path": "codex-rs/sample.rs",
            "source_tree": "a" * 40, "qualification_sha256": "b" * 64,
            "verified_platforms": ["linux-x86_64-gnu", ""],
        }]
        self.assertIn("invalid executed platform qualification entries",
                      "\n".join(validate(migration, verification)))

    def test_retirement_ready_rejects_unowned_source_deletion(self):
        migration, verification = incomplete()
        migration["retirement"]["ready"] = True
        migration["retirement"]["approved_paths"] = ["codex-rs/unowned.rs"]
        self.assertIn("no candidate module owns approved source deletion",
                      "\\n".join(validate(migration, verification)))

    def test_retirement_ready_requires_all_shared_source_owners(self):
        migration, verification = incomplete()
        migration["candidate_modules"][0]["retire_legacy"] = True
        migration["candidate_modules"][0]["production_dispatch_migrated"] = True
        migration["candidate_modules"].append({
            "id": "other_function_in_same_file",
            "source_path": "codex-rs/sample.rs",
            "retire_legacy": False,
            "production_dispatch_migrated": False,
        })
        migration["retirement"]["ready"] = True
        migration["retirement"]["approved_paths"] = ["codex-rs/sample.rs"]
        self.assertIn("shared source still has active or unqualified module owners",
                      "\\n".join(validate(migration, verification)))

    def test_retirement_ready_requires_the_owners_default_dispatch(self):
        migration, verification = incomplete()
        migration["candidate_modules"][0]["retire_legacy"] = True
        migration["retirement"]["ready"] = True
        migration["retirement"]["approved_paths"] = ["codex-rs/sample.rs"]
        self.assertIn("shared source still has active or unqualified module owners",
                      "\\n".join(validate(migration, verification)))

    def test_nested_or_mixed_case_git_metadata_cannot_be_retired(self):
        migration, verification = incomplete()
        for path in ("codex-rs/.git/config", "codex-rs/.GiT/objects", ".Git/config"):
            with self.subTest(path=path):
                migration["retirement"]["approved_paths"] = [path]
                self.assertIn("unsafe approved source path",
                              "\\n".join(validate(migration, verification)))

    def test_retired_flag_requires_readiness(self):
        migration, verification = incomplete()
        verification["legacy_source_retired"] = True
        self.assertIn("claimed retired without", "\n".join(validate(migration, verification)))


if __name__ == "__main__":
    unittest.main()
