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
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "implementation_maps", SCRIPTS / "hepta-implementation-maps.py"
)
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
        self.write(
            "docs/readiness/READINESS.json",
            {
                "implementationLanes": [
                    {"id": "test-lane", "modules": ["alpha", "beta"]}
                ]
            },
        )
        for name in ("alpha", "beta"):
            self.write(f"src/{name}/lib.rs", "pub fn calculate() {}\n")
            self.write(f"docs/modules/{name}/TECHNICAL.md", "Mapped source guide")
        self.write("tests/native.rs", "#[test] fn qualified() {}\n")
        self.write("host/caller.rs", "fn caller() {}\n")
        self.write("README.md", "source identity fixture\n")
        self.anchor = self.commit("sources")
        self.rows = {name: self.row(name, self.anchor) for name in ("alpha", "beta")}
        self.save_maps()
        self.commit("maps")

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
        )
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, *args],
            cwd=self.root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2) + "\n"
            if isinstance(data, (dict, list))
            else data,
            encoding="utf-8",
        )

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return {
            "commit": self.git("rev-parse", "HEAD"),
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }

    def module(self, name):
        return {
            "id": name,
            "owner": "owner",
            "deputy": "reviewer",
            "rootBindings": [{"path": f"src/{name}"}],
            "technicalDocument": f"docs/modules/{name}/TECHNICAL.md",
        }

    def row(self, name, anchor):
        return {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceBase": copy.deepcopy(anchor),
            "laneId": "test-lane",
            "module": name,
            "declaredRoots": [f"src/{name}"],
            "resolvedRoots": [f"src/{name}"],
            "sourceRootPresent": True,
            "productionImplementation": False,
            "operations": [
                {
                    "operation": "calculate",
                    "nativeSymbol": "calculate",
                    "sourcePath": f"src/{name}/lib.rs",
                    "tests": [],
                    "delegatedCallees": [],
                }
            ],
            "claimBoundary": {
                "nativeSourceMappingComplete": False,
                "productExecutionProved": False,
            },
        }

    def save_maps(self):
        for name, row in self.rows.items():
            self.write(f"docs/modules/{name}/IMPLEMENTATION_MAP.json", row)

    def change_maps(self):
        self.save_maps()
        self.commit("update map")

    def verify(self, modules=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            maps.verify(modules=modules)
        return json.loads(output.getvalue())

    def reject(self, modules=None):
        with self.assertRaises(SystemExit):
            self.verify(modules=modules)

    def test_verify_accepts_exact_expected_candidate_identity(self):
        candidate = maps.current_source_base()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            maps.verify(
                expected_sha=candidate["commit"],
                expected_tree=candidate["tree"],
            )
        self.assertEqual(
            json.loads(output.getvalue())["candidateSource"],
            candidate,
        )

    def test_verify_rejects_wrong_or_malformed_expected_candidate_identity(self):
        candidate = maps.current_source_base()
        with self.assertRaisesRegex(SystemExit, "expected candidate SHA"):
            maps.verify(expected_sha="f" * 40, expected_tree=candidate["tree"])
        with self.assertRaisesRegex(SystemExit, "--expected-tree must be"):
            maps.verify(expected_sha=candidate["commit"], expected_tree="not-a-tree")

    def test_scoped_verify_checks_only_selected_registered_modules(self):
        self.rows["beta"]["laneId"] = "wrong-lane"
        self.change_maps()

        result = self.verify(modules=["alpha"])
        self.assertEqual(result["modules"], 1)
        self.assertEqual(result["maps"], 1)
        self.assertEqual(result["selectedModules"], ["alpha"])
        self.assertEqual(result["registryModules"], 2)
        self.assertEqual(result["verificationScope"], "module_subset")
        self.reject()

    def test_scoped_verify_rejects_unknown_and_duplicate_modules(self):
        with self.assertRaisesRegex(SystemExit, "unknown selected module"):
            maps.verify(modules=["missing"])
        with self.assertRaisesRegex(SystemExit, "duplicate selected module identity"):
            maps.verify(modules=["alpha", "alpha"])

    def test_cli_routes_module_selection_to_verify(self):
        with (
            patch.object(
                sys,
                "argv",
                ["hepta-implementation-maps.py", "--module", "alpha", "verify"],
            ),
            patch.object(maps, "verify") as verify,
        ):
            maps.main()
        verify.assert_called_once_with(
            modules=["alpha"],
            expected_sha=None,
            expected_tree=None,
        )

    def closed_public_inventory(self, functions):
        self.write(
            "src/alpha/Cargo.toml", '[package]\nname = "alpha"\nversion = "0.1.0"\n'
        )
        self.write("src/alpha/src/lib.rs", functions)
        self.rows["alpha"]["sourceBase"] = self.commit("public crate source")
        self.rows["alpha"]["closedWorldPublicFunctions"] = True
        self.change_maps()

    def test_strong_navigation_migration_without_observation_survives_commit(self):
        self.rows["alpha"]["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        self.change_maps()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        row = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(row["sourceBase"], row["observedAtHead"])
        self.assertFalse(row["productionImplementation"])
        self.commit("persist explicit source observation")
        self.verify()
        before = (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        self.assertEqual(
            before,
            (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(),
        )

    def test_strong_migration_never_repairs_unproved_execution_by_adding_observation(
        self,
    ):
        self.rows["alpha"]["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        self.rows["alpha"]["productExecutionProved"] = True
        self.change_maps()
        before = (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes()
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        self.assertEqual(
            before,
            (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(),
        )

    def test_source_objects_keep_tests_delegates_callers_and_legacy_witnesses(self):
        row = self.rows["alpha"]
        row["operations"][0]["tests"] = ["tests/native.rs"]
        row["operations"][0]["delegatedCallees"] = ["src/beta/lib.rs"]
        row["productCallers"] = [{"path": "host/caller.rs"}]
        row["sourceObjects"] = [
            {"path": "README.md", "blobSha": self.git("rev-parse", "HEAD:README.md")}
        ]
        self.change_maps()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        migrated = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        paths = {entry["path"] for entry in migrated["sourceObjects"]}
        self.assertTrue(
            {"tests/native.rs", "src/beta/lib.rs", "host/caller.rs", "README.md"}
            <= paths
        )
        self.commit("preserve exact source witnesses")
        self.verify()
        self.write("README.md", "changed explicit source witness\n")
        self.commit("witness drift")
        self.reject()

    def test_source_objects_reject_self_reference_without_rewriting_maps(self):
        row = self.rows["alpha"]
        row["sourceObjects"] = [
            {"path": "docs/modules/alpha/IMPLEMENTATION_MAP.json", "object": "0" * 40}
        ]
        self.change_maps()
        before = (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes()
        with (
            self.assertRaisesRegex(ValueError, "own implementation map"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            maps.migrate(["alpha"])
        self.assertEqual(
            before,
            (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(),
        )

    def test_legacy_named_caller_normalizes_and_receives_exact_source_objects(self):
        self.rows["alpha"]["productCallerState"] = "compiled_adapter_not_activated"
        self.rows["alpha"]["productCallers"] = [
            {"path": "host/caller.rs", "symbol": "caller", "state": "not_activated"}
        ]
        self.change_maps()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        row = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(
            row["productCallers"],
            [
                {
                    "sourcePath": "host/caller.rs",
                    "nativeSymbol": "caller",
                    "state": "not_activated",
                }
            ],
        )
        self.assertIn(
            "host/caller.rs", {entry["path"] for entry in row["sourceObjects"]}
        )
        self.assertFalse(row["productionImplementation"])
        self.assertFalse(row["claimBoundary"]["productExecutionProved"])
        self.commit("canonical caller navigation")
        self.verify()

    def test_conflicting_legacy_caller_aliases_reject_before_any_write(self):
        for aliases in [
            {"path": "host/caller.rs", "sourcePath": "tests/native.rs"},
            {"path": "host/caller.rs", "symbol": "caller", "nativeSymbol": "forged"},
        ]:
            with self.subTest(aliases=aliases):
                self.rows["alpha"]["productCallers"] = [aliases]
                self.change_maps()
                before = (
                    self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
                ).read_bytes()
                with (
                    self.assertRaisesRegex(ValueError, "conflicting product caller"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    maps.migrate(["alpha"])
                self.assertEqual(
                    before,
                    (
                        self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
                    ).read_bytes(),
                )

    def test_closed_public_inventory_uses_resolved_crate_roots(self):
        self.closed_public_inventory("pub fn calculate() {}\n")
        self.verify()

    def test_closed_public_inventory_rejects_unmapped_exports(self):
        self.closed_public_inventory("pub fn calculate() {}\npub fn omitted() {}\n")
        with self.assertRaisesRegex(SystemExit, "public function inventory differs"):
            self.verify()

    def test_closed_public_inventory_rejects_nonexistent_exports(self):
        self.closed_public_inventory("fn calculate() {}\n")
        with self.assertRaisesRegex(SystemExit, "public function inventory differs"):
            self.verify()

    def test_public_inventory_excludes_methods_tests_and_literal_decoys(self):
        self.closed_public_inventory("""
pub fn calculate() { let ignored = \"} pub fn fake() {\"; }
pub struct Value;
impl Value { pub fn associated() {} }
mod tests { pub fn helper() {} }
/* nested /* } pub fn comment() {} */ still comment */
const TEXT: &str = r##"} pub fn raw_decoy() {}"##;
""")
        self.verify()

    def test_public_inventory_includes_const_reexports_not_types(self):
        self.closed_public_inventory(
            "mod api;\npub use api::calculate;\npub use api::Value;\n"
        )
        self.write(
            "src/alpha/src/api.rs",
            "pub const fn calculate() -> u8 { 1 }\npub struct Value;\nimpl Value { pub fn method() {} }\n",
        )
        self.rows["alpha"]["sourceBase"] = self.commit("const free function")
        self.change_maps()
        self.verify()

    def test_rebind_refreshes_exact_operation_blob(self):
        row = copy.deepcopy(self.rows["alpha"])
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["operations"][0]["sourceBlob"] = "0" * 40
        result = maps.migrate_map(
            row, self.modules[0], {"alpha": "test-lane"}, self.anchor
        )
        self.assertEqual(
            result["operations"][0]["sourceBlob"],
            self.git("rev-parse", "HEAD:src/alpha/lib.rs"),
        )
        self.assertFalse(result["claimBoundary"]["productExecutionProved"])

    def test_exact_blob_verify_requires_explicit_current_observation(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["operations"][0]["sourceBlob"] = self.git(
            "rev-parse", "HEAD:src/alpha/lib.rs"
        )
        self.change_maps()
        with self.assertRaisesRegex(
            SystemExit,
            "exact blob provenance requires an explicit current source observation",
        ):
            self.verify()

    def test_exact_blob_observation_covers_non_operation_evidence(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["operations"][0]["sourceBlob"] = self.git(
            "rev-parse", "HEAD:src/alpha/lib.rs"
        )
        row["operations"][0]["tests"] = [{"path": "tests/native.rs"}]
        row["observedAtHead"] = copy.deepcopy(self.anchor)
        row["observedSourcePaths"] = ["src/alpha"]
        self.change_maps()
        self.verify()
        self.write("tests/native.rs", "#[test] fn changed_qualification() {}\n")
        self.commit("change non-operation evidence")
        self.reject()

    def test_exact_blob_migration_preserves_provenance_and_rebinds_observation(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["operations"][0]["sourceBlob"] = self.git(
            "rev-parse", "HEAD:src/alpha/lib.rs"
        )
        row["observedAtHead"] = copy.deepcopy(self.anchor)
        row["observedSourcePaths"] = ["src/alpha"]
        self.change_maps()
        provenance = copy.deepcopy(self.anchor)

        self.write("src/alpha/lib.rs", "pub fn calculate() { let _x = 9; }\n")
        current = self.commit("change exact blob implementation")
        result = self.migrate(["alpha"])
        self.assertEqual(result["maps"], ["docs/modules/alpha/IMPLEMENTATION_MAP.json"])
        migrated = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(migrated["sourceBase"], provenance)
        self.assertEqual(migrated["observedAtHead"], current)
        self.assertEqual(
            migrated["operations"][0]["sourceBlob"],
            self.git("rev-parse", "HEAD:src/alpha/lib.rs"),
        )
        self.commit("bind exact blob current observation")
        result = self.verify()
        self.assertEqual(result["provenanceAnchoredExactBlobMaps"], 1)

        before = (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes()
        self.write("README.md", "later prose must not rewrite provenance\n")
        self.commit("prose after exact blob observation")
        self.assertEqual(self.migrate(["alpha"])["migrated"], 0)
        self.assertEqual(
            before,
            (self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").read_bytes(),
        )
        self.verify()

    def test_closed_world_writer_binding_preserves_exact_source_identity(self):
        row = self.rows["alpha"]
        row["productionWriterState"] = "owner_service_composed"
        row["productionWriterBindingPolicy"] = "closed_world"
        row["productionWriterBindings"] = [
            {"sourcePath": "src/alpha/lib.rs", "mustContain": "calculate"}
        ]
        self.change_maps()
        self.verify()
        self.write("src/alpha/lib.rs", "pub fn calculate() { let changed = true; }\n")
        self.commit("marker unchanged but source changed")
        self.reject()

    def test_composed_writer_rejects_missing_closed_world_bindings(self):
        row = self.rows["alpha"]
        row["productionWriterState"] = "owner_service_composed"
        row["productionWriterBindingPolicy"] = "closed_world"
        self.change_maps()
        self.reject()

    def test_closed_world_markers_cannot_escape_source_namespace(self):
        for source, marker in [
            ("src/alpha/lib.rs", "nonexistent_symbol"),
            ("../outside.rs", "calculate"),
            ("src/alpha/lib.rs", ""),
        ]:
            with self.subTest(source=source, marker=marker):
                with self.assertRaises(ValueError):
                    maps.validate_closed_world_bindings(
                        {
                            "productionWriterState": "owner_service_composed",
                            "productionWriterBindingPolicy": "closed_world",
                            "productionWriterBindings": [
                                {"sourcePath": source, "mustContain": marker}
                            ],
                        }
                    )

    def test_composed_caller_requires_nonempty_source_binding_list(self):
        for bindings in [[], None, {"callerPath": "src/alpha/lib.rs"}]:
            with self.subTest(bindings=bindings):
                with self.assertRaises(ValueError):
                    maps.validate_closed_world_bindings(
                        {
                            "productCallerState": "source_composed",
                            "productCallerBindingPolicy": "closed_world",
                            "productCallerBindings": bindings,
                        }
                    )

    def test_verifier_helpers_cannot_be_shadowed_by_duplicate_definitions(self):
        import ast

        tree = ast.parse(Path(maps.__file__).read_text(encoding="utf-8"))
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(len(names), len(set(names)))

    def test_partial_operator_inventory_cannot_claim_a_closed_map(self):
        with self.assertRaisesRegex(
            ValueError, "public operation inventory incomplete"
        ):
            maps.validate_operation_inventory(
                "learning.operator", [{"operation": "build_targets"}]
            )

    def test_rust_function_test_identity_resolves_to_exact_source(self):
        row = {
            "operations": [
                {
                    "sourcePath": "src/alpha/lib.rs",
                    "tests": ["src/alpha/lib.rs::tests::calculate"],
                }
            ]
        }
        self.assertEqual(maps.evidence_paths(row, []), ["src/alpha/lib.rs"])
        row["operations"][0]["tests"] = ["src/alpha/lib.rs::tests::missing_function"]
        with self.assertRaises(ValueError):
            maps.evidence_paths(row, [])

    def test_test_identity_does_not_admit_invalid_paths_or_symbols(self):
        for identity in [
            "../escape.rs::test",
            "src/alpha/lib.rs::tests::*",
            "src/alpha/lib.rs::",
            "src/alpha/lib.rs::../calculate",
        ]:
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                maps.evidence_paths({"operations": [{"tests": [identity]}]}, [])

    def test_guide_and_legacy_caller_spelling_are_exact_evidence(self):
        row = {
            "operations": [],
            "technicalGuide": "src/alpha/lib.rs",
            "productCallers": [{"path": "src/beta/lib.rs"}],
        }
        self.assertEqual(
            maps.evidence_paths(row, []), ["src/alpha/lib.rs", "src/beta/lib.rs"]
        )
        row["productCallers"][0]["path"] = "../outside.rs"
        with self.assertRaises(ValueError):
            maps.evidence_paths(row, [])

    def test_unchanged_ancestral_source_passes(self):
        self.assertEqual(
            self.verify()["candidateSource"]["commit"], self.git("rev-parse", "HEAD")
        )

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
        self.rows["alpha"]["operations"][0]["delegatedCallees"] = [
            {"path": "host/caller.rs"}
        ]
        self.change_maps()
        self.write("host/caller.rs", "fn changed_caller() {}\n")
        self.commit("caller drift")
        self.reject()

    def test_missing_mapped_test_rejects(self):
        self.rows["alpha"]["operations"][0]["tests"] = [
            {"path": "tests/does_not_exist.rs"}
        ]
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
        other = self.git(
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            self.anchor["tree"],
            "-m",
            "unrelated",
        )
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
        row = maps.migrate_map(
            self.rows["alpha"], self.modules[0], {"alpha": "test-lane"}, self.anchor
        )
        self.assertIs(row["claimBoundary"]["nativeSourceMappingComplete"], False)

    def test_generator_does_not_infer_complete_mapping(self):
        self.write(
            "qualification/module-execution-dossiers/detail/alpha.md",
            "**Implemented entrypoints:** `calculate` in [src/alpha/lib.rs]\n",
        )
        row = maps.map_for(self.modules[0], self.anchor, {"alpha": "test-lane"})
        self.assertIs(row["claimBoundary"]["nativeSourceMappingComplete"], False)

    def test_selected_migration_leaves_other_module_bytes_unchanged(self):
        beta = self.root / "docs/modules/beta/IMPLEMENTATION_MAP.json"
        before = beta.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            maps.migrate(["alpha"])
        self.assertEqual(beta.read_bytes(), before)

    def test_unknown_migration_module_fails_before_writes(self):
        before = {
            name: (
                self.root / f"docs/modules/{name}/IMPLEMENTATION_MAP.json"
            ).read_bytes()
            for name in self.rows
        }
        with self.assertRaises(SystemExit):
            maps.migrate(["alpha", "unknown"])
        for name, data in before.items():
            self.assertEqual(
                (
                    self.root / f"docs/modules/{name}/IMPLEMENTATION_MAP.json"
                ).read_bytes(),
                data,
            )

    def test_empty_registry_rejects(self):
        self.write("docs/modules/MODULES.json", {"modules": []})
        self.commit("empty registry")
        self.reject()

    def test_duplicate_module_identity_rejects(self):
        self.write(
            "docs/modules/MODULES.json", {"modules": [self.modules[0], self.modules[0]]}
        )
        self.commit("duplicate module")
        self.reject()

    def test_duplicate_json_keys_reject(self):
        path = self.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        text = path.read_text()
        path.write_text(
            text.replace(
                '"schemaVersion": 3,', '"schemaVersion": 3, "schemaVersion": 3,'
            )
        )
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

    def migrate(self, selected=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            maps.migrate(selected)
        return json.loads(output.getvalue())

    def normalize_maps(self):
        self.migrate()
        self.commit("normalize projections")
        self.rows = {
            name: maps.load(f"docs/modules/{name}/IMPLEMENTATION_MAP.json")
            for name in self.rows
        }

    def map_bytes(self):
        return {
            name: (
                self.root / f"docs/modules/{name}/IMPLEMENTATION_MAP.json"
            ).read_bytes()
            for name in self.rows
        }

    def test_repeated_migration_after_commit_is_noop(self):
        self.normalize_maps()
        before = self.map_bytes()
        self.assertEqual(self.migrate()["migrated"], 0)
        self.assertEqual(before, self.map_bytes())
        self.verify()

    def test_prose_edit_does_not_refresh_any_anchor(self):
        self.normalize_maps()
        before = self.map_bytes()
        self.write("README.md", "a later prose-only change\n")
        self.commit("prose after maps")
        self.assertEqual(self.migrate()["migrated"], 0)
        self.assertEqual(before, self.map_bytes())

    def test_all_module_migration_only_rebinds_changed_source(self):
        self.normalize_maps()
        before = self.map_bytes()
        self.write("src/alpha/lib.rs", "pub fn calculate() { let _x = 5; }\n")
        current = self.commit("alpha implementation")
        self.assertEqual(
            self.migrate()["maps"], ["docs/modules/alpha/IMPLEMENTATION_MAP.json"]
        )
        self.assertEqual(self.map_bytes()["beta"], before["beta"])
        alpha = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(alpha["sourceBase"], current)
        self.assertFalse(alpha["claimBoundary"]["productExecutionProved"])
        self.commit("alpha source observation")
        self.verify()
        self.assertEqual(self.migrate()["migrated"], 0)

    def test_observed_additional_input_rebind_is_still_checked(self):
        row = self.rows["alpha"]
        row["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
        row["observedAtHead"] = copy.deepcopy(self.anchor)
        row["observedSourcePaths"] = ["src/alpha", "host/caller.rs"]
        self.change_maps()
        self.normalize_maps()
        self.write("host/caller.rs", "fn caller_v2() {}\n")
        current = self.commit("change additional observation input")
        self.migrate(["alpha"])
        alpha = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(alpha["observedAtHead"], current)
        self.assertEqual(alpha["sourceBase"], current)
        self.commit("rebind additional input")
        self.verify()

    def test_migration_rejects_invalid_identity_before_any_write(self):
        self.rows["beta"]["sourceBase"]["tree"] = "0" * 40
        self.change_maps()
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_migration_does_not_repair_unknown_policy(self):
        self.rows["beta"]["sourceIdentityPolicy"] = "trust_me"
        self.change_maps()
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_migration_rejects_dirty_source_without_writing_maps(self):
        self.write("src/alpha/lib.rs", "// uncommitted\n")
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_migration_rejects_untracked_evidence_without_partial_write(self):
        self.rows["beta"]["operations"][0]["tests"] = ["tests/new.rs"]
        self.change_maps()
        self.write("tests/new.rs", "// not committed\n")
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_migration_rejects_missing_evidence_at_both_ends(self):
        self.rows["beta"]["operations"][0]["tests"] = ["tests/missing.rs"]
        self.change_maps()
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_new_committed_evidence_can_be_explicitly_rebound(self):
        self.write("tests/new.rs", "#[test] fn new_regression() {}\n")
        self.rows["alpha"]["operations"][0]["tests"] = ["tests/new.rs"]
        self.change_maps()
        self.reject()
        self.migrate(["alpha"])
        self.commit("bind new regression")
        self.verify()

    def test_noop_preserves_custom_json_formatting(self):
        self.normalize_maps()
        self.write(
            "docs/modules/alpha/IMPLEMENTATION_MAP.json",
            json.dumps(self.rows["alpha"], separators=(",", ":")) + "\n",
        )
        self.commit("compact existing projection")
        before = self.map_bytes()
        self.assertEqual(self.migrate()["migrated"], 0)
        self.assertEqual(before, self.map_bytes())

    def test_migration_rejects_duplicate_module_registry(self):
        self.write(
            "docs/modules/MODULES.json", {"modules": [self.modules[0], self.modules[0]]}
        )
        self.commit("duplicate migration selection")
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_migration_git_failure_is_not_treated_as_drift(self):
        original = maps.git

        def fail_diff(*args, **kwargs):
            if args and args[0] == "diff":
                raise subprocess.CalledProcessError(128, "git diff")
            return original(*args, **kwargs)

        before = self.map_bytes()
        with patch.object(maps, "git", side_effect=fail_diff):
            with self.assertRaises(subprocess.CalledProcessError):
                self.migrate()
        self.assertEqual(before, self.map_bytes())

    def test_repository_verification_scans_checkout_twice_not_per_module(self):
        with patch.object(
            maps, "require_clean_candidate", wraps=maps.require_clean_candidate
        ) as scans:
            self.verify()
        self.assertEqual(scans.call_count, 2)

    def test_object_query_count_is_bounded_independent_of_evidence_count(self):
        paths = [f"tests/evidence {i}.rs" for i in range(128)]
        for path in paths:
            self.write(path, "// independent evidence path\n")
        current = self.commit("many evidence paths")
        for row in self.rows.values():
            row["sourceBase"] = copy.deepcopy(current)
        self.rows["alpha"]["operations"][0]["tests"] = paths
        self.change_maps()
        with patch.object(maps, "git", wraps=maps.git) as queries:
            self.verify()
        batches = [
            call
            for call in queries.call_args_list
            if call.args[:2] == ("cat-file", "--batch-check=%(objecttype)")
        ]
        scalar = [
            call
            for call in queries.call_args_list
            if call.args[:2] == ("cat-file", "-t") and ":" in call.args[2]
        ]
        self.assertEqual(len(batches), 4)
        self.assertEqual(len(scalar), 0)

    def test_explicit_newline_and_tab_evidence_paths_remain_unambiguous(self):
        paths = ["tests/line\nbreak.rs", "tests/tab\tfile.rs", "tests/space file.rs"]
        for path in paths:
            self.write(path, "// unusual evidence path\n")
        current = self.commit("unusual explicit evidence")
        for row in self.rows.values():
            row["sourceBase"] = copy.deepcopy(current)
        self.rows["alpha"]["operations"][0]["tests"] = paths
        self.change_maps()
        self.verify()
        self.write(paths[0], "// changed\n")
        self.commit("newline path drift")
        self.reject()

    def test_malformed_batch_response_is_rejected(self):
        original = maps.git

        def truncate(*args, **kwargs):
            if args[:2] == ("cat-file", "--batch-check=%(objecttype)"):
                return ""
            return original(*args, **kwargs)

        with patch.object(maps, "git", side_effect=truncate):
            self.reject()

    def test_hidden_index_remains_rejected_during_migration(self):
        self.git("update-index", "--assume-unchanged", "README.md")
        before = self.map_bytes()
        with self.assertRaises(ValueError):
            self.migrate()
        self.assertEqual(before, self.map_bytes())


if __name__ == "__main__":
    unittest.main()
