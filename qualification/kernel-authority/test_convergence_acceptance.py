#!/usr/bin/env python3
"""Regression tests for the kernel.authority convergence projection."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import convergence_acceptance as convergence


class ConvergenceAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = convergence._load_json(convergence.DEFAULT_MANIFEST)

    def test_exact_source_projection_keeps_execution_claims_false(self) -> None:
        value = convergence.project(deepcopy(self.manifest))
        self.assertTrue(value["repositorySourceClosurePassed"])
        self.assertTrue(all(value["sourceChecks"].values()))
        for field in (
            "exactCandidateExecutionProved",
            "ordinaryDeploymentProviderWired",
            "allDeclaredPortsNativelyVerified",
            "targetCollectionExecuted",
            "runtimeOptimizationAuthorized",
            "productionImplementation",
            "productExecutionProved",
            "targetHostQualified",
            "independentAcceptance",
            "activationGranted",
            "releaseGranted",
        ):
            self.assertIs(value[field], False, field)

    def test_repository_manifest_cannot_self_grant_production(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["claimBoundary"]["productionImplementation"] = True
        with self.assertRaisesRegex(convergence.ConvergenceError, "must remain false"):
            convergence.validate_manifest(manifest)

    def test_compatibility_profile_cannot_be_relabelled_as_production(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["closures"]["productionTrustBootstrap"][
            "compatibilityProfileIsProduction"
        ] = True
        with self.assertRaisesRegex(convergence.ConvergenceError, "must remain false"):
            convergence.validate_manifest(manifest)

    def test_target_measurement_cannot_be_claimed_by_source_manifest(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["closures"]["measuredHotPathAndCapacity"][
            "targetCollectionExecuted"
        ] = True
        with self.assertRaisesRegex(convergence.ConvergenceError, "must remain false"):
            convergence.validate_manifest(manifest)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schemaVersion":1,"schemaVersion":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(convergence.ConvergenceError, "duplicate JSON key"):
                convergence._load_json(path)

    def test_projection_cannot_write_into_the_qualified_checkout(self) -> None:
        with self.assertRaisesRegex(convergence.ConvergenceError, "must not mutate"):
            convergence._write_json(
                convergence.ROOT / "qualification/kernel-authority/forbidden-output.json",
                {"never": "written"},
            )

    def test_convergence_projection_does_not_precreate_native_output(self) -> None:
        workflow = (
            convergence.ROOT
            / ".github/workflows/kernel-authority-production-closure.yml"
        ).read_text(encoding="utf-8")
        trust_lane = workflow.split("trust-bundle)", 1)[1].split(";;", 1)[0]
        self.assertIn(
            'convergence="$RUNNER_TEMP/authority-evidence/convergence-projection.json"',
            trust_lane,
        )
        self.assertIn('--output "$convergence"', trust_lane)
        self.assertIn('--output-dir "$output"', trust_lane)
        self.assertNotIn('mkdir -p "$output"', trust_lane)
        self.assertNotIn('--output "$output/', trust_lane)

    def test_target_capacity_never_materializes_candidate_bytes(self) -> None:
        workflow = (
            convergence.ROOT
            / ".github/workflows/kernel-authority-target-capacity.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(workflow.count("uses: actions/checkout@"), 1)
        for forbidden in (
            "Checkout candidate",
            "path: subject",
            "GITHUB_WORKSPACE/subject",
            "ref: ${{ inputs.candidate_sha }}",
            'git -C "$subject"',
        ):
            self.assertNotIn(forbidden, workflow)
        for required in (
            "GITHUB_API_URL: ${{ github.api_url }}",
            "GITHUB_REPOSITORY: ${{ github.repository }}",
            "/git/commits/{candidate_sha}",
            "payload.get(\"sha\") != candidate_sha",
            "candidate identity response did not contain an exact tree",
            'test ! -e "$EVIDENCE_ROOT"',
            "kernel-authority-target-capacity-${{ github.run_id }}-${{ github.run_attempt }}",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
