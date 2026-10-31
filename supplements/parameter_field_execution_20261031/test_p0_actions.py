"""Synthetic arithmetic and evidence-boundary fixtures; no scientific inputs."""

from contextlib import redirect_stdout
import io
import json
import unittest

import numpy as np

import p0_actions as p0


def choice(baseline=2, scores=None, threshold=.375):
    scores = [.5, .25, 0., -.125] if scores is None else scores
    greedy = max(range(4), key=scores.__getitem__)
    tied = scores.count(scores[greedy]) > 1
    active = greedy != baseline and not tied and scores[greedy] > threshold
    return {"predicted_advantages": scores, "chosen_action": greedy if active else baseline,
            "greedy_action": greedy, "predicted_margin": scores[greedy], "threshold": threshold,
            "standardized_norm": 1., "override": active, "certificate": False,
            "fallback_reason": None if active else ("baseline_or_tie" if greedy == baseline or tied else "calibration_gate")}


def a_fixture():
    calibration, differences = [], []
    for seed, baseline in p0.BASELINES.items():
        for schedule in range(6000, 6004):
            for prefix in ("baseline", "balanced"):
                for clock in range(0, 288, 48):
                    parent = f"schedule-{schedule}-{prefix}-step-{clock}"
                    for action in range(4):
                        differences.append({"seed": seed, "parent": parent, "action": action,
                            "baseline": baseline, "same_parent_baseline_reference": True,
                            "guard_accepted": False, "parent_clock": clock, "successor_clock": clock+48,
                            "difference": {"different_components": [], "reference_tail_state_equal": True,
                                **{c: {"l2": 0., "max_abs": 0., "first_different_tensor": None} for c in p0.COMPONENTS}}})
                    if schedule == 6003:
                        for mode in p0.MODES:
                            scores = [.5, .25, -.125, -.125]
                            scores[baseline] = 0.
                            calibration.append({"seed": seed, "mode": mode, "parent": parent,
                                "baseline": baseline, "choice": choice(baseline, scores),
                                "chosen_baseline_aligned_advantage": 0., "gated_selection_regret": .125,
                                "attainable_gain": .125, "chosen_action_is_optimal": False})
    return calibration, differences


def c_fixture():
    rows = []
    advantages = [.125, .25, 0., -.125]
    for seed in p0.C_SEEDS:
        for schedule in range(7000, 7004):
            for prefix in ("baseline", "balanced"):
                for clock in range(0, 96, 16):
                    parent = f"{len(rows)+1:064x}"
                    branches = []
                    for a, v in enumerate(advantages):
                        trace = [{"before": parent if offset == 0 else f"{300+a:064x}",
                            "start": start, "end": start+16, "action": a if offset == 0 else 2,
                            "schedule": schedule, "accepted": True, "clock_advances": True,
                            "after": f"{300+a:064x}"} for offset, start in enumerate(range(clock, 96, 16))]
                        branches.append({"action": a, "terminal_values": [.25+v, .5+v],
                            "terminal_state_sha256": f"{300+a:064x}",
                            "terminal_output_sha256": [f"{200+a:064x}"], "trace": trace})
                    rows.append({"schema": "hepta.fullstudy.C.branch-row.1", "mode": "ordinary",
                        "seed": seed, "schedule": schedule, "prefix": prefix, "clock": clock,
                        "decision": clock//16, "feature": [1.]*12, "advantages": advantages,
                        "fit": schedule != 7003, "calibration": schedule == 7003,
                        "prefix_branch_replay_verified": True, "parent_state_sha256": parent, "branches": branches})
    arrays = {"features": np.ones((96, 12)), "advantages": np.asarray([r["advantages"] for r in rows]),
              "fit": np.asarray([r["fit"] for r in rows]), "calibration": np.asarray([r["calibration"] for r in rows])}
    head = {"baseline": 2, "dimension": 12, "fit_count": 72, "calibration_count": 24, "ridge": 1.}
    return head, arrays, rows


class P0Tests(unittest.TestCase):
    def test_strict_gate_and_exact_tie(self):
        self.assertEqual(p0.validate_choice(choice(threshold=.5), 2), 2)
        self.assertEqual(p0.validate_choice(choice(scores=[.5, .5, 0., -.125]), 2), 2)
        self.assertEqual(p0.validate_choice(choice(), 2), 0)

    def test_nonfinite_wrong_baseline_and_forged_action_reject(self):
        for key, value in (("predicted_margin", float("inf")), ("standardized_norm", float("nan")),
                           ("chosen_action", 1), ("predicted_advantages", [.5, .25, .1, 0.])):
            invalid = choice()
            invalid[key] = value
            with self.assertRaises(ValueError):
                p0.validate_choice(invalid, 2)

    def test_requested_override_is_not_effective_change(self):
        result = p0.a_selected_successors(*a_fixture())
        self.assertEqual(len(result["rows"]), 108)
        for summary in result["summaries"]:
            self.assertEqual((summary["requested_overrides"], summary["accepted_requested_overrides"],
                              summary["requested_overrides_same_physical_successor_as_baseline"]), (12, 0, 12))
        self.assertTrue(all(r["controller_history_comparison_available"] is False for r in result["rows"]))

    def test_a_incomplete_population_and_fabricated_norm_reject(self):
        calibration, differences = a_fixture()
        with self.assertRaises(ValueError):
            p0.a_selected_successors(calibration, differences[:-1])
        next(r for r in differences if r["parent"].startswith("schedule-6003") and r["action"] == 0)["difference"]["parameters"]["l2"] = 1.
        with self.assertRaises(ValueError):
            p0.a_selected_successors(calibration, differences)

    def test_zero_attainable_gain_is_undefined_ratio(self):
        rows = p0.a_selected_successors(*a_fixture())["rows"]
        for row in rows:
            row.update(attainable_gain=0., gated_regret=0., realized_baseline_tail_advantage=0.)
        self.assertIsNone(p0.summarize(rows)["mean_regret_over_mean_attainable_gain"])

    def test_c_24_gated_rows_with_known_regret(self):
        result = p0.c_rows("ordinary", *c_fixture(), lambda *args: (0, choice()), np)
        summary = p0.summarize(result)
        self.assertEqual((len(result), summary["mean_realized_baseline_tail_advantage"],
                          summary["mean_gated_regret"], summary["mean_regret_over_mean_attainable_gain"]),
                         (24, .125, .125, .5))
        self.assertTrue(all(r["component_resolution_available"] is False for r in result))

    def test_c_partition_identity_and_same_successor_contradiction(self):
        for corruption in ("missing", "fit_leak", "baseline", "same_successor", "tail_action"):
            head, arrays, rows = c_fixture()
            if corruption == "missing":
                rows.pop()
            elif corruption == "fit_leak":
                arrays["fit"][0] = False
            elif corruption == "baseline":
                head["baseline"] = 3
            elif corruption == "tail_action":
                rows[0]["branches"][0]["trace"][1]["action"] = 1
            else:
                candidate, baseline = rows[0]["branches"][0], rows[0]["branches"][2]
                for left, right in zip(candidate["trace"], baseline["trace"], strict=True):
                    left["before"], left["after"] = right["before"], right["after"]
                candidate["terminal_state_sha256"] = baseline["terminal_state_sha256"]
            with self.assertRaises(ValueError):
                p0.c_rows("ordinary", head, arrays, rows, lambda *args: (0, choice()), np)

    def test_gate_blocks_before_scientific_input_read(self):
        with self.assertRaises(ValueError):
            p0.analyze({"gate": {"status": "INCOMPLETE"}})
        output = io.StringIO()
        with redirect_stdout(output):
            code = p0.main([])
        self.assertEqual((code, json.loads(output.getvalue())["status"]), (2, "NOT_EVALUATED"))
        self.assertFalse(json.loads(output.getvalue())["scientific_payloads_decoded"])

    def test_json_nonfinite_and_duplicate_keys_reject(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                p0.strict_json(raw)


if __name__ == "__main__":
    unittest.main()
