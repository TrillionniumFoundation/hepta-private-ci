"""E17 research: ORIGINAL pretrained Reader answer-information audit, label blind.

The canonical pre-score ZIP is verified by the E14 source owner before opening.
No original labels or prior scored ZIP members are read by this module.
Differences in frozen logits measure dependence on answer wording, NOT whether
that dependence is useful/causal for human task success. Never grant FinalUse.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
from math import exp, isfinite
from time import process_time_ns

from e14_multirc_route import (ARMS, ARCHIVE_SHA, OBS_ID, read_prelabel,
                              write_once)

SCHEMA = "hepta.e17.original-reader-answer-identifiability.v1"
DESCRIPTIVE_EPSILON = 0.001  # inherited V1 descriptor, NOT calibrated tolerance


def _prob(delta: float) -> float:
    if type(delta) not in (int, float) or not isfinite(delta) or abs(delta) > 200:
        raise ValueError("unbounded or nonnumeric pretrained margin")
    return 1 / (1 + exp(-delta)) if delta >= 0 else exp(delta) / (1 + exp(delta))


def analyze_observation(obs: dict) -> dict:
    """Original 33 real model logits, no human labels, no fitted parameters."""
    if (type(obs) is not dict or obs.get("observation_id") != OBS_ID
            or obs.get("actual_candidate_count") != 33 or obs.get("question_count") != 8
            or obs.get("passage_count") != 4 or type(obs.get("rows")) is not list
            or type(obs.get("predictions")) is not dict
            or set(obs["predictions"]) != set(ARMS)):
        raise ValueError("must inspect exact original pre-score receipt")
    if len(obs["rows"]) != 33 or any(len(obs["predictions"][a]) != 33 for a in ARMS):
        raise ValueError("incomplete 33-candidate frozen Reader panel")
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    task_ids: set[str] = set()
    for i, r in enumerate(obs["rows"]):
        if (type(r) is not dict or type(r.get("source_group")) is not str
                or type(r.get("question_slot")) is not int or r["question_slot"] not in (0, 1)
                or type(r.get("task_id")) is not str or r["task_id"] in task_ids):
            raise ValueError("duplicate/malformed original source IDs")
        task_ids.add(r["task_id"])
        groups[r["source_group"], r["question_slot"]].append(i)
    if len(groups) != 8 or len({k[0] for k in groups}) != 4 or any(
            not 2 <= len(v) <= 8 for v in groups.values()):
        raise ValueError("incomplete genuine same-question alternatives")
    questions = []
    for key in sorted(groups):
        indices = groups[key]
        per = {}
        for arm in ARMS:
            signed = []
            for i in indices:
                x = obs["predictions"][arm][i]
                if (type(x) is not dict or x.get("task_id") != obs["rows"][i]["task_id"]
                        or x.get("source_group") != key[0]
                        or x.get("question_slot") != key[1]
                        or type(x.get("logits")) is not list or len(x["logits"]) != 2
                        or any(type(v) not in (int, float) or not isfinite(v) for v in x["logits"])):
                    raise ValueError("incomplete pretrained logit/source binding")
                signed.append(float(x["logits"][1] - x["logits"][0]))
            p = [_prob(x) for x in signed]
            per[arm] = {
                "margin_span": max(signed) - min(signed),
                "probability_span": max(p) - min(p),
                "exactly_equal_margin_pairs": sum(a == b for a, b in combinations(signed, 2)),
                "candidate_pair_count": len(indices) * (len(indices) - 1) // 2,
                "distinct_hard_label_count": len({x >= 0 for x in signed}),
                "unlabeled_positive_class_count": sum(x >= 0 for x in signed),
            }
        questions.append({"source_group": key[0], "question_slot": key[1],
                          "candidate_count": len(indices), "arms": per})
    summary = {}
    for arm in ARMS:
        rows = [q["arms"][arm] for q in questions]
        summary[arm] = {
            "exactly_invariant_questions": sum(v["margin_span"] == 0 for v in rows),
            "near_invariant_questions_descriptive": sum(v["probability_span"] <= DESCRIPTIVE_EPSILON for v in rows),
            "one_hard_prediction_per_question": sum(v["distinct_hard_label_count"] == 1 for v in rows),
            "equal_margin_answer_pairs": sum(v["exactly_equal_margin_pairs"] for v in rows),
            "total_within_question_pairs": sum(v["candidate_pair_count"] for v in rows),
            "max_probability_span": max(v["probability_span"] for v in rows),
            "mean_probability_span": sum(v["probability_span"] for v in rows) / 8,
        }
    if sum(q["candidate_count"] for q in questions) != 33:
        raise ValueError("incomplete original candidate census")
    return {
        "schema": SCHEMA, "source_model_receipt_id": OBS_ID,
        "source_model_zip_sha256": ARCHIVE_SHA, "authority": "DENY_ALL",
        "source_passage_count": 4, "original_question_count": 8,
        "real_pretrained_candidate_count": 33,
        "human_labels_opened_in_blind_stage": False,
        "scored_historical_archive_member_opened_in_blind_stage": False,
        "new_pretrained_model_forwards": 0,
        "descriptive_probability_epsilon": DESCRIPTIVE_EPSILON,
        "questions": questions, "summary": summary,
        "answer_signal_is_not_verified_semantic_accuracy": True,
        "low_answer_variation_is_not_a_proof_of_no_useful_information": True,
        "same_question_answer_invariance_qualifies_system2": False,
        "model_selected": False, "production_accepted": False,
    }


def produce(archive: str, output: str) -> str:
    started = process_time_ns()
    source = read_prelabel(archive)
    record = analyze_observation(source)
    if process_time_ns() <= started:
        raise ValueError("nonpositive diagnostic clock observation")
    return write_once(output, record)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print(produce(args.archive, args.output), "DENY_ALL")
