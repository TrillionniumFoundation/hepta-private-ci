from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("taskflow_contract", Path(__file__).with_name("automation_taskflow_contract.py"))
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ContractTests(unittest.TestCase):
    """Protocol fixtures are not Rust executions or full repository validation."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path, markers in MODULE.SOURCE_MARKERS.items():
            self.write(path, "\n".join(markers) + "\n")
        path = "codex-rs/hepta-automation/src/lib.rs"
        self.write(path, self.read(path) + "pub const AUTOMATION_SCHEMA_VERSION: u32 = 21;\n")
        self.contract = {"schema": "hepta.automation-taskflow.contract.v1", "storeSchemaVersion": 21,
                         "taskflowSchemaVersion": 1, "migrationTopology": []}
        for version in range(17, 22):
            path = f"codex-rs/hepta-automation/migrations/{version:04d}_fixture.sql"
            marker = f"schema_version = {version}"
            self.write(path, marker + ";\n")
            self.contract["migrationTopology"].append({"version": version, "path": path, "requiredMarker": marker, "blobSha": hashlib.sha1(b"blob " + str(len((marker + ";\n").encode())).encode() + b"\0" + (marker + ";\n").encode()).hexdigest()})
        claims = {key: False for key in (*MODULE.REPOSITORY, *MODULE.COMPONENTS, *MODULE.EXTERNAL)}
        claims.update({"durableStoreSchemaVersion": 21, "boundedAdmissionBatchComplete": True,
                       "separateRecoveryBudgetComplete": True})
        self.implementation = {"module": "automation.taskflow", "productionImplementation": False,
                               "claimBoundary": claims, "remainingModuleGaps": ["Native execution pending."],
                               "repositoryControlledProductCompositionGaps": ["Durable circuit product pending."]}
        for name in ("TECHNICAL.md", "MIGRATION_V19_RUNBOOK.md", "SLO.md", "RELEASE_QUALIFICATION.md"):
            self.write(MODULE.MODULE + name, "Current status: CURRENT_IMPLEMENTATION.md\n")
        self.write(".github/workflows/automation-taskflow-focused.yml", """on:
  pull_request:
  workflow_call:
  push:
    branches: [main]
permissions:
  contents: read
# persist-credentials: false
# automation_taskflow_commands.py
""")
        self.write(".github/workflows/blocking-ci.yml", "automation-taskflow-focused:\n  needs:\n    - automation-taskflow-focused\n")
        self.sync()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def sync(self) -> None:
        self.write(MODULE.CONTRACT_PATH, MODULE.encoded(self.contract))
        self.write(MODULE.MAP_PATH, MODULE.encoded(self.implementation))
        MODULE.render(self.root)

    def verify(self) -> dict:
        return MODULE.verify(self.root, check_git=False)

    def test_partial_source_truth_is_not_false_whole_module_success(self) -> None:
        result = self.verify()
        self.assertEqual(result["storeSchemaVersion"], 21)
        self.assertEqual(result["migrationVersions"], [17, 18, 19, 20, 21])
        self.assertTrue(result["sourceStructureVerified"])
        for key in ("repositoryControlledClosure", "sourceIdentityVerified", "nativeExecutionProved", "release"):
            self.assertIs(result[key], False)
        self.assertNotIn("boundedRecoveryFairnessVerified", result)

    def test_render_is_idempotent_and_does_not_rewrite_sources_or_map(self) -> None:
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        MODULE.render(self.root)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_boolean_schema_rejected(self) -> None:
        self.contract["storeSchemaVersion"] = True
        self.write(MODULE.CONTRACT_PATH, json.dumps(self.contract))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_rust_schema_drift_rejected(self) -> None:
        path = "codex-rs/hepta-automation/src/lib.rs"
        self.write(path, self.read(path).replace("= 21;", "= 20;"))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_duplicate_schema_constant_rejected(self) -> None:
        path = "codex-rs/hepta-automation/src/lib.rs"
        self.write(path, self.read(path) + "pub const AUTOMATION_SCHEMA_VERSION: u32 = 21;\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_map_schema_drift_rejected(self) -> None:
        self.implementation["claimBoundary"]["durableStoreSchemaVersion"] = 19
        self.write(MODULE.MAP_PATH, json.dumps(self.implementation))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_migration_gap_rejected(self) -> None:
        self.contract["migrationTopology"].pop(2)
        self.write(MODULE.CONTRACT_PATH, json.dumps(self.contract))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_unregistered_migration_rejected(self) -> None:
        self.write("codex-rs/hepta-automation/migrations/0022_unreviewed.sql", "SELECT 1;\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_path_version_mismatch_rejected(self) -> None:
        self.contract["migrationTopology"][-1]["path"] = self.contract["migrationTopology"][-2]["path"]
        self.write(MODULE.CONTRACT_PATH, json.dumps(self.contract))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_marker_preserving_migration_edit_rejected(self) -> None:
        path = self.contract["migrationTopology"][-1]["path"]
        self.write(path, self.read(path) + "SELECT 'unreviewed SQL';\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_missing_marker_rejected(self) -> None:
        self.write(self.contract["migrationTopology"][-1]["path"], "SELECT 1;\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_external_gates_cannot_be_self_issued(self) -> None:
        for key in MODULE.EXTERNAL:
            with self.subTest(key=key):
                invalid = copy.deepcopy(self.implementation)
                invalid["claimBoundary"][key] = True
                self.write(MODULE.MAP_PATH, json.dumps(invalid))
                with self.assertRaises(MODULE.ContractError):
                    self.verify()
        self.sync()

    def test_missing_or_non_boolean_claims_reject(self) -> None:
        for value in (None, 1, "false"):
            invalid = copy.deepcopy(self.implementation)
            invalid["claimBoundary"]["durableNeuralCircuitProductComplete"] = value
            self.write(MODULE.MAP_PATH, json.dumps(invalid))
            with self.assertRaises(MODULE.ContractError):
                self.verify()

    def test_closure_cannot_hide_open_product_gaps(self) -> None:
        self.implementation["claimBoundary"]["repositoryControlledProductCompositionGapsClosed"] = True
        self.write(MODULE.MAP_PATH, json.dumps(self.implementation))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_closure_cannot_hide_open_source_gaps(self) -> None:
        self.implementation["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = True
        self.write(MODULE.MAP_PATH, json.dumps(self.implementation))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_product_requires_source_adapter(self) -> None:
        self.implementation["claimBoundary"]["durableNeuralCircuitProductComplete"] = True
        self.write(MODULE.MAP_PATH, json.dumps(self.implementation))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_duplicate_json_key_rejects(self) -> None:
        self.write(MODULE.CONTRACT_PATH, '{"storeSchemaVersion":21,"storeSchemaVersion":19}')
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_path_traversal_and_symlink_reject(self) -> None:
        for path in ("../outside", "/absolute", "a/../outside", "a\\outside", "a//b"):
            with self.subTest(path=path), self.assertRaises(MODULE.ContractError):
                MODULE.checked_path(self.root, path)
        os.symlink(self.root / "scripts", self.root / "alias")
        with self.assertRaises(MODULE.ContractError):
            MODULE.text(self.root, "alias/automation_taskflow_commands.py")

    def test_current_state_drift_rejects(self) -> None:
        state = json.loads(self.read(MODULE.STATE_PATH))
        state["storeSchemaVersion"] = 19
        self.write(MODULE.STATE_PATH, MODULE.encoded(state))
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_rendered_markdown_drift_rejects(self) -> None:
        self.write(MODULE.STATUS_PATH, self.read(MODULE.STATUS_PATH) + "all complete\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_write_qualification_rejected(self) -> None:
        path = ".github/workflows/automation-taskflow-focused.yml"
        self.write(path, self.read(path) + "jobs:\n  bad:\n    permissions:\n      contents: write\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_retired_repair_workflow_rejected(self) -> None:
        self.write(".github/workflows/automation-taskflow-qualification-repair.yml", "name: old repair\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def test_source_marker_removal_rejected(self) -> None:
        self.write("codex-rs/hepta-automation/src/scheduler.rs", "// removed\n")
        with self.assertRaises(MODULE.ContractError):
            self.verify()

    def git(self, *args: str) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, env=env, stderr=subprocess.PIPE).strip()

    def git_fixture(self) -> None:
        self.write("codex-rs/Cargo.toml", "[workspace]\n")
        self.write("codex-rs/Cargo.lock", "version = 4\n")
        self.git("init")
        self.git("config", "user.name", "Protocol fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", ".")
        self.git("commit", "-m", "source fixture")
        observed = self.git("rev-parse", "HEAD")
        paths = ["codex-rs/hepta-automation", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock"]
        objects = [{"path": p, "object": self.git("rev-parse", f"HEAD:{p}")} for p in paths]
        self.implementation.update({"observedAtHead": {"commit": observed, "tree": self.git("rev-parse", "HEAD^{tree}")},
                                   "observedSourcePaths": paths, "sourceObjects": objects,
                                   "exactSourceEvidence": {"entries": [{"path": p["path"], "blobSha": p["object"]} for p in objects[1:]]}})
        self.sync()
        self.git("add", ".")
        self.git("commit", "-m", "metadata fixture")

    def test_exact_source_identity_uses_current_candidate_not_anchor(self) -> None:
        self.git_fixture()
        result = MODULE.verify(self.root)
        self.assertEqual(result["candidate"]["commit"], self.git("rev-parse", "HEAD"))
        self.assertNotEqual(result["candidate"]["commit"], self.implementation["observedAtHead"]["commit"])
        self.assertTrue(result["sourceIdentityVerified"])
        self.assertFalse(result["nativeExecutionProved"])

    def test_dirty_mapped_file_rejects(self) -> None:
        self.git_fixture()
        self.write("codex-rs/Cargo.lock", "changed\n")
        with self.assertRaises(MODULE.ContractError):
            MODULE.verify_source_identity(self.root, self.implementation)

    def test_changed_committed_source_rejects_historical_observation(self) -> None:
        self.git_fixture()
        self.write("codex-rs/Cargo.lock", "changed\n")
        self.git("add", ".")
        self.git("commit", "-m", "source drift")
        with self.assertRaises(MODULE.ContractError):
            MODULE.verify_source_identity(self.root, self.implementation)

    def test_untracked_mapped_source_rejects(self) -> None:
        self.git_fixture()
        self.write("codex-rs/hepta-automation/src/hidden.rs", "hidden\n")
        with self.assertRaises(MODULE.ContractError):
            MODULE.verify_source_identity(self.root, self.implementation)

    def test_wrong_blob_and_wrong_tree_reject(self) -> None:
        self.git_fixture()
        for key in ("blob", "tree"):
            invalid = copy.deepcopy(self.implementation)
            if key == "blob":
                invalid["sourceObjects"][1]["object"] = "0" * 40
            else:
                invalid["observedAtHead"]["tree"] = "0" * 40
            with self.assertRaises(MODULE.ContractError):
                MODULE.verify_source_identity(self.root, invalid)

    def test_observe_binds_committed_source_without_upgrading_claims(self) -> None:
        self.git_fixture()
        original_claims = copy.deepcopy(self.implementation["claimBoundary"])
        self.write("codex-rs/Cargo.lock", "version = 4\n# changed source\n")
        self.git("add", ".")
        self.git("commit", "-m", "new source fixture")
        MODULE.observe(self.root)
        refreshed = MODULE.data(self.root, MODULE.MAP_PATH)
        self.assertEqual(refreshed["claimBoundary"], original_claims)
        self.assertEqual(refreshed["observedAtHead"]["commit"], self.git("rev-parse", "HEAD"))
        self.assertFalse(refreshed["claimBoundary"]["durableNeuralCircuitProductComplete"])
        MODULE.verify_source_identity(self.root, refreshed)

    def test_observe_refuses_uncommitted_source(self) -> None:
        self.git_fixture()
        self.write("codex-rs/Cargo.lock", "uncommitted source\n")
        with self.assertRaises(MODULE.ContractError):
            MODULE.observe(self.root)

    def test_workspace_input_omission_rejects(self) -> None:
        self.git_fixture()
        self.implementation["observedSourcePaths"].remove("codex-rs/Cargo.lock")
        with self.assertRaises(MODULE.ContractError):
            MODULE.verify_source_identity(self.root, self.implementation)


if __name__ == "__main__":
    unittest.main()
