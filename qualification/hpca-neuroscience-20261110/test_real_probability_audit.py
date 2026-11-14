"""Fail-closed, offline reanalysis of already exposed real-model outcomes."""
import copy
import math
from pathlib import Path
import unittest

from real_probability_audit import ARCHIVE_SHA256, analyse, read_archive

HERE = Path(__file__).resolve().parent


class ProbabilityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = read_archive(HERE / "real_cpu_clock_v1_RESULT.json")

    def test_real_archive_continuous_quality_not_equivalence(self):
        audit = analyse(self.raw)
        self.assertEqual(audit["qualification"], "HOLD_NO_GO")
        self.assertEqual(audit["authority"], "DENY_ALL")
        self.assertEqual(audit["raw_archive_sha256"], ARCHIVE_SHA256)
        self.assertTrue(audit["posthoc_exploratory"])
        self.assertEqual(set(audit["sections"]),
                         {"B_exposed_eval", "C_operator_constructed", "calibration"})
        b = audit["sections"]["B_exposed_eval"]
        c = audit["sections"]["C_operator_constructed"]
        self.assertEqual((b["question_count"], c["question_count"]), (4, 8))
        self.assertEqual(b["mean_heterogeneous_minus_uniform"]["accuracy"], 0)
        self.assertEqual(c["mean_heterogeneous_minus_uniform"]["accuracy"], 0)
        self.assertTrue(math.isclose(b["mean_heterogeneous_minus_uniform"]["log_loss"],
                                     -0.0091799222554, abs_tol=1e-10))
        self.assertTrue(math.isclose(c["mean_heterogeneous_minus_uniform"]["log_loss"],
                                     -0.0058623457379, abs_tol=1e-10))
        self.assertEqual(b["exploratory_two_sided_sign_flip_p_log_loss"], 0.25)
        self.assertEqual(c["exploratory_two_sided_sign_flip_p_log_loss"], 0.75)
        self.assertEqual(len(b["per_seed"]), 4)
        self.assertEqual(len(c["per_seed"]), 4)

    def test_corrupted_record_is_not_accepted_as_evidence(self):
        for change in ("probability", "missing_arm", "identity", "label", "cost", "claim"):
            bad = copy.deepcopy(self.raw)
            arm = bad["runs"][0]
            if change == "probability":
                arm["scores"]["B_exposed_eval"]["rows"][0]["p_yes"] = float("nan")
            elif change == "missing_arm":
                bad["runs"].pop()
            elif change == "identity":
                arm["scores"]["B_exposed_eval"]["rows"][0]["id"] = "forged"
            elif change == "label":
                arm["scores"]["B_exposed_eval"]["rows"][0]["truth"] = "maybe"
            elif change == "cost":
                arm["actual_updated_parameter_elements"] += 1
            else:
                bad["authority"] = "PRODUCTION_AUTHORIZED"
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyse(bad)

    def test_archive_identity_rejects_unrecognized_bytes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "RESULT.json"
            path.write_text('{"schema":"fake"}')
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                read_archive(path)


if __name__ == "__main__":
    unittest.main()
