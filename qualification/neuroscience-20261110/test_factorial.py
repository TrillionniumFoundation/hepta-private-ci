import unittest
from dataclasses import replace
from hashlib import sha256

from factorial import (
    ARMS, ContractError, FactorialTrialRow, _strict_json, evaluate_core_ndu,
)


def h(text):
    return sha256(text.encode("utf-8")).hexdigest()


def row(arm, *, seed=0, family="ACT", density="sparse",
        episode="ep0", gross=None, **changes):
    value = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 5.0}[arm]
    base = FactorialTrialRow(
        episode_id=episode, seed=seed, family=family,
        feedback_density=density, arm=arm, split="future_B",
        source_task_digest=h(f"train-A:{seed}:{family}:{episode}"),
        workload_digest=h(f"future-B:{seed}:{family}:{episode}"),
        shared_base_digest=h("frozen-base-model"),
        capacity_envelope_digest=h("registered-equal-opportunity"),
        evaluator_digest=h("frozen-independent-evaluator-identity-CLAIM"),
        training_seed_digest=h(f"training-seed:{seed}"),
        evaluation_seed_digest=h(f"future-eval-seed:{seed}"),
        feedback_budget_bits=100, query_budget=10, training_budget=20,
        compute_budget_us=1_000_000, actual_cpu_us=900_000,
        actual_wall_us=1_100_000, peak_rss_bytes=40_000_000,
        failed_attempts=0, gross_value=value if gross is None else gross,
        full_cost=0.2, old_task_score=0.8, ood_score=0.7,
        evaluator_independent=True,
        outcome_receipt_digest=h(f"receipt:{seed}:{family}:{density}:{episode}:{arm}"),
    )
    return replace(base, **changes)


def panel(seeds=2, densities=("sparse", "dense"), episodes=("ep0",)):
    return [
        row(arm, seed=seed, density=density, episode=episode)
        for seed in range(seeds)
        for density in densities
        for episode in episodes
        for arm in ARMS
    ]


def required(densities=("sparse", "dense")):
    return [("ACT", density) for density in densities]


class FactorialPreflightTests(unittest.TestCase):
    def test_four_required_contrasts_include_the_interaction(self):
        data = evaluate_core_ndu(panel(), required_cells=required())
        self.assertEqual(data["coverage"]["matched_blocks"], 4)
        self.assertEqual(data["coverage"]["seed_clusters"], 2)
        for name, expected in (("B_minus_A", 1), ("D_minus_C", 2),
                               ("D_minus_B", 3), ("interaction", 1)):
            self.assertAlmostEqual(data["net_contrasts"][name]["mean"], expected)
        self.assertEqual(data["research_posture"], "HOLD_NO_GO")
        self.assertEqual(data["owner_attestation"], "NOT_VERIFIED")
        self.assertEqual(data["authority"], "DENY_ALL")
        self.assertAlmostEqual(
            data["reported_resource_means_by_arm"]["A"]["cpu_us"], 900_000)

    def test_d_minus_a_alone_cannot_mask_negative_interaction(self):
        rows = [
            row(arm, gross={"A": 1, "B": 2, "C": 3, "D": 2}[arm])
            for arm in ARMS
        ]
        data = evaluate_core_ndu(rows, required_cells=required(("sparse",)))
        self.assertEqual(data["net_contrasts"]["D_minus_B"]["mean"], 0)
        self.assertAlmostEqual(data["net_contrasts"]["D_minus_C"]["mean"], -1)
        self.assertAlmostEqual(data["net_contrasts"]["interaction"]["mean"], -2)

    def test_missing_arm_or_cell_fails_not_as_zero(self):
        with self.assertRaisesRegex(ContractError, "missing required"):
            evaluate_core_ndu(panel()[:-1], required_cells=required())
        with self.assertRaisesRegex(ContractError, "seed missing"):
            evaluate_core_ndu(panel(densities=("sparse",)), required_cells=required())
        with self.assertRaisesRegex(ContractError, "unregistered"):
            evaluate_core_ndu(panel(), required_cells=required(("sparse",)))

    def test_same_task_or_seed_cannot_be_called_future_holdout(self):
        original = panel(seeds=1, densities=("sparse",))
        for change in (
            {"workload_digest": original[0].source_task_digest},
            {"evaluation_seed_digest": original[0].training_seed_digest},
            {"split": "training_A"},
        ):
            mutated = original.copy()
            mutated[0] = replace(mutated[0], **change)
            with self.subTest(change=change), self.assertRaises(ContractError):
                evaluate_core_ndu(mutated, required_cells=required(("sparse",)))

    def test_wrong_capacity_task_evaluator_or_opportunity_rejected(self):
        original = panel(seeds=1, densities=("sparse",))
        for change in (
            {"capacity_envelope_digest": h("extra-capacity")},
            {"evaluator_digest": h("different-evaluator")},
            {"shared_base_digest": h("different-base")},
            {"workload_digest": h("different-future-task")},
            {"query_budget": 11}, {"feedback_budget_bits": 101},
            {"compute_budget_us": 1_000_001},
        ):
            mutated = original.copy()
            mutated[0] = replace(mutated[0], **change)
            with self.subTest(change=change), self.assertRaisesRegex(
                    ContractError, "unmatched"):
                evaluate_core_ndu(mutated, required_cells=required(("sparse",)))

    def test_actual_resources_can_differ_but_must_be_present_and_within_budget(self):
        rows = panel(seeds=1, densities=("sparse",))
        rows[0] = replace(rows[0], actual_cpu_us=750_000,
                          failed_attempts=2, full_cost=0.8)
        data = evaluate_core_ndu(rows, required_cells=required(("sparse",)))
        self.assertAlmostEqual(data["reported_resource_means_by_arm"]["A"]["cpu_us"],
                               750_000)
        self.assertEqual(data["reported_resource_means_by_arm"]["A"]["failed_attempts"], 2)
        for invalid in ({"actual_cpu_us": 0}, {"peak_rss_bytes": 0},
                        {"actual_cpu_us": 1_000_001}, {"full_cost": -1},
                        {"actual_wall_us": False}):
            bad = rows.copy()
            bad[0] = replace(rows[0], **invalid)
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                evaluate_core_ndu(bad, required_cells=required(("sparse",)))

    def test_independent_and_old_ood_labels_are_not_inferred(self):
        rows = panel(seeds=1, densities=("sparse",))
        rows[0] = replace(rows[0], old_task_score=None, ood_score=None,
                          evaluator_independent=False)
        report = evaluate_core_ndu(rows, required_cells=required(("sparse",)))
        self.assertIsNone(report["retention_contrasts"])
        self.assertIsNone(report["ood_contrasts"])
        self.assertEqual(report["evaluator_independence"], "MISSING")
        self.assertEqual(report["research_posture"], "HOLD_NO_GO")

    def test_duplicate_reused_receipt_and_invalid_hash_rejected(self):
        rows = panel(seeds=1, densities=("sparse",))
        rows[0] = replace(rows[0], outcome_receipt_digest=rows[1].outcome_receipt_digest)
        with self.assertRaisesRegex(ContractError, "reused outcome"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))
        rows[0] = replace(rows[0], outcome_receipt_digest="a"*64,
                          shared_base_digest="bad")
        with self.assertRaisesRegex(ContractError, "digest"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))

    def test_seed_cluster_p_and_holm_adjustment_do_not_create_a_gate(self):
        report = evaluate_core_ndu(
            panel(seeds=16, densities=("sparse",)),
            required_cells=required(("sparse",)),
        )
        values = report["net_contrasts"]
        self.assertAlmostEqual(values["B_minus_A"]["one_sided_signflip_p_unadjusted"],
                               1 / 65_536)
        self.assertAlmostEqual(values["B_minus_A"]["holm_p_four_contrasts"],
                               4 / 65_536)
        self.assertEqual(report["research_posture"], "HOLD_NO_GO")
        many = evaluate_core_ndu(panel(seeds=17, densities=("sparse",)),
                                 required_cells=required(("sparse",)))
        for x in many["net_contrasts"].values():
            self.assertIsNone(x["one_sided_signflip_p_unadjusted"])
            self.assertIsNone(x["holm_p_four_contrasts"])

    def test_equal_cell_weight_ignores_duplicate_episode_counts(self):
        rows = panel(seeds=1, episodes=("e0",), densities=("dense", "sparse"))
        rows += [
            row(arm, seed=0, density="dense", episode="e1",
                gross={"A": 1, "B": 11, "C": 3, "D": 5}[arm])
            for arm in ARMS
        ]
        result = evaluate_core_ndu(rows, required_cells=required())
        # Sparse B-A=1, dense B-A=(1+10)/2=5.5; each cell gets 1/2 weight.
        self.assertAlmostEqual(result["net_contrasts"]["B_minus_A"]["mean"], 3.25)

    def test_duplicate_json_fields_and_nonfinite_constants_fail_closed(self):
        with self.assertRaisesRegex(ContractError, "duplicate JSON"):
            _strict_json('{"arm":"A","arm":"D"}')
        with self.assertRaisesRegex(ContractError, "nonfinite"):
            _strict_json('{"v": NaN}')
        self.assertEqual(_strict_json('{"v": 1}')["v"], 1)


    def test_frozen_cell_evaluator_cannot_change_between_training_seeds(self):
        rows = panel(seeds=2, densities=("sparse",))
        rows = [replace(r, evaluator_digest=h("late-evaluator-revision"))
                if r.seed == 1 else r for r in rows]
        with self.assertRaisesRegex(ContractError, "frozen cell"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))

    def test_frozen_cell_opportunity_cannot_change_between_episodes(self):
        rows = panel(seeds=1, densities=("sparse",), episodes=("e0", "e1"))
        rows = [replace(r, query_budget=99) if r.episode_id == "e1"
                else r for r in rows]
        with self.assertRaisesRegex(ContractError, "frozen cell"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))

    def test_unequal_per_seed_episode_cohort_rejected(self):
        rows = panel(seeds=2, densities=("sparse",))
        rows += [row(arm, seed=1, density="sparse", episode="extra")
                 for arm in ARMS]
        with self.assertRaisesRegex(ContractError, "unequal seed episode"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))

    def test_frozen_contract_may_differ_across_registered_cells(self):
        rows = panel(seeds=2)
        rows = [replace(r, evaluator_digest=h("dense-independent-evaluator"),
                        query_budget=20, compute_budget_us=1_500_000)
                if r.feedback_density == "dense" else r for r in rows]
        result = evaluate_core_ndu(rows, required_cells=required())
        self.assertEqual(result["coverage"]["matched_blocks"], 4)
        self.assertEqual(result["research_posture"], "HOLD_NO_GO")


if __name__ == "__main__":
    unittest.main()

