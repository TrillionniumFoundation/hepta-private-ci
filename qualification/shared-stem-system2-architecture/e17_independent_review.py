"""Independent E17 recomputation and historical-human mixed-question bound.

Reads original historical scored aggregate ONLY after the blind prediction
file is create-only sealed. Historical source score is not a new independent
human signer or a new heldout task outcome. No new pretrained model forwards.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
from math import exp, isclose, isfinite
from pathlib import Path
from zipfile import ZipFile

from e14_multirc_route import ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel, strict_json, write_once

SCHEMA = "hepta.e17.independent-reader-information-no-go.v1"
BLIND_SCHEMA = "hepta.e17.original-reader-answer-identifiability.v1"
HISTORICAL_SCORE = "multirc-native-candidate-scores/scores.json"
HISTORICAL_SHA = "3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4"


def _positive(logits):
    d = float(logits[1] - logits[0])
    if not isfinite(d) or abs(d) > 200:
        raise ValueError("unbounded historical logits")
    return exp(d) / (1 + exp(d)) if d < 0 else 1 / (1 + exp(-d))


def verify_blind_against_original(obs, receipt):
    expected_keys = {
        "schema", "source_model_receipt_id", "source_model_zip_sha256", "authority",
        "source_passage_count", "original_question_count", "real_pretrained_candidate_count",
        "human_labels_opened_in_blind_stage", "scored_historical_archive_member_opened_in_blind_stage",
        "new_pretrained_model_forwards", "descriptive_probability_epsilon", "questions", "summary",
        "answer_signal_is_not_verified_semantic_accuracy",
        "low_answer_variation_is_not_a_proof_of_no_useful_information",
        "same_question_answer_invariance_qualifies_system2", "model_selected", "production_accepted",
    }
    if (type(receipt) is not dict or set(receipt) != expected_keys
            or receipt.get("schema") != BLIND_SCHEMA
            or receipt.get("source_model_zip_sha256") != ARCHIVE_SHA
            or receipt.get("source_model_receipt_id") != OBS_ID
            or receipt.get("authority") != "DENY_ALL"
            or receipt.get("production_accepted") is not False
            or receipt.get("model_selected") is not False
            or receipt.get("same_question_answer_invariance_qualifies_system2") is not False
            or receipt.get("human_labels_opened_in_blind_stage") is not False
            or receipt.get("scored_historical_archive_member_opened_in_blind_stage") is not False
            or type(receipt.get("new_pretrained_model_forwards")) is not int
            or receipt.get("new_pretrained_model_forwards") != 0
            or receipt.get("source_passage_count") != 4
            or receipt.get("original_question_count") != 8
            or receipt.get("real_pretrained_candidate_count") != 33
            or type(receipt.get("descriptive_probability_epsilon")) is not float
            or receipt.get("descriptive_probability_epsilon") != .001
            or receipt.get("low_answer_variation_is_not_a_proof_of_no_useful_information") is not True
            or receipt.get("answer_signal_is_not_verified_semantic_accuracy") is not True):
        raise ValueError("unqualified original Reader geometry result")
    groups = defaultdict(list)
    for idx, item in enumerate(obs["rows"]):
        groups[(item["source_group"], item["question_slot"])].append(idx)
    if len(groups) != 8 or type(receipt.get("questions")) is not list or len(receipt["questions"]) != 8:
        raise ValueError("missing question panel")
    grand = {arm: {"exact": 0, "near": 0, "constant": 0, "pairs": 0, "total_pairs": 0} for arm in ARMS}
    for record, (key, indices) in zip(receipt["questions"], sorted(groups.items()), strict=True):
        if (type(record) is not dict or set(record) != {"source_group", "question_slot", "candidate_count", "arms"}
                or (record["source_group"], record["question_slot"]) != key
                or record["candidate_count"] != len(indices)
                or type(record["arms"]) is not dict or set(record["arms"]) != set(ARMS)):
            raise ValueError("modified original question inventory")
        for arm in ARMS:
            signed = []
            probabilities = []
            for index in indices:
                prediction = obs["predictions"][arm][index]
                if prediction["task_id"] != obs["rows"][index]["task_id"]:
                    raise ValueError("historical answer alignment changed")
                margins = prediction["logits"]
                signed.append(margins[1] - margins[0])
                probabilities.append(_positive(margins))
            expected = {"margin_span": max(signed) - min(signed),
                        "probability_span": max(probabilities) - min(probabilities),
                        "exactly_equal_margin_pairs": sum(a == b for a, b in combinations(signed, 2)),
                        "candidate_pair_count": len(indices) * (len(indices) - 1) // 2,
                        "distinct_hard_label_count": len({x >= 0 for x in signed}),
                        "unlabeled_positive_class_count": sum(x >= 0 for x in signed)}
            seen = record["arms"][arm]
            if type(seen) is not dict or set(seen) != set(expected):
                raise ValueError("incomplete Reader contrastive result")
            for field, value in expected.items():
                claimed = seen[field]
                if type(value) is float:
                    if type(claimed) is not float or not isclose(value, claimed, abs_tol=2e-15, rel_tol=0):
                        raise ValueError("altered original Reader span")
                elif type(claimed) is not int or claimed != value:
                    raise ValueError("altered original Reader contrastive count")
            obj = grand[arm]
            obj["exact"] += int(expected["margin_span"] == 0)
            obj["near"] += int(expected["probability_span"] <= .001)
            obj["constant"] += int(expected["distinct_hard_label_count"] == 1)
            obj["pairs"] += expected["exactly_equal_margin_pairs"]
            obj["total_pairs"] += expected["candidate_pair_count"]
    for arm, result in grand.items():
        sums = receipt.get("summary", {}).get(arm)
        expect = {"exactly_invariant_questions": result["exact"],
                  "near_invariant_questions_descriptive": result["near"],
                  "one_hard_prediction_per_question": result["constant"],
                  "equal_margin_answer_pairs": result["pairs"],
                  "total_within_question_pairs": result["total_pairs"]}
        if type(sums) is not dict or set(sums) != set(expect) | {"mean_probability_span", "max_probability_span"}:
            raise ValueError("missing aggregate Reader contrastive evidence")
        for field, val in expect.items():
            if type(sums[field]) is not int or sums[field] != val:
                raise ValueError("fabricated frozen Reader summary")
        observed = [q["arms"][arm]["probability_span"] for q in receipt["questions"]]
        if not isclose(sums["mean_probability_span"], sum(observed) / 8, abs_tol=2e-15, rel_tol=0):
            raise ValueError("altered mean signal")
        if not isclose(sums["max_probability_span"], max(observed), abs_tol=2e-15, rel_tol=0):
            raise ValueError("altered maximum signal")
    return grand


def review(archive: str, blind_path: str, blind_sha256: str, output: str) -> str:
    raw = Path(blind_path).read_bytes()
    if not 0 < len(raw) <= 100_000 or sha256(raw).hexdigest() != blind_sha256:
        raise ValueError("must seal blind file bytes before scored review")
    blind = strict_json(raw)
    obs = read_prelabel(archive)  # independently original SHA/reality checked
    summary = verify_blind_against_original(obs, blind)
    with ZipFile(archive) as z:
        score_bytes = z.read(HISTORICAL_SCORE)
    if sha256(score_bytes).hexdigest() != HISTORICAL_SHA:
        raise ValueError("historical original score bytes changed")
    previous = strict_json(score_bytes)
    if (previous.get("schema") != "hepta.multirc.genuine-answer-slate-evaluation.v1"
            or previous.get("observation_id") != OBS_ID
            or previous.get("candidate_count") != 33
            or previous.get("question_count") != 8
            or previous.get("independent_test_quality_established") is not False
            or previous.get("production_authorized") is not False
            or type(previous.get("results")) is not dict
            or set(previous["results"]) != set(ARMS)):
        raise ValueError("historical human-label-owner receipt missing")
    for arm, item in previous["results"].items():
        if (item.get("total") != 33 or item.get("registered_questions") != 8
                or item.get("mixed_label_question_count") != 8
                or item.get("complete_question_count") != 0):
            raise ValueError("mixed human labels cannot be re-established")
    # Proven only for fixed prediction driven solely by per-question-constant
    # no-query features; no inference about possible richer Reader architectures.
    if summary["no_query"]["constant"] != 8 or summary["no_query"]["exact"] != 8:
        raise ValueError("premise of same-question-constant no-query control absent")
    result = {
        "schema": SCHEMA, "authority": "DENY_ALL", "source_blind_sha256": blind_sha256,
        "historical_original_score_sha256": HISTORICAL_SHA,
        "source_model_archive_sha256": ARCHIVE_SHA, "pretrained_model_new_forward_count": 0,
        "original_source_passage_count": 4, "original_question_count": 8,
        "real_model_candidate_count": 33,
        "original_human_source_groups_with_both_labels": 8,
        "no_query_same_hard_label_questions": summary["no_query"]["constant"],
        "no_query_exactly_constant_questions": summary["no_query"]["exact"],
        "no_query_frozen_reader_complete_question_correct_bound": 0,
        "no_query_candidate_invariant_head_can_complete_mixed_question": False,
        "conditioned_exactly_constant_questions": summary["conditioned"]["exact"],
        "conditioned_near_invariant_questions": summary["conditioned"]["near"],
        "conditioned_same_hard_prediction_questions": summary["conditioned"]["constant"],
        "all_four_frozen_original_readers_recompute_labelblind_spans": True,
        "original_human_labels_not_independently_resigned": True,
        "not_a_prospective_reader_learning_result": True,
        "independent_future_source_groups": 0,
        "e15_e16_heldout_human_success_observed": False,
        "full_fbsde_utility_advantage_established": False,
        "selected_head_or_model": False, "production_accepted": False,
    }
    return write_once(output, result)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "blind", "blind-sha256", "output"):
        ap.add_argument("--" + name, required=True)
    opt = ap.parse_args()
    print(review(opt.archive, opt.blind, opt.blind_sha256, opt.output), "DENY_ALL")
