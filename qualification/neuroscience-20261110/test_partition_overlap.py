"""Fail closed on across-row A/B task overlap; synthetic declarations only."""
import unittest
from dataclasses import replace
from factorial import ContractError, evaluate_core_ndu
from test_factorial import panel, required, h

class PartitionTaskOverlapTests(unittest.TestCase):
    def test_other_seed_training_task_cannot_be_future_eval_task(self):
        rows = panel(seeds=2, densities=("sparse",))
        future_of_seed_zero = rows[0].workload_digest
        changed = [replace(r, source_task_digest=future_of_seed_zero)
                   if r.seed == 1 else r for r in rows]
        with self.assertRaisesRegex(ContractError, "training/evaluation task"):
            evaluate_core_ndu(changed, required_cells=required(("sparse",)))

    def test_other_episode_training_task_cannot_be_future_eval_task(self):
        rows = panel(seeds=1, densities=("sparse",), episodes=("ep0","ep1"))
        future_of_ep_zero = rows[0].workload_digest
        changed = [replace(r, source_task_digest=future_of_ep_zero)
                   if r.episode_id == "ep1" else r for r in rows]
        with self.assertRaisesRegex(ContractError, "training/evaluation task"):
            evaluate_core_ndu(changed, required_cells=required(("sparse",)))

    def test_valid_shared_training_task_and_four_arm_repeats_remain_legal(self):
        rows = panel(seeds=2, densities=("sparse",), episodes=("ep0","ep1"))
        changed = [replace(r,source_task_digest=h("shared-training-task-A"))
                   for r in rows]
        result = evaluate_core_ndu(changed, required_cells=required(("sparse",)))
        self.assertEqual(result["coverage"]["matched_blocks"], 4)
        self.assertEqual(result["authority"], "DENY_ALL")

if __name__ == "__main__":
    unittest.main()
