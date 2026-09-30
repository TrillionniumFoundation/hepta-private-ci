"""Real Git regressions for the narrow, read-only ui.native v6 bridge."""

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

import hepta_ui_native_map_adapter as adapter

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_adapter_maps", REPOSITORY / "scripts/hepta-implementation-maps.py"
)
assert SPEC is not None and SPEC.loader is not None
maps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maps)


class NativeMapAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root_patch = patch.object(maps, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Native adapter fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.modules = [
            {
                "id": "ui.native",
                "owner": "ui-platform",
                "deputy": "accessibility",
                "rootBindings": [{"path": "apps/hepta-native"}],
                "technicalDocument": "docs/modules/ui.native/TECHNICAL.md",
            },
            {"id": "alpha", "rootBindings": [{"path": "src/alpha"}]},
        ]
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        self.write(
            "docs/readiness/READINESS.json",
            {
                "implementationLanes": [
                    {"id": "fixture", "modules": ["ui.native", "alpha"]}
                ]
            },
        )
        # Keep actual production contracts, but use a small independent Cargo
        # graph so no source checkout or compiler is involved in the regressions.
        for name in (
            "journal",
            "journal_storage",
            "retirement",
            "platform",
            "runtime",
            "updater",
        ):
            relative = f"apps/hepta-native/src/{name}.rs"
            self.write(relative, (REPOSITORY / relative).read_text(encoding="utf-8"))
        self.crate(
            "apps/hepta-native",
            'gateway = { path = "../../codex-rs/hepta-native-gateway" }',
        )
        self.crate(
            "codex-rs/hepta-native-gateway",
            'contracts = { path = "../hepta-contracts" }\nprivate = { path = "../hepta-private-state" }',
        )
        self.crate(
            "codex-rs/hepta-contracts", 'utility = { path = "../utils/private-state" }'
        )
        self.crate(
            "codex-rs/hepta-private-state",
            'utility = { path = "../utils/private-state" }',
        )
        self.crate("codex-rs/utils/private-state")
        self.write("codex-rs/Cargo.toml", "[workspace]\nmembers = []\n")
        self.write("src/alpha/lib.rs", "pub fn calculate() {}\n")
        self.write(
            "apps/hepta-native/src/fixture_tests.rs", "#[test] fn fixture() {}\n"
        )
        self.write("apps/hepta-native/tests/fixture.rs", "#[test] fn fixture() {}\n")
        for relative in (
            "docs/modules/ui.native/TECHNICAL.md",
            "apps/hepta-native/DEVELOPMENT.md",
        ):
            self.write(relative, "Fixture source navigation\n")
        self.write(
            ".github/workflows/ui-native-qualification.yml",
            """on:
  push:
    paths:
      - '**'
  workflow_dispatch:
# exact head; ordered-parent merge
persist-credentials: false
cancel-in-progress: false
""",
        )
        self.row = json.loads(
            (REPOSITORY / "docs/modules/ui.native/IMPLEMENTATION_MAP.json").read_text()
        )
        self.row["testSurfaces"] = [
            "apps/hepta-native/src/*_tests.rs",
            "apps/hepta-native/tests/*.rs",
        ]
        self.states = {relative: {} for relative in adapter.native.STATE_FILES}
        self.states["docs/modules/ui.native/IMPLEMENTATION_MAP.json"] = self.row
        budget = "apps/hepta-native/STORAGE_BUDGETS.json"
        self.states[budget] = json.loads((REPOSITORY / budget).read_text())
        for relative, state in self.states.items():
            state.update(
                implementationSourceSha="0" * 40,
                implementationSourceTree="0" * 40,
                productionQualified=False,
                deploymentQualified=False,
                releaseAuthorized=False,
            )
            self.write(relative, state)
        self.source = self.commit("source freeze")
        self.reanchor(self.source)
        self.alpha = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "module": "alpha",
            "laneId": "fixture",
            "sourceBase": self.source,
            "declaredRoots": ["src/alpha"],
            "resolvedRoots": ["src/alpha"],
            "sourceRootPresent": True,
            "productionImplementation": False,
            "operations": [
                {
                    "operation": "calculate",
                    "nativeSymbol": "calculate",
                    "sourcePath": "src/alpha/lib.rs",
                }
            ],
            "claimBoundary": {"productExecutionProved": False},
        }
        self.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", self.alpha)
        self.candidate = self.commit("navigation anchors")

    def git(self, *args):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_NO_REPLACE_OBJECTS="1",
        )
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, *args],
            cwd=self.root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2) + "\n" if isinstance(value, dict) else value,
            encoding="utf-8",
        )

    def crate(self, relative, dependencies=""):
        self.write(
            relative + "/Cargo.toml",
            f'[package]\nname = "{Path(relative).name}"\nversion = "0.1.0"\n[dependencies]\n{dependencies}\n',
        )
        self.write(relative + "/src/lib.rs", "pub fn fixture() {}\n")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return {
            "commit": self.git("rev-parse", "HEAD"),
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }

    def reanchor(self, source):
        for relative, state in self.states.items():
            state.update(
                implementationSourceSha=source["commit"],
                implementationSourceTree=source["tree"],
            )
            self.write(relative, state)

    def save_row(self):
        self.write("docs/modules/ui.native/IMPLEMENTATION_MAP.json", self.row)
        self.commit("map mutation")

    def verify(self):
        output = io.StringIO()
        candidate = maps.current_source_base()
        with contextlib.redirect_stdout(output):
            maps.verify(
                expected_sha=candidate["commit"], expected_tree=candidate["tree"]
            )
        return json.loads(output.getvalue())

    def reject(self, message):
        with self.assertRaisesRegex(SystemExit, message):
            self.verify()

    def test_strict_checker_is_reused_and_v3_maps_stay_separate(self):
        previous = (
            adapter.native.ROOT,
            adapter.native._git_value,
            adapter.native._git_success,
        )
        with patch.object(
            adapter.native, "check_repository", wraps=adapter.native.check_repository
        ) as strict:
            evidence = self.verify()
        strict.assert_called_once_with()
        self.assertEqual(
            evidence["nativeSchemaAdapters"],
            [
                {
                    "module": "ui.native",
                    "schemaVersion": 6,
                    "implementationSource": self.source,
                    "ownedRoots": ["apps/hepta-native"],
                    "qualificationEstablished": False,
                }
            ],
        )
        self.assertEqual(evidence["maps"], 2)
        self.assertEqual(evidence["exactObservedFallbackMaps"], 1)
        self.assertFalse(evidence["productionImplementationProved"])
        self.assertEqual(
            (
                adapter.native.ROOT,
                adapter.native._git_value,
                adapter.native._git_success,
            ),
            previous,
        )

    def test_every_state_anchor_and_tree_must_match(self):
        for relative in adapter.native.STATE_FILES:
            for key in ("implementationSourceSha", "implementationSourceTree"):
                with self.subTest(relative=relative, key=key):
                    state = copy.deepcopy(self.states[relative])
                    state[key] = "f" * 40
                    self.write(relative, state)
                    self.commit("foreign state anchor")
                    self.reject("state (anchors|trees) disagree")
                    self.git("reset", "--hard", self.candidate["commit"])

    def test_committed_production_and_transitive_dependency_drift_reject(self):
        for relative in (
            "apps/hepta-native/src/runtime.rs",
            "codex-rs/utils/private-state/src/lib.rs",
        ):
            with self.subTest(relative=relative):
                path = self.root / relative
                path.write_text(path.read_text() + "\n// post-freeze drift\n")
                self.commit("changed production source")
                self.reject("after the frozen source")
                self.git("reset", "--hard", self.candidate["commit"])

    def test_current_source_and_hidden_index_reject(self):
        relative = "apps/hepta-native/src/runtime.rs"
        path = self.root / relative
        path.write_text(path.read_text() + "\n// worktree drift\n")
        self.reject("dirty")
        with self.assertRaisesRegex(ValueError, "working-tree drift"):
            adapter.strict_native_check(self.root, maps.git)
        self.git("update-index", "--assume-unchanged", relative)
        self.reject("candidate index hides")

    def test_untracked_source_cannot_enter_frozen_closure(self):
        self.write(
            "codex-rs/utils/private-state/src/injected.rs", "pub fn injected() {}\n"
        )
        self.reject("untracked source")

    def test_budget_contract_cannot_be_relaxed_by_metadata(self):
        relative = "apps/hepta-native/STORAGE_BUDGETS.json"
        budget = copy.deepcopy(self.states[relative])
        budget["performance"]["mutationP95Milliseconds"] = 1000000
        self.write(relative, budget)
        self.commit("relaxed budget")
        self.reject("budget contract changed")

    def test_nested_qualification_claim_in_any_state_rejects(self):
        for relative in adapter.native.STATE_FILES:
            state = copy.deepcopy(self.states[relative])
            state["forgedEvidence"] = {"releaseAuthorized": True}
            self.write(relative, state)
            self.commit("promoted qualification")
            self.reject("(falsely sets|execution claim promoted)")
            self.git("reset", "--hard", self.candidate["commit"])

    def test_incomplete_and_execution_claims_cannot_be_promoted(self):
        original = copy.deepcopy(self.row)
        for key in adapter.EXECUTION_CLAIMS:
            with self.subTest(key=key):
                self.row = copy.deepcopy(original)
                self.row["completion"] = {key: True}
                self.save_row()
                self.reject("execution claim promoted")
        self.row = copy.deepcopy(original)
        self.row["claimBoundary"]["productExecutionComplete"] = 0
        self.save_row()
        self.reject("values must be booleans")

    def test_operation_inventory_and_every_exact_entrypoint_reject_tampering(self):
        original = copy.deepcopy(self.row)
        for index in range(len(original["operations"])):
            with self.subTest(index=index):
                self.row = copy.deepcopy(original)
                self.row["operations"][index]["entrypoint"] += "_forged"
                self.save_row()
                self.reject("entrypoint identity")
        for operations in (
            original["operations"][:-1],
            [original["operations"][0]] * 6,
        ):
            self.row = copy.deepcopy(original)
            self.row["operations"] = operations
            self.save_row()
            self.reject("operation inventory")

    def test_owner_schema_and_registered_ownership_are_fixed(self):
        original = copy.deepcopy(self.row)
        for field, value in (
            ("owner", "foreign"),
            ("deputy", "foreign"),
            ("schemaVersion", True),
        ):
            self.row = copy.deepcopy(original)
            self.row[field] = value
            self.save_row()
            self.reject("(identity|only ui.native schema v6)")
        self.row = copy.deepcopy(original)
        self.save_row()
        self.modules[0]["rootBindings"] = [{"path": "codex-rs/hepta-native-gateway"}]
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        self.commit("changed ownership")
        self.reject("canonical owned roots changed")

    def test_registered_native_root_cannot_redirect_to_another_owner(self):
        self.write(
            "apps/hepta-native/BINDING.json",
            {
                "schema_version": 1,
                "module": "ui.native",
                "declared_root": "apps/hepta-native",
                "implementation_root": "codex-rs/hepta-native-gateway",
                "binding_mode": "canonical_alias",
                "duplicate_cargo_package_created": False,
                "model_authority": False,
                "provider_authority": False,
            },
        )
        self.commit("redirected owned root")
        self.reject("cannot be redirected by an alias")

    def test_new_source_freeze_still_requires_the_mapped_function(self):
        relative = "apps/hepta-native/src/runtime.rs"
        path = self.root / relative
        path.write_text(
            path.read_text().replace(
                "pub fn connect_runtime(", "fn hidden_connect_runtime("
            )
        )
        self.reanchor(self.commit("new source without mapped public function"))
        self.commit("new navigation anchors")
        self.reject("missing native entrypoint function: connect_runtime")

    def test_additional_roots_and_shared_utilities_must_be_dependencies(self):
        self.write("foreign/marker.rs", "pub fn foreign() {}\n")
        original = copy.deepcopy(self.row)
        for field in ("declaredRoots", "sharedUtilityDependencies"):
            self.row = copy.deepcopy(original)
            self.row[field].append("foreign")
            self.save_row()
            self.reject("not local dependencies")

    def test_missing_unsafe_and_untracked_test_references_reject(self):
        original = copy.deepcopy(self.row)
        for reference in ("apps/hepta-native/tests/absent*.rs", "../foreign.rs"):
            self.row = copy.deepcopy(original)
            self.row["testSurfaces"] = [reference]
            self.save_row()
            self.reject("(missing native test reference|non-canonical source path)")
        self.row = copy.deepcopy(original)
        self.row["testSurfaces"] = ["diagnostic/untracked.rs"]
        self.save_row()
        self.write("diagnostic/untracked.rs", "#[test] fn untracked() {}\n")
        self.reject("cat-file")

    def test_workflow_writes_and_dependency_filter_omissions_reject(self):
        relative = ".github/workflows/ui-native-qualification.yml"
        original = (self.root / relative).read_text()
        for workflow in (
            original + "permissions: {contents: write}\n",
            original.replace("'**'", "apps/hepta-native/**"),
        ):
            self.write(relative, workflow)
            self.commit("unsafe qualification workflow")
            self.reject("(contains|does not trigger)")

    def test_other_module_cannot_use_v6_bridge(self):
        row = copy.deepcopy(self.row)
        row["module"] = "alpha"
        self.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", row)
        self.commit("foreign v6 map")
        self.reject("alpha: schema must be v3")

    def sibling_anchor(self):
        current = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.source["commit"])
        self.write("sibling.md", "Same implementation; independent provenance\n")
        sibling = self.commit("sibling provenance")
        self.git("checkout", "--detach", current)
        return sibling

    def test_native_nonancestor_source_anchor_remains_rejected(self):
        self.reanchor(self.sibling_anchor())
        self.commit("foreign native provenance")
        self.reject("merge-base")

    def test_v3_cross_branch_provenance_stays_failed_with_valid_native_bridge(self):
        self.alpha["sourceBase"] = self.sibling_anchor()
        self.write("docs/modules/alpha/IMPLEMENTATION_MAP.json", self.alpha)
        self.commit("foreign alpha provenance")
        with self.assertRaises(SystemExit) as failure:
            self.verify()
        self.assertIn("alpha:", str(failure.exception))
        self.assertNotIn("ui.native:", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
