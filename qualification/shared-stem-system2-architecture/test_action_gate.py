"""Adversarial numeric control tests: mechanism only, no learned efficacy."""
import unittest
from dataclasses import replace
from action_gate import Candidate, choose, q

SHA = "1" * 64


def c(name, lo, hi, cost="0", feasible=True, sufficient=True, qualified=True):
    return Candidate(name, lo, hi, (("complete_work", cost),), feasible,
                     sufficient, qualified, SHA)


class ActionGateTest(unittest.TestCase):
    def test_dominant_after_cost(self):
        d = choose([c("ABSTAIN", "3", "3"), c("SOLVE", "7", "8", "1")])
        self.assertEqual((d.status, d.selected_action, d.lower_gap),
                         ("SELECT", "SOLVE", "3"))
        self.assertFalse(d.model_efficacy_measured)
        self.assertEqual(d.evaluator_authority, "DENY_ALL")

    def test_exact_solver_too_expensive(self):
        self.assertEqual(choose([c("ABSTAIN", "3", "3"),
                                 c("FBSDE", "7", "8", "6")]).selected_action, "ABSTAIN")

    def test_ambiguous_gap_stays_no_go(self):
        for lo, hi in [("2", "4"), ("3", "3"), ("1", "5")]:
            with self.subTest(lo=lo, hi=hi):
                self.assertEqual(choose([c("ABSTAIN", "3", "3"),
                                         c("SOLVE", lo, hi)]).status, "NO_GO")

    def test_missing_feasible_candidate_evidence(self):
        for bad in [c("UNKNOWN", "9", "9", qualified=False),
                    c("UNKNOWN", "9", "9", sufficient=False)]:
            self.assertEqual(
                choose([c("ABSTAIN", "3", "3"), c("SOLVE", "9", "9"), bad]).reason,
                "missing_or_unqualified_feasible_candidate",
            )

    def test_hard_feasibility_precedes_utility(self):
        d = choose([c("ABSTAIN", "3", "3"), c("BAD", "100", "100", feasible=False),
                    c("VALID", "5", "5")])
        self.assertEqual(d.selected_action, "VALID")

    def test_complete_cost_axes_charged(self):
        solve = Candidate("SOLVE", "10", "10",
                          (("cpu", "4"), ("token", "3"), ("verifier", "2")),
                          True, True, True, SHA)
        d = choose([c("ABSTAIN", "3", "3"), solve])
        self.assertEqual(d.selected_action, "ABSTAIN")
        self.assertEqual(d.complete_cost_lines, 4)

    def test_strict_margin(self):
        self.assertEqual(choose([c("ABSTAIN", "3", "3"),
                                 c("SOLVE", "5", "5")], minimum_margin="2").status, "NO_GO")

    def test_untrusted_and_invalid_reject(self):
        bad = [
            replace(c("SOLVE", "5", "5"), source_sha256="A" * 64),
            replace(c("SOLVE", "5", "5"), utility_lo="nan"),
            replace(c("SOLVE", "5", "5"), utility_hi="4"),
            replace(c("SOLVE", "5", "5"), qualified_bounds=1),
            replace(c("SOLVE", "5", "5"), costs=(("cpu", "1"), ("cpu", "2"))),
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                choose([c("ABSTAIN", "3", "3"), item])

    def test_missing_baseline_and_duplicate(self):
        for rows in [[c("SOLVE", "1", "1")], [c("ABSTAIN", "1", "1")] * 2,
                     [c("ABSTAIN", "1", "1")] * 129]:
            with self.assertRaises(ValueError):
                choose(rows)

    def test_canonical_rationals(self):
        for value in ("-1", "+1", "1.0", "01", "2/4", "0/1", "1/0",
                      "NaN", "1e5", "9" * 70):
            with self.subTest(value=value), self.assertRaises(ValueError):
                q(value)

    def test_invalid_baseline(self):
        with self.assertRaises(ValueError):
            choose([c("ABSTAIN", "1", "1", feasible=False)])

    def test_exact_fraction_gap(self):
        d = choose([c("ABSTAIN", "1/3", "1/3"), c("SOLVE", "2/3", "2/3")])
        self.assertEqual(d.lower_gap, "1/3")


if __name__ == "__main__":
    unittest.main()
