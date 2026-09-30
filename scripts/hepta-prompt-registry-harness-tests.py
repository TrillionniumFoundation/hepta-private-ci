#!/usr/bin/env python3
"""Offline adversarial tests for prompt.registry qualification evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


qualify = load("qualify", "hepta-prompt-registry-qualify.py")
summary = load("aggregate", "hepta-prompt-registry-aggregate.py")


class EvidenceTests(unittest.TestCase):
    def test_inventory_is_not_execution(self):
        self.assertEqual(qualify.completed_tests("tests::required: test\n0 tests, 0 benchmarks"), set())

    def test_ignored_and_failed_tests_are_not_passes(self):
        text = "test a::first ... ignored\ntest a::second ... FAILED\ntest a::third ... ok\n"
        self.assertEqual(qualify.completed_tests(text), {"a::third"})

    def test_profile_parser_ignores_noise_and_invalid_json(self):
        text = 'noise\n{"schema":"other"}\n{"bad\ntest prefix {"schema":"hepta.prompt-registry.x","count":1}\n'
        self.assertEqual(qualify.profile_rows(text), [{"schema": "hepta.prompt-registry.x", "count": 1}])

    def test_network_retry_requires_recognized_transport_failure(self):
        self.assertTrue(qualify.transient_network_failure("[28] Timeout was reached: operation too slow"))
        self.assertFalse(qualify.transient_network_failure("error[E0308]: mismatched types"))

    def test_missing_profiles_fail_closed(self):
        self.assertTrue(qualify.check_measurements("operational-profiles", []))
        self.assertTrue(qualify.check_measurements("pipeline-profile", []))

    def rows(self):
        scale = [{"schema": "hepta.prompt-registry.operational-scale.v2", "logicalRecords": n,
                  "inPlaceGc": {"collectedPayloadRecords": 1, "cleanupPending": False},
                  "snapshot": {"samples": 31}, "dereference": {"samples": 31}} for n in (1000, 8000, 16384)]
        fsync = [{"schema": "hepta.prompt-registry.fsync-profile.v2", "bytes": n,
                  "total": {"samples": 31}} for n in (4096, 65536, 1048576)]
        writers = [{"schema": "hepta.prompt-registry.writer-profile.v1", "finalLogicalRecords": n,
                    "registration": {"samples": 31}, "retirement": {"samples": 31}} for n in (1000, 8000, 16384)]
        return scale + fsync + writers

    def test_complete_bounded_profiles(self):
        self.assertEqual(qualify.check_measurements("operational-profiles", self.rows()), [])
        self.assertEqual(qualify.check_measurements("pipeline-profile", [
            {"schema": "hepta.prompt-registry.pipeline-profile.v1"}
        ] * 31), [])

    def test_duplicates_or_unfinished_collection_cannot_pass(self):
        rows = self.rows()
        self.assertTrue(qualify.check_measurements("operational-profiles", rows + rows[:1]))
        rows[0]["inPlaceGc"]["cleanupPending"] = True
        self.assertTrue(qualify.check_measurements("operational-profiles", rows))


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.receipts: list[tuple[Path, dict]] = []
        for profile, lane in sorted(summary.LANES):
            directory = self.root / (profile + "-" + lane)
            directory.mkdir()
            tested = ("a" if lane == "exact-head" else "c") * 40
            tree = "d" * 40
            live_map = {
                "schema": "hepta.prompt-registry.live-public-api-map.v1",
                "candidateSha": tested, "sourceTreeHash": tree,
                "closedWorldPublicFunctions": True,
                "dangerousLegacyPurgeSymbols": [],
                "productionReady": False, "mergeReady": False,
            }
            live_path = directory / "live-public-api-map.json"
            live_path.write_text(json.dumps(live_map), encoding="utf-8")
            checks = []
            for name in sorted(summary.REQUIRED[profile]):
                log = (f"actual fixture log for {name}\n").encode()
                (directory / (name + ".log")).write_bytes(log)
                attempt_name = name + ".attempt-1.log"
                (directory / attempt_name).write_bytes(log)
                checks.append({
                    "name": name, "command": ["fixture", name],
                    "required": [], "minimumPassed": 0,
                    "networkPrime": name == "dependency-prime",
                    "state": "passed", "exitCode": 0,
                    "postconditionFailures": [], "logSha256": hashlib.sha256(log).hexdigest(),
                    "attempts": [{"attempt": 1, "exitCode": 0, "durationSeconds": 0.1,
                                  "log": attempt_name, "logSha256": hashlib.sha256(log).hexdigest(),
                                  "transientNetworkFailure": False}],
                    "retried": False, "firstAttemptExitCode": 0, "finalAttemptExitCode": 0,
                    "passedTests": 1,
                })
            feature = {"profile": profile, "lane": lane, "workspaceDefaultFeatures": True}
            runner = {"system": "test", "machine": "x86_64", "name": "runner", "os": "Linux",
                      "arch": "X64", "environment": "github-hosted", "imageOs": "ubuntu24",
                      "imageVersion": "fixture", "targetTriple": "x86_64-unknown-linux-gnu"}
            docs = {"docs/file": "1" * 64}
            source_files = {"source/file": "0" * 64}
            receipt = {
                "schema": "hepta.prompt-registry.qualification-receipt.v3",
                "profile": profile, "lane": lane,
                "candidateSha": "a" * 40, "sourceSha": "a" * 40, "baseSha": "b" * 40,
                "testedSha": tested, "deterministicMergeSha": tested if lane == "base-merge" else None,
                "testedTree": tree, "sourceTreeHash": tree,
                "runId": "1", "runAttempt": "1", "workflowRunId": "1", "workflowRunAttempt": "1",
                "workflowSha": "e" * 40,
                "workflowRef": "TrillionniumFoundation/hepta-private-ci/.github/workflows/qualification.yml@refs/pull/1/merge",
                "workflowFileSha256": "2" * 64,
                "dependencyLockSha256": "f" * 64, "cargoLockSha256": "f" * 64,
                "implementationMapSha256": "3" * 64,
                "documentationManifest": docs, "documentationHash": summary.canonical_sha(docs),
                "sourceFiles": source_files, "sourceManifestSha256": summary.canonical_sha(source_files),
                "featureProfile": feature, "featureProfileSha256": summary.canonical_sha(feature),
                "testSetSha256": summary.canonical_sha([
                    {"name": row["name"], "command": row["command"], "required": row["required"],
                     "minimumPassed": row["minimumPassed"], "networkPrime": row["networkPrime"]}
                    for row in checks
                ]),
                "livePublicApiMapSha256": hashlib.sha256(live_path.read_bytes()).hexdigest(),
                "targetTriple": "x86_64-unknown-linux-gnu", "runner": runner,
                "runnerImageIdentitySha256": summary.canonical_sha(runner),
                "runnerImageDigest": None,
                "runnerImageDigestKind": "github-hosted-vm-identity-not-oci-content-digest",
                "checks": checks, "allRequiredChecksPassed": True, "firstFailure": None,
                "retryOccurred": False,
                "qualified": False, "mergeReady": False, "productionReady": False,
                "productActivated": False, "accepted": False, "released": False,
                "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
            }
            artifacts = {}
            for path in sorted(entry for entry in directory.rglob("*") if entry.is_file()):
                artifacts[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            receipt["artifactHashes"] = artifacts
            receipt_path = directory / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            self.receipts.append((receipt_path, receipt))

    def run_aggregate(self):
        return summary.aggregate(self.root, "a" * 40, "b" * 40, "1", "1")

    def rewrite(self, index=0, **values):
        receipt_path, receipt = self.receipts[index]
        receipt.update(values)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_four_lane_success_is_not_acceptance(self):
        result = self.run_aggregate()
        self.assertEqual(result["schema"], "hepta.prompt-registry.qualification-summary.v3")
        self.assertTrue(result["sourceQualified"])
        self.assertTrue(result["closedWorldPublicFunctions"])
        self.assertFalse(result["productExecutionProved"])
        self.assertFalse(result["mergeReady"])
        self.assertFalse(result["productionReady"])
        self.assertEqual(len(result["receiptSha256"]), 4)

    def test_missing_lane_rejected(self):
        self.receipts[0][0].unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_historical_attempt_or_cross_run_receipt_rejected(self):
        self.rewrite(runAttempt="2", workflowRunAttempt="2")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_raw_log_tampering_rejected(self):
        (self.receipts[0][0].parent / "public-api-map.log").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_artifact_manifest_omission_rejected(self):
        receipt_path, receipt = self.receipts[0]
        receipt["artifactHashes"].pop("live-public-api-map.json")
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_unjustified_retry_rejected(self):
        receipt_path, receipt = self.receipts[0]
        check = next(row for row in receipt["checks"] if row["name"] == "dependency-prime")
        first = dict(check["attempts"][0])
        first["exitCode"] = 1
        first["transientNetworkFailure"] = False
        second = dict(check["attempts"][0])
        second["attempt"] = 2
        check["attempts"] = [first, second]
        check["retried"] = True
        check["firstAttemptExitCode"] = 1
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_documentation_or_lock_mismatch_rejected(self):
        self.rewrite(index=1, documentationHash="4" * 64)
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.rewrite(index=1, documentationHash=self.receipts[0][1]["documentationHash"],
                     dependencyLockSha256="5" * 64, cargoLockSha256="5" * 64)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_dangerous_legacy_purge_evidence_rejected(self):
        path = self.receipts[0][0].parent / "live-public-api-map.json"
        data = json.loads(path.read_text())
        data["dangerousLegacyPurgeSymbols"] = ["legacy"]
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_failed_or_skipped_check_cannot_hide(self):
        receipt_path, receipt = self.receipts[0]
        receipt["checks"][0]["state"] = "not_run"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
