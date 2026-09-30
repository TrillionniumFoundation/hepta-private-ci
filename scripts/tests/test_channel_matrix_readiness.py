from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_readiness.py"
spec = importlib.util.spec_from_file_location("channel_matrix_readiness_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def empty_sha256() -> str:
    return hashlib.sha256(b"").hexdigest()


def provenance_row(stage: str = "source-head") -> dict:
    workspace = "/tmp/channel-matrix-readiness-fixture"
    files = [
        {
            "absolutePath": f"{workspace}/source",
            "repoRelativePath": "source",
            "gitBlob": "3" * 40,
            "sha256": "4" * 64,
            "bytes": 1,
            "tracked": True,
            "gitLsFilesErrorUnmatch": True,
            "trackedCheck": {
                "command": ["git", "ls-files", "--error-unmatch", "--", "source"],
                "exitStatus": 0,
                "stdoutSha256": "5" * 64,
                "stderrSha256": "6" * 64,
            },
            "introducedAtCommit": "7" * 40,
            "firstObservedStage": stage,
            "origin": "tracked_repository_source",
            "sourceClass": "tracked_repository_source",
            "classification": {
                "fixture": False,
                "workflow": False,
                "documentation": False,
                "generated": False,
                "cache": False,
                "artifact": False,
            },
        }
    ]
    clean = {
        "clean": True,
        "unstaged": [],
        "staged": [],
        "untrackedClosureInputs": [],
        "ignoredClosureInputs": [],
        "workspaceStatus": {
            "command": ["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"],
            "bytes": 0,
            "sha256": empty_sha256(),
            "empty": True,
        },
    }
    return {
        "schema": "hepta.channel-matrix-source-provenance.v1",
        "valid": True,
        "errors": [],
        "stage": stage,
        "workspaceRoot": workspace,
        "checkoutSha": "1" * 40,
        "checkoutTree": "2" * 40,
        "scan": {
            "defaultCommand": ["git", "ls-files", "-z"],
            "closureFileCount": 1,
            "closurePathInventorySha256": module.source_provenance.path_inventory(["source"]),
            "cleanBefore": clean,
            "cleanAfter": clean,
        },
        "execution": {
            "workflowRunId": "run-1",
            "attemptId": "1",
            "runnerImage": "ubuntu24:20260930",
            "targetTriple": "x86_64-unknown-linux-gnu",
        },
        "files": files,
        "sourceInventorySha256": module.source_provenance.aggregate(files),
        "sourceContentInventorySha256": module.source_provenance.canonical_digest(
            module.source_provenance.CONTENT_INVENTORY_DOMAIN,
            module.source_provenance.content_inventory(files),
        ),
        "claims": {
            "trackedSourceOnly": True,
            "generatedSourceIncluded": False,
            "cacheSourceIncluded": False,
            "artifactSourceIncluded": False,
            "authorityGranted": False,
        },
    }


class ReadinessTests(unittest.TestCase):
    def test_schema_contains_every_required_identity_and_denies_authority(self) -> None:
        row = module.skeleton(
            "pull_request",
            {
                "source": "1" * 40,
                "base": "2" * 40,
                "github_merge": "3" * 40,
                "workflow": "4" * 40,
                "final_merge": None,
            },
        )
        for field in (
            "candidate_key",
            "source_head_sha",
            "source_tree_hash",
            "frozen_source_sha",
            "frozen_source_tree_hash",
            "base_sha",
            "deterministic_merge_sha",
            "deterministic_merge_tree_hash",
            "github_merge_sha",
            "github_merge_tree_hash",
            "workflow_sha",
            "final_merge_sha",
            "final_merge_tree_hash",
            "workflow_run_id",
            "attempt_id",
            "runner_image",
            "target_triple",
            "Cargo.lock_hash",
            "migration_hash",
            "test_set_hash",
            "qualification_profile_hash",
            "implementation_map_hash",
            "documentation_hash",
            "source_tree_hash",
            "artifact_hashes",
            "required_lanes",
            "evidence_policy",
        ):
            self.assertIn(field, row)
        self.assertFalse(row["evidence_policy"]["crossAttemptMixingAllowed"])
        self.assertFalse(row["mergeReady"])
        self.assertFalse(row["productionQualified"])
        self.assertFalse(row["activation"])
        self.assertFalse(row["release"])
        self.assertFalse(row["authorityGranted"])

    def test_optional_sha_rejects_abbreviated_or_uppercase_values(self) -> None:
        self.assertIsNone(module.optional_sha(""))
        self.assertEqual(module.optional_sha("a" * 40), "a" * 40)
        with self.assertRaises(ValueError):
            module.optional_sha("a" * 12)
        with self.assertRaises(ValueError):
            module.optional_sha("A" * 40)

    def test_provenance_must_match_one_run_attempt_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory_value:
            directory = Path(directory_value)
            provenance = provenance_row()
            (directory / "source-provenance.json").write_text(
                json.dumps(provenance), encoding="utf-8"
            )
            lane = {
                "source": {"testedSha": "1" * 40, "testedTree": "2" * 40},
                "manifest": {"runId": "run-1", "runAttempt": "1"},
            }
            row = module.validate_provenance(
                directory, lane, "source-head", "run-1", "1"
            )
            self.assertEqual(row["execution"]["runnerImage"], "ubuntu24:20260930")
            with self.assertRaises(ValueError):
                module.validate_provenance(
                    directory, lane, "source-head", "run-1", "2"
                )
            provenance["files"][0]["gitBlob"] = "8" * 40
            (directory / "source-provenance.json").write_text(
                json.dumps(provenance), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "inventory digest"):
                module.validate_provenance(
                    directory, lane, "source-head", "run-1", "1"
                )

    def test_candidate_key_changes_for_attempt_or_artifact_identity(self) -> None:
        row = module.skeleton(
            "pull_request",
            {
                "source": "1" * 40,
                "base": "2" * 40,
                "github_merge": "3" * 40,
                "workflow": "4" * 40,
                "final_merge": None,
            },
        )
        git_fields = (
            "source_tree_hash",
            "frozen_source_sha",
            "frozen_source_tree_hash",
            "deterministic_merge_sha",
            "deterministic_merge_tree_hash",
            "github_merge_tree_hash",
        )
        for index, field in enumerate(git_fields, start=5):
            row[field] = f"{index:x}" * 40
        hash_fields = (
            "Cargo.lock_hash",
            "migration_hash",
            "test_set_hash",
            "qualification_profile_hash",
            "production_qualification_profile_hash",
            "process_fault_profile_hash",
            "transport_tcb_hash",
            "implementation_map_hash",
            "module_status_hash",
            "document_sources_hash",
            "review_slices_hash",
            "documentation_hash",
        )
        for index, field in enumerate(hash_fields, start=1):
            row[field] = f"{index:x}" * 64
        row["workflow_run_id"] = "run-1"
        row["attempt_id"] = "1"
        row["runner_image"] = {
            "source_head": "ubuntu24:fixture",
            "deterministic_merge": "ubuntu24:fixture",
        }
        row["target_triple"] = {
            "source_head": "x86_64-unknown-linux-gnu",
            "deterministic_merge": "x86_64-unknown-linux-gnu",
        }
        row["artifact_hashes"] = {"paired": "a" * 64}
        for lane in module.REPOSITORY_REQUIRED_LANES:
            row["lane_status"][lane] = "passed"
        first = module.readiness_key(row)
        row["attempt_id"] = "2"
        second = module.readiness_key(row)
        self.assertNotEqual(first, second)
        row["attempt_id"] = "1"
        row["artifact_hashes"]["paired"] = "b" * 64
        third = module.readiness_key(row)
        self.assertNotEqual(first, third)

    def test_repository_failure_can_never_be_merge_ready(self) -> None:
        with mock.patch.object(
            module.paired_v2,
            "_extended_lane",
            side_effect=ValueError("missing lane"),
        ):
            row = module.build(
                Path("missing-source"),
                Path("missing-merge"),
                Path("missing-pair"),
                "pull_request",
                "1" * 40,
                "2" * 40,
                "3" * 40,
                None,
                "4" * 40,
            )
        self.assertIsNone(row["candidate_key"])
        self.assertFalse(row["evidence_policy"]["nonMixableManifestKeyBound"])
        self.assertFalse(row["repositoryQualified"])
        self.assertFalse(row["mergeReady"])
        self.assertFalse(row["productionQualified"])
        self.assertIn("missing lane", row["blockers"])


if __name__ == "__main__":
    unittest.main()
