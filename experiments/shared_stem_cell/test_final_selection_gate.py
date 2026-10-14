import unittest

from experiments.shared_stem_cell.final_selection_gate import COVERAGE, SCHEMA, STEMS, SCALES, InvalidEvidence, audit

H = "a" * 64
R = "b" * 40


def bundle():
    def make_arm(name, *, stem, gain, head=16384):
        cases = [
            {"case_id": f"f{window}-{i}", "group_id": f"source-{i}",
             "window": f"future_{window}", "input_sha256": f"{window * 1000 + i:064x}",
             "observed_at": f"2026-10-{14 + window}T12:00:00+00:00",
             "status": "ok", "external_ndu": gain, "old_task": True,
             "negative_transfer": False}
            for window in (1, 2) for i in range(32)
        ]
        return {"id": name, "stem_id": stem, "model_revision": R,
                "stem_sha256": H, "tokenizer_sha256": H, "head_sha256": H,
                "head_parameters": head, "seed": 17, "training_steps": 120,
                "frozen_encoder": True, "cases": cases,
                "quality": {"brier": 0.1, "ece": 0.08,
                            "ood_false_acceptance_rate": 0.0, "old_task_regression": 0.0},
                "scales": [{"cells": n, "p95_ms": 10, "p99_ms": 13,
                            "peak_rss_bytes": 500_000_000, "gpu_peak_bytes": 200_000_000,
                            "recovery_ms": 18, "wal_fsync_count": 50} for n in SCALES]}
    arms = [make_arm("no_change", stem="no_change", gain=0, head=0)]
    arms.extend(make_arm(f"{name}-gated16k", stem=name, gain=0.15)
                for name in STEMS)
    return {"schema": SCHEMA, "origin": "measured", "protocol_sha256": H,
            "dataset_sha256": H, "host_profile_sha256": H,
            "observer_receipt_sha256": H, "freeze_at": "2026-10-14T00:00:00+00:00",
            "baseline": "no_change", "registered_arms": [a["id"] for a in arms],
            "training_steps": 120, "seed": 17, "bootstrap_replicates": 1000,
            "min_future_groups": 30,
            "limits": {"max_negative_transfer_rate": 0.02,
                       "max_old_task_regression": 0.02,
                       "max_brier_increase": 0.01, "max_ece_increase": 0.01,
                       "max_ood_false_acceptance_rate": 0.01, "max_p99_ms": 20,
                       "max_peak_rss_bytes": 1_000_000_000,
                       "max_gpu_peak_bytes": 1_000_000_000, "max_recovery_ms": 20},
            "coverage": {x: {"status": "measured", "artifact_sha256": H,
                             "arms": list(values)} for x, values in COVERAGE.items()},
            "arms": arms}


class SelectionGateTests(unittest.TestCase):
    def test_positive_paired_evidence_is_only_provisional(self):
        receipt = audit(bundle())
        self.assertIsNotNone(receipt["provisional_research_leader"])
        self.assertFalse(receipt["production_accepted"])
        self.assertFalse(receipt["model_selection_authority"])
        self.assertFalse(receipt["external_observer_signature_verified"])
        self.assertFalse(receipt["independent_source_groups_verified"])
        self.assertTrue(all(v["delta_ndu_lcb_familywise"] > 0 for v in receipt["arms"].values()))
        self.assertEqual(receipt["arms"]["mmbert-small-gated16k"]["adjusted_one_sided_alpha"], .0125)

    def test_fixture_cannot_qualify(self):
        b = bundle()
        b["origin"] = "fixture"
        self.assertIsNone(audit(b)["provisional_research_leader"])

    def test_missing_experiment_and_model_coverage_block(self):
        b = bundle()
        b["coverage"]["E5"]["status"] = "pending"
        self.assertIsNone(audit(b)["provisional_research_leader"])
        b = bundle()
        b["coverage"]["E1"]["arms"].remove("modernbert-base")
        self.assertIsNone(audit(b)["provisional_research_leader"])

    def test_future_source_group_count_gates(self):
        b = bundle()
        b["min_future_groups"] = 50
        self.assertIsNone(audit(b)["provisional_research_leader"])

    def test_cannot_drop_failed_case_or_reassign_source(self):
        b = bundle()
        b["arms"][1]["cases"].pop()
        with self.assertRaisesRegex(InvalidEvidence, "unpaired"):
            audit(b)
        b = bundle()
        b["arms"][1]["cases"][0]["group_id"] = "fabricated"
        with self.assertRaisesRegex(InvalidEvidence, "unpaired"):
            audit(b)

    def test_negative_transfer_and_calibration_veto(self):
        b = bundle()
        for row in b["arms"][1]["cases"]:
            row["negative_transfer"] = True
        self.assertFalse(audit(b)["arms"]["mmbert-small-gated16k"]["provisional_research_eligible"])
        b = bundle()
        b["arms"][1]["quality"]["brier"] = 0.3
        self.assertFalse(audit(b)["arms"]["mmbert-small-gated16k"]["quality_floors_reported"])

    def test_resource_and_recovery_veto(self):
        for key, bad in (("p99_ms", 25), ("recovery_ms", 25), ("peak_rss_bytes", 2_000_000_000)):
            with self.subTest(key=key):
                b = bundle()
                b["arms"][1]["scales"][3][key] = bad
                self.assertFalse(audit(b)["arms"]["mmbert-small-gated16k"]["physical_resource_floors_reported"])

    def test_missing_scale_is_malformed_not_ignored(self):
        b = bundle()
        b["arms"][1]["scales"].pop()
        with self.assertRaisesRegex(InvalidEvidence, "four physical scales"):
            audit(b)

    def test_nonchronological_windows_rejected(self):
        b = bundle()
        for arm in b["arms"]:
            for row in arm["cases"]:
                if row["window"] == "future_2":
                    row["observed_at"] = "2026-10-15T11:00:00Z"
        with self.assertRaisesRegex(InvalidEvidence, "not chronological"):
            audit(b)

    def test_impossible_future_and_floating_version_rejected(self):
        b = bundle()
        b["arms"][0]["cases"][0]["observed_at"] = "2026-10-13T00:00:00Z"
        with self.assertRaisesRegex(InvalidEvidence, "predates"):
            audit(b)
        b = bundle()
        b["arms"][1]["model_revision"] = "main"
        with self.assertRaisesRegex(InvalidEvidence, "not pinned"):
            audit(b)

    def test_broken_training_fairness_and_positive_failed_utility(self):
        b = bundle()
        b["arms"][1]["training_steps"] = 240
        with self.assertRaisesRegex(InvalidEvidence, "unfair"):
            audit(b)
        b = bundle()
        b["arms"][1]["cases"][0]["status"] = "failed"
        with self.assertRaisesRegex(InvalidEvidence, "positive utility"):
            audit(b)

    def test_registration_fails_closed(self):
        b = bundle()
        b["registered_arms"].pop()
        with self.assertRaisesRegex(InvalidEvidence, "preregistered"):
            audit(b)


if __name__ == "__main__":
    unittest.main()
