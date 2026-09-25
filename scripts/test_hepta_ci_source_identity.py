#!/usr/bin/env python3
"""Regression checks for event-bound source scope and executable CI test gates."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LANE_B = load_module("ci_source_lane_b", "hepta-lane-b-truth.py")
LANE_B_PATHS = load_module(
    "ci_source_lane_b_paths", "hepta-lane-b-path-guard.py"
)
LANE_E = load_module("ci_source_lane_e", "hepta-lane-e-closure.py")
IMAPS = load_module("ci_implementation_maps", "hepta-implementation-maps.py")


class GitSourceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "CI regression")
        self.git("config", "user.email", "ci-regression@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.source_base = self.commit("owned/seed.py", "seed", "source provenance")
        self.source_tree = self.git("rev-parse", "HEAD^{tree}")
        self.git("switch", "-q", "-c", "historical-side")
        self.commit("old-foreign.txt", "old", "historical foreign lane")
        self.git("switch", "-q", "-c", "target", self.source_base)
        self.commit("target.txt", "target", "historical target")
        self.git("merge", "--no-ff", "--no-edit", "historical-side")
        self.base = self.git("rev-parse", "HEAD")
        self.git("switch", "-q", "-c", "candidate")
        self.head = self.commit(
            "owned/provider.py", "provider", "current source change"
        )
        self.event = {
            "pull_request": {
                "base": {"ref": "target", "sha": self.base},
                "head": {"ref": "candidate", "sha": self.head},
                "body": "Ordinary explanation with no generated identity block.",
            }
        }
        self.event_path = Path(self.directory.name) / "event.json"
        self.truth = {
            "sourceBase": {"commit": self.source_base, "tree": self.source_tree}
        }
        self.manifest = {
            "schema": "hepta.lane-b-candidate-manifest.v3",
            "sourceBase": copy.deepcopy(self.truth["sourceBase"]),
            "allowedPathPrefixes": ["qualification/lane-b/"],
        }

    def git(self, *args: str, input_text: str | None = None) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            input=input_text,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(self, path: str, value: str, message: str) -> str:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")
        self.git("add", path)
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def test_lane_b_modern_policy_uses_exact_shared_source_checks(self) -> None:
        row = {
            "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
            "sourceBase": {
                "commit": self.head,
                "tree": self.git("rev-parse", "HEAD^{tree}"),
            },
            "resolvedRoots": ["owned"],
            "operations": [{"sourcePath": "owned/provider.py"}],
        }
        with mock.patch.object(LANE_B, "ROOT", self.root):
            self.assertEqual(
                LANE_B.verify_module_source_base(row, "fixture")[0], self.head
            )
            (self.root / "owned/provider.py").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(LANE_B.Invalid, "canonical source identity"):
                LANE_B.verify_module_source_base(row, "fixture")
            self.git("add", "owned/provider.py")
            self.git("commit", "-qm", "committed source drift")
            with self.assertRaisesRegex(LANE_B.Invalid, "canonical source identity"):
                LANE_B.verify_module_source_base(row, "fixture")

    def lane_a(self) -> subprocess.CompletedProcess:
        self.event_path.write_text(json.dumps(self.event), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_lane_a_pr_tuple.py"),
                "--event",
                str(self.event_path),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def lane_b(
        self, *, synthetic: bool = False, roots: tuple[str, ...] = ("owned",)
    ) -> list[str]:
        self.event_path.write_text(json.dumps(self.event), encoding="utf-8")
        env = {"GITHUB_EVENT_PATH": str(self.event_path)}
        if synthetic:
            env["HEPTA_SYNTHETIC_MERGE"] = "1"
        with (
            mock.patch.object(LANE_B, "ROOT", self.root),
            mock.patch.object(
                LANE_B, "module_maps", return_value=[{"resolvedRoots": list(roots)}]
            ),
            mock.patch.dict(os.environ, env, clear=True),
        ):
            return LANE_B.verify_candidate(self.manifest, self.truth)

    def maps_at(self, source_base: dict) -> list[dict]:
        truth = copy.deepcopy(self.truth)
        truth["modules"] = [
            {
                "module": module,
                "mapPath": f"docs/modules/{module}/IMPLEMENTATION_MAP.json",
                "operationIds": LANE_B.OPS[module],
            }
            for module in LANE_B.MODULES
        ]
        maps = [
            {
                "module": module,
                "sourceBase": copy.deepcopy(source_base),
                "operations": [
                    {"operation": operation} for operation in LANE_B.OPS[module]
                ],
            }
            for module in LANE_B.MODULES
        ]
        with (
            mock.patch.object(LANE_B, "ROOT", self.root),
            mock.patch.object(LANE_B, "load", side_effect=maps),
        ):
            return LANE_B.module_maps(truth)

    def test_module_provenance_can_advance_without_rewriting_lane_history(self) -> None:
        base = {"commit": self.head, "tree": self.git("rev-parse", "HEAD^{tree}")}
        maps = self.maps_at(base)
        self.assertEqual([row["sourceBase"] for row in maps], [base] * len(maps))
        self.assertNotEqual(base, self.truth["sourceBase"])

    def test_module_provenance_rejects_forged_tree_and_missing_commit(self) -> None:
        with self.assertRaisesRegex(LANE_B.Invalid, "source tree"):
            self.maps_at({"commit": self.head, "tree": self.source_tree})
        with self.assertRaises(LANE_B.Invalid):
            self.maps_at({"commit": "a" * 40, "tree": self.source_tree})
        for malformed in (None, {}, {"commit": [], "tree": self.source_tree}):
            with self.subTest(malformed=malformed), self.assertRaises(LANE_B.Invalid):
                self.maps_at(malformed)

    def test_module_provenance_rejects_unrelated_valid_git_tree(self) -> None:
        unrelated = self.git("commit-tree", self.source_tree, input_text="unrelated\n")
        with self.assertRaises(LANE_B.Invalid):
            self.maps_at({"commit": unrelated, "tree": self.source_tree})

    def test_lane_a_uses_event_and_git_without_body_registration(self) -> None:
        result = self.lane_a()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.split(": ", 1)[1])
        self.assertEqual(observed["head_sha"], self.head)
        self.assertEqual(observed["base_sha"], self.base)
        self.assertEqual(observed["commits"], 1)
        self.event["pull_request"]["body"] = (
            "<!-- lane-a-exact-subject:v4 -->\nhead SHA: stale"
        )
        self.assertEqual(self.lane_a().returncode, 0)

    def test_lane_a_rejects_wrong_checkout_missing_base_and_dirty_source(self) -> None:
        self.git("checkout", "--detach", self.base)
        self.assertIn("checkout is not", self.lane_a().stderr)
        self.git("checkout", "--detach", self.head)
        self.event["pull_request"]["base"]["sha"] = "a" * 40
        self.assertNotEqual(self.lane_a().returncode, 0)
        self.event["pull_request"]["base"]["sha"] = self.base
        (self.root / "owned/provider.py").write_text("uncommitted", encoding="utf-8")
        self.assertNotEqual(self.lane_a().returncode, 0)

    def test_lane_b_scopes_current_delta_despite_historical_merges(self) -> None:
        self.assertTrue(self.git("rev-list", "--merges", f"{self.source_base}..HEAD"))
        before = copy.deepcopy(self.manifest)
        self.assertEqual(self.lane_b(), ["owned/provider.py"])
        self.assertEqual(self.manifest, before)
        self.commit("other-lane/new.py", "other", "parallel lane")
        self.event["pull_request"]["head"]["sha"] = self.git("rev-parse", "HEAD")
        self.assertEqual(self.lane_b(), ["owned/provider.py"])

    def test_lane_b_excludes_target_only_changes_after_divergence(self) -> None:
        self.git("switch", "-q", "target")
        new_base = self.commit("owned/base-only.py", "target update", "target advances")
        self.git("switch", "-q", "candidate")
        self.event["pull_request"]["base"]["sha"] = new_base
        self.assertEqual(self.lane_b(), ["owned/provider.py"])

    def test_lane_b_rejects_stale_head_provenance_and_escaped_ownership(self) -> None:
        self.event["pull_request"]["head"]["sha"] = self.base
        with self.assertRaisesRegex(LANE_B.Invalid, "checkout is not"):
            self.lane_b()
        self.event["pull_request"]["head"]["sha"] = self.head
        with self.assertRaisesRegex(LANE_B.Invalid, "invalid owner root"):
            self.lane_b(roots=("../outside",))
        self.manifest["sourceBase"]["tree"] = "b" * 40
        with self.assertRaisesRegex(LANE_B.Invalid, "manifest source base"):
            self.lane_b()

    def test_synthetic_merge_checks_event_parents_and_recomputed_tree(self) -> None:
        tree = self.git("merge-tree", "--write-tree", self.base, self.head)
        valid = self.git(
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.head,
            input_text="synthetic\n",
        )
        self.git("checkout", "--detach", valid)
        self.assertEqual(self.lane_b(synthetic=True), ["owned/provider.py"])
        wrong_tree = self.git("rev-parse", f"{self.base}^{{tree}}")
        forged = self.git(
            "commit-tree",
            wrong_tree,
            "-p",
            self.base,
            "-p",
            self.head,
            input_text="wrong tree\n",
        )
        self.git("checkout", "--detach", forged)
        with self.assertRaisesRegex(LANE_B.Invalid, "tree differs"):
            self.lane_b(synthetic=True)
        swapped = self.git(
            "commit-tree",
            tree,
            "-p",
            self.head,
            "-p",
            self.base,
            input_text="wrong parents\n",
        )
        self.git("checkout", "--detach", swapped)
        with self.assertRaisesRegex(LANE_B.Invalid, "parents differ"):
            self.lane_b(synthetic=True)


class ImplementationMapSourceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "implementation-map regression")
        self.git("config", "user.email", "implementation-map@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        source = self.root / "owner-crate" / "src"
        source.mkdir(parents=True)
        (source / "lib.rs").write_text(
            "mod canonical;\npub use canonical::prepare;\n",
            encoding="utf-8",
        )
        (source / "canonical.rs").write_text(
            "pub fn prepare() {}\n",
            encoding="utf-8",
        )
        self.git("add", ".")
        self.git("commit", "-qm", "observed owner source")
        self.observed_commit = self.git("rev-parse", "HEAD")
        self.observed_tree = self.git("rev-parse", "HEAD^{tree}")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def observed_row(self) -> dict:
        return {
            "sourceBase": {"commit": self.observed_commit, "tree": self.observed_tree},
            "observedAtHead": {
                "commit": self.observed_commit,
                "tree": self.observed_tree,
            },
            "observedSourcePaths": ["owner-crate"],
        }

    def validate(self) -> list[str]:
        failures: list[str] = []
        with mock.patch.object(IMAPS, "ROOT", self.root):
            IMAPS.validate_observed_source(
                self.observed_row(),
                "owner.module",
                ["owner-crate"],
                failures,
            )
        return failures

    def test_exact_observed_source_survives_docs_only_commit_but_rejects_source_drift(
        self,
    ) -> None:
        docs = self.root / "docs" / "note.md"
        docs.parent.mkdir()
        docs.write_text("projection only\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "docs only")
        self.assertEqual(self.validate(), [])

        source = self.root / "owner-crate" / "src" / "canonical.rs"
        source.write_text(
            "pub fn prepare() {}\npub fn new_surface() {}\n", encoding="utf-8"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "owner source drift")
        failures = self.validate()
        self.assertTrue(
            any("mapped source/evidence changed" in failure for failure in failures),
            failures,
        )

    def test_closed_world_public_function_scan_tracks_root_exports(self) -> None:
        with mock.patch.object(IMAPS, "ROOT", self.root):
            self.assertEqual(
                IMAPS.public_rust_functions("owner-crate"),
                {"prepare"},
            )
        source = self.root / "owner-crate" / "src" / "lib.rs"
        source.write_text(
            "mod canonical;\npub use canonical::prepare;\npub fn direct() {}\n",
            encoding="utf-8",
        )
        with mock.patch.object(IMAPS, "ROOT", self.root):
            self.assertEqual(
                IMAPS.public_rust_functions("owner-crate"),
                {"prepare", "direct"},
            )


class SourceConformanceTests(unittest.TestCase):
    def test_cli_self_test_runs_the_real_entrypoint(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "hepta-lane-b-truth.py"), "self-test"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout)["operations"], LANE_B.OPERATION_COUNT
        )
        evaluation = subprocess.run(
            [sys.executable, str(SCRIPTS / "hepta-lane-e-closure.py"), "self-test"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(json.loads(evaluation.stdout)["ok"])

    def test_honest_module_gaps_do_not_claim_completion_or_hide_bad_anchors(
        self,
    ) -> None:
        truth = LANE_B.load(LANE_B.TRUTH)
        # This is a semantic claim/anchor test. Historical provenance is tested
        # against real temporary Git histories by GitSourceIdentityTests above.
        # Load the retained map fixtures directly so source-only archives can
        # exercise these assertions without pretending to possess Git ancestry.
        # Production module_maps and its provenance checks remain unchanged.
        maps = [LANE_B.load(LANE_B.ROOT / row["mapPath"]) for row in truth["modules"]]
        truth["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = False
        maps[0]["repositoryControlledGaps"] = [
            "Wire the registered owner to a real observer."
        ]
        maps[0]["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = False
        self.assertEqual(LANE_B.verify_truth(truth, maps)[0], LANE_B.OPERATION_COUNT)
        projection = LANE_B.native_projection(truth, maps)
        self.assertIn(maps[0]["repositoryControlledGaps"][0], projection)
        self.assertNotIn("source gaps closed", projection)
        truth["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = True
        with self.assertRaisesRegex(LANE_B.Invalid, "completion contradicts"):
            LANE_B.verify_truth(truth, maps)
        truth["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = False
        maps[0]["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = True
        with self.assertRaisesRegex(LANE_B.Invalid, "completion contradicts"):
            LANE_B.verify_truth(truth, maps)
        maps[0]["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = False
        maps[0]["operations"][0]["ownerEntrypoint"]["symbol"] = (
            "nonexistent_owner_symbol"
        )
        with self.assertRaisesRegex(LANE_B.Invalid, "missing symbol"):
            LANE_B.verify_truth(truth, maps)

    def test_path_guard_resolves_registered_cross_lane_owner_roots(self):
        truth = LANE_B_PATHS.load(LANE_B_PATHS.TRUTH)
        maps = {
            entry["module"]: LANE_B_PATHS.load(
                LANE_B_PATHS.ROOT / entry["mapPath"]
            )
            for entry in truth["modules"]
        }
        roots = {module: list(row["resolvedRoots"]) for module, row in maps.items()}
        LANE_B_PATHS.add_registered_delegate_roots(
            LANE_B_PATHS.ROOT, maps, roots
        )
        self.assertEqual(roots["learning.ledger"], ["codex-rs/hepta-learning-ledger"])
        self.assertEqual(roots["neuron.runtime"], ["codex-rs/hepta-neuron"])

        changed = copy.deepcopy(maps)
        agentd = changed["runtime.agentd"]
        operation = next(
            row
            for row in agentd["operations"]
            if row.get("operation") == "admit_revalidated_run_start"
        )
        operation["delegatedCallees"][0]["ownerModule"] = "unregistered.owner"
        with self.assertRaisesRegex(
            LANE_B_PATHS.Invalid, "unregistered delegated owner"
        ):
            LANE_B_PATHS.add_registered_delegate_roots(
                LANE_B_PATHS.ROOT, changed, {
                    module: list(row["resolvedRoots"])
                    for module, row in changed.items()
                }
            )

    def test_registered_cross_lane_delegate_preserves_owner_boundary(self):
        truth = LANE_B.load(LANE_B.TRUTH)
        maps = [LANE_B.load(LANE_B.ROOT / row["mapPath"]) for row in truth["modules"]]
        agentd = next(row for row in maps if row["module"] == "runtime.agentd")
        operation = next(
            row
            for row in agentd["operations"]
            if row.get("operation") == "admit_revalidated_run_start"
        )
        delegate = operation["delegatedCallees"][0]
        self.assertEqual(delegate["ownerModule"], "learning.ledger")
        self.assertEqual(LANE_B.verify_truth(truth, maps)[0], LANE_B.OPERATION_COUNT)
        delegate["ownerModule"] = "unregistered.owner"
        with self.assertRaisesRegex(LANE_B.Invalid, "unregistered delegated owner"):
            LANE_B.verify_truth(truth, maps)
        delegate["ownerModule"] = "neuron.runtime"
        with self.assertRaisesRegex(LANE_B.Invalid, "delegate-root escape"):
            LANE_B.verify_truth(truth, maps)


class DependencyOwnershipTests(unittest.TestCase):
    def test_alias_and_direct_dependency_are_not_arbitrary_ownership(self) -> None:
        roots = ["codex-rs/codex-app-server", "codex-rs/hepta-codex-adapter"]
        delegate = {
            "path": "codex-rs/core/src/codex_thread.rs",
            "buildTarget": "codex-core",
        }
        self.assertTrue(LANE_B.delegate_matches_owner("runtime.codex", roots, delegate))
        for wrong in (
            {**delegate, "buildTarget": "codex-tui"},
            {"path": "codex-rs/tui/src/lib.rs", "buildTarget": "codex-tui"},
            {**delegate, "path": "../outside/core/src/codex_thread.rs"},
        ):
            with self.subTest(wrong=wrong):
                self.assertFalse(
                    LANE_B.delegate_matches_owner("runtime.codex", roots, wrong)
                )
        with self.assertRaisesRegex(LANE_B.Invalid, "invalid source alias"):
            LANE_B.delegate_matches_owner("runtime.agentd", roots, delegate)


class WorkflowGateTests(unittest.TestCase):
    def findings(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(text, encoding="utf-8")
            with mock.patch.object(LANE_E, "WORKFLOW_PATH", path):
                findings = LANE_E.Findings()
                LANE_E.verify_workflow(findings)
                return [item.code for item in findings.items]

    def test_implementation_map_workflows_use_current_exact_source_cli(self) -> None:
        workflows = (
            "hepta-objective-admission.yml",
            "hepta-lane-d-semantic-conformance.yml",
            "hepta-contract-gate.yml",
        )
        root = SCRIPTS.parent / ".github" / "workflows"
        for name in workflows:
            with self.subTest(workflow=name):
                workflow = (root / name).read_text(encoding="utf-8")
                self.assertIn(
                    "python3 scripts/hepta-implementation-maps.py verify "
                    "--require-current-source",
                    workflow,
                )
                self.assertNotIn(
                    "hepta-implementation-maps.py verify --expected-sha", workflow
                )
                self.assertNotRegex(
                    workflow,
                    r"hepta-implementation-maps[.]py verify[\s\S]{0,160}"
                    r"--expected-(?:sha|tree)",
                )
                self.assertIn('test "$(git rev-parse HEAD)" = ', workflow)

    def test_real_just_and_legacy_cargo_commands_preserve_test_contract(self) -> None:
        text = LANE_E.WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual(self.findings(text), [])
        self.assertEqual(
            self.findings(text.replace("just test --locked", "cargo test --locked")), []
        )

    def test_comments_and_echo_cannot_substitute_for_executed_tests(self) -> None:
        text = LANE_E.WORKFLOW_PATH.read_text(encoding="utf-8")
        for replacement in ("echo just test --locked", "# just test --locked"):
            with self.subTest(replacement=replacement):
                self.assertIn(
                    "workflow_crate_missing",
                    self.findings(text.replace("just test --locked", replacement)),
                )

    def test_compilation_mentions_do_not_replace_test_package_or_causal_filter(
        self,
    ) -> None:
        text = LANE_E.WORKFLOW_PATH.read_text(encoding="utf-8")
        text = text.replace(
            "lane_e_causal_candidate_chain_is_digest_bound_and_deny_all",
            "unrelated_test",
        )
        self.assertIn("workflow_gate_missing", self.findings(text))
        original = LANE_E.WORKFLOW_PATH.read_text(encoding="utf-8")
        commands = original.replace("just test --locked", "just test --offline")
        self.assertIn("workflow_crate_missing", self.findings(commands))


if __name__ == "__main__":
    unittest.main()
