"""E14 independent ORIGINAL human-label score after sealed pre-score MultiRC routes.

Reopens a pinned public validation Parquet ONLY in this scoring process.
Reconstructs original task/group IDs independently, replays E12 full-tree
certificates with the independent numerical oracle, and recomputes the older
four-Reader owner score. No production or independent signer permission.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction as F
from hashlib import sha256
from math import comb, isclose
import json
from pathlib import Path
from zipfile import ZipFile

from e12_nonlinear_cert import Law, Solve, State, Trace
from e12_independent_audit import audit, exact, reference
from e14_multirc_route import (ARCHIVE_SHA, ARMS, CUT, OBS_ID, PANEL, POLICIES, SCHEMA,
                               SLATE, canonical, law_from_prob, positive, read_prelabel,
                               strict_json, write_once)

VAL_SHA = "5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada"
SCORE_SHA = "3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4"
SCORE_FILE = "multirc-native-candidate-scores/scores.json"
SCORE_SEAL = "multirc-native-candidate-scores/COMMITTED.json"
SCORE_SCHEMA = "hepta.multirc.genuine-answer-slate-evaluation.v1"
REVISION = "4e14482c58d790d467ecfb29b6790e1917bf8756"


def original_labels(raw_rows: list[dict], candidates: list[dict]) -> dict[str, int]:
    """Independently rebuild exact validation passage & candidate identity.

    This deliberately does not trust candidate/source-provided label fields,
    original cached score reports, or any artificially edited passage label.
    """
    if type(raw_rows) is not list or not 1 <= len(raw_rows) <= 100000:
        raise ValueError("complete bounded original validation Parquet rows required")
    if type(candidates) is not list or len(candidates) != 33:
        raise ValueError("complete original candidate census required")
    required = {"task_id", "source_group", "question_slot", "candidate_id", "original_v1_candidate"}
    for row in candidates:
        if (type(row) is not dict or set(row) != required
                or type(row["task_id"]) is not str or len(row["task_id"]) != 32
                or type(row["source_group"]) is not str or len(row["source_group"]) != 32
                or type(row["question_slot"]) is not int or row["question_slot"] not in (0,1)
                or type(row["candidate_id"]) is not int or not 0 <= row["candidate_id"] <= 10**9
                or type(row["original_v1_candidate"]) is not bool):
            raise ValueError("invalid exact original candidate source geometry")
    needed = {r["task_id"]: r for r in candidates}
    if len(needed) != 33:
        raise ValueError("duplicate candidate ID")
    labels = {}
    group_qids = {}
    groups = {r["source_group"] for r in candidates}
    seen_source_ids = set()
    for source in raw_rows:
        if type(source) is not dict or set(source) != {"paragraph", "question", "answer", "label", "idx"}:
            raise ValueError("original column schema drift")
        idx = source["idx"]
        if type(idx) is not dict or set(idx) != {"paragraph", "question", "answer"} or any(
            type(v) is not int or not 0 <= v <= 10**9 for v in idx.values()
        ) or type(source["label"]) is not int or source["label"] not in (0, 1):
            raise ValueError("original source identity or human label invalid")
        # The original dataset may have malformed text outside the selected
        # material. Only selected source groups must meet strict text limits.
        para = source["paragraph"]
        if type(para) is not str:
            continue
        passage_digest = sha256(json.dumps(para, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode()).hexdigest()
        group = sha256(f'validation:passage:{idx["paragraph"]}:{passage_digest}'.encode()).hexdigest()[:32]
        if group not in groups:
            continue
        if (not 0 < len(para) <= 900 or type(source["question"]) is not str
                or type(source["answer"]) is not str
                or not source["question"].strip() or not source["answer"].strip()):
            raise ValueError("selected original text unexpectedly malformed")
        task = sha256(f'{group}:q{idx["question"]}:a{idx["answer"]}'.encode()).hexdigest()[:32]
        seen_source_ids.add((group, idx["paragraph"]))
        if task not in needed:
            continue
        row = needed[task]
        if row["source_group"] != group or row["candidate_id"] != idx["answer"] or task in labels:
            raise ValueError("candidate original label/source mismatch")
        labels[task] = source["label"]
        group_qids.setdefault((group, row["question_slot"]), set()).add(idx["question"])
    if len(labels) != 33 or len({g for g, _ in seen_source_ids}) != 4 or len(group_qids) != 8:
        raise ValueError("missing original human annotation or changed source groups")
    if any(len(qids) != 1 for qids in group_qids.values()):
        raise ValueError("multiple original questions were merged under one slot")
    for group in groups:
        q0 = next(iter(group_qids[(group, 0)]))
        q1 = next(iter(group_qids[(group, 1)]))
        if q0 >= q1:
            raise ValueError("selected original question order differs")
        for slot in (0, 1):
            rows = [r for r in candidates if r["source_group"] == group and r["question_slot"] == slot]
            if (not 2 <= len(rows) <= 8 or sum(r["original_v1_candidate"] for r in rows) != 1
                    or min(r["candidate_id"] for r in rows) != next(r["candidate_id"] for r in rows if r["original_v1_candidate"])):
                raise ValueError("incomplete authentic answer slate")
    return labels


def read_validation(parquet_path: str):
    path = Path(parquet_path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size != 306_376:
        raise ValueError("missing or wrong original human validation material")
    if sha256(path.read_bytes()).hexdigest() != VAL_SHA:
        raise ValueError("original SuperGLUE material changed")
    import pyarrow.parquet as pq  # only in label-owner scorer, NEVER in proposer
    t = pq.read_table(str(path), columns=["paragraph", "question", "answer", "label", "idx"])
    return t.to_pylist()


def historical_owner_score(archive_path: str) -> dict:
    if sha256(Path(archive_path).read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError("original archived trained Reader changed")
    with ZipFile(archive_path) as z:
        original = z.read(SCORE_FILE)
        seal = strict_json(z.read(SCORE_SEAL))
    if (sha256(original).hexdigest() != SCORE_SHA
            or seal.get("scores_sha256") != SCORE_SHA
            or seal.get("schema") != "hepta.multirc.genuine-slate-score-seal.v1"
            or seal.get("production_authorized") is not False):
        raise ValueError("original label-owner scoring receipt corrupted")
    owner = strict_json(original)
    if (owner.get("schema") != SCORE_SCHEMA or owner.get("candidate_count") != 33
            or owner.get("question_count") != 8 or owner.get("slate_id") != SLATE
            or owner.get("official_multirc_score_established") is not False
            or owner.get("production_authorized") is not False):
        raise ValueError("owner scorer identity/policy changed")
    return owner


def decode_cert(d: dict) -> Solve:
    if type(d) is not dict or set(d) != set(Solve.__dataclass_fields__):
        raise ValueError("incomplete E12 receipt")
    t = d["trace"]
    if type(t) is not dict or set(t) != {"states", "z"} or type(t["states"]) is not list or type(t["z"]) is not list:
        raise ValueError("incomplete E12 states")
    states = []
    for s in t["states"]:
        if type(s) is not dict or set(s) != {"x", "y"}:
            raise ValueError("unexpected E12 state")
        states.append(State(**s))
    return Solve(**{**d, "trace": Trace(tuple(states), tuple(t["z"]))})


def source_verified_score(sealed: dict, source: dict, labels: dict[str, int], owner: dict) -> dict:
    """No decision learned/tuned after original human labels become available."""
    required = {"schema", "authority", "archive_sha256", "prelabel_observation_id",
                "slate_id", "original_labels_accessed", "human_labels_present_in_prediction_rows",
                "new_pretrained_forward_count", "actual_live_routing", "source_family",
                "threshold_derived_from_labelblind_feature_distribution", "exploratory_cutoff",
                "policies", "production_accepted", "rows"}
    if (type(sealed) is not dict or set(sealed) != required or sealed["schema"] != SCHEMA
            or sealed["authority"] != "DENY_ALL" or sealed["archive_sha256"] != ARCHIVE_SHA
            or sealed["prelabel_observation_id"] != OBS_ID or sealed["slate_id"] != SLATE
            or sealed["original_labels_accessed"] is not False
            or sealed["human_labels_present_in_prediction_rows"] is not False
            or type(sealed["new_pretrained_forward_count"]) is not int or sealed["new_pretrained_forward_count"] != 0
            or sealed["actual_live_routing"] is not False or sealed["production_accepted"] is not False
            or sealed["threshold_derived_from_labelblind_feature_distribution"] is not True
            or sealed["exploratory_cutoff"] != "9/100" or sealed["policies"] != list(POLICIES)
            or type(sealed["rows"]) is not list or len(sealed["rows"]) != 33):
        raise ValueError("unapproved E14 research route or leaked original labels")
    if set(labels) != {r["task_id"] for r in source["rows"]}:
        raise ValueError("original human label coverage differs")
    raw_vectors = {arm: [] for arm in ARMS}
    original_brier = {arm: 0.0 for arm in ARMS}
    group_spans = {arm: {} for arm in ARMS}
    stats = {name: dict(correct=0, total=33, brier_sum=0.0, routed_to_mean_pool=0,
                        recovered=0, lost=0) for name in POLICIES}
    qgroups = {}
    cheap_total = full_total = 0
    diffs = 0
    for i, (row, original) in enumerate(zip(sealed["rows"], source["rows"])):
        meta = {k: row[k] for k in ("source_group", "question_slot", "task_id", "candidate_id", "original_v1_candidate")}
        if meta != original or set(row) != set(meta) | {"probs", "law", "cheap_root", "cheap_cpu_ns", "cert", "policy_arms"}:
            raise ValueError("original source row or pre-score route mutated")
        truth = labels[original["task_id"]]
        pmap = {arm: positive(source["predictions"][arm][i]["logits"]) for arm in ARMS}
        if type(row["probs"]) is not dict or row["probs"] != pmap:
            raise ValueError("source pretrained probabilities mutated")
        law = law_from_prob(pmap["conditioned"])
        if row["law"] != asdict(law):
            raise ValueError("E12 law changed after model inference")
        cert = decode_cert(row["cert"])
        mathematical = audit(law, cert)
        if not mathematical.certified or mathematical.natural_task_improvement_proven:
            raise ValueError("independent global FBSDE verification failed")
        cheap = reference(law, (F(0),) * (2**law.depth-1))[2][0]
        if row["cheap_root"] != str(cheap) or type(row["cheap_cpu_ns"]) is not int or not 0 < row["cheap_cpu_ns"] < 10**12:
            raise ValueError("invented cheap baseline or work record")
        cheap_total += row["cheap_cpu_ns"]
        full_total += cert.cpu_ns
        root = exact(cert.trace.states[0].y)
        error = exact(cert.fixed_point_error_bound)
        expected = {arm: arm for arm in ARMS}
        expected.update(fixed_confidence="mean_pool_query_fused" if abs(F(str(pmap["conditioned"]))-F(1,2)) <= F(1,8) else "conditioned",
                        cheap_one_map="mean_pool_query_fused" if abs(cheap) <= CUT else "conditioned",
                        e12_full_tree="mean_pool_query_fused" if abs(root)+error <= CUT else "conditioned")
        if row["policy_arms"] != expected:
            raise ValueError("post-label routing or unsupported E12 threshold")
        if expected["cheap_one_map"] != expected["e12_full_tree"]:
            diffs += 1
        base_good = (pmap["conditioned"] >= 0.5) == bool(truth)
        for name, arm in expected.items():
            chosen = pmap[arm]
            correct = (chosen >= .5) == bool(truth)
            stats[name]["correct"] += int(correct)
            stats[name]["brier_sum"] += 2 * (chosen-truth)**2
            stats[name]["routed_to_mean_pool"] += int(arm == "mean_pool_query_fused" and name not in ARMS)
            stats[name]["recovered"] += int(correct and not base_good)
            stats[name]["lost"] += int(base_good and not correct)
        for arm in ARMS:
            hit = (pmap[arm] >= .5) == bool(truth)
            raw_vectors[arm].append(hit)
            original_brier[arm] += 2*(pmap[arm]-truth)**2
            group_spans[arm].setdefault((original["source_group"], original["question_slot"]), []).append((truth, pmap[arm]))
        qgroups.setdefault((original["source_group"], original["question_slot"]), set()).add(truth)
    if len(qgroups) != 8 or any(g != {0, 1} for g in qgroups.values()):
        raise ValueError("original mixed-label human question census missing")
    for arm in ARMS:
        scored = owner["results"][arm]
        correct = sum(raw_vectors[arm])
        brier = original_brier[arm] / 33
        spans = [max(x[1] for x in vv)-min(x[1] for x in vv) for vv in group_spans[arm].values()]
        if (correct != scored["correct"] or not isclose(brier, scored["brier"], abs_tol=2e-12)
                or not isclose(correct / 33, scored["accuracy"], abs_tol=2e-12)
                or scored["mixed_label_question_count"] != 8
                or scored["near_invariant_native_answer_question_count"] != sum(s <= 0.001 for s in spans)
                or not isclose(sum(spans)/8, scored["mean_within_question_native_answer_probability_span"], abs_tol=2e-12)):
            raise ValueError("original human MultiRC owner result not independently reproduced")
    for name in POLICIES:
        item = stats[name]
        item["accuracy"] = item["correct"] / 33
        item["brier"] = item.pop("brier_sum") / 33
    baseline = stats["conditioned"]
    return {
        "schema": "hepta.e14.independent-original-multirc-task-control.v1",
        "authority": "DENY_ALL", "original_archive_sha256": ARCHIVE_SHA,
        "human_validation_sha256": VAL_SHA, "original_owner_score_sha256": SCORE_SHA,
        "original_human_annotation_candidate_count": 33,
        "passages": 4, "questions": 8, "all_questions_mixed_original_labels": True,
        "real_pretrained_work_was_historical_not_reexecuted": True,
        "new_pretrained_model_calls": 0, "online_routing_executed": False,
        "self_observed_local_python_numerical_cpu_ns": {"cheap": cheap_total, "full_e12": full_total},
        "historical_whole_panel_paid_reader_calls": 132,
        "policy_switch_differences_cheap_vs_e12": diffs,
        "evaluation_arms": stats,
        "incremental_e12_real_task_superiority_established": False,
        "p_value_not_interpreted_as_independent_33_tasks": True,
        "not_future_time_or_multi_family": True,
        "complete_online_cost_comparison": False,
        "production_accepted": False,
    }


def score(archive: str, prelabel_path: str, prelabel_sha: str,
          parquet_path: str, output: str) -> str:
    raw = Path(prelabel_path).read_bytes()
    if sha256(raw).hexdigest() != prelabel_sha:
        raise ValueError("original create-only prelabel seal mismatch")
    prelabel = strict_json(raw)
    source = read_prelabel(archive)
    label_rows = read_validation(parquet_path)
    labels = original_labels(label_rows, source["rows"])
    original = historical_owner_score(archive)
    result = source_verified_score(prelabel, source, labels, original)
    return write_once(output, result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "prelabel", "prelabel-sha256", "validation-parquet", "output"):
        p.add_argument("--" + arg, required=True)
    args = p.parse_args()
    print(json.dumps({"score_sha256": score(args.archive, args.prelabel,
                                               args.prelabel_sha256,
                                               args.validation_parquet, args.output),
                      "authority": "DENY_ALL"}, sort_keys=True))
