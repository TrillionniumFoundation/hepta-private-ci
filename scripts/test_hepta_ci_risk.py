import json
import subprocess
import tomllib
import tempfile
import unittest
from pathlib import Path

from scripts.hepta_ci_risk import classify
from scripts.hepta_ci_risk import project
from scripts.hepta_ci_scope import GROUPS
from scripts.hepta_ci_scope import generated_package_groups


ROOT = Path(__file__).resolve().parents[1]


class CiRiskTests(unittest.TestCase):
    def scope(self, **values):
        scope = {group: False for group in GROUPS}
        scope.update(native=False, derived=False, full_repo=False)
        scope.update(values)
        return scope

    def test_risk_order_matches_execution_boundary(self):
        self.assertEqual(classify(self.scope()), "ordinary")
        self.assertEqual(classify(self.scope(inference=True, native=True)), "ordinary")
        self.assertEqual(classify(self.scope(lifecycle=True, native=True)), "stateful")
        self.assertEqual(classify(self.scope(effects=True, native=True)), "effect")
        self.assertEqual(classify(self.scope(full_repo=True)), "effect")

    def test_execution_policy_keeps_ordinary_feedback_bounded(self):
        ordinary = project(self.scope(inference=True, native=True))
        self.assertEqual(ordinary["lanes"], ["source-head"])
        self.assertFalse(ordinary["require_exact_source"])
        self.assertEqual(ordinary["ordinary_feedback_target_minutes"], 10)
        self.assertEqual(ordinary["scoped_timeout_minutes"], 15)
        self.assertEqual(ordinary["architecture_timeout_minutes"], 15)

        stateful = project(self.scope(lifecycle=True, native=True))
        self.assertEqual(stateful["lanes"], ["source-head", "base-merge"])
        self.assertTrue(stateful["require_exact_source"])
        self.assertEqual(stateful["scoped_timeout_minutes"], 40)
        self.assertEqual(stateful["architecture_timeout_minutes"], 60)

    def test_required_workflows_consume_risk_projection(self):
        architecture = (
            ROOT / ".github/workflows/hepta-architecture-convergence.yml"
        ).read_text(encoding="utf-8")
        blocking = (ROOT / ".github/workflows/blocking-ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("lane: ${{ fromJSON(needs.plan.outputs.lanes) }}", architecture)
        self.assertNotIn(
            "github.event_name == 'pull_request' && '[\"source-head\",\"base-merge\"]'",
            architecture,
        )
        self.assertIn("RISK: ${{ needs.plan.outputs.risk }}", architecture)
        self.assertIn("run_native=false", architecture)
        self.assertIn(
            "timeout-minutes: ${{ fromJSON(needs.plan.outputs.timeout_minutes) }}",
            architecture,
        )
        self.assertIn(".architecture_timeout_minutes", architecture)

        self.assertIn(
            "scoped_timeout_minutes: ${{ steps.scope.outputs.scoped_timeout_minutes }}",
            blocking,
        )
        scoped = blocking.split("  hepta-scoped:", 1)[1].split("  lightweight:", 1)[0]
        self.assertIn(
            "timeout-minutes: ${{ fromJSON(needs.scope.outputs.scoped_timeout_minutes) }}",
            scoped,
        )
        self.assertNotIn("timeout-minutes: 40", scoped)

    def test_package_groups_are_loaded_only_from_generated_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "docs/modules/CI_MATRIX.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "schema": "hepta.module-ci-matrix.v1",
                        "groups": sorted(GROUPS),
                        "packages": [
                            {
                                "packagePath": "codex-rs/hepta-sample",
                                "packageName": "codex-hepta-sample",
                                "module": "sample.module",
                                "ciGroups": ["lifecycle"],
                                "compileLayer": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                generated_package_groups(root), {"hepta-sample": {"lifecycle"}}
            )


class ExactModuleRiskTests(unittest.TestCase):
    """Use real commits, not mutable worktree or a hand-built expected scope."""

    def setUp(self):
        from scripts.test_hepta_module_manifest import module_text

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI module test")
        self.git("config", "user.email", "ci-module@example.invalid")
        self.put(
            "codex-rs/Cargo.toml",
            '[workspace]\nmembers=["hepta-leaf", "hepta-host", "hepta-unrelated"]\n',
        )
        for name in ("leaf", "host", "unrelated"):
            self.put(
                f"codex-rs/hepta-{name}/Cargo.toml",
                f'[package]\nname="codex-hepta-{name}"\nversion="0.1.0"\n',
            )
            self.put(
                f"codex-rs/hepta-{name}/src/lib.rs", "pub fn value() -> u32 { 1 }\n"
            )
        host = self.root / "codex-rs/hepta-host/Cargo.toml"
        host.write_text(
            host.read_text()
            + '[dependencies]\ncodex-hepta-leaf={path="../hepta-leaf"}\n'
        )
        self.manifest = "docs/modules/feature.leaf/module.toml"
        self.source = "codex-rs/hepta-leaf/src/lib.rs"
        self.put(
            self.manifest,
            module_text("feature.leaf", 0, "codex-rs/hepta-leaf").replace(
                'ciGroups = ["lifecycle"]', 'ciGroups = ["learning"]'
            ),
        )
        self.base = self.commit()

    def git(self, *args):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def replace(self, path, old, new):
        target = self.root / path
        value = target.read_text()
        self.assertIn(old, value)
        target.write_text(value.replace(old, new))

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "test change")
        return self.git("rev-parse", "HEAD")

    def risk(self, paths, base=None):
        from scripts.hepta_ci_modules import assess_changes

        head = self.commit()
        return assess_changes(self.root, paths, base or self.base, head)[0]

    def test_module_manifest_is_not_unknown_toml_or_release(self):
        from scripts.hepta_ci_scope import select

        scope = select(["docs/modules/memory.retrieval/module.toml"])
        self.assertFalse(scope["full_repo"])
        self.assertTrue(scope["learning"])
        self.assertTrue(scope["lifecycle"])
        self.assertFalse(scope["effects"])
        self.assertNotEqual(project(scope)["risk"], "release")
        self.assertTrue(select(["docs/unrecognized.toml"])["full_repo"])

    def test_group_membership_is_not_change_risk(self):
        self.put(self.source, "pub fn value() -> u32 { 2 }\n")
        self.assertEqual(self.risk([self.source]), "ordinary")

    def test_presentation_only_manifest_edit_stays_ordinary(self):
        self.replace(self.manifest, "order = 0", "order = 1")
        self.assertEqual(self.risk([self.manifest]), "ordinary")

    def test_stateful_owner_keeps_recovery_lane(self):
        self.replace(self.manifest, 'state = "stateless"', 'state = "stateful"')
        base = self.commit()
        self.put(self.source, "pub fn value() -> u32 { 2 }\n")
        self.assertEqual(self.risk([self.source], base), "stateful")

    def test_candidate_cannot_downgrade_its_old_state(self):
        self.replace(self.manifest, 'state = "stateless"', 'state = "stateful"')
        base = self.commit()
        self.replace(self.manifest, 'state = "stateful"', 'state = "read_only"')
        self.put(self.source, "pub fn value() -> u32 { 2 }\n")
        self.assertEqual(self.risk([self.source, self.manifest], base), "stateful")

    def test_authority_change_keeps_effect_boundary(self):
        self.replace(self.manifest, "writes = []", 'writes = ["private_data"]')
        self.assertEqual(self.risk([self.manifest]), "effect")

    def test_unknown_manifest_field_is_not_presentation(self):
        self.replace(
            self.manifest, "order = 0", "order = 0\nnew_critical_semantics = true"
        )
        self.assertEqual(self.risk([self.manifest]), "stateful")

    def test_unknown_state_fails_instead_of_becoming_stateless(self):
        self.replace(
            self.manifest, 'state = "stateless"', 'state = "new_unknown_state"'
        )
        with self.assertRaises(ValueError):
            self.risk([self.manifest])

    def test_malformed_manifest_fails_closed(self):
        self.put(self.manifest, "not a TOML document")
        with self.assertRaises(tomllib.TOMLDecodeError):
            self.risk([self.manifest])

    def test_manifest_removal_keeps_retirement_lane(self):
        (self.root / self.manifest).unlink()
        self.assertEqual(self.risk([self.manifest]), "stateful")

    def test_manifest_impact_selects_actual_owner_and_reverse_consumer(self):
        from scripts.hepta_ci_dependencies import plan

        self.replace(self.manifest, "order = 0", "order = 1")
        result = plan(self.root, self.base, self.commit())
        self.assertEqual(result["packages"], ["codex-hepta-host", "codex-hepta-leaf"])
        self.assertFalse(result["full_workspace"])

    def test_deleted_manifest_preserves_old_consumer_edges(self):
        from scripts.hepta_ci_dependencies import plan

        (self.root / self.manifest).unlink()
        result = plan(self.root, self.base, self.commit())
        self.assertEqual(result["packages"], ["codex-hepta-host", "codex-hepta-leaf"])
        self.assertFalse(result["full_workspace"])

    def test_runtime_catalog_embedding_is_an_input_edge(self):
        from scripts.hepta_ci_dependencies import plan

        self.put("docs/modules/MODULES.json", '{"modules": []}')
        self.put(
            "codex-rs/hepta-unrelated/src/lib.rs",
            'const CATALOG: &str = include_str!("../../../docs/modules/MODULES.json");\n',
        )
        base = self.commit()
        self.replace(self.manifest, "order = 0", "order = 1")
        result = plan(self.root, base, self.commit())
        self.assertEqual(
            result["packages"],
            ["codex-hepta-host", "codex-hepta-leaf", "codex-hepta-unrelated"],
        )
        self.assertFalse(result["full_workspace"])

    def test_release_is_explicit_not_full_workspace_synonym(self):
        self.put(".github/workflows/release.yml", "name: fixture\n")
        self.assertEqual(self.risk([".github/workflows/release.yml"]), "release")
        self.assertEqual(
            classify({group: True for group in GROUPS} | {"full_repo": True}), "effect"
        )

    def test_build_program_cannot_use_read_only_owner_shortcut(self):
        self.put("codex-rs/hepta-leaf/build.rs", "fn main() {}\n")
        self.assertEqual(self.risk(["codex-rs/hepta-leaf/build.rs"]), "effect")

    def test_dependency_change_keeps_integration_checks(self):
        path = "codex-rs/hepta-leaf/Cargo.toml"
        self.replace(path, 'version="0.1.0"', 'version="0.1.1"')
        self.assertEqual(self.risk([path]), "stateful")

    def test_dirty_worktree_does_not_change_pinned_risk(self):
        from scripts.hepta_ci_modules import assess_changes

        self.put(self.source, "pub fn value() -> u32 { 2 }\n")
        head = self.commit()
        self.put(self.manifest, "deliberately invalid uncommitted TOML")
        self.assertEqual(
            assess_changes(self.root, [self.source], self.base, head)[0], "ordinary"
        )

    def test_duplicate_package_owner_is_rejected(self):
        self.put(
            "docs/modules/feature.other/module.toml",
            (self.root / self.manifest)
            .read_text()
            .replace("feature.leaf", "feature.other"),
        )
        with self.assertRaises(ValueError):
            self.risk(["docs/modules/feature.other/module.toml"])


if __name__ == "__main__":
    unittest.main()
