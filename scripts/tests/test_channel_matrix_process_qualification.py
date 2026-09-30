"""Closed process-crash qualification tests for channel.matrix."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_process_qualification as process


class ProcessQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.candidate = {"commit": "a" * 40, "tree": "b" * 40}
        self.profile, _ = process.load_profile()

    @staticmethod
    def write(path: Path, row) -> None:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")

    def manifest(self) -> Path:
        scenarios = []
        for index, (scenario_id, invariants) in enumerate(
            self.profile["scenarios"].items()
        ):
            artifact = self.root / f"process-{index:02d}.json"
            artifact.write_text(
                json.dumps(
                    {
                        "scenario": scenario_id,
                        "invariants": list(invariants),
                        "result": "pass",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            payload = artifact.read_bytes()
            scenarios.append(
                {
                    "id": scenario_id,
                    "result": "pass",
                    "observedInvariants": list(invariants),
                    "artifact": {
                        "path": artifact.name,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                }
            )
        manifest = self.root / "process.manifest.json"
        self.write(
            manifest,
            {
                "schema": process.MANIFEST_SCHEMA,
                "candidate": self.candidate,
                "result": "pass",
                "execution": {
                    "principal": "matrix-target-operator",
                    "runId": "target-run-001",
                    "attemptId": "1",
                    "hostFingerprint": "macbook-arm64-01",
                    "runnerImage": "macos-arm64-qualified",
                    "targetTriple": "aarch64-apple-darwin",
                    "startedAtUnixMs": 1_800_000_000_000,
                    "finishedAtUnixMs": 1_800_000_100_000,
                    "storeBackend": self.profile["storeBackend"],
                    "transport": self.profile["transport"],
                    "homeserverImageDigest": "sha256:" + "1" * 64,
                    "agentdSha256": "2" * 64,
                    "matrixdSha256": "3" * 64,
                    "testBinarySha256": "4" * 64,
                    "configurationSha256": "5" * 64,
                    "processIdentityLedgerSha256": "6" * 64,
                },
                "scenarios": scenarios,
                "authorityGranted": False,
                "activation": False,
                "promotion": False,
                "release": False,
            },
        )
        return manifest

    def test_complete_process_manifest_validates(self):
        row = process.validate_manifest(self.manifest(), self.candidate)
        self.assertEqual(row["result"], "pass")
        self.assertEqual(
            [item["id"] for item in row["scenarios"]],
            sorted(self.profile["scenarios"]),
        )
        self.assertEqual(
            row["execution"]["storeBackend"], "sqlite_wal_single_writer"
        )
        self.assertFalse(row["authorityGranted"])
        encoded = json.dumps(row, sort_keys=True).encode()
        self.assertEqual(
            process.validate_result(encoded, self.candidate)["profileSha256"],
            row["profileSha256"],
        )

    def test_missing_or_failed_scenario_fails_closed(self):
        manifest = self.manifest()
        row = json.loads(manifest.read_text())
        row["scenarios"].pop()
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

        manifest = self.manifest()
        row = json.loads(manifest.read_text())
        row["scenarios"][0]["result"] = "fail"
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

    def test_incomplete_invariant_or_reused_artifact_fails_closed(self):
        manifest = self.manifest()
        row = json.loads(manifest.read_text())
        row["scenarios"][0]["observedInvariants"].pop()
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

        manifest = self.manifest()
        row = json.loads(manifest.read_text())
        row["scenarios"][1]["artifact"] = copy.deepcopy(
            row["scenarios"][0]["artifact"]
        )
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

    def test_wrong_backend_candidate_or_authority_claim_fails_closed(self):
        manifest = self.manifest()
        row = json.loads(manifest.read_text())
        row["execution"]["storeBackend"] = "postgresql"
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

        manifest = self.manifest()
        with self.assertRaises(ValueError):
            process.validate_manifest(
                manifest, {"commit": "c" * 40, "tree": "d" * 40}
            )

        row = json.loads(manifest.read_text())
        row["activation"] = True
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            process.validate_manifest(manifest, self.candidate)

    def test_profile_is_closed_sorted_and_covers_required_oracles(self):
        profile, digest = process.load_profile()
        self.assertEqual(len(digest), 64)
        self.assertEqual(profile["storeBackend"], "sqlite_wal_single_writer")
        self.assertEqual(profile["transport"], "matrix_synapse_authenticated")
        self.assertEqual(list(profile["scenarios"]), sorted(profile["scenarios"]))
        invariants = {
            invariant
            for values in profile["scenarios"].values()
            for invariant in values
        }
        for required in (
            "no_duplicate_nonrepeatable_effect",
            "unknown_never_not_started",
            "stale_generation_cannot_commit",
            "durable_memory_state_no_silent_split",
            "old_token_cannot_continue",
            "current_owner_only",
            "bounded_reconciliation",
            "required_outcome_evidence_retained",
        ):
            self.assertIn(required, invariants)


if __name__ == "__main__":
    unittest.main()
