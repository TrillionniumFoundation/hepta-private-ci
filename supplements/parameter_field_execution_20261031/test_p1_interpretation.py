"""Synthetic paired endpoints exercise interpretation of the original analysis."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

import numpy as np

from experiments.parameter_field_fullstudy_20261029 import analysis
from supplements.parameter_field_execution_20261031 import p1_interpretation as interpretation


def c_fixture(dual_increment=-.02, ordinary_increment=-.04, retention=-.005):
    # Counts below are only for bounded synthetic tests, never a scientific plan.
    protocol = json.loads(Path(analysis.__file__).with_name("PROTOCOL.json").read_text())
    protocol["task_and_data"]["fresh_final"].update(task_pairs=2, clean_pairs=2)
    records = []
    for seed in range(801, 809):
        for architecture, method in analysis.C_ARMS:
            for role in ("task", "clean"):
                conditions = analysis.CONDITIONS if role == "task" else ("clean",)
                pairs, marks, values = [], [], []
                increment = dual_increment if architecture == "dual" else ordinary_increment
                for pair in range(2):
                    for index, condition in enumerate(conditions):
                        # Large shared seed/pair terms cancel only when pairing is correct.
                        offset = (seed - 800) * 2. + pair + index * .03
                        if role == "task":
                            offset += .3 if architecture == "dual" else .2
                            offset += increment if method == "field12" else 0.
                        elif method != "frozen":
                            offset += retention
                        pairs.append([f"{role}-{pair}-0", f"{role}-{pair}-1"])
                        marks.append(condition)
                        values.append(offset)
                records.append({
                    "seed": seed, "schedule_id": None if method == "frozen" else 8000,
                    "architecture": architecture, "method": method, "role": role,
                    "source_ids": pairs, "conditions": marks,
                    "values": {"reward": np.asarray(values), "audit": np.asarray(values) * .8},
                })
    return protocol, records


PASSED_CONTEXT = {"integrity": {"status": "passed", "scope": "synthetic fixture only"}}


class InterpretationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol, cls.records = c_fixture()
        cls.formal = analysis.summarize(cls.records, "C", cls.protocol)

    def interpret(self, formal=None, context=None):
        return interpretation.interpret("C", self.formal if formal is None else formal,
                                        evidence_context=PASSED_CONTEXT if context is None else context)

    def test_positive_interaction_with_negative_simple_effects_is_only_less_harm(self):
        before = deepcopy(self.formal)
        result = self.interpret()
        self.assertEqual(self.formal, before)
        self.assertTrue(result["registered_statistical_thresholds"]["interaction_and_retention_thresholds_pass"])
        self.assertEqual(result["statistical_relationship"],
                         "positive_interaction_with_two_negative_simple_effects_less_harm")
        self.assertEqual(result["effects"]["dual field increment task"]["status"],
                         "below_threshold_both_observers")
        self.assertAlmostEqual(self.formal["effects"]["interaction task"]["point"]["reward"], .02)
        self.assertEqual((result["adoption"], result["unconditional_net_benefit"]),
                         ("not_assessed", "not_assessed"))

    def test_pairing_and_record_order_do_not_change_interpretation(self):
        records = deepcopy(self.records)
        for row in records:
            row["source_ids"].reverse()
            row["conditions"].reverse()
            row["values"] = {key: value[::-1] for key, value in row["values"].items()}
        reordered = analysis.summarize(records[::-1], "C", self.protocol)
        self.assertEqual(self.interpret(reordered), self.interpret())
        records[0]["source_ids"][0][0] = "unpaired"
        with self.assertRaises(ValueError):
            analysis.summarize(records, "C", self.protocol)

    def test_positive_dual_and_interaction_are_distinct_from_retention(self):
        protocol, records = c_fixture(.04, .01, -.02)
        formal = analysis.summarize(records, "C", protocol)
        result = self.interpret(formal)
        self.assertEqual(result["statistical_relationship"], "positive_interaction_and_positive_dual_increment")
        self.assertFalse(result["registered_statistical_thresholds"]["interaction_and_retention_thresholds_pass"])
        self.assertEqual(result["effects"]["dual-field minus warmstart clean"]["status"],
                         "below_threshold_both_observers")

    def test_inconclusive_missing_negative_and_observer_conflict_are_separate(self):
        cases = [([-.01, .01], "inconclusive"), ([0., 0.], "inconclusive"),
                 ([-.1, -.01], "below_threshold_both_observers")]
        for interval, expected in cases:
            formal = deepcopy(self.formal)
            formal["effects"]["dual field increment task"]["ci"] = {o: interval for o in analysis.OBSERVERS}
            with self.subTest(interval=interval):
                self.assertEqual(self.interpret(formal)["effects"]["dual field increment task"]["status"], expected)
        formal = deepcopy(self.formal)
        formal["effects"]["dual field increment task"]["ci"]["audit"] = [.01, .1]
        self.assertEqual(self.interpret(formal)["effects"]["dual field increment task"]["status"], "observer_conflict")
        formal["effects"]["dual field increment task"]["ci"].pop("audit")
        output = self.interpret(formal)
        self.assertEqual((output["effects"]["dual field increment task"]["status"], output["status"]),
                         ("missing", "incomplete_analysis"))
        self.assertEqual(interpretation.interpret("C")["status"], "missing_analysis")

    def test_unknown_or_failed_integrity_activity_and_cost_are_not_inferred(self):
        unknown = interpretation.interpret("C", self.formal)
        self.assertEqual(unknown["status"], "integrity_not_established")
        context = {
            "integrity": {"status": "failed", "scope": "synthetic checksum failure"},
            "activity": {"status": "whole_state_change_only", "scope": "C calibration, not deployment"},
            "cost_coverage": {"status": "partial", "scope": "historical campaign CPU unknown"},
        }
        output = self.interpret(context=context)
        self.assertEqual(output["evidence_context"], context)
        self.assertEqual(output["status"], "integrity_blocked")
        self.assertEqual(output["adoption"], "not_assessed")
        self.assertEqual(self.interpret()["evidence_context"]["activity"]["status"], "unknown")

    def test_wrong_family_seed_or_nonfinite_interval_refuses(self):
        for kind in ("family", "seed", "nonfinite"):
            formal = deepcopy(self.formal)
            if kind == "family":
                formal["formal_family"].reverse()
            elif kind == "seed":
                formal["seeds"] = list(range(801, 808))
            else:
                formal["effects"]["interaction task"]["ci"]["reward"][0] = float("nan")
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.interpret(formal)

    def test_b_margin_and_taper_direction_do_not_become_information_or_net_benefit(self):
        names = interpretation.B_EFFECTS
        formal = {"stage": "B", "formal_family": list(names), "seeds": [17, 29, 43],
                  "observers": list(analysis.OBSERVERS), "effects": {},
                  "statistical_thresholds": {"field_advantage_thresholds_pass": False}}
        for name in names:
            point = 0. if "clean" in name else .0005 if name == "field-ordinary task" else .02
            formal["effects"][name] = {"point": {o: point for o in analysis.OBSERVERS},
                "ci": {o: [point - .0001, point + .0001] for o in analysis.OBSERVERS}}
        output = interpretation.interpret("B", formal, evidence_context=PASSED_CONTEXT)
        self.assertEqual(output["effects"]["field-ordinary task"]["status"], "below_threshold_both_observers")
        self.assertEqual(output["effects"]["fixed-taper-field task (secondary)"]["status"], "supported_both_observers")
        self.assertEqual(output["registered_statistical_thresholds"], formal["statistical_thresholds"])
        self.assertEqual(output["unconditional_net_benefit"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
