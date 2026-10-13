"""Pure regression tests; model outputs may only come from exact pinned ZIPs."""

from pathlib import Path
import unittest

from reader_three_cohort_gate import join_verified, audit


READER = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"


def fixture():
    cross = {
        "schema": "hepta.memory-cell.cross-population-evidence.v1",
        "source_zip_sha256": {x: "a" * 64 for x in (
            "event_model", "event_replay", "locomo_public", "locomo_retrieval",
            "locomo_targets", "locomo_model", "locomo_score")},
        "reader_identity": READER,
        "observed_completed_model_calls": 144,
        "pooled_accuracy": None,
        "controlled_authored_event": {
            "original_model_calls": 112,
            "calibration_stable_under_leave_one_out": False,
            "arms": {
                "entity_time": {
                    "strict_correct": 8,
                    "correct_with_full_public_citation_path": 4,
                },
                "organized": {
                    "strict_correct": 8,
                    "correct_with_full_public_citation_path": 4,
                },
            },
        },
        "published_locomo": {
            "original_model_calls": 32,
            "source_family_proxies": 2,
            "published_development_questions": 16,
            "arms": {
                "lexical_k4": {
                    "mean_diagnostic_token_f1": 0.172082580982,
                    "prompt_tokens": 6254,
                    "successful_model_calls": 16,
                },
                "lexical_k8": {
                    "mean_diagnostic_token_f1": 0.111481900950,
                    "prompt_tokens": 10473,
                    "successful_model_calls": 16,
                },
            },
        },
        "qualification": {
            "frozen_reader_evidence_transfer_proven": False,
            "calibrated_k_stable": False,
            "independent_future_source_families": 0,
            "human_certified_sufficient_contexts": 0,
            "semantic_citation_precision": None,
            "parametric_memory_training_qualified": False,
            "production_accepted": False,
        },
    }
    pub = {
        "schema": "hepta.locomo.publisher-support-postrun.v1",
        "frozen_reader_identity": READER,
        "original_model_calls": 16,
        "matched_public_family_proxies": 2,
        "exact_zip_sha256": {"plan": "b"*64, "reader": "c"*64, "score": "d"*64},
        "original_matched_f1": {
            "lexical_k4": {
                "baseline_token_f1": 0.17208258098192508,
                "privileged_token_f1": 0.2643761961930344,
                "descriptive_delta": 0.09229361521110932,
                "paired_wins": 8,
                "paired_losses": 5,
                "paired_ties": 3,
            },
            "lexical_k8": {
                "baseline_token_f1": 0.11148190095003518,
                "privileged_token_f1": 0.2643761961930344,
                "descriptive_delta": 0.15289429524299925,
                "paired_wins": 10,
                "paired_losses": 3,
                "paired_ties": 3,
            },
        },
        "publisher_privileged_support_visible_effect": {
            "k4_missing_publisher_support": {"questions": 5},
            "k4_already_had_publisher_support": {"questions": 8},
        },
        "publisher_source_selection_is_privileged": True,
        "new_independently_admitted_source_families": 0,
        "independent_semantic_citation_judgement": False,
        "parameter_memory_gain_established": False,
        "production_accepted": False,
    }
    return cross, pub


class NoFalsePromotionTests(unittest.TestCase):
    def test_correct_lineage_keeps_all_no_go_boundaries(self):
        result = join_verified(*fixture())
        self.assertEqual(result["original_real_model_calls"], 160)
        self.assertEqual(result["distinct_evaluation_questions"], 24)
        self.assertEqual(result["real_calibration_calls"], 40)
        self.assertEqual(result["real_publisher_privileged_reader_calls"], 16)
        self.assertIsNone(result["pooled_answer_accuracy"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["parameter_memory_gain_established"])
        self.assertTrue(result["publisher_support_is_annotation_privileged_not_online"])
        self.assertAlmostEqual(
            result["comparable_published_locomo_f1"]["lexical_k4"][
                "descriptive_privileged_delta"
            ],
            0.09229361521110932,
        )

    def test_reader_identity_mismatch_is_not_cross_reader_gain(self):
        cross, pub = fixture()
        pub["frozen_reader_identity"] = "f" * 64
        with self.assertRaises(ValueError):
            join_verified(cross, pub)

    def test_missing_or_fake_generations_reject(self):
        for member, field, value in (
            ("cross", "observed_completed_model_calls", 143),
            ("publisher", "original_model_calls", 15),
            ("publisher", "matched_public_family_proxies", 3),
        ):
            cross, pub = fixture()
            (cross if member == "cross" else pub)[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                join_verified(cross, pub)

    def test_published_baseline_must_match_original_score(self):
        for name in ("lexical_k4", "lexical_k8"):
            cross, pub = fixture()
            pub["original_matched_f1"][name]["baseline_token_f1"] = .9999
            with self.subTest(name=name), self.assertRaises(ValueError):
                join_verified(cross, pub)

    def test_nonfinite_or_inconsistent_f1_reject(self):
        for bad in (float("nan"), float("inf"), -0.1, True):
            cross, pub = fixture()
            pub["original_matched_f1"]["lexical_k4"]["privileged_token_f1"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                join_verified(cross, pub)

    def test_claimed_independent_review_or_training_qualification_reject(self):
        cases = [
            ("cross", "qualification", "parametric_memory_training_qualified", True),
            ("cross", "qualification", "production_accepted", True),
            ("publisher", None, "publisher_source_selection_is_privileged", False),
            ("publisher", None, "independent_semantic_citation_judgement", True),
            ("publisher", None, "parameter_memory_gain_established", True),
        ]
        for who, sec, field, new in cases:
            cross, pub = fixture()
            block = cross if who == "cross" else pub
            (block[sec] if sec else block)[field] = new
            with self.subTest(field=field), self.assertRaises(ValueError):
                join_verified(cross, pub)

    def test_citation_and_graph_claim_reassignment_reject(self):
        for arm, field in (
            ("organized", "strict_correct"),
            ("organized", "correct_with_full_public_citation_path"),
        ):
            cross, pub = fixture()
            cross["controlled_authored_event"]["arms"][arm][field] = 7
            with self.subTest(field=field), self.assertRaises(ValueError):
                join_verified(cross, pub)

    def test_duplicate_or_missing_source_partition_rejects_before_open(self):
        with self.assertRaises(ValueError):
            audit({"publisher_model": Path("/no/such/file")})


if __name__ == "__main__":
    unittest.main()
