"""Independent read-only V9 source/feature/Head re-forward and label audit.

Original task truth is opened ONLY after the private precommit/answer seal.
The producer's ranking code is used for replay of exact physical Head tensors;
statistics are independently reconstructed without its scoring functions.
This is same-host independent file and tensor verification, NOT external reviewer
signature, HF numerical parity, prospective time-window or production admission.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time

SCHEMA = "hepta.stem.v9.original-minilm-locomo-continual-shadow.v1"
SHA_PRODUCER = "6d43bfdbd5613f885bc7722506eb847f3997a141f2464ea3cfa27c15396e97e6"
ORIGINAL_CORPUS_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ORIGINAL_MODEL_SHA = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"
ORIGINAL_TOKENIZER_SHA = "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"
OLD = ("conv-26", "conv-30", "conv-41")
NEW = ("conv-42", "conv-43", "conv-44")
HELD = ("conv-47", "conv-48", "conv-49", "conv-50")
SEEDS = (41, 47, 53)
ARMS = ("frozen", "new_only", "low_lr", "equal_budget_replay")
PUBLISHABLE = ("physical-receipt.json", "postseal-weak-score.json")
PRIVATE = ("source-only.json", "train-only-labels.json", "precommit.json",
           "original-predictions.json", "private-vectors.npy")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def hash_path(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def obj(path):
    data = json.loads(Path(path).read_bytes(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    return data


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def safe_tree(folder):
    folder = Path(folder)
    expect = set(PRIVATE + PUBLISHABLE)
    require(folder.is_dir() and not folder.is_symlink(), "unsafe experiment directory")
    found = {p.name for p in folder.iterdir()}
    require(found == expect, "exact private source/evidence file inventory changed")
    for p in folder.iterdir():
        require(p.is_file() and not p.is_symlink() and p.stat().st_size < 18_000_000,
                "unsafe/nonfinite source or output file")
    return folder


def check_documents(root, source, training, plan, pred, physical, post):
    require(source.get("schema") == SCHEMA + ".source-only", "wrong source schema")
    require(set(source) == {"schema", "families", "source_contains_publisher_gold",
                            "future_calendar_windows", "production_authorized"},
            "extra source fields may carry heldout gold")
    require(source["source_contains_publisher_gold"] is False
            and source["production_authorized"] is False
            and source["future_calendar_windows"] == 0, "unsafe source authority")
    require(set(source["families"]) == set(OLD + NEW + HELD), "source root missing")
    num = 0
    ids_by_family = {}
    source_roster = {}
    for f, body in source["families"].items():
        require(set(body) == {"passages", "questions"}, "source contains non-source data")
        docs = body["passages"]
        qs = body["questions"]
        require(len(docs) >= 100 and len(qs) >= 100, "source inventory abridged")
        require(all(isinstance(d, dict) and set(d) == {"id", "text"}
                    and isinstance(d["id"], str) and d["id"]
                    and isinstance(d["text"], str) and d["text"] for d in docs),
                "invalid original source-only texts")
        require(all(isinstance(q, dict) and set(q) == {"id", "text"}
                    and isinstance(q["text"], str) and q["text"].strip()
                    and q["id"] == f + "/q" + str(i) for i, q in enumerate(qs)),
                "source question IDs/bytes changed")
        docids = [d["id"] for d in docs]
        require(len(docids) == len(set(docids)), "duplicate source IDs")
        ids_by_family[f] = set(docids)
        source_roster.update({q["id"]: f for q in qs})
        num += len(docs) + len(qs)
    require(num == physical["encoded_original_sources_and_questions"], "unaccounted Encoder data")
    require(physical["actual_original_encoder_forward_batches"] == math.ceil(num / 16),
            "false physical batched Encoder counter")
    require(physical["actual_original_encoder_token_positions"] >= 3 * num,
            "missing original encoded token positions")
    require(training.get("schema") == SCHEMA + ".train-only-gold"
            and set(training) == {"schema", "labels", "heldout_labels_present", "production_authorized"}
            and training["heldout_labels_present"] is False
            and training["production_authorized"] is False, "train/test partition violation")
    trainids = {q["id"]: f for f in OLD + NEW for q in source["families"][f]["questions"]}
    require(set(training["labels"]) == set(trainids), "training labels complete/disjoint")
    for qid, values in training["labels"].items():
        require(isinstance(values, list) and len(values) == len(set(values))
                and values == sorted(values) and all(x in ids_by_family[trainids[qid]] for x in values),
                "train label not source bound")
    require(set(plan) == {"schema", "source_sha256", "train_sha256", "weights_sha256",
                          "tokenizer_sha256", "dataset_sha256", "families_old", "families_new",
                          "families_heldout", "arms", "seeds", "head_parameters", "steps_old",
                          "steps_new", "batch", "top_k", "heldout_gold_admitted",
                          "no_selected_model", "production_authorized"}, "plan changed")
    require(plan["schema"] == SCHEMA + ".registered-plan"
            and plan["families_old"] == list(OLD) and plan["families_new"] == list(NEW)
            and plan["families_heldout"] == list(HELD)
            and plan["arms"] == list(ARMS) and plan["seeds"] == list(SEEDS)
            and plan["head_parameters"] == 6914 and plan["steps_old"] == 240
            and plan["steps_new"] == 240 and plan["batch"] == 64 and plan["top_k"] == 3
            and plan["heldout_gold_admitted"] is False
            and plan["no_selected_model"] is True and plan["production_authorized"] is False,
            "registered scientific protocol changed")
    require(plan["weights_sha256"] == ORIGINAL_MODEL_SHA
            and plan["tokenizer_sha256"] == ORIGINAL_TOKENIZER_SHA
            and plan["dataset_sha256"] == ORIGINAL_CORPUS_SHA, "original pretrained material changed")
    require(plan["source_sha256"] == hash_path(root / "source-only.json")
            and plan["train_sha256"] == hash_path(root / "train-only-labels.json"),
            "source/label plan SHA mismatch")
    for item in (physical, post):
        require(item["original_source_sha256"] == ORIGINAL_CORPUS_SHA,
                "unverified corpus SHA")
        require(item["precommit_sha256"] == hash_path(root / "precommit.json"),
                "cross-receipt precommit mismatch")
        require(item["production_authorized"] is False, "production authority forged")
    require(physical["original_model_sha256"] == ORIGINAL_MODEL_SHA
            and physical["original_tokenizer_sha256"] == ORIGINAL_TOKENIZER_SHA
            and physical["source_sha256"] == hash_path(root / "source-only.json")
            and physical["train_sha256"] == hash_path(root / "train-only-labels.json")
            and physical["original_predictions_sha256"] == hash_path(root / "original-predictions.json")
            and physical["precommit_sha256"] == pred["precommit_sha256"]
            and post["original_predictions_sha256"] == physical["original_predictions_sha256"],
            "physical output not exact precommitted source")
    require(physical["frozen_source_only_rankings"] is True
            and physical["original_heldout_reader_answers"] == 0
            and physical["human_verified_end_to_end_task_success"] is None
            and physical["original_hf_operator_tokenizer_parity_verified"] is False
            and physical["original_future_calendar_windows"] == 0
            and physical["signed_model_owner"] is False
            and physical["complete_lifecycle_cost_matched"] is False
            and physical["stem_winner_verified"] is False
            and physical["retention_repair_verified"] is False,
            "fabricated ability/result")
    require(pred.get("schema") == SCHEMA + ".original-prediction-seal"
            and set(pred) == {"schema", "precommit_sha256", "source_sha256",
                              "full_heldout_denominator", "top_k", "rankings",
                              "heldout_publisher_gold_not_read", "production_authorized"}
            and pred["heldout_publisher_gold_not_read"] is True
            and pred["production_authorized"] is False
            and pred["source_sha256"] == plan["source_sha256"], "answer seal changed")
    held_roster = {qid: f for qid, f in source_roster.items() if f in HELD}
    expected_arms = {"bm25_full", "dense_full"} | {
        f"seed{seed}/{arm}" for seed in SEEDS for arm in ARMS}
    require(pred["full_heldout_denominator"] == len(held_roster)
            and set(pred["rankings"]) == set(held_roster)
            and pred["top_k"] == 3, "dropped heldout case")
    for qid, by_arm in pred["rankings"].items():
        require(set(by_arm) == expected_arms, "missing physical Head or cheap arm")
        for ids in by_arm.values():
            require(isinstance(ids, list) and len(ids) == 3 and len(set(ids)) == 3
                    and set(ids) <= ids_by_family[held_roster[qid]], "fabricated source IDs")
    train_rows = physical["physical_train_rows"]
    require(len(train_rows) == 12 and set((x["seed"], x["arm"]) for x in train_rows)
            == {(s, a) for s in SEEDS for a in ARMS}, "missing trained Head attempts")
    for item in train_rows:
        arm = item["arm"]
        start, end = item["warmup"], item["continuation"]
        require(item["head_parameters"] == 6914 and HEX.fullmatch(item["head_start_sha256"])
                and HEX.fullmatch(item["head_end_sha256"]), "head parameter/weight digest false")
        require(start["optimizer_steps"] == 240
                and start["train_example_exposures"] == 240 * 64,
                "original training budget changed")
        expected_new = 0 if arm == "frozen" else (240 * 32 if arm == "equal_budget_replay" else 240 * 64)
        expected_old = 240 * 32 if arm == "equal_budget_replay" else 0
        require(end["optimizer_steps"] == (0 if arm == "frozen" else 240)
                and end["new_examples"] == expected_new
                and end["old_replay_examples"] == expected_old
                and end["train_example_exposures"] == expected_new + expected_old
                and math.isfinite(end["process_cpu_seconds"])
                and end["process_cpu_seconds"] >= 0,
                "train exposures/CPU accounting false")
        if arm == "frozen":
            require(item["head_start_sha256"] == item["head_end_sha256"],
                    "frozen Head secretly trained")
    require(post["publisher_weak_retrieval_proxy_only"] is True
            and post["independent_human_task_success"] is None
            and post["reader_full_task_answer_calls"] == 0
            and post["equal_total_lifecycle_compute"] is False
            and post["cross_task_learning_superiority_verified"] is False
            and post["stem_winner_verified"] is False
            and post["retention_old_training_panel_verified"] is False
            and post["independent_calendar_future_windows"] == 0,
            "invalid source-proxy-only admission")
    return len(source_roster), len(held_roster)


def reproduce_model_results(directory, source, train_only, pred, physical):
    """Re-run complete 12 physical Head training lineages from pinned features."""
    import numpy as np
    import torch
    from stem_v9_original_continual import (
        GatedHead, feature, lexical_bm25, private_head_sha, sample_pairs, topk, train
    )
    torch.set_num_threads(2)
    directory = Path(directory)
    arr = np.load(directory / "private-vectors.npy", allow_pickle=False)
    require(arr.shape == (physical["encoded_original_sources_and_questions"], 384)
            and arr.dtype == np.float32 and np.isfinite(arr).all(),
            "original physical features shape or values changed")
    require(hashlib.sha256(arr.tobytes()).hexdigest() == physical["private_feature_matrix_sha256"],
            "feature bytes changed after actual original Encoder execution")
    keys = []
    for fam in sorted(source["families"]):
        body = source["families"][fam]
        keys.extend(fam + "/" + d["id"] for d in body["passages"])
        keys.extend(q["id"] for q in body["questions"])
    require(len(keys) == len(set(keys)) == len(arr), "pretrained feature rows identity changed")
    vectors = {k: torch.from_numpy(arr[i].copy()) for i, k in enumerate(keys)}
    old_x, old_y, old_q = sample_pairs(source, train_only, vectors, OLD)
    new_x, new_y, new_q = sample_pairs(source, train_only, vectors, NEW)
    require(old_q == physical["old_train_question_count"]
            and new_q == physical["new_train_question_count"],
            "different original training cohort")
    by_head = {(r["seed"], r["arm"]): r for r in physical["physical_train_rows"]}
    sha_pass = 0
    source_rank_pass = 0
    for seed in SEEDS:
        model = GatedHead(seed)
        train(model, old_x, old_y, seed=seed*100+1, steps=240, lr=.001)
        for arm in ARMS:
            out = model.clone()
            if arm != "frozen":
                train(out, new_x, new_y, seed=seed*1000+7,
                      steps=240, lr=.0002 if arm == "low_lr" else .001,
                      replay=(old_x, old_y) if arm == "equal_budget_replay" else None)
            original = by_head[(seed, arm)]
            require(private_head_sha(out) == original["head_end_sha256"],
                    "physical trained tensor bytes do not replay")
            sha_pass += 1
            with torch.no_grad():
                for fam in HELD:
                    body = source["families"][fam]
                    docs = body["passages"]
                    matrix = torch.stack([vectors[fam + "/" + d["id"]] for d in docs])
                    for q in body["questions"]:
                        scores = out(feature(vectors[q["id"]], matrix)).tolist()
                        actual = topk(scores, docs)
                        require(actual == pred["rankings"][q["id"]][f"seed{seed}/{arm}"],
                                "whole-task original predicted sources fail complete model replay")
                        source_rank_pass += 1
    return sha_pass, source_rank_pass


def independent_publisher_recount(corpus, source, pred, post):
    """Compute weak result without importing producer weak_gold()/score()."""
    data = json.loads(Path(corpus).read_bytes())
    family_map = {r["sample_id"]: r for r in data}
    for arm, per_family in post["per_arm_source_root_aggregates"].items():
        require(arm in {"bm25_full", "dense_full"} | {
            f"seed{s}/{a}" for s in SEEDS for a in ARMS}, "unknown ranking arm")
        require(set(per_family) == set(HELD), "missing heldout family")
        for fam in HELD:
            obj = family_map[fam]
            dset = {d["id"] for d in source["families"][fam]["passages"]}
            allq = obj["qa"]
            totals = {"total_questions": len(allq), "weak_supported": 0,
                      "unknown_annotation": 0, "any_support_top3": 0, "all_support_top3": 0}
            for i, raw in enumerate(allq):
                truth = raw.get("evidence")
                if not isinstance(truth, list) or not truth or any(not isinstance(x,str) or x not in dset for x in truth):
                    totals["unknown_annotation"] += 1
                    continue
                totals["weak_supported"] += 1
                selected = set(pred["rankings"][f"{fam}/q{i}"][arm])
                totals["any_support_top3"] += bool(selected.intersection(truth))
                totals["all_support_top3"] += set(truth).issubset(selected)
            require(totals == per_family[fam], "independent publisher scoring mismatch")
    return len(post["per_arm_source_root_aggregates"]) * len(HELD)


def run_audit(folder, *, producer_script, original_root, replay=True):
    folder = safe_tree(folder)
    require(hash_path(producer_script) == SHA_PRODUCER,
            "physical producer source bytes differ from archived original run")
    source = obj(folder / "source-only.json")
    train_only = obj(folder / "train-only-labels.json")
    plan = obj(folder / "precommit.json")
    pred = obj(folder / "original-predictions.json")
    physical = obj(folder / "physical-receipt.json")
    post = obj(folder / "postseal-weak-score.json")
    source_n, test_n = check_documents(folder, source, train_only, plan, pred, physical, post)
    root = Path(original_root)
    require(hash_path(root / "locomo.json") == ORIGINAL_CORPUS_SHA,
            "actual public source digest changed after seal")
    per_family_reviewed = independent_publisher_recount(root / "locomo.json", source, pred, post)
    sha_pass = rank_pass = 0
    if replay:
        sha_pass, rank_pass = reproduce_model_results(folder, source, train_only, pred, physical)
    return {"schema": SCHEMA + ".independent-private-recount",
            "source_script_sha256": SHA_PRODUCER,
            "original_corpus_sha256": ORIGINAL_CORPUS_SHA,
            "original_prediction_sha256": hash_path(folder / "original-predictions.json"),
            "source_records_recounted": source_n,
            "heldout_original_questions_recounted": test_n,
            "independently_recomputed_family_arm_scores": per_family_reviewed,
            "actual_physical_head_digest_replays": sha_pass,
            "actual_original_head_source_rank_replays": rank_pass,
            "replay_executed": replay,
            "HF_parity_verified": False,
            "independent_evaluator_authorized": False,
            "prospective_future_windows": 0,
            "task_success_or_model_superiority_qualified": False,
            "production_authorized": False}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--directory", required=True)
    p.add_argument("--producer", required=True)
    p.add_argument("--original-root", required=True)
    p.add_argument("--no-replay", action="store_true")
    args = p.parse_args()
    start = time.perf_counter()
    out = run_audit(args.directory, producer_script=args.producer,
                    original_root=args.original_root, replay=not args.no_replay)
    out["actual_audit_wall_seconds"] = time.perf_counter() - start
    print(json.dumps(out, sort_keys=True))
