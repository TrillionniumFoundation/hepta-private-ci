"""Negative controls for finite-tree FBSDE research boundary."""
import copy
import unittest

from fbsde_boundary_audit import InvalidTree, exact_control, solve


def trial():
    return {"source_id": "fixture-not-independent", "root": "root", "nodes": {
        "root": {"kind": "chance", "seen": [], "cost_ppm": 100000, "edges": [
            {"child": "unknown0", "mass_ppm": 700000},
            {"child": "known1", "mass_ppm": 300000}]},
        "unknown0": {"kind": "choice", "seen": ["bit=0"], "cost_ppm": 0,
                     "info_set": "observed-bit-zero", "edges": [
                        {"child": "bad", "action": "stop"},
                        {"child": "both", "action": "verify"}]},
        "known1": {"kind": "choice", "seen": ["bit=1"], "cost_ppm": 0,
                   "info_set": "observed-bit-one", "edges": [
                       {"child": "good", "action": "stop"},
                       {"child": "both1", "action": "verify"}]},
        "bad": {"kind": "terminal", "seen": ["bit=0"], "cost_ppm": 0, "success": False},
        "good": {"kind": "terminal", "seen": ["bit=1"], "cost_ppm": 0, "success": True},
        "both": {"kind": "and", "seen": ["bit=0"], "cost_ppm": 50000, "edges": [
            {"child": "true0"}, {"child": "true1"}]},
        "true0": {"kind": "terminal", "seen": ["bit=0"], "cost_ppm": 0, "success": True},
        "true1": {"kind": "terminal", "seen": ["bit=0"], "cost_ppm": 0, "success": True},
        "both1": {"kind": "terminal", "seen": ["bit=1"], "cost_ppm": 0, "success": False}}}


def policy():
    return {"observed-bit-zero": "verify", "observed-bit-one": "stop"}


class FiniteTreeAuditTests(unittest.TestCase):
    def test_exact_conditional_value_and_martingale(self):
        receipt = solve(trial(), policy())
        self.assertEqual(receipt["root_value"], [835000, 1000000] if False else [167, 200])
        self.assertEqual(receipt["chance_conditions"][0]["backward_residual"], [0, 1])
        self.assertEqual(receipt["chance_conditions"][0]["Z"], [1, 20])
        self.assertFalse(receipt["continuous_fbsde_solved"])

    def test_every_interface_matches_with_global_continuation(self):
        record = solve(trial(), policy())
        values = {k: num / den for k, (num, den) in record["node_values"].items()}
        self.assertTrue(solve(trial(), policy(), interfaces=values)["interface_coverage_complete"])
        values["unknown0"] = 0.0
        with self.assertRaisesRegex(InvalidTree, "discontinuous backward interface"):
            solve(trial(), policy(), interfaces=values)

    def test_missing_interior_interface_fails_closed(self):
        record = solve(trial(), policy())
        values = {k: num / den for k, (num, den) in record["node_values"].items()}
        del values["unknown0"]
        with self.assertRaisesRegex(InvalidTree, "all interfaces"):
            solve(trial(), policy(), interfaces=values)

    def test_finite_exact_control_never_selects_lucky_noise(self):
        reference = exact_control(trial())
        self.assertEqual(reference["enumerated_policies"], 4)
        self.assertEqual(reference["best_policy"], policy())
        self.assertEqual(reference["best_value"], solve(trial(), policy())["root_value"])

    def test_missing_or_future_policy_not_silently_selected(self):
        for selected in ({}, {"observed-bit-zero": "verify"},
                         {"observed-bit-zero": "verify", "observed-bit-one": "unregistered"}):
            with self.subTest(selected=selected), self.assertRaises(InvalidTree):
                solve(trial(), selected)

    def test_and_is_not_or(self):
        bad = trial()
        bad["nodes"]["true1"]["success"] = False
        self.assertEqual(solve(bad, policy())["root_value"], [1, 5])

    def test_wrong_probability_mass_rejected(self):
        bad = trial()
        bad["nodes"]["root"]["edges"][1]["mass_ppm"] = 299999
        with self.assertRaisesRegex(InvalidTree, "mass conservation"):
            solve(bad, policy())

    def test_future_leakage_rejected_on_deterministic_edge(self):
        bad = trial()
        bad["nodes"]["bad"]["seen"].append("future-answer")
        with self.assertRaisesRegex(InvalidTree, "deterministic edge"):
            solve(bad, policy())

    def test_hindsight_choice_violating_information_set_rejected(self):
        bad = trial()
        bad["nodes"]["unknown0"]["info_set"] = "common"
        bad["nodes"]["known1"]["info_set"] = "common"
        with self.assertRaisesRegex(InvalidTree, "information set"):
            solve(bad, {"common": "verify"})

    def test_cycle_rejected_even_when_unselected(self):
        bad = trial()
        bad["nodes"]["unknown0"]["edges"].append({"child": "root", "action": "loop"})
        with self.assertRaises(InvalidTree):
            solve(bad, policy())

    def test_unreachable_node_and_duplicate_chance_event_rejected(self):
        bad = trial()
        bad["nodes"]["unused"] = {"kind": "terminal", "seen": [], "cost_ppm": 0, "success": True}
        with self.assertRaisesRegex(InvalidTree, "unreachable"):
            solve(bad, policy())
        bad = trial()
        bad["nodes"]["known1"]["seen"] = ["bit=0"]
        with self.assertRaises(InvalidTree):
            solve(bad, policy())

    def test_no_gold_labels_or_zero_cost_fiction_are_filled(self):
        bad = trial()
        del bad["nodes"]["good"]["success"]
        with self.assertRaisesRegex(InvalidTree, "node fields"):
            solve(bad, policy())
        bad = trial()
        bad["nodes"]["root"]["cost_ppm"] = -1
        with self.assertRaises(InvalidTree):
            solve(bad, policy())

    def test_source_is_bound_to_exact_bytes_and_finite_numbers(self):
        a, b = trial(), trial()
        b["nodes"]["root"]["cost_ppm"] += 1
        self.assertNotEqual(solve(a, policy())["input_sha256"], solve(b, policy())["input_sha256"])
        receipt = solve(a, policy())
        offered = {k: num / den for k, (num, den) in receipt["node_values"].items()}
        offered["root"] = float("nan")
        with self.assertRaisesRegex(InvalidTree, "nonfinite"):
            solve(a, policy(), interfaces=offered)


if __name__ == "__main__":
    unittest.main()
