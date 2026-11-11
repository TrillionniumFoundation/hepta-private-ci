"""Adversarial qualification of the exposed-only HPCA V2 paired readout."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from real_probability_audit_v2 import analyse, read_archive, SECTIONS, ARCHIVE_SHA256

HERE = Path(__file__).resolve().parent


class V2ProbabilityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_archive(HERE / "real_cpu_clock_v2_RESULT.json")

    def test_negative_accuracy_and_tiny_continuous_differences(self):
        value = analyse(self.source)
        self.assertEqual(value["candidate"], "HOLD_NO_GO")
        self.assertEqual(value["authority"], "DENY_ALL")
        self.assertFalse(value["confirmatory_inference"])
        self.assertEqual(value["input_sha256"], ARCHIVE_SHA256)
        self.assertEqual(set(value["sections"]), set(SECTIONS))
        expected = {
            "B_exposed_eval": (4, 0.0001749712898092, 0.5),
            "C_operator_constructed": (8, 0.0001112570871699, 0.625),
            "calibration": (4, 0.000173747951924, 0.375),
        }
        for section, (questions, mean_loss, p_value) in expected.items():
            with self.subTest(section=section):
                actual = value["sections"][section]
                self.assertEqual(actual["questions"], questions)
                self.assertEqual(actual["mean_bursty_minus_interleaved"]["accuracy"], 0)
                self.assertTrue(math.isclose(actual["mean_bursty_minus_interleaved"]["log_loss"],
                                             mean_loss, abs_tol=1e-12))
                self.assertEqual(actual["exploratory_two_sided_signflip_p_log_loss"], p_value)
                self.assertEqual(len(actual["per_seed"]), 4)

    def test_mutations_fail_closed(self):
        for kind in ("missing_arm", "order", "plan", "source", "token", "weight",
                     "reload", "score", "future_label", "authority"):
            bad = copy.deepcopy(self.source)
            pair = bad["runs"][0]
            if kind == "missing_arm":
                bad["runs"].pop()
            elif kind == "order":
                pair["arm_order"].reverse()
            elif kind == "plan":
                pair["plan_digest"] = "changed"
            elif kind == "source":
                pair["step_log"][0]["source_id"] = "changed"
            elif kind == "token":
                pair["step_log"][0]["input_tokens"] += 1
            elif kind == "weight":
                pair["actual_updated_parameter_elements"] += 1
            elif kind == "reload":
                pair["cold_reload_max_p_yes_difference"] = 0.5
            elif kind == "score":
                pair["scores"]["B_exposed_eval"]["rows"][0]["p_yes"] = float("nan")
            elif kind == "future_label":
                pair["scores"]["B_exposed_eval"]["rows"][0]["truth"] = "wrong"
            elif kind == "authority":
                bad["authority"] = "PRODUCTION_AUTHORIZED"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                analyse(bad)

    def test_bytes_must_be_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.json"
            path.write_text('{"schema":"HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED"}')
            with self.assertRaisesRegex(ValueError, "frozen source identity"):
                read_archive(path)


if __name__ == "__main__":
    unittest.main()
