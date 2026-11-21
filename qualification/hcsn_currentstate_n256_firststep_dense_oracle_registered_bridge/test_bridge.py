"""Static controls for the registered execution bridge."""

import json
import unittest
from pathlib import Path


HERE = Path(__file__).parent
WORKFLOW = HERE.parents[1] / ".github/workflows/hcsn-currentstate-n256-execution-freeze-protocol.yml"


class BridgeTest(unittest.TestCase):
    def test_same_key_and_one_attempt(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(request["unique_execution_key"], "hcsn-n256-firststep-dense-oracle-hosted-20261118-c06d-001")
        self.assertEqual((request["prior_numerical_attempt_count"], request["maximum_numerical_attempts"]), (0, 1))

    def test_branch_guard_and_no_manual_numerical_path(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("github.event_name == 'pull_request'", workflow)
        self.assertIn("github.head_ref == 'research/hcsn-n256-firststep-dense-oracle-registered-bridge-20261120-c06d'", workflow)
        self.assertEqual(workflow.count("dense_oracle_hosted.launcher"), 1)
        self.assertIn("cancel-in-progress: false", workflow)

    def test_no_run_observation_stays_zero(self):
        observed = json.loads((HERE / "NO_RUN_OBSERVATION.json").read_text())
        self.assertIsNone(observed["dedicated_one_shot_run_id"])
        self.assertEqual({name: observed[name] for name in (
            "n256_input_reads", "n256_serializer_calls", "dynamic_steps",
            "dense_expm_actions", "torch_calls", "optimizer_steps",
        )}, {name: 0 for name in (
            "n256_input_reads", "n256_serializer_calls", "dynamic_steps",
            "dense_expm_actions", "torch_calls", "optimizer_steps",
        )})


if __name__ == "__main__":
    unittest.main()
