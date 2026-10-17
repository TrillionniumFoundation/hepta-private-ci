from dataclasses import replace
import unittest
from fabric import Denied, sha
from science_gate import HeldCase, Probability, SealedArm, exact_mcnemar, review, seal


SOURCE = sha(b"original held publisher root")
GOLD = (HeldCase("a", "root1", "t0", 1), HeldCase("b", "root2", "t1", 0),
        HeldCase("c", "root3", "t0", 0), HeldCase("d", "root4", "t1", 1))


def fixture():
    probs = {"no_change": (.1, .9, .9, .1), "split": (.9, .1, .1, .9),
             "type_prior": (.9, .1, .1, .9), "zero_feature": (.9, .1, .1, .9)}
    arms = []
    for name, v in probs.items():
        candidate = SealedArm(name, SOURCE, tuple(Probability(g.case_id, p) for g, p in zip(GOLD, v)),
                              sha(b"unset"), 256 if name == "split" else 0, 0)
        arms.append(replace(candidate, sealed_prediction_sha256=seal(candidate)))
    return tuple(arms)


class GateTests(unittest.TestCase):
    def test_type_prior_reproduces_split_no_false_ability(self):
        r = review(gold=GOLD, arms=fixture(), registered_source_digest=SOURCE, fit_roots=frozenset({"train-root"}))
        self.assertEqual(r["status"], "HOLD_NO_GO")
        self.assertEqual(r["split_vs_type_prior_decision_parity"], 4)
        self.assertEqual(r["split_vs_zero_feature_decision_parity"], 4)
        self.assertFalse(r["learned_representation_effect_verified"])
        self.assertEqual(r["arm_metrics"]["split"]["correct"], 4)

    def test_mcnemar_exact(self):
        self.assertAlmostEqual(exact_mcnemar(12, 8), 0.5034446716308594)
        self.assertEqual(exact_mcnemar(0, 0), 1)

    def test_changed_sealed_probability(self):
        arms = list(fixture())
        bad = list(arms[1].predictions)
        bad[0] = Probability("a", .4)
        arms[1] = replace(arms[1], predictions=tuple(bad))
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=tuple(arms), registered_source_digest=SOURCE, fit_roots=frozenset())

    def test_source_leakage_rejected(self):
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=fixture(), registered_source_digest=SOURCE, fit_roots=frozenset({"root1"}))

    def test_missing_arm_rejected(self):
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=fixture()[:-1], registered_source_digest=SOURCE, fit_roots=frozenset())

    def test_arm_source_swapping_rejected(self):
        arms = list(fixture())
        arms[0] = replace(arms[0], source_digest=sha(b"other"))
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=tuple(arms), registered_source_digest=SOURCE, fit_roots=frozenset())

    def test_zero_feature_nonefinite_rejected(self):
        arms = list(fixture())
        bad = list(arms[-1].predictions)
        bad[1] = Probability("b", float("nan"))
        arms[-1] = replace(arms[-1], predictions=tuple(bad))
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=tuple(arms), registered_source_digest=SOURCE, fit_roots=frozenset())

    def test_predictions_not_held_order_rejected(self):
        arms = list(fixture())
        arms[1] = replace(arms[1], predictions=tuple(reversed(arms[1].predictions)))
        with self.assertRaises(Denied):
            review(gold=GOLD, arms=tuple(arms), registered_source_digest=SOURCE, fit_roots=frozenset())

if __name__ == "__main__":
    unittest.main()
