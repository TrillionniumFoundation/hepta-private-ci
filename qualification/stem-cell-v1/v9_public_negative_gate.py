"""Read-only source-only FAIL-CLOSED regression on V9 public negative result.

This does NOT rerun original pretrained weights. It checks public SHA-bound
numbers/negative authority and refuses an invented winning model or future data.
"""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA="hepta.stem.v9.original-minilm-locomo-continual-shadow.v1"
ROOTS=("conv-47","conv-48","conv-49","conv-50")
ARMS=("bm25_full","dense_full")+tuple(f"seed{s}/{a}" for s in (41,47,53)
      for a in ("frozen","new_only","low_lr","equal_budget_replay"))
EXPECTED={"bm25_full":372,"dense_full":223,
          "seed41/frozen":26,"seed41/new_only":15,"seed41/low_lr":11,"seed41/equal_budget_replay":17,
          "seed47/frozen":78,"seed47/new_only":35,"seed47/low_lr":36,"seed47/equal_budget_replay":50,
          "seed53/frozen":9,"seed53/new_only":6,"seed53/low_lr":2,"seed53/equal_budget_replay":6}


def verify(physical, scored, train, audit):
    if (physical.get("schema") != SCHEMA + ".original-physical-receipt"
        or scored.get("schema") != SCHEMA + ".postseal-weak-scored"
        or train.get("schema") != SCHEMA + ".postsealed-train-retention-diagnostic"
        or audit.get("schema") != SCHEMA + ".independent-private-recount"):
        raise ValueError("V9 exact public schema required")
    if (physical["original_predictions_sha256"] != scored["original_predictions_sha256"]
        or physical["original_predictions_sha256"] != train["original_prediction_sha256"]
        or physical["original_predictions_sha256"] != audit["original_prediction_sha256"]):
        raise ValueError("original sealed source identities changed")
    if (physical["actual_original_encoder_forward_batches"] != 492
        or physical["encoded_original_sources_and_questions"] != 7868
        or physical["actual_original_encoder_token_positions"] != 225366
        or physical["original_heldout_reader_answers"] != 0
        or physical["signed_model_owner"] is not False
        or physical["original_hf_operator_tokenizer_parity_verified"] is not False
        or physical["production_authorized"] is not False
        or physical["stem_winner_verified"] is not False
        or physical["retention_repair_verified"] is not False):
        raise ValueError("original model or authority claim unsupported")
    if (scored["heldout_question_total"] != 829
        or scored["heldout_source_family_count"] != 4
        or scored["independent_calendar_future_windows"] != 0
        or scored["publisher_weak_retrieval_proxy_only"] is not True
        or scored["independent_human_task_success"] is not None
        or scored["equal_total_lifecycle_compute"] is not False
        or scored["production_authorized"] is not False):
        raise ValueError("invalid weak-score report or false production qualification")
    scores = scored["per_arm_source_root_aggregates"]
    if set(scores) != set(ARMS):
        raise ValueError("missing original comparator")
    for arm in ARMS:
        rootrows=scores[arm]
        if set(rootrows) != set(ROOTS):
            raise ValueError("incomplete root-level denominator")
        if (sum(x["total_questions"] for x in rootrows.values()) != 829
            or sum(x["weak_supported"] for x in rootrows.values()) != 822
            or sum(x["unknown_annotation"] for x in rootrows.values()) != 7
            or sum(x["any_support_top3"] for x in rootrows.values()) != EXPECTED[arm]):
            raise ValueError("source-first negative retriever counts altered")
        for x in rootrows.values():
            if (not 0 <= x["all_support_top3"] <= x["any_support_top3"] <= x["weak_supported"]
                or x["unknown_annotation"]+x["weak_supported"] != x["total_questions"]):
                raise ValueError("publisher support counts inconsistent")
    if (len(physical["physical_train_rows"]) != 12
        or len(train["rows"]) != 12
        or train["complete_original_train_roots"] != 6
        or train["old_original_train_questions"] != 494
        or train["new_original_train_questions"] != 660
        or train["read_publisher_heldout_answers"] is not False
        or train["independent_old_task_holdout_retention_verified"] is not False
        or train["new_task_independent_generalization_verified"] is not False
        or train["original_V6_retention_blocker_closed"] is not False
        or train["production_authorized"] is not False):
        raise ValueError("old/new TRAIN-only diagnostic falsely promoted")
    for item in train["rows"]:
        if item["after"]["old_train"]["correct"] > item["after"]["old_train"]["total"]:
            raise ValueError("impossible old-training correctness")
        if item["after"]["new_train"]["correct"] > item["after"]["new_train"]["total"]:
            raise ValueError("impossible new-training correctness")
    if (audit["actual_physical_head_digest_replays"] != 12
        or audit["actual_original_head_source_rank_replays"] != 829*12
        or audit["independently_recomputed_family_arm_scores"] != 56
        or audit["replay_executed"] is not True
        or audit["task_success_or_model_superiority_qualified"] is not False
        or audit["production_authorized"] is not False):
        raise ValueError("independent audit scope/authority changed")
    return True


def main():
    base=Path(__file__).parent
    def read(name):return json.loads((base/name).read_bytes())
    verify(read("STEM_V9_PHYSICAL_RECEIPT_20261015.json"),
           read("STEM_V9_POSTSEAL_WEAK_SCORES_20261015.json"),
           read("STEM_V9_TRAIN_DIAGNOSTIC_20261015.json"),
           read("STEM_V9_INDEPENDENT_AUDIT_20261015.json"))
    print(json.dumps({"original_heldout_questions":829,"actual_original_pretrained_batches":492,
                      "source_gate_passed":True,"physical_model_rerun":False,
                      "retrained_head_winner":False,"production_authorized":False},sort_keys=True))

if __name__=="__main__":main()
