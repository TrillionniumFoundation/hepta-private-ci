from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.test_compact_engine_qualification_legacy import *  # noqa: F401,F403
from scripts.test_compact_engine_qualification_legacy import QUALIFICATION, write


class CompactEngineExactSourceIdentityTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def create_exact_repository(self, root: Path) -> tuple[str, str]:
        required = set(QUALIFICATION.MIGRATION_INPUTS)
        required.update(QUALIFICATION.DOCUMENTATION_INPUTS)
        required.update(QUALIFICATION.QUALIFICATION_PROFILE_INPUTS)
        required.update(
            {
                Path("codex-rs/Cargo.toml"),
                Path("codex-rs/Cargo.lock"),
                QUALIFICATION.AGENTD_HOST,
                Path("codex-rs/hepta-compact-engine/src/lib.rs"),
                Path("codex-rs/hepta-compact-engine/src/owner_tests.rs"),
            }
        )
        for path in sorted(required):
            if path == Path("codex-rs/hepta-compact-engine/src/lib.rs"):
                content = (
                    "pub fn owner_entrypoint() {}\n"
                    "#[cfg(test)]\n"
                    "mod owner_tests;\n"
                )
            elif path == Path("codex-rs/hepta-compact-engine/src/owner_tests.rs"):
                content = "#[test]\nfn owner_contract() {}\n"
            else:
                content = f"fixture {path.as_posix()}\n"
            write(root / path, content)

        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "compact.engine exact identity test")
        self.git(root, "config", "user.email", "compact-engine-test@example.invalid")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "source fixture")
        observed_commit = self.git(root, "rev-parse", "HEAD")
        observed_tree = self.git(root, "rev-parse", "HEAD^{tree}")

        lib_path = "codex-rs/hepta-compact-engine/src/lib.rs"
        test_path = "codex-rs/hepta-compact-engine/src/owner_tests.rs"
        crate_path = "codex-rs/hepta-compact-engine"
        lib_blob = self.git(root, "rev-parse", f"HEAD:{lib_path}")
        test_blob = self.git(root, "rev-parse", f"HEAD:{test_path}")
        crate_tree = self.git(root, "rev-parse", f"HEAD:{crate_path}")

        implementation_map: dict[str, Any] = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "module": "compact.engine",
            "mappingSourceIdentityMode": "exact_blob",
            "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
            "technicalGuide": "docs/modules/compact.engine/TECHNICAL.md",
            "recoveryProtocol": "docs/modules/compact.engine/RECOVERY_PROTOCOL_V2.md",
            "qualificationWorkflow": ".github/workflows/compact-engine-qualification.yml",
            "capacityWorkflow": ".github/workflows/compact-engine-capacity.yml",
            "declaredRoots": [crate_path],
            "resolvedRoots": [crate_path],
            "sourceRoot": [crate_path],
            "operations": [
                {
                    "operation": "owner",
                    "nativeSymbol": "owner_entrypoint",
                    "sourcePath": lib_path,
                    "sourcePathExists": True,
                    "sourceBlob": lib_blob,
                    "tests": [test_path],
                    "delegatedCallees": [],
                }
            ],
            "qualificationVerifier": {
                "path": "scripts/compact_engine_qualification.py",
                "tests": "scripts/test_compact_engine_qualification.py",
                "workflow": ".github/workflows/compact-engine-qualification.yml",
            },
            "observedSourcePaths": [
                crate_path,
                "scripts/compact_engine_qualification.py",
                "scripts/compact_engine_qualification_legacy.py",
                "scripts/test_compact_engine_qualification.py",
                "scripts/test_compact_engine_qualification_legacy.py",
            ],
            "observedAtHead": {
                "commit": observed_commit,
                "tree": observed_tree,
            },
            "exactSourceEvidence": {
                "kind": "path_blob_manifest_v1",
                "entries": [
                    {"path": lib_path, "blobSha": lib_blob},
                    {"path": test_path, "blobSha": test_blob},
                ],
            },
            "sourceObjects": [
                {"path": crate_path, "object": crate_tree},
                {"path": lib_path, "object": lib_blob},
                {"path": test_path, "object": test_blob},
            ],
        }
        write(
            root / QUALIFICATION.MAP_PATH,
            json.dumps(implementation_map, indent=2, sort_keys=True) + "\n",
        )
        self.git(root, "add", QUALIFICATION.MAP_PATH.as_posix())
        self.git(root, "commit", "-qm", "implementation map")
        return self.git(root, "rev-parse", "HEAD"), lib_path

    def test_exact_object_manifest_is_generated_from_current_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            head, _ = self.create_exact_repository(root)
            report = QUALIFICATION.verify_implementation_map(root)
            self.assertTrue(report["verified"])
            self.assertTrue(report["source_identity_enforced"])
            self.assertTrue(report["source_identity_verified"])
            self.assertEqual(report["source_object_manifest"]["head_commit"], head)
            self.assertRegex(report["source_object_manifest_hash"], r"^[0-9a-f]{64}$")

    def test_dirty_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, lib_path = self.create_exact_repository(root)
            write(root / lib_path, "pub fn owner_entrypoint() {}\n// dirty\n")
            with self.assertRaisesRegex(
                QUALIFICATION.QualificationError,
                "dirty or untracked",
            ):
                QUALIFICATION.verify_implementation_map(root)

    def test_committed_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, lib_path = self.create_exact_repository(root)
            write(
                root / lib_path,
                "pub fn owner_entrypoint() {}\n#[cfg(test)]\nmod owner_tests;\n// drift\n",
            )
            self.git(root, "add", lib_path)
            self.git(root, "commit", "-qm", "drift")
            with self.assertRaisesRegex(
                QUALIFICATION.QualificationError,
                "sourceBlob mismatch",
            ):
                QUALIFICATION.verify_implementation_map(root)

    def test_final_main_push_binds_github_merge_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            head, _ = self.create_exact_repository(root)
            output = root / "readiness.json"
            original = QUALIFICATION._legacy_build

            def fake_legacy(*args: Any, **kwargs: Any) -> dict[str, Any]:
                return {
                    "github_merge_sha": None,
                    "generation_errors": [],
                    "requiredLanesPassed": True,
                    "mergeReady": False,
                    "productionQualified": True,
                    "claim_boundary": {},
                }

            QUALIFICATION._legacy_build = fake_legacy
            try:
                manifest = QUALIFICATION.build_readiness_manifest(
                    root,
                    root / "artifacts",
                    output,
                    source_head_sha=head,
                    frozen_source_sha=head,
                    workflow_sha=head,
                    github_merge_sha="",
                    final_merge_sha=head,
                    workflow_run_id="42",
                    attempt_id="1",
                    event_name="push",
                    source_result="success",
                    qualify_result="success",
                    capacity_result="success",
                    postmerge_result="success",
                )
            finally:
                QUALIFICATION._legacy_build = original

            self.assertEqual(manifest["github_merge_sha"], head)
            self.assertEqual(
                manifest["github_merge_sha_source"],
                "main_push_workflow_sha",
            )
            self.assertTrue(manifest["requiredLanesPassed"])
            self.assertTrue(manifest["productionQualified"])
            self.assertTrue(manifest["source_identity_verified"])


if __name__ == "__main__":
    unittest.main()
