"""Exercise the real map verifier against disposable Git repositories."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "hepta_implementation_maps_identity_tests", SCRIPTS / "hepta-implementation-maps.py"
)
MAPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAPS)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Source identity test")
        self.git("config", "user.email", "source-identity@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.modules = [
            {"id": mid, "rootBindings": [{"path": f"src/{mid}"}]}
            for mid in ("alpha", "beta")
        ]
        self.write_json("docs/modules/MODULES.json", {"modules": self.modules})
        self.write_json("docs/readiness/READINESS.json", {
            "implementationLanes": [{"id": "lane", "modules": ["alpha", "beta"]}]
        })
        for mid in ("alpha", "beta"):
            self.write(f"src/{mid}/lib.rs", "pub fn run() {}\n")
        self.write("Cargo.lock", "# Source dependency fixture\n")
        self.commit("source")
        self.base = {"commit": self.git("rev-parse", "HEAD"),
                     "tree": self.git("rev-parse", "HEAD^{tree}")}
        self.rows = {}
        for mid in ("alpha", "beta"):
            root = f"src/{mid}"
            self.rows[mid] = {
                "schema": "hepta.module-implementation-map.v3", "schemaVersion": 3,
                "module": mid, "laneId": "lane", "sourceBase": dict(self.base),
                "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
                "declaredRoots": [root], "resolvedRoots": [root],
                "sourceRootPresent": True, "productionImplementation": False,
                "operations": [{"operation": "run", "nativeSymbol": "run",
                                "sourcePath": f"{root}/lib.rs"}],
                "claimBoundary": {"productExecutionProved": False},
            }
        self.observed()
        root_patch = patch.object(MAPS, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, text=True,
                              capture_output=True, check=True).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def write_json(self, path, value):
        self.write(path, json.dumps(value) + "\n")

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def save_maps(self):
        paths = []
        for mid, row in self.rows.items():
            path = f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
            self.write_json(path, row)
            paths.append(path)
        # The selected map is itself a committed input. Do not accidentally
        # commit staged/unstaged native changes in the dirty-source tests.
        self.git("add", "--", *paths)
        if self.git("diff", "--cached", "--name-only", "--", *paths):
            self.git("commit", "--only", "-qm", "map inputs", "--", *paths)

    def observed(self):
        for mid, row in self.rows.items():
            row["observedAtHead"] = dict(self.base)
            row["observedSourcePaths"] = [f"src/{mid}", "Cargo.lock"]

    def verify(self, *, strict=False):
        self.save_maps()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if strict:
                MAPS.verify(require_current_source=True)
            else:
                MAPS.verify()
        return json.loads(output.getvalue())

    def rejects(self, fragment, *, strict=False):
        with self.assertRaisesRegex(SystemExit, fragment):
            self.verify(strict=strict)

    def test_all_modern_maps_do_not_require_a_legacy_row(self):
        result = self.verify()
        self.assertEqual(result["exactObservedFallbackMaps"], 2)
        self.assertEqual(result["legacyProvenanceOnlyMaps"], [])

    def test_current_candidate_is_generated_not_written_into_maps(self):
        self.verify(strict=True)
        before = {p: p.read_bytes() for p in self.root.glob("docs/modules/*/*.json")}
        with contextlib.redirect_stdout(io.StringIO()):
            MAPS.verify(require_current_source=True)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_mixed_migration_preserves_navigation(self):
        del self.rows["beta"]["sourceIdentityPolicy"]
        result = self.verify()
        self.assertEqual(result["exactObservedFallbackMaps"], 2)
        self.assertEqual(result["legacyProvenanceOnlyMaps"], [])
        self.assertTrue(result["currentSourceIdentityRequired"])
        self.assertFalse(result["productionImplementationProved"])

    def test_equally_stale_legacy_maps_are_not_current_evidence(self):
        for row in self.rows.values():
            row.pop("sourceIdentityPolicy")
        self.write("notes.md", "another commit\n")
        self.commit("documentation")
        result = self.verify()
        self.assertEqual(result["legacyProvenanceOnlyMaps"], [])
        self.assertEqual(result["candidateSource"]["commit"], self.git("rev-parse", "HEAD"))
        self.write("src/alpha/lib.rs", "pub fn unobserved() {}\n")
        self.commit("uniform old anchors must not hide changed source")
        self.rejects("changed after source observation")
        self.rejects("changed after source observation", strict=True)

    def test_invalid_legacy_anchor_still_fails(self):
        for row in self.rows.values():
            row.pop("sourceIdentityPolicy")
        self.rows["beta"]["sourceBase"]["commit"] = "b" * 40
        self.rejects("FAIL_HEPTA_IMPLEMENTATION_MAPS")

    def test_empty_module_registry_fails(self):
        self.write_json("docs/modules/MODULES.json", {"modules": []})
        self.git("commit", "--only", "-qm", "empty registry", "--", "docs/modules/MODULES.json")
        self.rejects("module registry must be nonempty")

    def test_malformed_identity_fails_without_type_error(self):
        self.rows["alpha"]["sourceBase"]["commit"] = ["not", "a", "sha"]
        self.rejects("literal commit/tree")

    def test_unknown_policy_fails(self):
        self.rows["alpha"]["sourceIdentityPolicy"] = "permissive"
        self.rejects("unknown source identity policy")

    def test_old_candidate_without_observation_fails(self):
        for row in self.rows.values():
            row.pop("observedAtHead")
            row.pop("observedSourcePaths")
        self.write("notes.md", "another commit\n")
        self.commit("documentation")
        self.rejects("neither candidate nor exact observed source")

    def test_documentation_only_commits_preserve_observed_source(self):
        self.observed()
        self.write("notes.md", "another commit\n")
        self.commit("documentation")
        result = self.verify(strict=True)
        self.assertEqual(result["exactObservedFallbackMaps"], 2)
        self.assertEqual(self.rows["alpha"]["sourceBase"], self.base)

    def test_observed_source_commit_drift_fails(self):
        self.observed()
        self.write("src/alpha/lib.rs", "pub fn changed() {}\n")
        self.commit("changed source")
        self.rejects("changed after source observation")

    def test_declared_dependency_drift_fails(self):
        self.observed()
        self.write("Cargo.lock", "# Changed dependency\n")
        self.commit("changed dependency")
        self.rejects("changed after source observation")

    def test_wrong_observed_tree_fails(self):
        self.observed()
        self.rows["alpha"]["observedAtHead"]["tree"] = "f" * 40
        self.rejects("source tree mismatch")

    def test_omitted_source_root_fails(self):
        self.observed()
        self.rows["alpha"]["observedSourcePaths"] = ["Cargo.lock"]
        self.rejects("observed source paths omit resolved roots")

    def test_dirty_source_cannot_pass_strict_current_candidate(self):
        self.write("src/alpha/lib.rs", "pub fn dirty() {}\n")
        self.rejects("dirty|uncommitted evidence", strict=True)

    def test_staged_source_cannot_pass_strict_current_candidate(self):
        self.write("src/alpha/lib.rs", "pub fn staged() {}\n")
        self.git("add", "src/alpha/lib.rs")
        self.rejects("dirty|uncommitted evidence", strict=True)

    def test_untracked_source_cannot_pass_strict_current_candidate(self):
        self.write("src/alpha/new.rs", "pub fn new() {}\n")
        self.rejects("dirty|uncommitted evidence", strict=True)

    def test_ignored_source_cannot_pass_strict_current_candidate(self):
        self.write(".git/info/exclude", "new.rs\n")
        self.write("src/alpha/new.rs", "pub fn ignored() {}\n")
        self.rejects("dirty|uncommitted evidence", strict=True)

    def test_symlink_observation_cannot_hide_target_changes(self):
        self.observed()
        (self.root / "dependency-link").symlink_to("Cargo.lock")
        self.commit("link")
        self.rows["alpha"]["observedSourcePaths"].append("dependency-link")
        self.rejects("symlink source path")

    def test_non_canonical_observed_path_fails(self):
        self.observed()
        self.rows["alpha"]["observedSourcePaths"].append("src/alpha/../beta")
        self.rejects("non-canonical source path")

    def test_non_ancestor_observation_fails(self):
        self.observed()
        self.write("branch-only.md", "not in candidate history\n")
        self.commit("unmerged candidate")
        other = {"commit": self.git("rev-parse", "HEAD"),
                 "tree": self.git("rev-parse", "HEAD^{tree}")}
        self.git("checkout", "--detach", "-q", self.base["commit"])
        self.rows["alpha"]["sourceBase"] = dict(other)
        self.rows["alpha"]["observedAtHead"] = dict(other)
        self.rejects("FAIL_HEPTA_IMPLEMENTATION_MAPS")

    def test_git_pathspec_metacharacters_are_literal(self):
        self.write("dependency[1]", "original\n")
        self.commit("dependency with literal name")
        self.base = {"commit": self.git("rev-parse", "HEAD"),
                     "tree": self.git("rev-parse", "HEAD^{tree}")}
        for row in self.rows.values():
            row["sourceBase"] = dict(self.base)
        self.observed()
        self.rows["alpha"]["observedSourcePaths"].append("dependency[1]")
        self.write("dependency[1]", "changed\n")
        self.commit("changed literal dependency")
        self.rejects("changed after source observation")

    def test_strict_flag_is_not_a_mutation_command(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "hepta-implementation-maps.py"),
             "generate", "--require-current-source"],
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("applies only to verify", result.stderr)


if __name__ == "__main__":
    unittest.main()
