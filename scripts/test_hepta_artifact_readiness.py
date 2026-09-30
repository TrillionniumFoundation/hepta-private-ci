"""Adversarial tests for matrix-level learning.artifacts readiness."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import hepta_artifact_readiness as readiness

SOURCE = "1" * 40
BASE = "2" * 40
EVENT = "3" * 40
SYNTHETIC = "4" * 40
SOURCE_TREE = "5" * 40
SYNTHETIC_TREE = "6" * 40
DOC_TREE = "7" * 40
RUN_ID = "12345"
RUN_ATTEMPT = "1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_fixture(root: Path) -> tuple[Path, Path]:
    workflow = root / "workflow.yml"
    implementation_map = root / "implementation-map.json"
    workflow.write_text("name: fixture\n", encoding="utf-8")
    implementation_map.write_text('{"module":"learning.artifacts"}\n', encoding="utf-8")
    workflow_hash = digest(workflow.read_bytes())
    map_hash = digest(implementation_map.read_bytes())
    bundles = root / "bundles"
    for profile, expected in readiness.PROFILES.items():
        for lane in readiness.LANES:
            bundle = bundles / f"learning-artifacts-{profile}-{lane}"
            runner_dir = bundle / "artifact-runner-identity"
            evidence_dir = bundle / "artifact-evidence"
            runner_dir.mkdir(parents=True)
            evidence_dir.mkdir(parents=True)
            candidate = SOURCE if lane == "exact-head" else SYNTHETIC
            tree = SOURCE_TREE if lane == "exact-head" else SYNTHETIC_TREE
            identity = {
                "schema": readiness.RUNNER_SCHEMA,
                "sourceSha": SOURCE,
                "baseSha": BASE,
                "githubEventSha": EVENT,
                "candidateSha": candidate,
                "candidateTree": tree,
                "sourceTreeObject": SOURCE_TREE,
                "documentationTreeObject": DOC_TREE,
                "profile": profile,
                "lane": lane,
                "expectedArchitecture": expected["targetTriple"],
                "toolchain": expected["toolchain"],
                "runnerOs": expected["runnerOs"],
                "runnerArch": expected["runnerArch"],
                "runnerImage": "qualified-image",
                "runnerImageVersion": "20260930.1",
                "rustcVerbose": f"rustc fixture\nhost: {expected['targetTriple']}\n",
                "cargoVersion": "cargo fixture",
                "cargoLockSha256": "8" * 64,
                "workflowSha256": workflow_hash,
                "implementationMapSha256": map_hash,
                "workflowRunId": RUN_ID,
                "workflowRunAttempt": RUN_ATTEMPT,
            }
            (runner_dir / "runner-identity.json").write_text(
                json.dumps(identity, sort_keys=True), encoding="utf-8"
            )
            gates = {
                gate: {"status": "completed", "exitCode": 0}
                for gate in readiness.REQUIRED_GATES
            }
            receipt = {
                "schema": readiness.RECEIPT_SCHEMA,
                "sourceCommit": SOURCE,
                "baseCommit": BASE,
                "testedCommit": candidate,
                "testedTree": tree,
                "lane": lane,
                "runner": {
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_RUN_ID": RUN_ID,
                    "GITHUB_RUN_ATTEMPT": RUN_ATTEMPT,
                    "GITHUB_JOB": "qualify",
                    "RUNNER_OS": expected["runnerOs"],
                },
                "sourceObjects": {"source": "9" * 40},
                "gates": gates,
                "execution": {"passed": 1, "skipped": 0, "retries": 0},
                "traceability": [],
                "errors": [],
                "qualified": True,
                "completion": {
                    "nativeCandidateQualified": True,
                    "requirementTraceabilityComplete": True,
                    "moduleComplete": False,
                },
                "claimBoundary": {
                    "productionImplementation": False,
                    "productExecutionProved": False,
                    "independentAcceptance": False,
                    "activation": False,
                    "release": False,
                },
            }
            payload = readiness.canonical(receipt)
            (evidence_dir / "qualification.json").write_bytes(payload)
            (evidence_dir / "qualification.sha256").write_text(digest(payload) + "\n")
            (evidence_dir / "inventory.stdout").write_text(
                json.dumps({"profile": profile, "lane": lane}), encoding="utf-8"
            )
    return workflow, implementation_map


def build(root: Path, workflow: Path, implementation_map: Path):
    return readiness.build_manifest(
        root / "bundles", SOURCE, BASE, EVENT, RUN_ID, RUN_ATTEMPT, None,
        workflow, implementation_map,
    )


class ReadinessTests(unittest.TestCase):
    def test_complete_matrix_is_merge_ready_but_not_production_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            manifest, complete = build(root, workflow, implementation_map)
            self.assertTrue(complete)
            self.assertTrue(manifest["repositoryCandidateQualified"])
            self.assertTrue(manifest["mergeReady"])
            self.assertFalse(manifest["productionQualified"])
            self.assertEqual(manifest["deterministicMergeSha"], SYNTHETIC)
            self.assertEqual(len(manifest["matrix"]), 8)
            self.assertTrue(all(value is False for value in manifest["externalClaims"].values()))

    def test_missing_lane_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            victim = next((root / "bundles").glob("*macos-aarch64-stable-synthetic-merge"))
            for path in sorted(victim.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            victim.rmdir()
            manifest, complete = build(root, workflow, implementation_map)
            self.assertFalse(complete)
            self.assertFalse(manifest["mergeReady"])
            self.assertTrue(any("missing" in error or "expected" in error for error in manifest["errors"]))

    def test_cross_attempt_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            receipt_path = next((root / "bundles").rglob("qualification.json"))
            receipt = json.loads(receipt_path.read_text())
            receipt["runner"]["GITHUB_RUN_ATTEMPT"] = "2"
            payload = readiness.canonical(receipt)
            receipt_path.write_bytes(payload)
            receipt_path.with_name("qualification.sha256").write_text(digest(payload) + "\n")
            manifest, complete = build(root, workflow, implementation_map)
            self.assertFalse(complete)
            self.assertFalse(manifest["mergeReady"])
            self.assertTrue(any("attempt" in error for error in manifest["errors"]))

    def test_synthetic_merge_identity_must_be_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            runner_path = next(path for path in (root / "bundles").rglob("runner-identity.json")
                               if "linux-aarch64-stable-synthetic-merge" in str(path))
            identity = json.loads(runner_path.read_text())
            identity["candidateSha"] = "a" * 40
            runner_path.write_text(json.dumps(identity, sort_keys=True))
            receipt_path = runner_path.parent.parent / "artifact-evidence" / "qualification.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["testedCommit"] = "a" * 40
            payload = readiness.canonical(receipt)
            receipt_path.write_bytes(payload)
            receipt_path.with_name("qualification.sha256").write_text(digest(payload) + "\n")
            manifest, complete = build(root, workflow, implementation_map)
            self.assertFalse(complete)
            self.assertTrue(any("synthetic merge identity" in error for error in manifest["errors"]))

    def test_incomplete_traceability_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            receipt_path = next((root / "bundles").rglob("qualification.json"))
            receipt = json.loads(receipt_path.read_text())
            receipt["completion"]["requirementTraceabilityComplete"] = False
            payload = readiness.canonical(receipt)
            receipt_path.write_bytes(payload)
            receipt_path.with_name("qualification.sha256").write_text(digest(payload) + "\n")
            manifest, complete = build(root, workflow, implementation_map)
            self.assertFalse(complete)
            self.assertTrue(any("traceability" in error for error in manifest["errors"]))

    def test_workflow_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow, implementation_map = write_fixture(root)
            workflow.write_text("name: changed-after-lane\n")
            manifest, complete = build(root, workflow, implementation_map)
            self.assertFalse(complete)
            self.assertTrue(any("workflow" in error for error in manifest["errors"]))


if __name__ == "__main__":
    unittest.main()
