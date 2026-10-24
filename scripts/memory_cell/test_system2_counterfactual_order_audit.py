"""Strict paired-order metrics: correct token != cited answer != safe refusal."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system2_counterfactual_order_audit import (
    ARMS,
    CAP,
    FROZEN_READER_SHA256,
    ORDER_ARMS,
    read_original,
    run,
    summarize,
)
from system2_multihop_counterfactual import cases, select


def synthetic_data(*, style="grounded"):
    pairs = cases()
    data = {}
    for pair in pairs:
        for case in pair:
            for arm in ARMS:
                selection = select(arm, case.question, case.documents)
                if arm in ORDER_ARMS:
                    answer = (
                        case.answer
                        + " "
                        + " ".join(
                            "[E" + str(i + 1) + "]" for i in range(len(selection))
                        )
                    )
                    if style == "wrong":
                        answer = pair[0].answer
                    elif style == "uncited":
                        answer = case.answer
                else:
                    answer = "I do not have enough evidence."
                key = (case.question.identity, arm)
                data[key] = dict(
                    qid=case.question.identity,
                    arm=arm,
                    answer=answer,
                    status="succeeded",
                    selected=[d.identity for d in selection],
                    reader=dict(
                        reader_identity=FROZEN_READER_SHA256,
                        reader_profile="mock-frozen",
                        generated_tokens=CAP,
                        input_tokens=80 + len(selection) * 20,
                        input_ids_digest=hashlib.sha256(
                            (
                                case.question.identity
                                + repr(tuple(d.identity for d in selection))
                            ).encode()
                        ).hexdigest(),
                    ),
                )
    return dict(
        rows=data,
        pairs=pairs,
        profile="mock-frozen",
        original_prediction_sha256="c" * 64,
        archive_sha256="d" * 64,
        internal_verified_files=21,
    )


class CounterfactualOrderTests(unittest.TestCase):
    def test_16_paired_units_not_160_independent_trials(self):
        out = summarize(synthetic_data())
        self.assertEqual(
            (
                out["distinct_causal_pairs"],
                out["question_variants"],
                out["original_model_calls"],
                out["new_model_calls"],
            ),
            (16, 32, 160, 0),
        )
        self.assertEqual(
            out["paired_order"]["both_correct_pairs_by_order"],
            {"joined_top3": 16, "reversed_join_top3": 16},
        )

    def test_sufficient_answer_without_citations_is_not_grounded(self):
        out = summarize(synthetic_data(style="uncited"))
        for row in out["group_by_arm"]:
            if row["arm"] in ORDER_ARMS:
                self.assertEqual(row["exact_target_only"], 32)
                self.assertEqual(row["strict_answer_and_complete_citation"], 0)
        self.assertEqual(
            out["paired_order"]["both_correct_pairs_by_order"],
            {"joined_top3": 16, "reversed_join_top3": 16},
        )
        self.assertEqual(
            out["paired_order"]["both_grounded_pairs_by_order"],
            {"joined_top3": 0, "reversed_join_top3": 0},
        )

    def test_frozen_target_but_wrong_answer_cannot_count_flip(self):
        out = summarize(synthetic_data(style="wrong"))
        self.assertEqual(
            out["paired_order"]["both_correct_pairs_by_order"],
            {"joined_top3": 0, "reversed_join_top3": 0},
        )
        self.assertEqual(
            out["paired_order"]["identical_answer_despite_target_flip"],
            {"joined_top3": 16, "reversed_join_top3": 16},
        )

    def test_reversed_source_identity_must_truly_be_reversed(self):
        data = synthetic_data()
        pair = data["pairs"][0]
        qid = pair[0].question.identity
        data["rows"][qid, ORDER_ARMS[1]]["selected"][0] = "FORGED-EXCERPT"
        with self.assertRaisesRegex(ValueError, "reversed arm"):
            summarize(data)

    def test_token_cardinality_cannot_drift_across_order_contrast(self):
        data = synthetic_data()
        qid = data["pairs"][0][0].question.identity
        data["rows"][qid, ORDER_ARMS[1]]["reader"]["input_tokens"] += 1
        with self.assertRaisesRegex(ValueError, "reversed arm"):
            summarize(data)

    def test_identical_tokenized_prompt_cannot_claim_order_intervention(self):
        data = synthetic_data()
        qid = data["pairs"][1][0].question.identity
        left = data["rows"][qid, ORDER_ARMS[0]]["reader"]["input_ids_digest"]
        data["rows"][qid, ORDER_ARMS[1]]["reader"]["input_ids_digest"] = left
        with self.assertRaisesRegex(ValueError, "reversed arm"):
            summarize(data)

    def test_model_calls_are_never_simulated_in_audit(self):
        out = summarize(synthetic_data())
        self.assertFalse(out["production_accepted"])
        self.assertFalse(out["general_ndu_fbsde_gain"])
        self.assertTrue(out["correlated_synthetic_pairs"])
        self.assertEqual(out["new_model_calls"], 0)

    def test_external_pinned_parent_must_not_be_optional(self):
        with patch(
            "system2_counterfactual_order_audit.verified_archive",
            side_effect=ValueError("untrusted archive"),
        ):
            with self.assertRaisesRegex(ValueError, "untrusted archive"):
                read_original(Path("arbitrary.zip"))

    def test_missing_pair_cannot_silently_reduce_denominator(self):
        data = synthetic_data()
        data["pairs"] = data["pairs"][:-1]
        with self.assertRaisesRegex(ValueError, "16-pair"):
            summarize(data)

    def test_no_file_written_after_pinned_archive_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order.json"
            with patch(
                "system2_counterfactual_order_audit.read_original",
                side_effect=ValueError("invalid historical SHA"),
            ):
                with self.assertRaisesRegex(ValueError, "invalid historical SHA"):
                    run(Path(tmp) / "fake.zip", path)
            self.assertFalse(path.exists())

    def test_summary_fields_do_not_include_case_gold_or_raw_answers(self):
        out = summarize(synthetic_data())
        exported = json.dumps(out, sort_keys=True)
        self.assertNotIn("selected_evidence", exported)
        for p in out["paired_order"]["pairs"]:
            self.assertNotIn("answer", p)


if __name__ == "__main__":
    unittest.main()
