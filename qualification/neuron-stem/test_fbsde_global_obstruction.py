"""Exact rational tests; no pretrained model or stochastic solver evidence."""
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest

from fbsde_global_obstruction import classify, experiment, experiment_case, local_segment


class ObstructionTests(unittest.TestCase):
    def test_local_unique_yet_no_global_solution(self):
        report = experiment_case(F(1), F(1), F(1), segments=2)
        self.assertEqual(report["boundary_case"], "no_solution")
        self.assertTrue(report["each_short_segment_unique"])
        self.assertEqual(report["reset_final_terminal_residual"], "0")
        self.assertEqual(report["reset_max_y_interface_jump"], "2")
        self.assertEqual(report["reset_path"], [["1", "2", "2"], ["2", "4", "4"]])
        self.assertEqual(report["properly_stitched_path"], [])

    def test_local_unique_yet_infinitely_many_global_solutions(self):
        r = experiment_case(F(0), F(1), F(1), 2)
        self.assertEqual(r["boundary_case"], "nonunique")
        self.assertEqual(r["reset_max_y_interface_jump"], "0")
        self.assertEqual(r["nonunique_global_witnesses"],
                         [["0", "0", "0"], ["0", "1", "1"]])

    def test_correct_global_field_transports_the_terminal_slope(self):
        r = experiment_case(F(1), F(4, 5), F(1), 4)
        self.assertEqual(r["boundary_case"], "unique")
        self.assertEqual(r["analytic_initial_y"], "5")
        self.assertTrue(r["regular_global_field_admitted"])
        self.assertEqual(r["properly_stitched_path"][-1][-1], "5")
        self.assertNotEqual(r["reset_max_y_interface_jump"], "0")

    def test_pole_crossing_unique_boundary_value_is_not_regular_field(self):
        r = experiment_case(F(1), F(3, 2), F(1), 2)
        self.assertEqual(r["boundary_case"], "unique")
        self.assertEqual(r["analytic_initial_y"], "-2")
        self.assertFalse(r["regular_global_field_admitted"])
        self.assertNotEqual(r["reset_max_y_interface_jump"], "0")

    def test_exact_input_admission(self):
        for x, t, g in ((1, F(1), F(1)), (F(1), 1., F(1)),
                        (F(1), F(0), F(1)), (F(1), F(1), F(0))):
            with self.subTest(case=(x, t, g)), self.assertRaises(ValueError):
                classify(x, t, g)
        with self.assertRaises(ValueError):
            local_segment(F(1), F(1), F(1))
        with self.assertRaises(ValueError):
            experiment_case(F(1), F(1), F(1), 1)

    def test_registered_study_profile_publishes_only_research_receipt(self):
        # Integration with the existing FBSDE study dispatcher/owner contract.
        import fbsde_study
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "global-obstruction"
            outcome = fbsde_study.run(path, profile="global_obstruction_v1")
            sealed = json.loads((path / "report.json").read_text())
            self.assertEqual(outcome, sealed)
            self.assertEqual(len(outcome["sources_sha256"]), 2)
            self.assertFalse(outcome["production_accepted"])
            with self.assertRaises(FileExistsError):
                fbsde_study.run(path, profile="global_obstruction_v1")

    def test_complete_scoped_negative_census(self):
        r = experiment()
        self.assertEqual(len(r["cases"]), 4)
        self.assertEqual([v["boundary_case"] for v in r["cases"]],
                         ["unique", "no_solution", "nonunique", "unique"])
        self.assertTrue(all(not v["production_accepted"] for v in r["cases"]))
        self.assertFalse(r["independent_model_efficacy"])


if __name__ == "__main__":
    unittest.main()
