"""Fail-closed tampering checks against THREE original model-output ZIPs.

The standalone workflow supplies pinned raw artifacts. When they have not
been supplied, these checks skip; they never synthesize successful model runs.
"""

import os
from pathlib import Path
import tempfile
import unittest

from stem_strict_three_success import PINS, _load_archive, compare_pinned_runs


class ThreeCompleteRealRunsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "STEM_REPRO_INPUT_DIR" not in os.environ:
            raise unittest.SkipTest("three original model artifacts not mounted")
        directory = Path(os.environ["STEM_REPRO_INPUT_DIR"])
        cls.archives = {
            run: _load_archive(directory / f"{run}.zip", run) for run in PINS
        }
        cls.directory = directory

    def amend(self, run="38114716982", **changes):
        updated = dict(self.archives)
        updated[run] = dict(self.archives[run], **changes)
        return updated

    def test_full_real_three_run_manifests_and_correct_denominators(self):
        receipt = compare_pinned_runs(self.archives)
        self.assertEqual(len(receipt["run_details"]), 3)
        self.assertEqual(
            [
                receipt["run_details"][run]["verified_sha256_manifest_members"]
                for run in PINS
            ],
            [127, 130, 130],
        )
        self.assertEqual(receipt["attempts_per_run"], 576)
        self.assertTrue(
            all(
                x["changed_exact_record_fields"]["answer"] == 0
                for x in receipt["comparisons"].values()
            )
        )
        self.assertFalse(receipt["production_accepted"])

    def test_bitwise_latent_drift_must_not_be_hidden_by_identical_answers(self):
        receipt = compare_pinned_runs(self.archives)
        self.assertTrue(
            receipt["comparisons"]["38114504922"][
                "persistent_training_bitwise_identical"
            ]
        )
        third = receipt["comparisons"]["38114716982"]
        self.assertFalse(third["persistent_training_bitwise_identical"])
        self.assertEqual(third["changed_exact_record_fields"]["feature_digest"], 576)
        self.assertGreater(third["maximum_absolute_head_tensor_delta"], 0)
        self.assertEqual(
            third["changed_exact_record_fields"]["generated_ids_digest"], 0
        )

    def test_reader_output_bytes_tampered_but_source_unchanged_rejected(self):
        raw = self.archives["38114716982"]["predictions"].copy()
        raw[0] = dict(raw[0], answer=raw[0]["answer"] + " mutated")
        with self.assertRaisesRegex(ValueError, "native answer"):
            compare_pinned_runs(self.amend(predictions=raw))

    def test_changed_reader_identity_prompt_tokens_and_evidence_rejected(self):
        source = self.archives["38114716982"]["predictions"]
        for key in (
            "generator_identity",
            "generator_profile",
            "input_ids_digest",
            "generated_ids_digest",
            "delivered_evidence",
        ):
            rows = source.copy()
            rows[0] = dict(
                rows[0], receipt=dict(rows[0]["receipt"], **{key: "changed"})
            )
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "Reader token"),
            ):
                compare_pinned_runs(self.amend(predictions=rows))

    def test_incomplete_planned_census_fails_not_silently_skipped(self):
        rows = self.archives["38114716982"]["predictions"][:-1]
        with self.assertRaisesRegex(ValueError, "incomplete native planned"):
            compare_pinned_runs(self.amend(predictions=rows))

    def test_changed_model_or_question_cohort_cannot_pass(self):
        plan = self.archives["38114716982"]["plan"]
        for field in ("dataset_sha256", "reader_inventory", "primary_policy"):
            altered = dict(plan, **{field: "different"})
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "registration drift"),
            ):
                compare_pinned_runs(self.amend(plan=altered))

    def test_production_admission_not_self_issued(self):
        report = dict(
            self.archives["38114716982"]["report"],
            production_accepted=True,
        )
        with self.assertRaisesRegex(ValueError, "cannot certify"):
            compare_pinned_runs(self.amend(report=report))

    def test_older_missing_posthoc_observer_not_backfilled(self):
        result = compare_pinned_runs(self.archives)
        self.assertIsNone(
            result["run_details"]["38114107704"][
                "final_checkpoint_test_transfer_native_support_net_gain"
            ]
        )
        self.assertEqual(
            result["run_details"]["38114716982"][
                "final_checkpoint_test_transfer_native_support_net_gain"
            ],
            0,
        )
        self.assertEqual(
            result["run_details"]["38114716982"]["candidate_weak_source_retrieval_gap"][
                "test"
            ]["support_missing_from_pool"],
            2,
        )

    def test_corrupting_even_one_zip_byte_fails_before_model_receipt_read(self):
        source = (self.directory / "38114716982.zip").read_bytes()
        broken = bytearray(source)
        broken[123] ^= 1
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.zip"
            path.write_bytes(broken)
            with self.assertRaisesRegex(ValueError, "ZIP digest"):
                _load_archive(path, "38114716982")


if __name__ == "__main__":
    unittest.main()
