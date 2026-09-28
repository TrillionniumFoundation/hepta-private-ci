import copy
import json
import unittest
from pathlib import Path

try:
    from scripts.hepta_experiment_design import validate_decision_cell_design
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_experiment_design import validate_decision_cell_design


class DecisionCellDesignTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "docs/learning/EXPERIMENTS.json"
        self.registry = json.loads(path.read_text())

    def reject(self, mutate, message):
        candidate = copy.deepcopy(self.registry)
        mutate(candidate)
        with self.assertRaisesRegex(ValueError, message):
            validate_decision_cell_design(candidate)

    def test_planned_unresolved_design_is_valid_without_becoming_execution_evidence(
        self,
    ):
        before = copy.deepcopy(self.registry)
        self.assertIsNone(validate_decision_cell_design(self.registry))
        self.assertEqual(before, self.registry)

    def test_duplicate_registry_ids_cannot_shadow_entries(self):
        for collection in ("families", "quantitativeProfiles"):
            with self.subTest(collection=collection):
                self.reject(
                    lambda r: r[collection].append(r[collection][0]), "duplicate ID"
                )

    def test_missing_family_or_profile_is_rejected(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(familyIds=["unknown"]),
            "unknown experiment family",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(
                quantitativeProfile="unknown"
            ),
            "unknown quantitative profile",
        )

    def test_pairing_cannot_omit_duplicate_or_substitute_a_backend(self):
        for values in (
            ["deterministic_existing"],
            ["duplicate", "duplicate"],
            ["substitute"],
        ):
            with self.subTest(values=values):
                self.reject(
                    lambda r: r["decisionCellBackendDesign"].update(
                        pairedArmIds=values
                    ),
                    "paired panel|duplicate ID",
                )

    def test_unequal_heads_cannot_be_reported_as_a_paired_backend_comparison(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["candidateArms"][1].update(
                headProfile="other"
            ),
            "heads must match",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["candidateArms"].append(
                r["decisionCellBackendDesign"]["candidateArms"][0]
            ),
            "duplicate ID",
        )

    def test_pairing_alone_cannot_remove_the_encoder_comparison(self):
        design = self.registry["decisionCellBackendDesign"]
        design["candidateArms"] = [
            a for a in design["candidateArms"] if a["backend"] != "encoder"
        ]
        design["pairedArmIds"] = [a["id"] for a in design["candidateArms"]]
        with self.assertRaisesRegex(
            ValueError, "must include comparator, Laya and encoder"
        ):
            validate_decision_cell_design(self.registry)

    def test_comparison_cannot_drop_input_roles_or_use_point_estimate_ood(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(
                commonInputRoles=["question", "state"]
            ),
            "complete input roles",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(
                oodThresholdRule="point_estimate"
            ),
            "multiplicity-adjusted upper bound",
        )

    def test_seed_replicates_are_distinct_nonnegative_integers(self):
        self.registry["decisionCellBackendDesign"]["seedReplicates"] = [0, 29]
        validate_decision_cell_design(self.registry)
        for values in ([True, 29], [17, 17], [-1, 29], [1.5, 29]):
            with self.subTest(values=values):
                self.reject(
                    lambda r: r["decisionCellBackendDesign"].update(
                        seedReplicates=values
                    ),
                    "seed",
                )

    def test_split_order_rejects_future_leakage_but_allows_different_ordinals(self):
        windows = self.registry["decisionCellBackendDesign"]["splitWindowOrder"]
        for key in windows:
            windows[key] = windows[key] * 10 + 3
        validate_decision_cell_design(self.registry)
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["splitWindowOrder"].update(
                selection=99
            ),
            "split order",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["splitWindowOrder"].update(
                training=False
            ),
            "split ordinal",
        )

    def test_resource_budget_must_cover_the_planned_panel(self):
        self.registry["decisionCellBackendDesign"]["resourceLimits"][
            "maximumParallelTrainingJobs"
        ] = 4
        validate_decision_cell_design(self.registry)
        for key, value in (
            ("maximumBackendCandidates", 1),
            ("maximumEvaluationRows", 1),
            ("maximumSearchTrialsPerArm", 1),
            ("maximumParallelTrainingJobs", 100),
            ("maximumSearchTrialsPerArm", True),
        ):
            with self.subTest(key=key):
                self.reject(
                    lambda r: r["decisionCellBackendDesign"]["resourceLimits"].update(
                        {key: value}
                    ),
                    "budget|positive integer",
                )

    def test_referenced_safety_profile_cannot_be_weakened(self):
        self.reject(
            lambda r: r["quantitativeProfiles"][0].update(
                maximumOodFalseAcceptancePpm=999999
            ),
            "weakened ceiling",
        )
        self.reject(
            lambda r: r["quantitativeProfiles"][0].update(
                minimumEffectiveSampleSize=True
            ),
            "weakened floor",
        )

    def test_statistical_profile_preserves_probability_bounds_and_interval_rule(self):
        for key, value in (
            ("confidenceLevelPpm", 1),
            ("familywiseAlphaPpm", 999999),
            ("targetPowerPpm", 1),
            ("confidenceLevelPpm", True),
            ("confidenceLevelPpm", 1000000),
            ("familywiseAlphaPpm", 0),
            ("familywiseAlphaPpm", 10000),
            ("candidateRule", "point_estimate"),
        ):
            with self.subTest(key=key, value=value):
                self.reject(
                    lambda r: r["quantitativeProfiles"][0].update({key: value}),
                    "probability|weakened statistical|support the familywise|interval superiority",
                )

    def test_required_adaptation_and_teacher_comparisons_cannot_be_dropped(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(
                adaptationArmIds=["placeholder"]
            ),
            "adaptation panel omits",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["teacher"].update(
                arms=["no_teacher"]
            ),
            "teacher panel omits",
        )

    def test_design_cannot_self_certify_teacher_or_execution(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["teacher"].update(
                dataUseRights="confirmed"
            ),
            "cannot confirm teacher evidence",
        )
        self.reject(
            lambda r: r["decisionCellBackendDesign"]["teacher"].update(
                unconfirmedDisposition="allow"
            ),
            "must block collection",
        )
        for key in (
            "executionCompleted",
            "trainingCompleted",
            "backendSelected",
            "calibratedTrustEstablished",
            "futureWindowEfficacyEstablished",
        ):
            with self.subTest(key=key):
                self.reject(
                    lambda r: r["decisionCellBackendDesign"].update({key: True}),
                    "cannot establish",
                )

    def test_unbound_resources_cannot_allow_execution(self):
        self.reject(
            lambda r: r["decisionCellBackendDesign"].update(
                unboundResourceDisposition="allow"
            ),
            "must block execution",
        )


if __name__ == "__main__":
    unittest.main()
