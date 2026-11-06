"""Synthetic arithmetic/admission controls only; zero real R2 observations."""

import copy
import itertools
import json
from pathlib import Path
import unittest

import numpy as np

from check_readiness import readiness
from r2_capture import audit, digest, CATEGORIES, RAW_FIELDS
from r2_statistics import ce, contrasts, crossed_analysis, _weighted_ce, METHODS


ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "PROTOCOL.json").read_bytes())


def fixture():
    """A fabricated, explicitly synthetic format example, never an actual run."""
    seeds = PROTOCOL["analysis"]["fit_seeds"]
    tariffs = {"cpu_second": 0.02, "wall_second": 0.001,
               "services": {"synthetic-format-example": 0.0}}
    design = {"schema": "hepta.r2.panel-design.v1", "protocol_sha256": digest(PROTOCOL),
              "source_clusters": ["SYNTHETIC_cluster_a", "SYNTHETIC_cluster_b"],
              "fit_seeds": seeds, "draws": [0, 1], "methods": list(METHODS),
              "strong_reference": "planner", "cost_unit": "declared_abstract_research_utility",
              "failure_utilities": {s: -1.0 for s in ("failed", "cancelled", "timeout", "incomplete")},
              "abstention_utility": 0.0, "budget_estimand": "same_total_budget",
              "tariff_manifest": tariffs, "tariff_manifest_sha256": digest(tariffs)}
    for key in ("test_seal_sha256", "custody_receipt_sha256", "candidate_manifest_sha256", "validation_selection_sha256"):
        design[key] = digest({"SYNTHETIC_NOT_ACTUAL": key})
    capture = {"schema": "hepta.r2.capture.v1", "design_sha256": digest(design),
               "episodes": [], "outer_event_ids": []}
    events, outcomes = [], []

    def event(event_id, owner, scope, **extra):
        return {"id": event_id, "episode_id": owner, "scope": scope, "status": "not_run",
                "not_run_reason": "synthetic format example, no physical work", "selected": False,
                "metering": "exclusive", "cost_unit": design["cost_unit"], "cost": 0.0,
                "cpu_seconds": 0.0, "wall_seconds": 0.0, "service_fee": 0.0,
                "service_tariff_key": "synthetic-format-example", "service_units": 0.0,
                "raw_measurements": {k: 0.0 for k in RAW_FIELDS}, "unknown_raw_costs": [], **extra}

    for fit, cluster, draw, method in itertools.product(seeds, design["source_clusters"], [0, 1], METHODS):
        eid = f"SYNTHETIC:{fit}:{cluster}:{draw}:{method}"
        ids = [eid + ":" + category for category in sorted(CATEGORIES)]
        capture["episodes"].append({"id": eid, "fit_seed": fit, "source_cluster_id": cluster,
                                    "draw": draw, "method": method, "event_ids": ids})
        for category, event_id in zip(sorted(CATEGORIES), ids, strict=True):
            events.append(event(event_id, eid, "episode", category=category))
        outcomes.append({"id": eid, "status": "completed", "utility": 0.25, "sealed_cost": 0.0,
                         "independent_label_receipt_sha256": digest({"SYNTHETIC_LABEL": eid})})
    for fit, method in itertools.product(seeds, ("00", "10", "01", "11")):
        event_id = f"SYNTHETIC:training:{fit}:{method}"
        capture["outer_event_ids"].append(event_id)
        events.append(event(event_id, None, "training", fit_seed=fit, method=method))
    for scope in ("setup", "analysis", "publication"):
        event_id = "SYNTHETIC:outer:" + scope
        capture["outer_event_ids"].append(event_id)
        events.append(event(event_id, None, scope))
    capture["payload_sha256"] = digest({"events": sorted(events, key=lambda x: x["id"]),
                                         "outcomes": sorted(outcomes, key=lambda x: x["id"])})
    return {"synthetic": True, "design": design, "capture": capture, "events": events, "outcomes": outcomes}


def audited(bundle, *, original_capture=None):
    return audit(bundle, PROTOCOL, design_sha256=digest(bundle["design"]),
                 capture_sha256=digest(original_capture or bundle["capture"]))


class Arithmetic(unittest.TestCase):
    def test_arm_ce_difference_is_not_ce_of_paired_differences(self):
        a, b = np.array([-1.0, 1.0]), np.array([1.0, -1.0])
        self.assertAlmostEqual(ce(a)-ce(b), 0.0)
        self.assertLess(ce(a-b), -1.0)

    def test_weighted_crossed_resampling_equals_explicit_selected_panel(self):
        matrix = np.random.default_rng(13).normal(size=(3, 4, 2, 7))
        fw, cw = np.array([[2, 0, 1]]), np.array([[0, 2, 1, 1]])
        got = _weighted_ce(matrix, fw, cw)[0]
        selected = matrix[[0, 0, 2]][:, [1, 1, 2, 3]]
        np.testing.assert_allclose(got, [ce(selected[..., i]) for i in range(7)], atol=1e-12)

    def test_rare_resample_recenters_when_global_shift_underflows(self):
        matrix = np.full((2, 2, 2, 7), 1000.0)
        matrix[0, 0] = -1000.0
        got = _weighted_ce(matrix, np.array([[0, 2]]), np.array([[0, 2]]))
        np.testing.assert_array_equal(got, np.full((1, 7), 1000.0))

    def test_original_99999_and_seven_contrasts_with_constant_known_effects(self):
        values = np.array([0.0, 0.1, 0.2, 0.5, 0.3, 0.4, 0.15])
        matrix = np.broadcast_to(values, (32, 4, 2, 7)).copy()
        result = crossed_analysis(matrix, "planner")
        expected = contrasts(dict(zip(METHODS, values, strict=True)), "planner")
        self.assertEqual(len(result["contrasts"]), 7)
        self.assertEqual(result["bootstrap"]["replicates"], 99999)
        self.assertEqual(result["bootstrap"]["tail_probability"], 0.05/14)
        for key, point in expected.items():
            self.assertAlmostEqual(result["contrasts"][key], point)
            np.testing.assert_allclose(result["familywise95_bonferroni_percentile_intervals"][key], [point, point], atol=1e-12)


class Accounting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = fixture()

    def test_complete_synthetic_roster_is_arithmetic_only(self):
        matrix, report = audited(self.base)
        self.assertEqual(matrix.shape, (32, 2, 2, 7))
        self.assertEqual(report["episode_count"], 896)
        self.assertFalse(report["custody_and_truth_authenticated_by_this_checker"])
        self.assertTrue(report["no_update"])

    def test_missing_entire_fit_rejects(self):
        b = copy.deepcopy(self.base)
        b["capture"]["episodes"] = [x for x in b["capture"]["episodes"] if x["fit_seed"] != PROTOCOL["analysis"]["fit_seeds"][0]]
        with self.assertRaisesRegex(ValueError, "missing registered episode"):
            audited(b)

    def test_missing_outcome_rejects(self):
        b = copy.deepcopy(self.base)
        b["outcomes"].pop()
        with self.assertRaisesRegex(ValueError, "missing/extra outcome"):
            audited(b)

    def test_unselected_cost_removed_rejects_even_if_outcome_seal_changed(self):
        b = copy.deepcopy(self.base)
        b["events"][0]["status"] = "failed"
        b["events"][0]["cpu_seconds"] = 50.0
        b["events"][0]["cost"] = 1.0
        b["outcomes"][0]["sealed_cost"] = 1.0
        with self.assertRaisesRegex(ValueError, "capture payload changed"):
            audited(b)

    def test_missing_event_rejects(self):
        b = copy.deepcopy(self.base)
        b["events"].pop(0)
        with self.assertRaisesRegex(ValueError, "missing/unregistered captured event"):
            audited(b)

    def test_identical_receipt_deduplicates(self):
        b = copy.deepcopy(self.base)
        b["events"].append(copy.deepcopy(b["events"][0]))
        _, report = audited(b)
        self.assertEqual(report["identical_duplicate_receipts"], 1)

    def test_conflicting_receipt_rejects(self):
        b = copy.deepcopy(self.base)
        altered = copy.deepcopy(b["events"][0]); altered["selected"] = True
        b["events"].append(altered)
        with self.assertRaisesRegex(ValueError, "conflicting physical receipt"):
            audited(b)

    def test_inclusive_leaf_rejects(self):
        b = copy.deepcopy(self.base); b["events"][0]["metering"] = "inclusive"
        with self.assertRaisesRegex(ValueError, "inclusive envelope"):
            audited(b)

    def test_unknown_price_is_not_zero(self):
        b = copy.deepcopy(self.base); b["events"][0]["cost"] = None
        with self.assertRaisesRegex(ValueError, "unknown/nonfinite event cost"):
            audited(b)

    def test_unreported_unknown_energy_rejects(self):
        b = copy.deepcopy(self.base); b["events"][0]["raw_measurements"]["energy_joules"] = None
        with self.assertRaisesRegex(ValueError, "unknown raw cost"):
            audited(b)

    def test_unsealed_reference_rejects(self):
        b = copy.deepcopy(self.base); b["design"]["strong_reference"] = None
        b["capture"]["design_sha256"] = digest(b["design"])
        with self.assertRaisesRegex(ValueError, "reference not sealed"):
            audited(b)


class Readiness(unittest.TestCase):
    def test_actual_six_open_gates_cannot_dispatch(self):
        state = json.loads((ROOT / "READINESS_INPUT.json").read_bytes())
        result = readiness(PROTOCOL, state)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(len(result["open_gates"]), 6)
        self.assertFalse(result["test_dispatch_allowed"])

    def test_self_declared_pass_is_not_custody(self):
        state = json.loads((ROOT / "READINESS_INPUT.json").read_bytes())
        state["actual_gates"]["EVALUATOR_CUSTODY"]["status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "JSON gate cannot grant"):
            readiness(PROTOCOL, state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
