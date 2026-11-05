"""Synthetic ledger/estimator behavior, not neural efficacy measurements."""

import copy
import itertools
import math
from pathlib import Path
import tempfile
import unittest

from .factorial import ARMS, CATEGORIES, FAILURES, analyze, audit_panel, certainty_equivalent, digest, effects, historical_summary, _read_pinned


def fixture():
    design = {"schema": "hepta.factorial-design.v1", "sources": ["s0", "s1"],
              "training_seeds": [17, 29, 43], "replicates": [0],
              "stratum": {"core": "synthetic", "width": 2}, "cost_unit": "test_tariff",
              "gamma": 2, "training_budget_estimand": "uncontrolled", "failure_utilities": {status: -1.0 for status in FAILURES}}
    capture = {"schema": "hepta.factorial-capture.v1", "design_sha256": digest(design),
               "episodes": [], "outer_event_ids": []}
    rows, events = [], []
    for source, seed, repeat, arm in itertools.product(design["sources"], design["training_seeds"], design["replicates"], ARMS):
        eid = f"{source}:{seed}:{repeat}:{arm}"
        ids = []
        for category in sorted(CATEGORIES):
            event_id = f"{eid}:{category}"
            ids.append(event_id)
            events.append({"id": event_id, "episode_id": eid, "scope": "episode", "category": category,
                           "cost": .01, "status": "completed", "selected": True, "metering": "exclusive"})
        capture["episodes"].append({"id": eid, "source_id": source, "training_seed": seed,
                                    "replicate": repeat, "arm": arm, "event_ids": ids})
        utility = {"00": .4, "10": .45, "01": .55, "11": .7}[arm] + (source == "s1") * .1
        rows.append({"id": eid, "status": "completed", "utility": utility, "sealed_cost": .06})
    for seed, arm in itertools.product(design["training_seeds"], ARMS):
        event_id = f"training:{seed}:{arm}"
        capture["outer_event_ids"].append(event_id)
        events.append({"id": event_id, "episode_id": None, "scope": "training", "category": "optimizer",
                       "training_seed": seed, "arm": arm, "cost": .75, "status": "completed",
                       "selected": True, "metering": "exclusive"})
    bundle = {"design": design, "capture": capture, "rows": rows, "events": events}
    return bundle


def run(bundle, bootstrap=0):
    return analyze(bundle, digest(bundle["design"]), digest(bundle["capture"]), bootstrap)


class FactorialTest(unittest.TestCase):
    def test_paired_four_arm_contrasts_and_crossed_bootstrap(self):
        report = run(fixture(), 200)
        expected = {"controller_on_frozen": .05, "generator_on_fixed": .15,
                    "controller_on_learned": .15, "generator_on_learned_control": .25,
                    "joint_minus_baseline": .3, "interaction": .1}
        for metric in ("ce_effects", "mean_effects"):
            for key, value in expected.items():
                self.assertAlmostEqual(report[metric][key], value)
        for interval in report["bootstrap"]["ce_effect_percentile_95"].values():
            self.assertAlmostEqual(interval[0], interval[1])
        self.assertEqual(report["audit"]["outer_costs_unamortized"], {"training": 9.0})
        self.assertAlmostEqual(report["audit"]["episode_cost"], 24 * .06)
        self.assertFalse(report["confirmation"])

    def test_seed_cluster_resampling_preserves_seed_shocks(self):
        bundle = fixture()
        for row, entry in zip(bundle["rows"], bundle["capture"]["episodes"]):
            if entry["arm"] == "10":
                row["utility"] += (entry["training_seed"] == 43) - .05
        report = run(bundle, 2000)
        lower, upper = report["bootstrap"]["ce_effect_percentile_95"]["controller_on_frozen"]
        # Entire seeds move together: all three draws can select the one +1 seed.
        # Resampling the six source/seed rows independently gives a narrower upper CI.
        self.assertAlmostEqual(lower, 0.)
        self.assertAlmostEqual(upper, 1.)

    def test_ce_subtraction_is_not_ce_of_paired_differences(self):
        a, b = [0., 2.], [2., 0.]
        delta = effects({"00": certainty_equivalent(a), "10": certainty_equivalent(b),
                         "01": 0., "11": 0.})["controller_on_frozen"]
        self.assertEqual(delta, 0.)
        self.assertLess(certainty_equivalent([y - x for x, y in zip(a, b)]), -1.)
        self.assertTrue(math.isfinite(certainty_equivalent([-1000000., 1000000.])))
        self.assertEqual(certainty_equivalent([1., 3.], gamma=0), 2.)

    def test_shared_event_and_identical_receipt_retry_charged_once(self):
        bundle = fixture()
        before = run(bundle)
        event = copy.deepcopy(bundle["events"][0])
        bundle["events"].append(event)
        bundle["capture"]["episodes"][0]["event_ids"].append(event["id"])
        after = run(bundle)
        self.assertEqual(before["ce"], after["ce"])
        self.assertEqual(after["audit"]["duplicate_receipt_retries"], 1)
        bundle["events"][-1]["cost"] += .1
        with self.assertRaisesRegex(ValueError, "conflicting"):
            run(bundle)

    def test_unselected_and_failed_work_is_not_free(self):
        bundle = fixture()
        before = run(bundle)
        row = bundle["rows"][1]
        eid = row["id"]
        event = {"id": eid + ":discarded", "episode_id": eid, "scope": "episode",
                 "category": "generation", "cost": .8, "status": "failed", "selected": False,
                 "metering": "exclusive"}
        bundle["events"].append(event)
        bundle["capture"]["episodes"][1]["event_ids"].append(event["id"])
        row["sealed_cost"] += .8
        after = run(bundle)
        self.assertGreater(before["ce_effects"]["controller_on_frozen"], 0)
        self.assertLess(after["ce_effects"]["controller_on_frozen"], 0)
        self.assertEqual(after["audit"]["candidate_costs"]["unselected"], .8)
        bundle["events"].remove(event)
        row["sealed_cost"] -= .8
        with self.assertRaisesRegex(ValueError, "physical events"):
            run(bundle)

    def test_all_noncompletion_outcomes_preserved(self):
        for status in FAILURES:
            with self.subTest(status=status):
                bundle = fixture()
                row = bundle["rows"][1]
                row.update(status=status, utility=-1.)
                result = run(bundle)
                self.assertEqual(result["audit"]["statuses"][status], 1)
                self.assertLess(result["ce_effects"]["controller_on_frozen"], 0.)
                bundle["rows"].remove(row)
                with self.assertRaisesRegex(ValueError, "missing.*outcomes"):
                    run(bundle)

    def test_capture_and_design_cannot_be_silently_edited(self):
        bundle = fixture()
        original_design, original_capture = digest(bundle["design"]), digest(bundle["capture"])
        bundle["capture"]["episodes"].pop()
        with self.assertRaisesRegex(ValueError, "capture digest"):
            audit_panel(bundle, original_design, original_capture)
        bundle = fixture()
        bundle["design"]["failure_utilities"]["timeout"] = .8
        with self.assertRaisesRegex(ValueError, "design digest"):
            audit_panel(bundle, original_design, original_capture)

    def test_unknown_negative_and_missing_cost_refused(self):
        for bad in (None, -0.1, float("nan"), float("inf"), True):
            with self.subTest(cost=bad):
                bundle = fixture()
                bundle["events"][0]["cost"] = bad
                with self.assertRaises(ValueError):
                    run(bundle)
        bundle = fixture()
        bundle["events"][0]["category"] = "unscoped"
        with self.assertRaisesRegex(ValueError, "category"):
            run(bundle)

    def test_inclusive_double_accounting_and_cross_arm_reuse_refused(self):
        bundle = fixture()
        bundle["events"][0]["metering"] = "inclusive"
        with self.assertRaisesRegex(ValueError, "nested/inclusive"):
            run(bundle)
        bundle = fixture()
        bundle["capture"]["episodes"][1]["event_ids"].append(bundle["events"][0]["id"])
        with self.assertRaisesRegex(ValueError, "cross-episode/arm"):
            run(bundle)
        bundle = fixture()
        bundle["rows"][0]["sealed_cost"] += .01
        with self.assertRaisesRegex(ValueError, "seal/ledger"):
            run(bundle)

    def test_fixed_manifest_panel_cannot_drop_a_seed(self):
        bundle = fixture()
        bundle["capture"]["episodes"] = [e for e in bundle["capture"]["episodes"] if e["training_seed"] != 29]
        with self.assertRaisesRegex(ValueError, "panel"):
            run(bundle)

    def test_historical_summary_preserves_strata_and_claim_scope(self):
        arms = {f"{mode}.{suffix}": {"population_ce_plugin": value, "mean_net_return": value, "failures": 0}
                for mode in ("dual", "ordinary") for suffix, value in
                {"frozen.fixed": .4, "frozen.dynamic": .45, "joint.fixed": .55, "joint.dynamic": .7}.items()}
        matrix = {"schema": "hepta.v3.readable-complete-matrix", "cells": [
            {"seed": seed, "width": width, "arms": copy.deepcopy(arms), "original_result_sha256": "fixture"}
            for seed in (17, 29) for width in (32, 64)]}
        protocol = {"seeds": [17, 29], "widths": [32, 64], "modes": ["dual", "ordinary"]}
        result = historical_summary(matrix, protocol)
        self.assertEqual(len(result["cells"]), 8)
        self.assertFalse(result["raw_trajectory_and_event_audit"])
        self.assertFalse(result["new_confidence_intervals"])
        matrix["cells"].pop()
        with self.assertRaisesRegex(ValueError, "historical.*matrix"):
            historical_summary(matrix, protocol)

    def test_training_cannot_be_shared_or_omitted_as_free(self):
        bundle = fixture()
        bundle["events"][-1]["arm"] = "shared"
        with self.assertRaisesRegex(ValueError, "one arm/seed"):
            run(bundle)
        bundle = fixture()
        event = bundle["events"].pop()
        bundle["capture"]["outer_event_ids"].remove(event["id"])
        with self.assertRaisesRegex(ValueError, "missing training cost cell"):
            run(bundle)

    def test_pinned_bytes_reject_rewritten_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "file SHA"):
                _read_pinned(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
