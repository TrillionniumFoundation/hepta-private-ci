from __future__ import annotations

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
            "source_head_sha",
            "frozen_source_sha",
            "base_sha",
            "deterministic_merge_sha",
            "github_merge_sha",
            "workflow_sha",
            "final_merge_sha",
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
        ):
            self.assertIn(field, row)
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

    def test_provenance_must_match_one_run_and_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory_value:
            directory = Path(directory_value)
            provenance = {
                "schema": "hepta.channel-matrix-source-provenance.v1",
                "valid": True,
                "errors": [],
                "stage": "source-head",
                "checkoutSha": "1" * 40,
                "checkoutTree": "2" * 40,
                "execution": {
                    "workflowRunId": "run-1",
                    "attemptId": "1",
                    "runnerImage": "ubuntu24:20260930",
                    "targetTriple": "x86_64-unknown-linux-gnu",
                },
                "files": [
                    {
                        "absolutePath": "/tmp/source",
                        "repoRelativePath": "source",
                        "gitBlob": "3" * 40,
                        "sha256": "4" * 64,
                        "tracked": True,
                        "gitLsFilesErrorUnmatch": True,
                    }
                ],
                "claims": {
                    "trackedSourceOnly": True,
                    "generatedSourceIncluded": False,
                    "cacheSourceIncluded": False,
                    "artifactSourceIncluded": False,
                    "authorityGranted": False,
                },
            }
            (directory / "source-provenance.json").write_text(
                json.dumps(provenance), encoding="utf-8"
            )
            lane = {
                "source": {"testedSha": "1" * 40, "testedTree": "2" * 40},
                "manifest": {"runId": "run-1", "runAttempt": "1"},
            }
            row = module.validate_provenance(directory, lane, "source-head", "run-1", "1")
            self.assertEqual(row["execution"]["runnerImage"], "ubuntu24:20260930")
            with self.assertRaises(ValueError):
                module.validate_provenance(directory, lane, "source-head", "run-1", "2")

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
        self.assertFalse(row["repositoryQualified"])
        self.assertFalse(row["mergeReady"])
        self.assertFalse(row["productionQualified"])
        self.assertIn("missing lane", row["blockers"])


if __name__ == "__main__":
    unittest.main()
