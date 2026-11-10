"""Synthetic-only contractual negatives, not model or owner experiments."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

from factorial import ARMS, FactorialContractError, FactorialRow, factorial_evidence, _holm_p


def h(s):
    return sha256(s.encode()).hexdigest()


def panel(count=4, families=("dense_ACT",)):
    rows = []
    for seed in range(count):
        for family in families:
            for arm in ARMS:
                rows.append(FactorialRow(
                    episode_id=f"future-B-{seed}-{family}", seed=seed,
                    family=family, arm=arm,
                    workload_digest=h(f"task-{seed}-{family}"),
                    train_data_digest=h("disjoint-train-A"),
                    evaluator_digest=h("held-out-B-owner-declaration"),
                    capacity_contract_digest=h("matched-contract"),
                    core_model_digest=h("ordinary-core" if arm in "AB" else "hepta-core"),
                    controller_digest=h("ordinary-control" if arm in "AC" else "NDU-control"),
                    feedback_contract_digest=h(f"locked-{family}"),
                    outcome_receipt_digest=h(f"{seed}/{family}/{arm}/outcome"),
                    query_budget=10, training_budget=200, compute_budget_us=10_000,
                    feedback_budget_bits=8,
                    gross_value={"A": 1.0, "B": 2.0, "C": 3.0, "D": 5.0}[arm],
                    full_cost={"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4}[arm],
                    retention_value={"A": 0.95, "B": 0.94, "C": 0.90, "D": 0.88}[arm],
                    wall_time_us=1000, cpu_time_us=800, gpu_time_us=0,
                    failed_actions=0, evaluator_independent=False))
    return rows


class FactorialPreflightTests(unittest.TestCase):
    def test_full_cost_contrasts_and_holm(self):
        result = factorial_evidence(panel())
        got = result["contrasts"]
        self.assertEqual(result["seed_clusters"], 4)
        for name, expected in (('B_minus_A', 0.9), ('D_minus_C', 1.9),
                               ('D_minus_B', 2.8), ('interaction', 1.0)):
            self.assertAlmostEqual(got[name]["mean_net_delta"], expected)
            self.assertEqual(got[name]["one_sided_exact_signflip_p"], 1 / 16)
            self.assertEqual(got[name]["holm_four_contrasts_p"], 0.25)
        self.assertEqual(result["authority"], "DENY_ALL")
        self.assertEqual(result["credential_verification"], "NOT_PERFORMED")
        self.assertEqual(result["qualification"], "HOLD_NO_GO")
        self.assertFalse(result["all_evaluator_independence_declared"])

    def test_multiple_families_reused_seed_not_double_counted(self):
        result = factorial_evidence(panel(3, ("dense_ACT", "sparse_CTRL")))
        self.assertEqual(result["blocks"], 6)
        self.assertEqual(result["seed_clusters"], 3)
        self.assertEqual(result["contrasts"]["B_minus_A"]["one_sided_exact_signflip_p"], .125)

    def test_missing_arm_fails_closed(self):
        with self.assertRaisesRegex(FactorialContractError, "missing"):
            factorial_evidence(panel(1)[:-1])

    def test_no_duplicate_trial_or_receipt(self):
        rows = panel(1)
        with self.assertRaisesRegex(FactorialContractError, "duplicate"):
            factorial_evidence(rows + [replace(rows[0], outcome_receipt_digest=h("extra"))])
        rows[1] = replace(rows[1], outcome_receipt_digest=rows[0].outcome_receipt_digest)
        with self.assertRaisesRegex(FactorialContractError, "reused"):
            factorial_evidence(rows)

    def test_identity_and_opportunity_must_match(self):
        variants = {
            "task": {"workload_digest": h("other")},
            "train": {"train_data_digest": h("future-B-leak")},
            "eval": {"evaluator_digest": h("other")},
            "capacity": {"capacity_contract_digest": h("other")},
            "feedback": {"feedback_contract_digest": h("other")},
            "query": {"query_budget": 11},
            "train_budget": {"training_budget": 201},
            "compute": {"compute_budget_us": 10001},
            "label": {"feedback_budget_bits": 9},
            "core": {"core_model_digest": h("wrong-core")},
            "controller": {"controller_digest": h("wrong-control")},
        }
        for name, mutation in variants.items():
            with self.subTest(name=name):
                rows = panel(1)
                rows[1] = replace(rows[1], **mutation)
                with self.assertRaises(FactorialContractError):
                    factorial_evidence(rows)

    def test_missing_outcome_withholds_inference_not_imputed(self):
        rows = panel(4)
        rows[3] = replace(rows[3], gross_value=None)
        got = factorial_evidence(rows)
        self.assertEqual(got["missing_outcome_blocks"], 1)
        for result in got["contrasts"].values():
            self.assertIsNone(result["mean_net_delta"])
            self.assertIsNone(result["one_sided_exact_signflip_p"])
            self.assertIsNone(result["holm_four_contrasts_p"])

    def test_missing_retention_and_resources_are_explicit(self):
        rows = panel(1)
        rows[0] = replace(rows[0], retention_value=None, gpu_time_us=None)
        got = factorial_evidence(rows)
        self.assertEqual(got["missing_retention_blocks"], 1)
        self.assertEqual(got["missing_resource_blocks"], 1)
        self.assertIsNone(got["contrasts"]["D_minus_B"]["mean_retention_delta"])
        self.assertIsNone(got["actual_resource_mean_by_arm"]["B"]["cpu_time_us"])

    def test_invalid_values_not_coerced(self):
        variants = ("seed", "query_budget", "training_budget", "compute_budget_us",
                    "feedback_budget_bits", "wall_time_us", "cpu_time_us",
                    "gpu_time_us", "failed_actions")
        for field in variants:
            with self.subTest(field=field):
                rows = panel(1)
                rows[0] = replace(rows[0], **{field: True})
                with self.assertRaises(FactorialContractError):
                    factorial_evidence(rows)
        for field, value in (("gross_value", float('nan')),
                             ("full_cost", -1), ("retention_value", float('inf')),
                             ("evaluator_independent", 'true'),
                             ("outcome_receipt_digest", 'unverified')):
            with self.subTest(field=field):
                rows = panel(1)
                rows[0] = replace(rows[0], **{field: value})
                with self.assertRaises(FactorialContractError):
                    factorial_evidence(rows)

    def test_exact_signflip_not_extended_beyond_16_clusters(self):
        result = factorial_evidence(panel(17))
        self.assertEqual(result["seed_clusters"], 17)
        for contrast in result["contrasts"].values():
            self.assertIsNone(contrast["one_sided_exact_signflip_p"])
            self.assertIsNone(contrast["holm_four_contrasts_p"])

    def test_holm_stepdown_order_and_monotonicity(self):
        values = {"a": 0.01, "b": 0.03, "c": 0.02, "d": 0.8}
        self.assertEqual(_holm_p(values), {"a": .04, "b": .06, "c": .06, "d": .8})
        self.assertTrue(all(v is None for v in _holm_p({"a": .01, "b": None}).values()))

    def test_adverse_family_visible_despite_positive_pooled_value(self):
        rows = panel(4, ("dense_ACT", "sparse_CTRL"))
        rows = [replace(row, gross_value=0.5)
                if row.family == "dense_ACT" and row.arm == "D" else row
                for row in rows]
        got = factorial_evidence(rows)
        self.assertGreater(got["contrasts"]["D_minus_B"]["mean_net_delta"], 0)
        self.assertLess(got["family_contrasts"]["dense_ACT"]["D_minus_B"]["mean_net_delta"], 0)
        self.assertGreater(got["family_contrasts"]["sparse_CTRL"]["D_minus_B"]["mean_net_delta"], 0)
        self.assertEqual(got["negative_net_families_by_contrast"]["D_minus_B"], ["dense_ACT"])
        self.assertEqual(got["qualification"], "HOLD_NO_GO")

    def test_missing_any_future_outcome_masks_all_family_diagnostics(self):
        rows = panel(2, ("dense_ACT", "sparse_CTRL"))
        rows[0] = replace(rows[0], full_cost=None)
        got = factorial_evidence(rows)
        self.assertIsNone(got["negative_net_families_by_contrast"]["D_minus_B"])
        for family in ("dense_ACT", "sparse_CTRL"):
            for contrast in got["family_contrasts"][family].values():
                self.assertIsNone(contrast["mean_net_delta"])

    def test_family_roster_omission_is_not_a_matched_panel(self):
        rows = panel(2, ("dense_ACT", "sparse_CTRL"))
        rows = [row for row in rows
                if not (row.seed == 1 and row.family == "dense_ACT")]
        with self.assertRaisesRegex(FactorialContractError, "unequal family"):
            factorial_evidence(rows)

    def test_extra_episode_for_one_seed_is_not_balanced(self):
        rows = panel(2, ("dense_ACT",))
        copies = [replace(row, episode_id="future-extra",
                          outcome_receipt_digest=h(f"extra/{row.arm}"))
                  for row in rows if row.seed == 0]
        with self.assertRaisesRegex(FactorialContractError, "unequal family"):
            factorial_evidence(rows + copies)

    def test_model_identity_swap_between_families_refused(self):
        rows = panel(2, ("dense_ACT", "sparse_CTRL"))
        rows = [replace(row, core_model_digest=h("swapped-hepta-core"))
                if row.family == "sparse_CTRL" and row.arm in ("C", "D")
                else row for row in rows]
        with self.assertRaisesRegex(FactorialContractError, "cohort identity drift"):
            factorial_evidence(rows)

    def test_evaluator_identity_swap_between_families_refused(self):
        rows = panel(2, ("dense_ACT", "sparse_CTRL"))
        rows = [replace(row, evaluator_digest=h("second-evaluator"))
                if row.family == "sparse_CTRL" else row for row in rows]
        with self.assertRaisesRegex(FactorialContractError, "cohort identity drift"):
            factorial_evidence(rows)

    def test_train_eval_identical_digest_is_refused(self):
        rows = panel(1)
        rows = [replace(row, train_data_digest=row.workload_digest)
                for row in rows]
        with self.assertRaisesRegex(FactorialContractError, "disjointness violated"):
            factorial_evidence(rows)


if __name__ == "__main__":
    unittest.main()
