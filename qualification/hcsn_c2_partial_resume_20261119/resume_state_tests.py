"""Exercise real stored partial state and reject state-losing recovery variants."""

import copy
import json
from pathlib import Path
import unittest

import torch

from resume_state import validate_partial_state
from resources import resource_rejections


HERE = Path(__file__).resolve().parent


class PartialResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = json.loads((HERE / "REQUEST.json").read_text())
        cls.fit = cls.request["fits"][0]
        cls.bound = json.loads((HERE / "BINDINGS.json").read_text())["fits"][cls.fit["name"]]
        cls.state = torch.load(HERE / "evidence/source-input/update-00001757.pt", weights_only=True)
        roster = json.loads((HERE / "evidence/source-input/TRAIN_ROSTER.json").read_text())
        cls.rows = [{"id": row["id"], "y": range(row["events"])} for row in roster["train"]]
        cls.plan = {"batch_size": 32, "micro_batch_size": 8}

    def validate(self, state, bound=None):
        return validate_partial_state(state, self.fit, self.bound if bound is None else bound, self.rows, self.plan)

    def test_real_archived_cursor_restores_without_rng_or_batch_replay(self):
        result = self.validate(copy.deepcopy(self.state))
        self.assertEqual(result, self.state["continuation_cursor"])
        self.assertEqual((result["current_epoch"], result["next_episode_offset"], result["completed_effective_batches"]),
                         (147, 160, 5))
        result["episode_indices"][0] = -1
        self.assertNotEqual(result, self.state["continuation_cursor"])

    def test_missing_adam_is_rejected(self):
        state = copy.deepcopy(self.state)
        del state["optimizer"]
        with self.assertRaisesRegex(ValueError, "complete partial checkpoint"):
            self.validate(state)

    def test_inconsistent_adam_age_is_rejected(self):
        state = copy.deepcopy(self.state)
        next(iter(state["optimizer"]["state"].values()))["step"].add_(1)
        with self.assertRaisesRegex(ValueError, "AdamW moment/age"):
            self.validate(state)

    def test_invalid_cursor_or_lost_objectives_rejected_even_with_matching_binding(self):
        for mutation in ("duplicate_order", "wrong_offset", "lost_objective", "wrong_epoch", "wrong_numerator"):
            with self.subTest(mutation=mutation):
                state, bound = copy.deepcopy(self.state), copy.deepcopy(self.bound)
                cursor = state["continuation_cursor"]
                if mutation == "duplicate_order":
                    cursor["episode_indices"][0] = cursor["episode_indices"][1]
                elif mutation == "wrong_offset":
                    cursor["next_episode_offset"] += 1
                elif mutation == "lost_objective":
                    cursor["completed_batch_objectives"].pop()
                elif mutation == "wrong_epoch":
                    cursor["current_epoch"] += 1
                else:
                    cursor["completed_batch_objectives"][0]["weighted_loss_numerator"] += 1
                bound["partial_cursor"] = copy.deepcopy(cursor)
                with self.assertRaises(ValueError):
                    self.validate(state, bound)

    def test_actual_allocation_and_headroom_fail_closed(self):
        budget = self.request["budget"]
        rows = [{"path": "fixture", "memory.max": str(8 * 1024**3),
                 "memory.current": str(32 * 1024**2), "cpu.max": "100000 100000"}]
        self.assertEqual(resource_rejections(rows, budget), [])
        for key, value in (("memory.max", "max"), ("memory.current", str(2 * 1024**3)),
                           ("cpu.max", "max 100000")):
            changed = copy.deepcopy(rows)
            changed[0][key] = value
            self.assertTrue(resource_rejections(changed, budget))


if __name__ == "__main__":
    unittest.main()
