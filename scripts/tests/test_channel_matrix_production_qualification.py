"""Closed production-evidence profile tests for channel.matrix."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_production_qualification as production


class ProductionQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.candidate = {"commit": "a" * 40, "tree": "b" * 40}
        self.profile, _ = production.load_profile()

    @staticmethod
    def write(path: Path, row) -> None:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")

    def process_validation(self) -> dict:
        profile, profile_sha256 = production.process.load_profile()
        execution = {
            "principal": "matrix-target-operator",
            "runId": "process-run-001",
            "attemptId": "1",
            "hostFingerprint": "macbook-arm64-01",
            "runnerImage": "macos-arm64-qualified",
            "targetTriple": "aarch64-apple-darwin",
            "startedAtUnixMs": 1_800_000_000_000,
            "finishedAtUnixMs": 1_800_000_100_000,
            "storeBackend": profile["storeBackend"],
            "transport": profile["transport"],
            "homeserverImageDigest": "sha256:" + "1" * 64,
            "agentdSha256": "2" * 64,
            "matrixdSha256": "3" * 64,
            "testBinarySha256": "4" * 64,
            "configurationSha256": "5" * 64,
            "processIdentityLedgerSha256": "6" * 64,
        }
        return {
            "schema": production.process.RESULT_SCHEMA,
            "candidate": self.candidate,
            "result": "pass",
            "execution": execution,
            "profileSha256": profile_sha256,
            "manifest": {
                "path": "process.manifest.json",
                "bytes": 123,
                "sha256": "7" * 64,
            },
            "scenarios": [
                {
                    "id": scenario_id,
                    "observedInvariants": list(invariants),
                    "artifact": {
                        "path": f"{scenario_id.lower()}.json",
                        "bytes": 1,
                        "sha256": hashlib.sha256(scenario_id.encode()).hexdigest(),
                    },
                }
                for scenario_id, invariants in profile["scenarios"].items()
            ],
            "authorityGranted": False,
            "activation": False,
            "promotion": False,
            "release": False,
        }

    def manifest(self, scope: str) -> Path:
        checks = []
        for index, check_id in enumerate(self.profile[scope]):
            artifact = self.root / f"{scope}-{index:02d}.json"
            if scope == "target_qualification" and check_id == production.PROCESS_CHECK_ID:
                artifact.write_text(
                    json.dumps(self.process_validation(), indent=2, sort_keys=True) + "\n"
                )
            else:
                artifact.write_text(
                    json.dumps({"check": check_id, "result": "pass"})
                )
            payload = artifact.read_bytes()
            checks.append(
                {
                    "id": check_id,
                    "result": "pass",
                    "artifact": {
                        "path": artifact.name,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                }
            )
        manifest = self.root / f"{scope}.manifest.json"
        self.write(
            manifest,
            {
                "schema": production.MANIFEST_SCHEMA,
                "scope": scope,
                "candidate": self.candidate,
                "result": "pass",
                "executor": {
                    "principal": "matrix-target-operator",
                    "hostFingerprint": "host-fingerprint-01",
                    "startedAtUnixMs": 1_800_000_000_000,
                    "finishedAtUnixMs": 1_800_000_100_000,
                },
                "checks": checks,
                "authorityGranted": False,
                "activation": False,
                "release": False,
            },
        )
        return manifest

    def test_complete_target_and_acceptance_manifests_validate(self):
        for scope in production.SCOPES:
            row = production.validate_manifest(self.manifest(scope), self.candidate)
            self.assertEqual(row["result"], "pass")
            self.assertEqual(row["scope"], scope)
            self.assertEqual(
                {artifact["id"] for artifact in row["artifacts"]},
                set(self.profile[scope]),
            )
            self.assertFalse(row["authorityGranted"])
            if scope == "target_qualification":
                self.assertEqual(
                    row["processFaultMatrix"]["scenarioCount"],
                    len(production.process.load_profile()[0]["scenarios"]),
                )
            else:
                self.assertIsNone(row["processFaultMatrix"])

    def test_missing_failed_or_duplicate_check_fails_closed(self):
        manifest = self.manifest("target_qualification")
        row = json.loads(manifest.read_text())
        row["checks"].pop()
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

        manifest = self.manifest("target_qualification")
        row = json.loads(manifest.read_text())
        row["checks"][0]["result"] = "fail"
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

        manifest = self.manifest("target_qualification")
        row = json.loads(manifest.read_text())
        row["checks"][1]["id"] = row["checks"][0]["id"]
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

    def test_wrong_candidate_tampered_artifact_and_authority_claim_fail_closed(self):
        manifest = self.manifest("target_qualification")
        wrong = {"commit": "c" * 40, "tree": "d" * 40}
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, wrong)

        row = json.loads(manifest.read_text())
        artifact = self.root / row["checks"][0]["artifact"]["path"]
        artifact.write_text(artifact.read_text() + "tamper")
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

        manifest = self.manifest("target_qualification")
        row = json.loads(manifest.read_text())
        row["activation"] = True
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

    def test_process_validation_is_not_an_opaque_artifact(self):
        manifest = self.manifest("target_qualification")
        row = json.loads(manifest.read_text())
        process_check = next(
            check
            for check in row["checks"]
            if check["id"] == production.PROCESS_CHECK_ID
        )
        artifact = self.root / process_check["artifact"]["path"]
        validation = json.loads(artifact.read_text())
        validation["candidate"]["commit"] = "c" * 40
        artifact.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        payload = artifact.read_bytes()
        process_check["artifact"]["bytes"] = len(payload)
        process_check["artifact"]["sha256"] = hashlib.sha256(payload).hexdigest()
        self.write(manifest, row)
        with self.assertRaises(ValueError):
            production.validate_manifest(manifest, self.candidate)

    def test_profile_is_sorted_closed_and_scope_specific(self):
        profile, digest = production.load_profile()
        self.assertEqual(len(digest), 64)
        self.assertEqual(set(profile), set(production.SCOPES))
        self.assertIn("encrypted_room_rotation", profile["target_qualification"])
        self.assertIn("protected_backup_restore", profile["target_qualification"])
        self.assertIn(production.PROCESS_CHECK_ID, profile["target_qualification"])
        self.assertIn("security_threat_review", profile["independent_acceptance"])
        self.assertTrue(
            set(profile["target_qualification"]).isdisjoint(
                profile["independent_acceptance"]
            )
        )


if __name__ == "__main__":
    unittest.main()
