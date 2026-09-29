from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-objective-evidence-project.py"
SOURCE = "1" * 40
TREE = "2" * 40
LOG = "3" * 64


def current_state() -> dict:
    return {
        "schema": "hepta.objective-compiler-current-state.v2",
        "schemaVersion": 2,
        "module": "objective.compiler",
        "implementationState": {
            "core": "source_complete",
            "productComposition": "source_composed_durable_proof_bound_not_activated",
            "semanticHardening": "source_complete_pending_exact_candidate_receipts",
            "qualificationEvidence": "dynamic_receipt_projection_required",
            "independentAcceptance": "external_receipt_required",
            "canaryPromotionRollback": "source_policy_not_activated",
        },
        "truth": {
            "productionImplementation": False,
            "accepted": False,
            "activated": False,
            "released": False,
        },
        "evidenceProjection": {
            "schema": "hepta.objective-evidence-projection.v2",
            "producer": "scripts/hepta-objective-evidence-project.py",
            "dynamicClaims": [
                "sourceHeadQualification",
                "syntheticMergeQualification",
                "targetHostMeasurement",
            ],
            "manualPassFieldsForbidden": True,
        },
        "requiredChecks": ["source", "merge"],
        "externalGates": ["independent acceptance"],
    }


def candidate(kind: str, exit_code: int = 0) -> dict:
    return {
        "kind": kind,
        "clean": True,
        "checks": [
            {
                "name": "test",
                "status": "completed",
                "exitCode": exit_code,
                "logSha256": LOG,
            }
        ],
    }


def resources() -> dict:
    return {
        "schema": "hepta.objective-command-resource-observation.v1",
        "scope": "one isolated fixture command process tree",
        "peakResidentSetBytes": 4096,
        "userCpuNanoseconds": 10,
        "systemCpuNanoseconds": 5,
        "wallNanoseconds": 20,
        "minorPageFaults": 1,
        "majorPageFaults": 0,
        "voluntaryContextSwitches": 1,
        "involuntaryContextSwitches": 0,
    }


def native_fixture() -> dict:
    return {
        "schema": "hepta.objective-native-fixture.v1",
        "sourceCommit": SOURCE, "sourceTree": TREE,
        "exitCode": 0, "artifactsUnchangedAfterExecution": True,
        "buildCostsExcludedFromFixtureResources": True,
        "nativeFfiQualificationProved": False,
        "cargoArtifactMessagesSha256": LOG, "testListSha256": LOG,
        "executionOutputSha256": LOG,
        "artifacts": [{"path": "/fixture/test", "sha256": LOG, "sizeBytes": 42}],
        "executable": "/fixture/test", "testName": "module::measurement",
        "executionCommand": ["/fixture/test", "module::measurement", "--ignored", "--exact", "--nocapture", "--test-threads=1"],
        "buildCommand": ["cargo", "test", "--locked", "--release", "--no-run"],
    }


def target_receipt() -> dict:
    paths = (
        "ordinary_authenticated_admission_compile",
        "maximum_conflict_extraction",
        "signed_objective_daemon_round_trip",
    )
    return {
        "schema": "hepta.objective-target-host-evidence.v2",
        "sourceCommit": SOURCE,
        "sourceTree": TREE,
        "workflowRunId": "18",
        "workflowRunAttempt": "1",
        "workflowCommit": "4" * 40,
        "workflowRef": "workflow@refs/heads/test",
        "hostProfileId": "ci-host",
        "measurements": [
            {"path": path, "fixtureProcessResources": resources(), "nativeFixture": native_fixture()} for path in paths
        ],
        "interpretation": {
            "fixtureResourcesIsolatedByFreshHelperProcess": True,
            "buildCostsExcludedFromFixtureResources": True,
            "nativeArtifactsBoundBeforeAndAfterExecution": True,
            "nativeFfiQualificationProved": False,
            "memoryIsNotPerInternalPhaseAllocation": True,
            "dynamicAuthorizationCachingAllowed": False,
            "atomicAppendCheckpointHandoffBoundaryPreserved": True,
        },
    }


class EvidenceProjectionTest(unittest.TestCase):
    def run_projection(
        self,
        exact: dict | None,
        target: dict | None,
        state: dict | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict | None, bytes]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_value = current_state() if state is None else state
            state_bytes = (json.dumps(state_value) + "\n").encode()
            (root / "state.json").write_bytes(state_bytes)
            argv = [
                sys.executable,
                str(SCRIPT),
                "--source-commit",
                SOURCE,
                "--source-tree",
                TREE,
                "--current-state",
                str(root / "state.json"),
                "--output",
                str(root / "projection.json"),
            ]
            if exact is not None:
                (root / "exact.json").write_text(json.dumps(exact), encoding="utf-8")
                argv += ["--exact-execution", str(root / "exact.json")]
            if target is not None:
                (root / "target.json").write_text(json.dumps(target), encoding="utf-8")
                argv += ["--target-measurement", str(root / "target.json")]
            completed = subprocess.run(argv, text=True, capture_output=True)
            output = root / "projection.json"
            return (
                completed,
                json.loads(output.read_text()) if output.exists() else None,
                state_bytes,
            )

    def test_projects_receipts_without_promoting_acceptance(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "runId": "17",
            "runAttempt": "1",
            "workflowCommit": "4" * 40,
            "workflowRef": "workflow@refs/heads/test",
            "candidates": [candidate("source-head"), candidate("synthetic-merge")],
            "checksPassed": True,
            "errors": [],
        }
        completed, value, state_bytes = self.run_projection(exact, target_receipt())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["status"]["sourceHeadQualification"], "passed")
        self.assertEqual(value["status"]["syntheticMergeQualification"], "passed")
        self.assertEqual(value["status"]["targetHostMeasurement"], "observed")
        self.assertEqual(
            value["executionEvidence"]["targetHostMeasurement"]["runId"], "18"
        )
        self.assertEqual(
            value["sourceState"]["artifactSha256"],
            hashlib.sha256(state_bytes).hexdigest(),
        )
        self.assertEqual(
            value["truth"],
            {
                "productionImplementation": False,
                "accepted": False,
                "activated": False,
                "released": False,
            },
        )

    def test_incomplete_candidate_is_failed_not_passed(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "candidates": [candidate("source-head", 1)],
            "checksPassed": False,
            "errors": ["observed failure"],
        }
        completed, value, _ = self.run_projection(exact, None)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["status"]["sourceHeadQualification"], "failed")
        self.assertEqual(value["status"]["syntheticMergeQualification"], "failed")
        self.assertFalse(
            value["executionEvidence"]["exactExecution"]["checksPassed"]
        )

    def test_checks_passed_cannot_disagree_with_observed_checks(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "candidates": [candidate("source-head"), candidate("synthetic-merge")],
            "checksPassed": False,
            "errors": [],
        }
        completed, value, _ = self.run_projection(exact, None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)

    def test_source_identity_mismatch_refuses_projection(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": "9" * 40,
            "sourceTree": TREE,
            "candidates": [],
            "checksPassed": False,
            "errors": [],
        }
        completed, value, _ = self.run_projection(exact, None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)

    def test_static_manifest_cannot_embed_dynamic_pass_fields(self) -> None:
        state = current_state()
        state["implementationState"]["currentHeadQualification"] = "passed"
        completed, value, _ = self.run_projection(None, target_receipt(), state)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)

    def test_target_receipt_requires_all_workloads_and_isolated_resources(self) -> None:
        target = target_receipt()
        target["measurements"].pop()
        completed, value, _ = self.run_projection(None, target)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)

        target = target_receipt()
        del target["measurements"][0]["fixtureProcessResources"]
        completed, value, _ = self.run_projection(None, target)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)

    def test_native_evidence_rejects_wrong_source_missing_digest_and_build_in_sample(self) -> None:
        for field, invalid in (
            ("sourceCommit", "9" * 40), ("sourceTree", "9" * 40),
            ("exitCode", True), ("exitCode", 1), ("artifacts", []),
            ("executionOutputSha256", "missing"), ("artifactsUnchangedAfterExecution", False),
            ("buildCostsExcludedFromFixtureResources", False), ("nativeFfiQualificationProved", True),
            ("executionCommand", ["cargo", "test"]), ("buildCommand", ["cargo", "test"]),
        ):
            target = target_receipt()
            target["measurements"][0]["nativeFixture"][field] = invalid
            completed, value, _ = self.run_projection(None, target)
            with self.subTest(field=field, invalid=invalid):
                self.assertNotEqual(completed.returncode, 0)
                self.assertIsNone(value)
        for legacy in (True, False):
            target = target_receipt()
            if legacy:
                target["schema"] = "hepta.objective-target-host-evidence.v1"
            else:
                del target["measurements"][0]["nativeFixture"]
            completed, value, _ = self.run_projection(None, target)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIsNone(value)

    def test_current_state_truth_cannot_promote_release(self) -> None:
        state = copy.deepcopy(current_state())
        state["truth"]["released"] = True
        completed, value, _ = self.run_projection(None, target_receipt(), state)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
