from pathlib import Path
import unittest

from legacy_v3.numeric_graph import SERIES_NAMES
from v5.contracts import INTENTS
from v5.graph_assets import Assets, DOMAINS
from v5.graph_process import execute_request
from v5.graph_runtime import GraphRuntime
from v5.joint_cases import independent_target, uniform_addresses
from v5.joint_grading import exact_result, grade_domain


PROJECT = Path(__file__).resolve().parents[1]


class RecoveredGraphMechanisms(unittest.TestCase):
    def test_real_saved_models_and_actual_edge_ablations_on_known_fixtures(self):
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                parameter = GraphRuntime(
                    PROJECT / "assets", domain, 8011, mode="parameter"
                )
                strong = GraphRuntime(PROJECT / "assets", domain, 8011, mode="strong")
                exact, _ = Assets(PROJECT / "assets").exact(domain)
                addresses, _ = uniform_addresses(
                    parameter.reader, len(INTENTS), 8011, domain
                )
                scrambled_correct = 0
                for intent, address in zip(INTENTS, addresses, strict=True):
                    date = f"{address[0]:04d}-{address[1]:02d}"
                    request = {
                        "utterance": f"Manual graph capability fixture for {SERIES_NAMES[domain]} at {date}.",
                        "series_name": SERIES_NAMES[domain],
                        "date": date,
                    }
                    target = independent_target(exact, domain, intent, address)
                    connected = parameter.execute(
                        request, intent, "parameter_connected"
                    )
                    baseline = strong.execute(request, intent, "strong_planner")
                    self.assertTrue(exact_result(connected["actual"], target))
                    self.assertTrue(exact_result(baseline["actual"], target))
                    removed = parameter.execute(request, intent, "parameter_removed")
                    if intent == "at":
                        self.assertEqual(removed["actual"], connected["actual"])
                    else:
                        self.assertIsNone(removed["actual"])
                        self.assertEqual(
                            removed["execution"]["disposition"],
                            "removed_cross_cell_edge",
                        )
                    scrambled = parameter.execute(request, intent, "parameter_permuted")
                    scrambled_correct += exact_result(scrambled["actual"], target)
                self.assertEqual(scrambled_correct, 2)
                receipt = parameter.receipt()
                self.assertEqual(
                    receipt["parameter_identity_before"],
                    receipt["parameter_identity_after"],
                )
                self.assertFalse(
                    any("/codecs/" in name for name in receipt["consumed_asset_files"])
                )

    def test_gold_fields_rejected_before_any_model_load(self):
        with self.assertRaisesRegex(ValueError, "forbids grader fields"):
            execute_request(
                {
                    "schema": "hepta.memory.v5.graph-read-request.v1",
                    "gold_intent": "mean3",
                }
            )

    def test_exact_grade_requires_ordered_provenance_and_no_numeric_tolerance(self):
        target = {
            "kind": "number",
            "value": 1.0,
            "support": ["co2:2000-01", "co2:2000-02"],
        }
        self.assertTrue(exact_result(dict(target), target))
        self.assertFalse(exact_result({**target, "value": 1.0 + 1e-12}, target))
        self.assertFalse(
            exact_result(
                {**target, "support": list(reversed(target["support"]))}, target
            )
        )

    def test_composed_count_boundary_is_exactly_twelve_of_one_hundred_twenty(self):
        target = {"kind": "number", "value": 1, "support": ["fixture"]}
        graders, actual, strong, oracle = [], [], [], []

        def arm(value):
            return {
                "actual": value,
                "execution": {"calls": 0},
                "numeric_read_calls": 0,
                "numeric_coordinates_read": 0,
            }

        for index in range(216):
            intent = "previous" if index < 120 else "at" if index < 144 else None
            graders.append(
                {
                    "template_id": str(index),
                    "gold_intent": intent,
                    "target": target if intent else None,
                }
            )
            decision = {"accepted_intent": intent, "raw_label": intent or "__reject__"}
            connected = target if index < 84 or 120 <= index < 144 else None
            ablated = target if index < 72 or 120 <= index < 144 else None
            actual.append(
                {
                    "decision": decision,
                    "arms": {
                        "parameter_connected": arm(connected),
                        "parameter_removed": arm(ablated),
                        "parameter_permuted": arm(ablated),
                    },
                }
            )
            strong.append(
                {"decision": decision, "arms": {"strong_planner": arm(connected)}}
            )
            oracle.append(
                {
                    "parameter_oracle": arm(target if intent else None),
                    "strong_oracle": arm(target if intent else None),
                }
            )
        scores = grade_domain(graders, actual, strong, oracle)
        self.assertEqual(scores["composed_gain_vs_removed"], 0.1)
        self.assertEqual(scores["composed_gain_vs_permuted"], 0.1)
        self.assertTrue(scores["checks"]["composed_actual_ablation_gain"])


if __name__ == "__main__":
    unittest.main()
