import copy
import unittest

from experiments.shared_stem_cell.paired_frontier import InvalidFrontier, audit


SHA = "a" * 64


def campaign():
    rows = [
        {"case_id": f"case-{i}", "group": f"group-{i}", "input_sha256": f"{i:064x}",
         "status": "ok", "correct": True, "active_flops": 100, "wall_ns": 1000}
        for i in range(4)
    ]
    a = {"name": "replicated_421m", "model_sha256": SHA, "stem_sha256": SHA,
         "scope": "same-workspace", "isolated_process": True,
         "resident_model_bytes": 421_000_000 * 2, "peak_rss_bytes": 1_000_000_000,
         "train_active_flops": 50000, "train_wall_ns": 100000,
         "energy_joules": 10.0, "encoder_forward_calls": 4, "outcomes": rows}
    b = copy.deepcopy(a)
    b.update(name="shared_stem", resident_model_bytes=140_000_000 * 2,
             peak_rss_bytes=500_000_000, train_active_flops=20000,
             train_wall_ns=60000, energy_joules=5.0, encoder_forward_calls=1)
    b["outcomes"] = copy.deepcopy(rows)
    for row in b["outcomes"]:
        row["active_flops"] = 50
        row["wall_ns"] = 800
    return {"schema": "hepta.stem.paired-physical-frontier.v1",
            "objective_sha256": SHA, "source_sha256": SHA,
            "observer_receipt_sha256": SHA, "host_profile_sha256": SHA,
            "arms": [a, b]}


class PairedFrontierTests(unittest.TestCase):
    def test_paired_strict_pareto_and_independence_not_fabricated(self):
        result = audit(campaign(), baseline="replicated_421m")
        self.assertTrue(result["comparisons"]["shared_stem"]["strict_paired_pareto"])
        self.assertFalse(result["comparisons"]["shared_stem"]["full_promotion_qualified"])
        self.assertFalse(result["external_observer_authenticity_verified"])
        self.assertEqual(result["observations"]["shared_stem"]["unique_input_count"], 4)
        self.assertEqual(result["observations"]["shared_stem"]["encoder_forward_calls"], 1)

    def test_missing_flops_or_energy_is_null_not_savings(self):
        data = campaign()
        data["arms"][1]["outcomes"][0]["active_flops"] = None
        data["arms"][1]["energy_joules"] = None
        result = audit(data, baseline="replicated_421m")
        self.assertIsNone(result["comparisons"]["shared_stem"]["resource_deltas_vs_baseline"]["total_active_flops"])
        self.assertIsNone(result["comparisons"]["shared_stem"]["resource_deltas_vs_baseline"]["energy_joules"])
        self.assertFalse(result["comparisons"]["shared_stem"]["strict_paired_pareto"])

    def test_case_or_content_swap_fails_even_if_accuracy_matches(self):
        for key, bad in (("input_sha256", SHA), ("group", "other"), ("case_id", "duplicate")):
            with self.subTest(key=key):
                data = campaign()
                data["arms"][1]["outcomes"][0][key] = bad
                with self.assertRaises(InvalidFrontier):
                    audit(data, baseline="replicated_421m")

    def test_survivorship_cannot_drop_failure(self):
        data = campaign()
        data["arms"][1]["outcomes"].pop()
        with self.assertRaisesRegex(InvalidFrontier, "nonpaired"):
            audit(data, baseline="replicated_421m")

    def test_failure_remains_in_quality_denominator(self):
        data = campaign()
        row = data["arms"][1]["outcomes"][0]
        row["status"], row["correct"] = "failed", False
        result = audit(data, baseline="replicated_421m")
        self.assertFalse(result["comparisons"]["shared_stem"]["empirical_group_nonregression"])
        self.assertFalse(result["comparisons"]["shared_stem"]["strict_paired_pareto"])

    def test_failed_case_cannot_claim_correct(self):
        data = campaign()
        data["arms"][1]["outcomes"][0]["status"] = "abstain"
        with self.assertRaises(InvalidFrontier):
            audit(data, baseline="replicated_421m")

    def test_cross_scope_comparison_is_not_authorized(self):
        data = campaign()
        data["arms"][1]["scope"] = "other-workspace"
        with self.assertRaisesRegex(InvalidFrontier, "cross-scope"):
            audit(data, baseline="replicated_421m")

    def test_process_peak_does_not_borrow_shared_process_memory(self):
        data = campaign()
        data["arms"][1]["isolated_process"] = False
        with self.assertRaisesRegex(InvalidFrontier, "separate per-arm process"):
            audit(data, baseline="replicated_421m")

    def test_null_rss_does_not_silently_get_estimated(self):
        data = campaign()
        data["arms"][1]["peak_rss_bytes"] = None
        self.assertFalse(audit(data, baseline="replicated_421m")
                         ["comparisons"]["shared_stem"]["complete_physical_counters"])

    def test_negative_transfer_prevents_pareto_even_when_cheaper(self):
        data = campaign()
        data["arms"][1]["outcomes"][2]["correct"] = False
        self.assertFalse(audit(data, baseline="replicated_421m")
                         ["comparisons"]["shared_stem"]["strict_paired_pareto"])

    def test_missing_baseline_identity_blocks(self):
        with self.assertRaises(InvalidFrontier):
            audit(campaign(), baseline="missing")


if __name__ == "__main__":
    unittest.main()
