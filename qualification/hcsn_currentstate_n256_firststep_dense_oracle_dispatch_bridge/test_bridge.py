"""Static controls for the separately frozen Ubuntu 24.04 repair."""

import json
import unittest
from pathlib import Path


HERE = Path(__file__).parent
WORKFLOW = HERE.parents[1] / ".github/workflows/hepta-contract-gate.yml"
OPENBAO = HERE.parents[1] / ".github/workflows/openbao-compatibility.yml"
HOSTED_WORKFLOW = HERE.parents[1] / ".github/workflows/hcsn-currentstate-n256-firststep-dense-oracle-hosted.yml"
FREEZE_WORKFLOW = HERE.parents[1] / ".github/workflows/hcsn-currentstate-n256-execution-freeze-protocol.yml"


class BridgeTest(unittest.TestCase):
    def test_same_key_and_single_attempt_budget(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(request["unique_execution_key"], "hcsn-n256-firststep-dense-oracle-hosted-20261118-c06d-001")
        self.assertEqual((request["prior_numerical_attempt_count"], request["maximum_numerical_attempts"]), (0, 1))
        self.assertEqual(request["manual_dispatch_limit"], 0)
        self.assertEqual(request["trigger_event"], "push")

    def test_registered_workflow_has_exact_branch_push(self):
        workflow = WORKFLOW.read_text()
        self.assertNotIn("hcsn_n256_one_shot", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.event_name == 'push'", workflow)
        self.assertIn("github.ref_name == 'research/hcsn-n256-firststep-dense-oracle-ubuntu24-repair-20261120-c06d'", workflow)
        self.assertEqual(workflow.count("dense_oracle_hosted.launcher"), 1)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 2)
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("python-version: 3.12.3", workflow)

    def test_prior_transports_remain_zero(self):
        observed = json.loads((HERE / "NO_RUN_CHAIN.json").read_text())
        self.assertEqual([item["numerical_attempts"] for item in observed["sources"]], [0, 0])
        self.assertEqual(observed["cumulative_numerical_attempts"], 0)
        self.assertTrue(all(item["dedicated_run_id"] is None for item in observed["sources"]))

    def test_contract_default_is_preserved(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("if: ${{ github.ref_name != 'research/hcsn-n256-firststep-dense-oracle-ubuntu24-repair-20261120-c06d' }}", workflow)
        self.assertIn("python3 scripts/hepta-docs.py verify --profile", workflow)

    def test_openbao_is_restored(self):
        workflow = OPENBAO.read_text()
        self.assertNotIn("hcsn-n256-one-shot", workflow)
        self.assertIn("python3 scripts/verify_openbao_compatibility.py", workflow)

    def test_first_dispatch_rejection_is_zero_run(self):
        rejected = json.loads((HERE / "DISPATCH_001_REJECTION.json").read_text())
        self.assertEqual((rejected["github_http_status"], rejected["h_exit_code"]), (422, 1))
        self.assertIsNone(rejected["actions_run_id"])
        self.assertEqual((rejected["dynamic_steps"], rejected["dense_expm_actions"]), (0, 0))

    def test_second_dispatch_rejection_is_zero_run(self):
        rejected = json.loads((HERE / "DISPATCH_002_REJECTION.json").read_text())
        self.assertEqual((rejected["github_http_status"], rejected["h_exit_code"]), (422, 1))
        self.assertIsNone(rejected["actions_run_id"])
        self.assertEqual((rejected["dynamic_steps"], rejected["dense_expm_actions"]), (0, 0))

    def test_third_dispatch_rejection_is_zero_run(self):
        rejected = json.loads((HERE / "DISPATCH_003_REJECTION.json").read_text())
        self.assertEqual((rejected["github_http_status"], rejected["h_exit_code"]), (422, 1))
        self.assertIsNone(rejected["actions_run_id"])
        self.assertEqual((rejected["dynamic_steps"], rejected["dense_expm_actions"]), (0, 0))

    def test_push_admission_rejections_are_zero_job(self):
        names = ("PUSH_CONTRACT_REJECTION.json", "PUSH_HOSTED_REJECTION.json", "PUSH_FREEZE_REJECTION.json")
        rows = [json.loads((HERE / name).read_text()) for name in names]
        self.assertEqual({row["actions_run_id"] for row in rows}, {44846825298, 44846823906, 44846822585})
        self.assertTrue(all(row["conclusion"] == "failure" for row in rows))
        self.assertTrue(all(row["actions_job_count"] == row["artifact_count"] == 0 for row in rows))
        self.assertTrue(all(row["dynamic_steps"] == row["dense_expm_actions"] == 0 for row in rows))

    def test_python_runtime_rejection_is_zero_numerical(self):
        rejected = json.loads((HERE / "PUSH_PYTHON_REJECTION.json").read_text())
        self.assertEqual((rejected["actions_run_id"], rejected["actions_job_id"]), (44847784583, 136671635724))
        self.assertTrue(rejected["checkout_completed"])
        self.assertFalse(rejected["setup_python_completed"])
        self.assertFalse(rejected["launcher_completed"])
        self.assertEqual(rejected["artifact_count"], 0)
        self.assertEqual((rejected["dynamic_steps"], rejected["dense_expm_actions"], rejected["optimizer_steps"]), (0, 0, 0))

    def test_exact_python_is_available_on_explicit_runner(self):
        available = json.loads((HERE / "PYTHON_RUNTIME_AVAILABILITY.json").read_text())
        self.assertEqual((available["python_version"], available["selected_runner"]), ("3.12.3", "ubuntu-24.04"))
        self.assertEqual(available["selected_file"], "python-3.12.3-linux-24.04-x64.tar.gz")
        self.assertTrue(available["selected_file_available"])
        self.assertFalse(available["rejected_matching_file_available"])
        self.assertFalse(available["runtime_execution"])

    def test_install_commands_are_valid_folded_scalars(self):
        invalid = "run: python -m pip install --only-binary=:all: -r"
        for path in (WORKFLOW, HOSTED_WORKFLOW, FREEZE_WORKFLOW):
            text = path.read_text()
            self.assertNotIn(invalid, text)
            self.assertIn("run: >-", text)
            self.assertIn("python -m pip install --only-binary=:all: -r", text)

    def test_contract_uses_repair_verifier_only(self):
        workflow = WORKFLOW.read_text()
        self.assertEqual(workflow.count("dispatch_bridge.verify_source"), 1)
        self.assertNotIn("registered_bridge.verify_source", workflow)
        self.assertNotIn("dense_oracle_hosted.verify_source", workflow)


if __name__ == "__main__":
    unittest.main()
