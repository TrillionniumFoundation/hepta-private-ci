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


if __name__ == "__main__":
    unittest.main()
