"""Focused, independently authored reproduction of PR #2086's P1 parity defect.

Not an execution of the full GitHub test suite or evidence of model quality.
"""
import unittest

PAIRS = {
    "P1": (("shared_learned", "shared_frozen"),
           ("shared_learned", "replicated_learned")),
    "P2": (("split_children", "parent_unsplit"),),
    "P4": (("ndu_solver", "bellman"),),
}


def validate_arm(stage, name, train_steps):
    if not isinstance(train_steps, int) or isinstance(train_steps, bool) or train_steps < 0:
        raise ValueError("invalid train_steps")
    if stage == "P1" and name.endswith("_frozen") and train_steps != 0:
        raise ValueError("frozen Head cannot report optimizer steps")
    if stage == "P1" and name.endswith("_learned") and train_steps == 0:
        raise ValueError("learned Head has no optimizer steps")


def validate_pair(stage, left, right, steps):
    # This truth condition is copied from the proposed source change.
    for name in (left, right):
        validate_arm(stage, name, steps[name])
    match_steps = stage in ("P2", "P4") or (
        stage == "P1" and left.endswith("_learned") == right.endswith("_learned")
    )
    if match_steps and steps[left] != steps[right]:
        raise ValueError("unmatched learning effort in causal comparison")
    return match_steps


class StepParityRepro(unittest.TestCase):
    def test_frozen_vs_learned_is_valid_despite_0_vs_24_steps(self):
        s = dict(shared_learned=24, shared_frozen=0)
        self.assertFalse(validate_pair("P1", "shared_learned", "shared_frozen", s))
        # This confirms the *old* rule rejects the legitimate P1 positive baseline.
        self.assertTrue(24 != 0)

    def test_equal_learned_steps_valid(self):
        s = dict(shared_learned=24, replicated_learned=24)
        self.assertTrue(validate_pair("P1", "shared_learned", "replicated_learned", s))

    def test_unmatched_learned_steps_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmatched learning effort"):
            validate_pair("P1", "shared_learned", "replicated_learned",
                          dict(shared_learned=24, replicated_learned=25))

    def test_frozen_with_positive_steps_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "frozen Head"):
            validate_pair("P1", "shared_learned", "shared_frozen",
                          dict(shared_learned=24, shared_frozen=1))

    def test_learned_zero_steps_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "learned Head"):
            validate_pair("P1", "shared_learned", "shared_frozen",
                          dict(shared_learned=0, shared_frozen=0))

    def test_p2_mismatched_training_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmatched learning effort"):
            validate_pair("P2", "split_children", "parent_unsplit",
                          dict(split_children=24, parent_unsplit=25))

    def test_p4_mismatched_training_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmatched learning effort"):
            validate_pair("P4", "ndu_solver", "bellman",
                          dict(ndu_solver=24, bellman=25))

    def test_untrusted_bool_steps_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            validate_pair("P1", "shared_learned", "shared_frozen",
                          dict(shared_learned=24, shared_frozen=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
