from copy import deepcopy
import unittest

from .metacontrol_value_gate import digest, evaluate


def plan():
    methods = ["conditional", "light", "fixed"]
    return dict(
        cases={"a0": "a", "a1": "a", "b0": "b"},
        candidate="conditional",
        baselines=methods[1:],
        bounds={m: [0, 1] for m in methods},
        one_off_costs={m: 0 for m in methods},
        margin=0.02,
    )


def rows(p, values):
    return [
        dict(
            case_id=c,
            method=m,
            net_value=v,
            costs_complete=True,
            evidence_kind="measured_terminal",
        )
        for m, vs in values.items()
        for c, v in zip(p["cases"], vs, strict=True)
    ]


class ValueGateTests(unittest.TestCase):
    def gate(self, p, r):
        return evaluate(p, r, expected_plan_sha256=digest(p))

    def test_source_weighting_and_every_baseline(self):
        p = plan()
        r = rows(p, {"conditional": [1, 1, 0], "light": [0, 0, 0], "fixed": [0, 0, 0]})
        result = self.gate(p, r)
        self.assertEqual(result["net_intervals"]["conditional"], [0.5, 0.5])
        self.assertTrue(result["finite_cohort_gate_passed"])
        self.assertFalse(result["adoption_authorized"])
        r[-1]["net_value"] = 1
        self.assertEqual(self.gate(p, r)["decision"], "NoUpdate")

    def test_missing_results_keep_the_planned_denominator(self):
        p = plan()
        r = rows(
            p,
            {
                "conditional": [0.8, None, None],
                "light": [0, 0.9, 0.9],
                "fixed": [0, 0, 0],
            },
        )
        result = self.gate(p, r)
        self.assertLess(result["candidate_minus_baseline"]["light"][0], 0)
        self.assertEqual(
            result["denominators"]["conditional"],
            dict(planned=3, observed_priced=1, unknown=2),
        )
        self.assertEqual(result["decision"], "NoUpdate")
        r = [x for x in r if x["method"] != "conditional"]
        self.assertEqual(self.gate(p, r)["denominators"]["conditional"]["unknown"], 3)

    def test_one_off_and_unknown_costs_are_not_zero(self):
        p = plan()
        r = rows(p, {"conditional": [0.8] * 3, "light": [0.5] * 3, "fixed": [0] * 3})
        p["one_off_costs"]["conditional"] = 0.9
        self.assertEqual(self.gate(p, r)["decision"], "NoUpdate")
        p["one_off_costs"]["conditional"] = None
        self.assertIsNone(self.gate(p, r)["candidate_minus_baseline"]["light"])
        p["one_off_costs"]["conditional"] = 0
        r[0]["costs_complete"] = False
        self.assertEqual(self.gate(p, r)["decision"], "NoUpdate")

    def test_pin_tampering_duplicate_prediction_and_unregistered_case_rejected(self):
        p = plan()
        r = rows(p, {"conditional": [0.8] * 3})
        with self.assertRaises(ValueError):
            evaluate(p, r, expected_plan_sha256="0" * 64)
        for field, value in (
            ("case_id", "unknown"),
            ("evidence_kind", "prediction"),
            ("net_value", 2),
        ):
            changed = deepcopy(r)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                self.gate(p, changed)
        with self.assertRaises(ValueError):
            self.gate(p, r + [r[0]])
