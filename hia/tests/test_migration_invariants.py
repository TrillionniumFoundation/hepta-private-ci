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

    def test_retires_only_when_all_independent_gates_closed(self):
        migration, verification = incomplete()
        for item in migration["capabilities"]:
            item["migration_status"] = "fully_qualified"
            item["production_dispatch_migrated"] = True
        migration["whole_codex_rewritten"] = verification["whole_codex_rewritten"] = True
        migration["production_dispatch_migrated"] = verification["production_dispatch_migrated"] = True
        migration["toolchain"]["complete_compiler_runtime_qualified"] = True
        migration["current_qualification"]["template_performance_closed"] = True
        migration["retirement"]["ready"] = True
        self.assertEqual(validate(migration, verification), [])

    def test_retired_flag_requires_readiness(self):
        migration, verification = incomplete()
        verification["legacy_source_retired"] = True
        self.assertIn("claimed retired without", "\n".join(validate(migration, verification)))


if __name__ == "__main__":
    unittest.main()
