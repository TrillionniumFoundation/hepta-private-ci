#!/usr/bin/env python3
import unittest

from ndu_experiment_runner_contract import RunnerContractError, validate_external_manifest
from ndu_evidence_manifest import build_shadow_manifest


class ExperimentRunnerContractTests(unittest.TestCase):
    def test_shadow_fixture_cannot_be_submitted_as_external_evidence(self):
        with self.assertRaises(RunnerContractError):
            validate_external_manifest(build_shadow_manifest(17))

if __name__ == "__main__":
    unittest.main()
