"""Cross-process functional test of owner CAS, validity fencing, and budgets."""

import json
from pathlib import Path
import tempfile
import unittest

from migration import run_functional


class MigrationIntegrationTest(unittest.TestCase):
    def test_real_models_transfer_only_after_cas_and_stale_results_are_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "functional"
            result = run_functional(output)
            self.assertTrue(result["all_checks_passed"], result["checks"])
            self.assertEqual([p["returncode"] for p in result["processes"]], [0, 0])
            self.assertEqual(len({p["pid"] for p in result["processes"]}), 2)
            operations = json.loads((output / "OPERATIONS.json").read_text())
            self.assertEqual(operations["source_initial"]["result"]["output"],
                             operations["target_after_controller_reopen"]["result"]["output"])
            self.assertEqual(operations["prepared"]["result"]["copied_bytes"], result["initial_checkpoint"]["artifact_bytes"])
            self.assertFalse(operations["target_before_cas"]["ok"])
            self.assertFalse(operations["worker_publish_denied"]["ok"])
            for name in ["byte_budget", "wall_budget"]:
                self.assertEqual(operations[name]["details"]["copied_bytes"], 0)
                self.assertFalse(operations[name]["details"]["serving_authorized"])
            for name in ["old_inflight_after_cas", "correction_inflight_rejected", "revocation_inflight_rejected"]:
                self.assertFalse(operations[name]["ok"])
                self.assertTrue(operations[name]["details"]["postcheck_failed"])
                self.assertTrue(operations[name]["details"]["output_discarded"])
                self.assertNotIn("output", operations[name])
            for node, checkpoint in [("source", "initial"), ("target", "corrected")]:
                training = json.loads((output / node / (checkpoint + "-training.json")).read_text())
                self.assertNotEqual(training["fit"]["initial_parameter_sha256"], training["fit"]["final_parameter_sha256"])
                self.assertEqual(training["fit"]["steps"], 80)
                self.assertEqual(training["commit"]["trained_records"], 4)


if __name__ == "__main__":
    unittest.main()
