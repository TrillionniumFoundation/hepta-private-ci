"""Behavioral provenance regressions against real, disposable Git repositories."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("implementation_maps", SCRIPTS / "hepta-implementation-maps.py")
assert SPEC is not None and SPEC.loader is not None
maps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maps)


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(maps, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Source identity test")
        self.git("config", "user.email", "source-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.modules = [self.module("alpha"), self.module("beta")]
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        self.write("docs/readiness/READINESS.json", {"implementationLanes": [{"id": "test-lane", "modules": ["alpha", "beta"]}]})
        for name in ("alpha", "beta"):
            self.write(f"src/{name}/lib.rs", "pub fn calculate() {}\n")
        self.write("tests/native.rs", "#[test] fn qualified() {}\n")
        self.write("host/caller.rs", "fn caller() {}\n")
        self.write("README.md", "source identity fixture\n")
        self.anchor = self.commit("sources")
        self.rows = {name: self.row(name, self.anchor) for name in ("alpha", "beta")}
        self.save_maps()
        self.commit("maps")

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *args], cwd=self.root, env=env, check=True, text=True, capture_output=True).stdout.strip()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n" if isinstance(data, (dict, list)) else data, encoding="utf-8")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return {"commit": self.git("rev-parse", "HEAD"), "tree": self.git("rev-parse", "HEAD^{tree}")}

    def module(self, name):
        return {"id": name, "owner": "owner", "deputy": "reviewer", "rootBindings": [{"path": f"src/{name}"}], "technicalDocument": f"docs/modules/{name}/TECHNICAL.md"}

    def row(self, name, anchor):
        return {
            "schema": "hepta.module-implementation-map.v3", "schemaVersion": 3,
            "sourceBase": copy.deepcopy(anchor), "laneId": "test-lane", "module": name,
            "declaredRoots": [f"src/{name}"], "resolvedRoots": [f"src/{name}"],
            "sourceRootPresent": True, "productionImplementation": False,
            "operations": [{"operation": "calculate", "nativeSymbol": "calculate", "sourcePath": f"src/{name}/lib.rs", "tests": [], "delegatedCallees": []}],
            "claimBoundary": {"nativeSourceMappingComplete": False, "productExecutionProved": False},
        }

    def save_maps(self):
        for name, row in self.rows.items():
            self.write(f"docs/modules/{name}/IMPLEMENTATION_MAP.json", row)

    def change_maps(self):
        self.save_maps()
        self.commit("update map")

    def verify(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            maps.verify()
        return json.loads(output.getvalue())

    def reject(self):
        with self.assertRaises(SystemExit):
            self.verify()

    def test_unchanged_ancestral_source_passes(self):
        self.assertEqual(self.verify()["candidateSource"]["commit"], self.git("rev-parse", "HEAD"))

    def test_independent_module_anchors_pass(self):
        self.write("src/beta/lib.rs", "pub fn calculate() { let _x = 1; }\n")
        self.rows["beta"]["sourceBase"] = self.commit("beta only")
        self.change_maps()
        self.verify()

    def test_all_candidate_policy_maps_pass_without_legacy_batch(self):
        for row in self.rows.values():
            row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
            row["observedAtHead"] = copy.deepcopy(row["sourceBase"])
            row["observedSourcePaths"] = list(row["resolvedRoots"])
        self.change_maps()
        self.verify()

    def test_document_only_commit_preserves_evidence(self):
        self.write("README.md", "new prose does not change native source\n")
        self.commit("prose")
        self.verify()

    def test_untracked_ci_report_outside_sources_is_not_a_mutation(self):
        self.write(".hepta-evidence/source-head.json", {"test": "report"})
        self.verify()

    def test_uniformly_stale_maps_reject(self):
        self.write("src/alpha/lib.rs", "pub fn changed() {}\n")
        self.commit("native drift")
        self.reject()

    def test_new_file_in_root_rejects(self):
        self.write("src/alpha/new.rs", "pub fn new_operation() {}\n")
        self.commit("new operation")
        self.reject()

    def test_removed_file_in_root_rejects(self):
        (self.root / "src/alpha/lib.rs").unlink()
        self.commit("delete operation")
        self.reject()

    def test_mapped_test_drift_rejects(self):
        self.rows["alpha"]["operations"][0]["tests"] = [{"path": "tests/native.rs"}]
        self.change_maps()
        self.write("tests/native.rs", "// the test was removed\n")
        self.commit("test drift")
        self.reject()

    def test_delegated_caller_drift_rejects(self):
        self.rows["alpha"]["operations"][0]["delegatedCallees"] = [{"path": "host/caller.rs"}]
        self.change_maps()
        self.write("host/caller.rs", "fn changed_caller() {}\n")
        self.commit("caller drift")
        self.reject()

    def test_missing_mapped_test_rejects(self):
        self.rows["alpha"]["operations"][0]["tests"] = [{"path": "tests/does_not_exist.rs"}]
        self.change_maps()
        self.reject()

    def test_symbolic_source_ref_rejects(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        for row in self.rows.values():
            row["sourceBase"] = {"commit": "HEAD^", "tree": tree}
        self.change_maps()
        self.reject()

    def test_wrong_tree_rejects(self):
        self.rows["alpha"]["sourceBase"]["tree"] = "0" * 40
        self.change_maps()
        self.reject()

    def test_nonancestor_rejects(self):
        other = self.git("-c", "commit.gpgsign=false", "commit-tree", self.anchor["tree"], "-m", "unrelated")
        for row in self.rows.values():
            row["sourceBase"]["commit"] = other
        self.change_maps()
        self.reject()

    def test_unavailable_commit_rejects(self):
        self.rows["alpha"]["sourceBase"]["commit"] = "0" * 40
        self.change_maps()
        self.reject()

    def test_staged_source_change_rejects(self):
        self.write("src/alpha/lib.rs", "// staged native drift\n")
        self.git("add", "src/alpha/lib.rs")
        self.reject()

    def test_unstaged_source_change_rejects(self):
        self.write("src/alpha/lib.rs", "// unstaged native drift\n")
        self.reject()

    def test_untracked_source_rejects(self):
        self.write("src/alpha/untracked.rs", "// new source must be committed\n")
        self.reject()

    def test_path_traversal_rejects(self):
        self.rows["alpha"]["operations"][0]["tests"] = [{"path": "../outside.rs"}]
        self.change_maps()
        self.reject()

    def test_git_pathspec_magic_rejects(self):
        self.rows["alpha"]["operations"][0]["tests"] = [{"path": ":(exclude)src/alpha"}]
        self.change_maps()
        self.reject()

    def test_symlink_evidence_rejects(self):
        (self.root / "tests/link.rs").symlink_to("../src/alpha/lib.rs")
        anchor = self.commit("symlink source")
        for row in self.rows.values():
            row["sourceBase"] = anchor
        self.rows["alpha"]["operations"][0]["tests"] = [{"path": "tests/link.rs"}]
        self.change_maps()
        self.reject()

    def test_unknown_identity_policy_rejects(self):
        self.rows["alpha"]["sourceIdentityPolicy"] = "skip_verification"
        self.change_maps()
        self.reject()

    def test_observed_additional_input_drift_rejects(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["observedAtHead"] = copy.deepcopy(self.anchor)
        row["observedSourcePaths"] = ["src/alpha", "host/caller.rs"]
        self.change_maps()
        self.write("host/caller.rs", "fn changed_observer() {}\n")
        self.commit("observed input drift")
        self.reject()

    def test_observed_paths_must_cover_resolved_roots(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["observedAtHead"] = copy.deepcopy(self.anchor)
        row["observedSourcePaths"] = ["host/caller.rs"]
        self.change_maps()
        self.reject()

    def test_ambient_git_dir_does_not_redirect_verification(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.root / "missing.git")}):
            self.verify()

    def test_replace_object_cannot_forge_anchor_tree(self):
        self.write("src/alpha/lib.rs", "pub fn substituted() {}\n")
        changed = self.commit("different native source")
        replacement = self.git("commit-tree", changed["tree"], "-m", "fake anchor")
        self.git("replace", self.anchor["commit"], replacement)
        for row in self.rows.values():
            row["sourceBase"]["tree"] = changed["tree"]
        self.change_maps()
        self.reject()

    def test_migration_does_not_promote_mapping_claim(self):
        row = maps.migrate_map(self.rows["alpha"], self.modules[0], {"alpha": "test-lane"}, self.anchor)
        self.assertIs(row["claimBoundary"]["nativeSourceMappingComplete"], False)

    def test_generator_does_not_infer_complete_mapping(self):
        self.write("qualification/module-execution-dossiers/detail/alpha.md", "**Implemented entrypoints:** `calculate` in [src/alpha/lib.rs]\n")
        row = maps.map_for(self.modules[0], self.anchor, {"alpha": "test-lane"})
        self.assertIs(row["claimBoundary"]["nativeSourceMappingComplete"], False)

    def test_selected_migration_leaves_other_module_bytes_unchanged(self):
        beta = self.root / "docs/modules/beta/IMPLEMENTATION_MAP.json"
        before = beta.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        self.assertEqual(beta.read_bytes(), before)

    def test_unknown_migration_module_fails_before_writes(self):
        before = {name: (self.root / f"docs/modules/{name}/IMPLEMENTATION_MAP.json").read_bytes() for name in self.rows}
        with self.assertRaises(SystemExit):
            maps.migrate(["alpha", "unknown"])
        for name, data in before.items():
            self.assertEqual((self.root / f"docs/modules/{name}/IMPLEMENTATION_MAP.json").read_bytes(), data)

    def test_empty_registry_rejects(self):
        self.write("docs/modules/MODULES.json", {"modules": []})
        self.commit("empty registry")
        self.reject()

    def test_duplicate_module_identity_rejects(self):
        self.write("docs/modules/MODULES.json", {"modules": [self.modules[0], self.modules[0]]})
        self.commit("duplicate module")
        self.reject()

    def test_duplicate_json_keys_reject(self):
        path = self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        text = path.read_text()
        path.write_text(text.replace('"schemaVersion": 3,', '"schemaVersion": 3, "schemaVersion": 3,'))
        self.commit("ambiguous JSON")
        self.reject()

    def test_assume_unchanged_cannot_hide_native_drift(self):
        source = "src/alpha/lib.rs"
        self.git("update-index", "--assume-unchanged", source)
        self.write(source, "pub fn substituted() {}\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_skip_worktree_cannot_hide_native_drift(self):
        source = "src/alpha/lib.rs"
        self.git("update-index", "--skip-worktree", source)
        self.write(source, "pub fn substituted() {}\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_combined_index_flags_cannot_hide_native_drift(self):
        source = "src/alpha/lib.rs"
        self.git("update-index", "--skip-worktree", source)
        self.git("update-index", "--assume-unchanged", source)
        self.write(source, "pub fn substituted() {}\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_hidden_registry_is_rejected_before_it_controls_verification(self):
        path = "docs/modules/MODULES.json"
        self.git("update-index", "--assume-unchanged", path)
        # Omitting alpha would otherwise hide its committed source drift.
        self.write(path, {"modules": [self.modules[1]]})
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_hidden_map_cannot_change_the_claim_input(self):
        path = "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        self.git("update-index", "--skip-worktree", path)
        row = copy.deepcopy(self.rows["alpha"])
        row["productionImplementation"] = True
        self.write(path, row)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_clean_hidden_index_is_not_an_exact_checkout(self):
        self.git("update-index", "--assume-unchanged", "README.md")
        self.reject()

    def test_clearing_hidden_flag_restores_verification_without_rebinding(self):
        self.git("update-index", "--skip-worktree", "src/alpha/lib.rs")
        self.git("update-index", "--no-skip-worktree", "src/alpha/lib.rs")
        self.verify()

    def test_hidden_filename_record_cannot_split_the_index_check(self):
        path = "src/alpha/space tab\tnewline\nfile.rs"
        self.write(path, "pub fn extra() {}\n")
        anchor = self.commit("unusual tracked filename")
        for row in self.rows.values():
            row["sourceBase"] = anchor
        self.change_maps()
        self.verify()
        self.git("update-index", "--assume-unchanged", path)
        self.write(path, "pub fn changed() {}\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.reject()

    def test_rejecting_hidden_index_does_not_clear_user_flags(self):
        self.git("update-index", "--skip-worktree", "src/alpha/lib.rs")
        index = self.root / ".git/index"
        before = index.read_bytes()
        self.reject()
        self.assertEqual(index.read_bytes(), before)
        self.assertTrue(self.git("ls-files", "-v", "src/alpha/lib.rs").startswith("S "))


if __name__ == "__main__":
    unittest.main()
