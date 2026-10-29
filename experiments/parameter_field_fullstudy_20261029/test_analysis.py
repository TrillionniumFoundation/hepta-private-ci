"""Small paired synthetic endpoints only; no model/scientific scoring or disk data."""

from copy import deepcopy
import unittest

import numpy as np

from . import analysis


def protocol():
    statistics = lambda size, seed: {"bootstrap_draws": 8000, "bootstrap_seed": seed,
                                     "formal_family_size_per_observer": size, "family_alpha": .05, "retention_margin": .01}
    b = {"fixed_model_count": 3, "schedule_ids": list(range(106000, 106016)),
         "methods": list(analysis.B_METHODS[:-1]), "statistics": statistics(10, 291029)}
    b["statistics"]["formal_family"] = [e[0] for e in analysis.B_EFFECTS]
    return {"shared_guard48_learning": {"fixed_model_seeds": [17, 29, 43]}, "stage_B": b,
            "stage_C": {"paired_training_seeds": list(range(801, 809)), "statistics": statistics(8, 291030)},
            "task_and_data": {name: {"task_pairs": 3, "clean_pairs": 2} for name in ("fresh_qualification", "fresh_final")}}


def record(seed, schedule, method, role, offset, architecture=None):
    count = 3 if role == "task" else 2
    conditions = analysis.CONDITIONS if role == "task" else ("clean",)
    identities, marks, values = [], [], []
    for pair in range(count):
        for c, condition in enumerate(conditions):
            identities.append([f"{role}:{2 * pair}", f"{role}:{2 * pair + 1}"])
            marks.append(condition)
            values.append(offset + seed * .0001 + pair * .001 + c * .0002)
    values = np.asarray(values)
    result = {"seed": seed, "schedule_id": schedule, "method": method, "role": role,
              "source_ids": identities, "conditions": marks, "values": {"reward": values, "audit": values * .8}}
    if architecture is not None:
        result["architecture"] = architecture
    return result


def b_records(seed_effects=None):
    result = []
    offsets = {"ordinary": .1, "field12": .1, "full_current_state": .07, "history6": .1, "fixed_taper": .12, "frozen": 0.}
    for seed in (17, 29, 43):
        for method in analysis.B_METHODS:
            for schedule in ([None] if method == "frozen" else range(106000, 106016)):
                for role in ("task", "clean"):
                    offset = offsets[method] + ((schedule - 106000) * .0001 if method != "frozen" else 0.)
                    if method == "field12" and seed_effects:
                        offset += seed_effects[seed]
                    row = record(seed, schedule, method, role, offset)
                    row["costs"] = {"cpu_seconds": {"field12": 2., "fixed_taper": .5}.get(method, 1.),
                                    "peak_rss_bytes": 100.}
                    if role == "clean":
                        row["costs"] = {}
                    result.append(row)
    return result


def c_records():
    result = []
    offsets = {("ordinary", "ordinary"): .1, ("ordinary", "field12"): .12,
               ("dual", "ordinary"): .15, ("dual", "field12"): .2,
               ("ordinary", "frozen"): 0., ("dual", "frozen"): 0.}
    for seed in range(801, 809):
        for architecture, method in analysis.C_ARMS:
            for role in ("task", "clean"):
                offset = offsets[architecture, method]
                if role == "clean":
                    offset = 0. if method == "frozen" else (-.02 if (architecture, method) == ("dual", "field12") else -.005)
                result.append(record(seed, None if method == "frozen" else 8000, method, role, offset, architecture))
    return result


class AnalysisTests(unittest.TestCase):
    def test_identical_paired_policies_have_exact_zero_and_keep_negative_effects(self):
        result = analysis.summarize(b_records(), "B", protocol())
        self.assertEqual(len(result["effects"]), 10)
        effect = result["effects"]["field-ordinary task"]
        self.assertEqual(effect["point"], {"reward": 0., "audit": 0.})
        self.assertEqual(effect["ci"], {"reward": [0., 0.], "audit": [0., 0.]})
        self.assertLess(result["effects"]["full-state-field task"]["ci"]["reward"][1], 0)
        self.assertFalse(result["statistical_thresholds"]["field_advantage_thresholds_pass"])
        self.assertEqual(result["costs"]["arms"]["frozen"]["expected_paths"], 3)
        self.assertEqual(result["costs"]["arms"]["field12"]["metrics"]["cpu_seconds"]["sum_over_recorded_paths"], 96.)
        self.assertEqual(result["costs"]["field_minus_taper_descriptive"]["cpu_seconds"]["mean_difference"], 1.5)
        self.assertNotIn("sum_over_recorded_paths", result["costs"]["arms"]["field12"]["metrics"]["peak_rss_bytes"])

    def test_b_does_not_resample_fixed_models(self):
        result = analysis.summarize(b_records({17: .01, 29: -.02, 43: .03}), "B", protocol())
        effect = result["effects"]["field-ordinary task"]
        for value in effect["ci"]["reward"]:
            self.assertAlmostEqual(value, .02 / 3, places=13)
        self.assertLess(effect["per_seed"]["29"]["reward"], 0)
        self.assertFalse(result["statistical_thresholds"]["field_task_deltas_nonnegative_each_fixed_model"])

    def test_c_known_interaction_and_negative_retention_preserved(self):
        result = analysis.summarize(c_records(), "C", protocol())
        effect = result["effects"]["interaction task"]
        self.assertEqual(len(result["effects"]), 8)
        self.assertAlmostEqual(effect["point"]["reward"], .03, places=13)
        for value in effect["ci"]["reward"]:
            self.assertAlmostEqual(value, .03, places=13)
        self.assertTrue(result["statistical_thresholds"]["interaction_positive_both_observers"])
        self.assertFalse(result["statistical_thresholds"]["interaction_and_retention_thresholds_pass"])
        self.assertLess(result["effects"]["dual-field minus warmstart clean"]["ci"]["audit"][1], -.01)

    def test_alignment_is_independent_of_record_and_row_order(self):
        rows = c_records()
        reference = analysis.summarize(rows, "C", protocol())
        for row in rows:
            row["source_ids"].reverse()
            row["conditions"].reverse()
            row["values"] = {k: v[::-1] for k, v in row["values"].items()}
        result = analysis.summarize(rows[::-1], "C", protocol())
        self.assertEqual(result, reference)

    def test_incomplete_nonfinite_unpaired_or_duplicate_frozen_data_fail(self):
        originals = c_records()
        cases = [originals[:-1], originals + [deepcopy(originals[-1])]]
        altered = deepcopy(originals)
        altered[0]["values"]["audit"][0] = np.nan
        cases.append(altered)
        altered = deepcopy(originals)
        altered[0]["source_ids"][0][0] = "unpaired-source"
        cases.append(altered)
        altered = deepcopy(originals)
        altered[0]["schedule_id"] = 99
        cases.append(altered)
        for rows in cases:
            with self.subTest(case=len(rows)), self.assertRaises(ValueError):
                analysis.summarize(rows, "C", protocol())


if __name__ == "__main__":
    unittest.main()
