"""Adversarial, synthetic-only contract tests. Not model efficacy evidence."""
from hashlib import sha256
import unittest

from factorial import audit, EvidenceError, SCHEMA


def d(s):
    return sha256(str(s).encode()).hexdigest()


def fixture(n=4):
    families = ["text", "multimodal", "correction", "prepare", "stop", "retention"]
    m = {
        "schema": SCHEMA, "source_sha": "1" * 40, "source_tree_sha": "2" * 40,
        "evaluator_digest": d("eval"), "data_digest": d("data"),
        "seed_assignment_digest": d("assign"),
        "training_contract_digest": d("traincontract"),
        "core_arch_digests": {"ordinary": d("ordinary"), "hepta": d("hepta")},
        "seeds": list(range(n)), "families": families,
        "regimes": ["dense", "sparse"],
        "practical_delta": 0.02, "retention_floor": 0.9,
    }
    rows = []
    for seed in m["seeds"]:
        for family in families:
            for regime in m["regimes"]:
                for arm in "ABCD":
                    core = "ordinary" if arm in "AB" else "hepta"
                    rows.append({
                        "seed": seed, "family": family, "regime": regime,
                        "arm": arm, "core": core, "ndu": arm in "BD",
                        "core_arch_digest": m["core_arch_digests"][core],
                        "trained_model_digest": d((seed, family, regime, arm, "model")),
                        "task_instance": f"{seed}-{family}-{regime}",
                        "task_a_digest": d((seed, family, regime, "A")),
                        "task_b_digest": d((seed, family, regime, "B")),
                        "task_c_digest": d((seed, family, regime, "C")),
                        "result_receipt_digest": d((seed, family, regime, arm, "receipt")),
                        "train_end_sequence": 10, "eval_start_sequence": 11,
                        "resource_caps": {"wall_us": 1000, "cpu_us": 1000,
                                          "memory_bytes": 2048, "api_calls": 2,
                                          "tokens": 50, "feedback_bits": 8,
                                          "train_updates": 10},
                        "actual_resources": {"wall_us": 100, "cpu_us": 70,
                                             "peak_rss_bytes": 500, "api_calls": 1,
                                             "tokens_in": 5, "tokens_out": 10,
                                             "energy_millijoules": 3},
                        "gross_utility": {"A": 0.2, "B": 0.3, "C": 0.4, "D": 0.6}[arm],
                        "cost_utility": 0.05,
                        "old_task_retention": 0.95,
                        "safety_failures": 0, "timeout": False,
                    })
    return m, rows


class FactorialShadowTests(unittest.TestCase):
    def test_full_roster_and_correct_four_contrasts(self):
        m, rows = fixture()
        r = audit(m, rows)
        self.assertEqual(r["verdict"], "HOLD_NO_GO")
        self.assertEqual(r["authority"], "DENY_ALL")
        self.assertEqual((r["paired_blocks"], r["evaluated_rows"]), (48, 192))
        self.assertAlmostEqual(r["primary"]["B-A"]["mean_net_difference"], 0.1)
        self.assertAlmostEqual(r["primary"]["D-C"]["mean_net_difference"], 0.2)
        self.assertAlmostEqual(r["primary"]["D-B"]["mean_net_difference"], 0.3)
        self.assertAlmostEqual(r["primary"]["interaction"]["mean_net_difference"], 0.1)
        self.assertEqual(r["actual_resource_totals_by_arm"]["A"]["cpu_us"], 48*70)
        self.assertAlmostEqual(r["retention_contrasts"]["D-C"], 0.)

    def test_row_order_is_not_science(self):
        m, rows = fixture()
        self.assertEqual(audit(m, rows)["input_digest"],
                         audit(m, list(reversed(rows)))["input_digest"])

    def test_reject_missing_arm_even_with_many_other_rows(self):
        m, rows = fixture()
        with self.assertRaises(EvidenceError):
            audit(m, rows[1:])

    def test_reject_duplicate_or_reused_effect_receipt(self):
        m, rows = fixture()
        rows[1]["result_receipt_digest"] = rows[0]["result_receipt_digest"]
        with self.assertRaisesRegex(EvidenceError, "reused result receipt"):
            audit(m, rows)

    def test_reject_mislabeled_2x2_controller(self):
        m, rows = fixture()
        rows[0]["ndu"] = True
        with self.assertRaisesRegex(EvidenceError, "mislabeled"):
            audit(m, rows)

    def test_reject_unequal_budget_even_when_scores_look_good(self):
        m, rows = fixture()
        rows[0]["resource_caps"]["cpu_us"] += 1
        with self.assertRaisesRegex(EvidenceError, "resource opportunities differ"):
            audit(m, rows)

    def test_reject_training_label_leak_into_future_eval(self):
        m, rows = fixture()
        rows[0]["task_b_digest"] = rows[0]["task_a_digest"]
        with self.assertRaisesRegex(EvidenceError, "must differ"):
            audit(m, rows)

    def test_reject_temporal_overlap(self):
        m, rows = fixture()
        rows[0]["eval_start_sequence"] = 10
        with self.assertRaisesRegex(EvidenceError, "later"):
            audit(m, rows)

    def test_reject_owner_signoff_boolean_spoof_for_production(self):
        m, rows = fixture()
        for r in rows:
            r["owner_attested"] = True
            r["evaluator_independent"] = True
            r["cold_recovery_verified"] = True
        report = audit(m, rows)
        self.assertEqual(report["verdict"], "HOLD_NO_GO")
        self.assertEqual(report["attestation"], "UNVERIFIED_EXTERNAL_OWNER_AND_EVALUATOR")

    def test_missing_old_task_retention_is_not_zero_and_never_go(self):
        m, rows = fixture()
        rows[0]["old_task_retention"] = None
        report = audit(m, rows)
        self.assertIs(report["retention_complete"], False)
        self.assertEqual(report["missing_retention_rows"], 1)
        self.assertIsNone(report["retention_contrasts"])
        self.assertEqual(report["verdict"], "HOLD_NO_GO")

    def test_reject_nonfinite_and_boolean_costs(self):
        m, rows = fixture()
        rows[0]["gross_utility"] = float('nan')
        with self.assertRaisesRegex(EvidenceError, "nonfinite"):
            audit(m, rows)
        m, rows = fixture()
        rows[0]["actual_resources"]["cpu_us"] = True
        with self.assertRaisesRegex(EvidenceError, "numeric actual"):
            audit(m, rows)

    def test_reject_unregistered_seed_or_family(self):
        m, rows = fixture()
        rows[0]["seed"] = 200
        with self.assertRaisesRegex(EvidenceError, "out-of-roster"):
            audit(m, rows)

    def test_safety_failure_is_measured_not_a_pass(self):
        m, rows = fixture()
        rows[0]["safety_failures"] = 1
        rows[0]["timeout"] = True
        r = audit(m, rows)
        self.assertEqual(r["safety_failures"], 1)
        self.assertEqual(r["timeouts"], 1)
        self.assertEqual(r["failures_by_arm"]["A"]["timeouts"], 1)
        self.assertEqual(r["verdict"], "HOLD_NO_GO")

    def test_exact_signflip_clustered_not_episode_pseudoreplication(self):
        m, rows = fixture(n=4)
        r = audit(m, rows)
        self.assertEqual(r["primary"]["D-C"]["one_sided_exact_signflip_p"], 1/16)
        self.assertEqual(r["primary"]["D-C"]["holm_four_primary_p"], 0.25)
        self.assertEqual(r["registered_seeds"], 4)

    def test_more_than_16_seeds_p_is_unknown_not_invented(self):
        m, rows = fixture(n=17)
        r = audit(m, rows)
        self.assertIsNone(r["primary"]["D-C"]["one_sided_exact_signflip_p"])
        self.assertIsNone(r["primary"]["D-C"]["holm_four_primary_p"])


if __name__ == '__main__':
    unittest.main()
