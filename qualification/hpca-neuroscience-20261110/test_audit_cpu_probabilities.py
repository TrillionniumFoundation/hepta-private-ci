"""Test the audit gate only, not task efficacy or model provenance."""
import copy
import unittest

from audit_cpu_probabilities import analyze


def score(p, label):
    pred = "yes" if p >= 0.5 else "no"
    return {
        "accuracy": float(pred == label),
        "rows": [{
            "id": "task-1", "prompt_sha256": "a" * 64,
            "truth": label, "p_yes": p,
            "prediction": pred, "correct": pred == label
        }],
    }


def fixture():
    runs = []
    for seed in (11, 17):
        for arm in ("uniform", "heterogeneous"):
            score_map = {
                "B_exposed_eval": score(.7 if arm == "uniform" else .8, "yes"),
                "C_operator_constructed": score(.3 if arm == "uniform" else .2, "no")
            }
            runs.append({
                "seed": seed, "arm": arm,
                "steps": 2, "input_tokens_train": 20,
                "actual_updated_parameter_elements": 32,
                "scores": score_map,
                "cold_reloaded_scores": copy.deepcopy(score_map),
            })
    return {
        "schema": "HPCA-REAL-CPU-LORA-CLOCK-V1",
        "decision": "HOLD_NO_GO",
        "seeds": [11, 17],
        "runs": runs,
        "steps_per_arm": 2,
        "identities": {"model_safetensors_sha256": "b" * 64},
    }


class AuditTests(unittest.TestCase):
    def test_valid_paired_probabilities_can_change_with_identical_accuracy(self):
        result = analyze(fixture(), "c" * 64)
        self.assertEqual(result["status"], "HOLD_NO_GO")
        for family in ("B_exposed_eval", "C_operator_constructed"):
            means = result["task_families"][family]["mean_heterogeneous_minus_uniform"]
            self.assertEqual(means["accuracy"], 0)
            self.assertLess(means["log_loss"], 0)
            self.assertLess(means["brier"], 0)

    def test_missing_arm_refused(self):
        obj = fixture()
        obj["runs"].pop()
        with self.assertRaisesRegex(ValueError, "missing/extra arm"):
            analyze(obj, "c" * 64)

    def test_duplicate_arm_refused(self):
        obj = fixture()
        obj["runs"][1]["arm"] = "uniform"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            analyze(obj, "c" * 64)

    def test_evaluation_label_drift_refused(self):
        obj = fixture()
        row = obj["runs"][1]["scores"]["B_exposed_eval"]["rows"][0]
        row["truth"] = "no"
        row["correct"] = False
        obj["runs"][1]["scores"]["B_exposed_eval"]["accuracy"] = 0.0
        with self.assertRaisesRegex(ValueError, "unpaired"):
            analyze(obj, "c" * 64)

    def test_non_finite_probability_refused(self):
        obj = fixture()
        obj["runs"][0]["scores"]["B_exposed_eval"]["rows"][0]["p_yes"] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            analyze(obj, "c" * 64)

    def test_probability_prediction_mismatch_refused(self):
        obj = fixture()
        obj["runs"][0]["scores"]["B_exposed_eval"]["rows"][0]["prediction"] = "no"
        with self.assertRaisesRegex(ValueError, "prediction/probability"):
            analyze(obj, "c" * 64)

    def test_headline_accuracy_mismatch_refused(self):
        obj = fixture()
        obj["runs"][0]["scores"]["B_exposed_eval"]["accuracy"] = 0.0
        with self.assertRaisesRegex(ValueError, "headline"):
            analyze(obj, "c" * 64)

    def test_forged_cold_reload_refused(self):
        obj = fixture()
        obj["runs"][0]["cold_reloaded_scores"]["B_exposed_eval"] = score(.6, "yes")
        with self.assertRaisesRegex(ValueError, "cold reload probability"):
            analyze(obj, "c" * 64)

    def test_unequal_optimizer_opportunity_refused(self):
        obj = fixture()
        obj["runs"][0]["actual_updated_parameter_elements"] = 31
        with self.assertRaisesRegex(ValueError, "update budget"):
            analyze(obj, "c" * 64)

    def test_unequal_token_opportunity_refused(self):
        obj = fixture()
        obj["runs"][0]["input_tokens_train"] = 21
        with self.assertRaisesRegex(ValueError, "token opportunity"):
            analyze(obj, "c" * 64)

    def test_no_efficacy_authority_and_source_pin_required(self):
        obj = fixture()
        with self.assertRaisesRegex(ValueError, "pin required"):
            analyze(obj, "")
        result = analyze(obj, "c" * 64)
        self.assertTrue(result["open_gates"])
        self.assertEqual(result["authority"], "READ_ONLY_NOT_OWNER_ATTESTED")


if __name__ == "__main__":
    unittest.main()
