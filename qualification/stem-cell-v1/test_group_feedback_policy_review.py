"""Exercise the real original stdlib review with source-only feedback-policy cases."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from group_attention_campaign_review import _digest, review
from test_group_attention_campaign_review import fixture


def seal_policy(root):
    records = fixture(root)
    protocol = copy.deepcopy(records["protocol"])
    report = copy.deepcopy(records["report"])
    protocol["training_feedback_policy"] = "no_verifier_v1"
    for name, receipt in report["training"].items():
        receipt.update(training_feedback_policy="no_verifier_v1",
                       training_feedback_callback=False,
                       training_verifier_oracle_enabled=False,
                       training_feedback_calls=0, nonzero_feedback_batches=0,
                       feedback_interface="no_training_verifier_and_zero_initial_feedback")
    report["training"]["core"]["depth_supervision"] = "mean_all_steps"
    report["protocol_sha256"] = _digest(protocol)
    (root / "protocol.json").write_text(json.dumps(protocol))
    (root / "report.json").write_text(json.dumps(report))
    return protocol, report


class TrainFeedbackPolicyAuditTests(unittest.TestCase):
    def test_independent_original_audit_accepts_zero_oracle_controls(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            seal_policy(root)
            self.assertTrue(review(root)["passed"])

    def test_reject_untrusted_training_oracle_receipt(self):
        for field, value in (
            ("training_feedback_calls", 2),
            ("nonzero_feedback_batches", 1),
            ("training_feedback_callback", True),
            ("training_verifier_oracle_enabled", True),
            ("training_feedback_policy", "legacy_oracle_v1"),
            ("depth_supervision", "final_step"),
        ):
            with tempfile.TemporaryDirectory() as name:
                root = Path(name)
                _, report = seal_policy(root)
                report["training"]["core"][field] = value
                (root / "report.json").write_text(json.dumps(report))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    review(root)

    def test_reject_unregistered_policy_even_if_resigned_locally(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            protocol, report = seal_policy(root)
            protocol["training_feedback_policy"] = "invented"
            report["protocol_sha256"] = _digest(protocol)
            (root / "protocol.json").write_text(json.dumps(protocol))
            (root / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "TRAIN verifier"):
                review(root)


if __name__ == "__main__":
    unittest.main()
