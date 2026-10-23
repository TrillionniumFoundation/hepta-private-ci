"""No model weights, data downloads, or promotion in these adversarial fixtures."""
import hashlib
import unittest

from replacement_gate import EXPECTED, SPLITS
from prepare_news_cohorts import ARCHIVE_SHA256
from replacement_source_audit import _frozen_rows_sha256, assess_source_binding


def fixture():
    cohorts = {}
    for split in SPLITS:
        cohorts[split] = [dict(source_id=f"{split}-{i}",
                               source_group_id=f"g-{split}-{i}", label=i % 4,
                               source_row_sha256=hashlib.sha256(f"{split}-{i}".encode()).hexdigest())
                          for i in range(8)]
    digest = _frozen_rows_sha256(cohorts)
    models = {}
    for name in EXPECTED:
        models[name] = {"candidate": name, "per_split_limit": 8,
                        "source_archive_sha256": ARCHIVE_SHA256,
                        "frozen_selected_rows_sha256": digest,
                        "scores": {split: {"rows": [dict(source_id=r["source_id"],
                                            source_group_id=r["source_group_id"],
                                            label=r["label"], language="en",
                                            is_ood=split == "ood") for r in cohort]}
                                   for split, cohort in cohorts.items()}}
    return models, {"source_archive_sha256": ARCHIVE_SHA256}, cohorts


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.models, self.manifest, self.cohorts = fixture()

    def audit(self):
        return assess_source_binding(self.models, self.manifest, self.cohorts, 8)

    def test_replay_consistent_still_review_only(self):
        r = self.audit()
        self.assertEqual(r["source_binding_preflight"], "REVIEW_REQUIRED")
        self.assertFalse(r["physical_model_forward_independently_attested"])
        self.assertFalse(r["production_activation_allowed"])

    def test_same_fake_manifest_across_arms_is_insufficient(self):
        for arm in self.models.values():
            arm["frozen_selected_rows_sha256"] = "0" * 64
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_relabel_with_matching_ids_rejected(self):
        for arm in self.models.values():
            arm["scores"]["future_1"]["rows"][0]["label"] = 2
        self.assertTrue(any("row 0" in e for e in self.audit()["blockers"]))

    def test_reordered_rows_rejected(self):
        self.models[EXPECTED[3]]["scores"]["future_2"]["rows"].reverse()
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_source_group_alias_rejected(self):
        self.models[EXPECTED[0]]["scores"]["calibration"]["rows"][1]["source_group_id"] = "fake"
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_cross_split_source_row_substitution_rejected(self):
        self.cohorts["future_1"][0]["source_row_sha256"] = "0" * 64
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_wrong_publisher_archive_rejected(self):
        self.manifest["source_archive_sha256"] = "f" * 64
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_missing_arm_or_changed_sample_budget_rejected(self):
        del self.models[EXPECTED[2]]
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")
        self.models, self.manifest, self.cohorts = fixture()
        self.models[EXPECTED[-1]]["per_split_limit"] = 16
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_malformed_scores_fail_closed(self):
        self.models[EXPECTED[1]]["scores"]["ood"] = {"rows": None}
        self.assertEqual(self.audit()["source_binding_preflight"], "BLOCKED")

    def test_unbounded_or_wrong_sampling_rejected(self):
        self.assertEqual(assess_source_binding(self.models, self.manifest,
                                               self.cohorts, 4096)["source_binding_preflight"], "BLOCKED")


    def test_workflow_uses_full_argv_and_source_replay(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows" /
                    "hepta-neuron-five-model-physical-shadow.yml").read_text()
        self.assertIn('"    unittest.main()
 + '{args[@]}"', workflow)
        self.assertNotIn('"    unittest.main()
 + '{args[$]}"', workflow)
        self.assertIn("replacement_source_audit.py", workflow)
        self.assertIn("test_replacement_source_audit.py", workflow)


if __name__ == "__main__":
    unittest.main()
