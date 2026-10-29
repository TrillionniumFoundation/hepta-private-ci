"""Recovery contract tests over retained evidence, with no task execution."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from experiments.first_passage_adaptive.credit_execution import HERE
from experiments.first_passage_adaptive.credit_recovery import InspectionOnlyOwner, expectations, export_account, isolated_probes, read_json, restore_state, uninterrupted_reference
from experiments.first_passage_adaptive.native_execution import canonical, sha


CASE = HERE / "evidence/credit_execution_20261029_v1/run/feedback_enabled"


class RecoveryTests(unittest.TestCase):
    def test_recovery_owner_capability_refuses_execution_before_starting_a_process(self):
        owner = object.__new__(InspectionOnlyOwner)
        owner.execute_attempts, owner.inspection_calls = 0, 0
        with self.assertRaisesRegex(ValueError, "forbids native task execution"):
            owner.invoke(Path("unused"), {}, inspect=False)
        self.assertEqual(owner.execute_attempts, 1)
        self.assertEqual(owner.inspection_calls, 0)

    def test_reconstruction_equals_uninterrupted_live_settlement_reference(self):
        restored, context = restore_state(CASE, expectations(CASE))
        live, response = uninterrupted_reference(CASE)
        self.assertEqual(export_account(restored), export_account(live))
        self.assertEqual(isolated_probes(restored, context["last_response"]), isolated_probes(live, response))

    def test_missing_terminal_settlement_is_not_treated_as_an_earlier_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "case"
            shutil.copytree(CASE, target, ignore=shutil.ignore_patterns("data"))
            (target / "credit/0002.json").unlink()
            with self.assertRaisesRegex(ValueError, "settlement files"):
                restore_state(target, expectations(CASE))

    def test_rehashed_price_corruption_is_rejected_by_accounting_recomputation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "case"
            shutil.copytree(CASE, target, ignore=shutil.ignore_patterns("data"))
            path = target / "credit/0001.json"
            receipt = read_json(path)
            receipt["record"]["price_after"] += 0.01
            receipt["sha256"] = sha(receipt["record"])
            path.write_bytes(canonical(receipt))
            step = read_json(target / "steps/0001.json")
            step["credit_settlement"] = receipt
            (target / "steps/0001.json").write_bytes(canonical(step))
            with self.assertRaisesRegex(ValueError, "arithmetic"):
                restore_state(target, expectations(CASE))

    def test_a_different_expected_terminal_anchor_cannot_be_adopted(self):
        changed = copy.deepcopy(expectations(CASE))
        changed["final_owner_anchor"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "terminal expectation"):
            restore_state(CASE, changed)


if __name__ == "__main__":
    unittest.main()
