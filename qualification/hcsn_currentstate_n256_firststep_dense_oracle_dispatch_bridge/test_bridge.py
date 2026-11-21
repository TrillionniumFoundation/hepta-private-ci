"""Static controls for the registered manual-dispatch bridge."""

import json
import unittest
from pathlib import Path


HERE = Path(__file__).parent
WORKFLOW = HERE.parents[1] / ".github/workflows/openbao-compatibility.yml"


class BridgeTest(unittest.TestCase):
    def test_same_key_and_single_attempt_budget(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(request["unique_execution_key"], "hcsn-n256-firststep-dense-oracle-hosted-20261118-c06d-001")
        self.assertEqual((request["prior_numerical_attempt_count"], request["maximum_numerical_attempts"]), (0, 1))
        self.assertEqual(request["manual_dispatch_limit"], 1)

    def test_registered_workflow_has_exact_opt_in(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("hcsn_n256_one_shot", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("github.ref_name == 'research/hcsn-n256-firststep-dense-oracle-dispatch-bridge-20261120-c06d'", workflow)
        self.assertEqual(workflow.count("dense_oracle_hosted.launcher"), 1)

    def test_prior_transports_remain_zero(self):
        observed = json.loads((HERE / "NO_RUN_CHAIN.json").read_text())
        self.assertEqual([item["numerical_attempts"] for item in observed["sources"]], [0, 0])
        self.assertEqual(observed["cumulative_numerical_attempts"], 0)
        self.assertTrue(all(item["dedicated_run_id"] is None for item in observed["sources"]))

    def test_openbao_default_is_preserved(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("if: ${{ !inputs.hcsn_n256_one_shot }}", workflow)
        self.assertIn("python3 scripts/verify_openbao_compatibility.py", workflow)


if __name__ == "__main__":
    unittest.main()
