"""Independent source-scoped Reader failure attribution (research only).

This is an analysis of *sealed, supplied* four-condition physical receipts. It
never runs a model, authenticates annotators or declares semantic sufficiency.
The removed-premise arm has NO inherited binary correctness label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections import defaultdict

PLAN = "hepta.reader.support-causal-plan.v1"
OBS = "hepta.reader.support-causal-observation.v2"
REPLAY = "hepta.reader.support-causal-replay.v1"
REVIEW = "hepta.reader.source-blind-adjudication.v1"
RESULT = "hepta.reader.failure-attribution.v1"
CONDITIONS = ("no_evidence", "ordinary_retrieval", "support_candidate", "premise_removed")
MAX_FILE = 8 * 1024 * 1024


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _sha(value):
    return type(value) is str and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _source_key(source):
    return hashlib.sha256(" ".join(source.split()).casefold().encode()).hexdigest()


def _p1(logits):
    if (type(logits) is not list or len(logits) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in logits)):
        raise ValueError("invalid Reader logits")
    diff = float(logits[1]) - float(logits[0])
    return 1 / (1 + math.exp(-max(-700, min(700, diff))))


def _condition_texts(row):
    pieces = [row["evidence"][a:b] for a, b in row["support_spans"]]
    return {"no_evidence": "Evidence unavailable.",
            "ordinary_retrieval": row["evidence"],
            "support_candidate": "\n".join(pieces),
            "premise_removed": "\n".join(p for i, p in enumerate(pieces)
                                            if i != row["critical_span_index"])}


def _sealed(obj, key):
    return (type(obj) is dict and _sha(obj.get(key)) and
            obj[key] == digest({k: v for k, v in obj.items() if k != key}))


def attribute(plan, observed, replay, labels, reviews):
    """Attribute candidate-level failure modes, never approve a model/Cell."""
    if (type(plan) is not dict or plan.get("schema") != PLAN
            or not _sealed(plan, "plan_id") or type(plan.get("rows")) is not list
            or not 2 <= len(plan["rows"]) <= 256
            or plan.get("labels_available_to_runner") is not False
            or plan.get("support_independently_verified") is not False
            or not _sha(plan.get("model_sha256")) or not _sha(plan.get("panel_sha256"))):
        raise ValueError("original label-blind plan must be sealed")
    n = len(plan["rows"])
    if (not _sealed(observed, "observation_id") or observed.get("schema") != OBS
            or observed.get("plan_id") != plan["plan_id"]
            or observed.get("model_sha256") != plan["model_sha256"]
            or observed.get("panel_sha256") != plan["panel_sha256"]
            or observed.get("condition_order") != list(CONDITIONS)
            or set(observed) != {"schema", "plan_id", "panel_sha256", "model_sha256",
                "reader_weights_sha256", "condition_order", "rows", "physical_encoder_calls",
                "physical_reader_calls", "physical_query_calls", "measured_whole_call_wall_ns",
                "original_prediction_replay_verified", "external_semantic_sufficiency_authenticated",
                "independent_real_source_authenticated", "reading_labels",
                "measured_complete_model_lifecycle", "production_authorized", "authority",
                "observation_id"}
            or observed.get("authority") != "DENY_ALL"
            or observed.get("production_authorized") is not False
            or type(observed.get("measured_whole_call_wall_ns")) is not int
            or observed["measured_whole_call_wall_ns"] <= 0
            or observed.get("reading_labels") is not False
            or observed.get("original_prediction_replay_verified") is not True
            or observed.get("external_semantic_sufficiency_authenticated") is not False
            or observed.get("independent_real_source_authenticated") is not False
            or observed.get("measured_complete_model_lifecycle") is not False
            or any(type(observed.get(key)) is not int or observed[key] != amount
                   for key, amount in (("physical_encoder_calls", 4*n),
                                       ("physical_reader_calls", 4*n),
                                       ("physical_query_calls", n)))
            or type(observed.get("rows")) is not list or len(observed["rows"]) != n):
        raise ValueError("unsealed original Reader observation or physical-call census")
    if (not _sealed(replay, "replay_id") or replay.get("schema") != REPLAY
            or replay.get("observation_id") != observed["observation_id"]
            or replay.get("plan_id") != plan["plan_id"]
            or replay.get("model_sha256") != plan["model_sha256"]
            or replay.get("reader_weights_sha256") != observed.get("reader_weights_sha256")
            or set(replay) != {"schema", "observation_id", "plan_id", "model_sha256",
                "reader_weights_sha256", "physically_reexecuted_encoder_calls",
                "physically_reexecuted_reader_calls", "physically_reexecuted_query_calls",
                "max_absolute_logit_difference", "actual_reexecution_wall_ns",
                "exact_frozen_model_loader_used", "external_original_model_signer_verified",
                "independent_semantic_sufficiency_verified", "label_owner_material_opened",
                "production_authorized", "authority", "replay_id"}
            or replay.get("authority") != "DENY_ALL"
            or replay.get("production_authorized") is not False
            or type(replay.get("actual_reexecution_wall_ns")) is not int
            or replay["actual_reexecution_wall_ns"] <= 0
            or replay.get("label_owner_material_opened") is not False
            or replay.get("independent_semantic_sufficiency_verified") is not False
            or replay.get("external_original_model_signer_verified") is not False
            or replay.get("exact_frozen_model_loader_used") is not False
            or any(type(replay.get(key)) is not int or replay[key] != amount
                   for key, amount in (("physically_reexecuted_encoder_calls", 4*n),
                                       ("physically_reexecuted_reader_calls", 4*n),
                                       ("physically_reexecuted_query_calls", n)))
            or type(replay.get("max_absolute_logit_difference")) not in (int, float)
            or not 0 <= replay["max_absolute_logit_difference"] <= 1e-5):
        raise ValueError("complete second Reader execution receipt required")
    ids = [r["task_id"] for r in plan["rows"]]
    if (len(set(ids)) != n or
            type(labels) is not dict or set(labels) != {"schema", "plan_id", "labels"}
            or labels["schema"] != "hepta.reader.support-label-owner.v1"
            or labels["plan_id"] != plan["plan_id"]
            or type(labels["labels"]) is not dict or set(labels["labels"]) != set(ids)
            or any(type(v) is not int or v not in (0, 1) for v in labels["labels"].values())):
        raise ValueError("independently opened original binary owner labels required")
    if (type(reviews) is not dict or set(reviews) != {"schema", "plan_id",
                "observation_id", "labels_visible", "reviewers", "review_id"}
            or not _sealed(reviews, "review_id") or reviews["schema"] != REVIEW
            or reviews["plan_id"] != plan["plan_id"]
            or reviews["observation_id"] != observed["observation_id"]
            or reviews["labels_visible"] is not False
            or type(reviews["reviewers"]) is not list or len(reviews["reviewers"]) != 2):
        raise ValueError("two post-prediction, label-blind adjudication inventories required")
    source_seen, groups = {}, set()
    for source in plan["rows"]:
        group, content = source["source_group"], source["evidence"]
        if (type(group) is not str or not group or type(content) is not str or not content
                or _source_key(content) in source_seen and source_seen[_source_key(content)] != group):
            raise ValueError("aliased source root cannot count as independent evidence")
        source_seen[_source_key(content)] = group
        groups.add(group)
    if len(groups) < 2:
        raise ValueError("multiple independently named source roots required")
    reviewer_rows = []
    reviewer_ids = set()
    for reviewer in reviews["reviewers"]:
        if (type(reviewer) is not dict or set(reviewer) != {"reviewer_id", "rows"}
                or type(reviewer["reviewer_id"]) is not str
                or not reviewer["reviewer_id"] or reviewer["reviewer_id"] in reviewer_ids
                or type(reviewer["rows"]) is not list or len(reviewer["rows"]) != n):
            raise ValueError("missing or duplicated independent adjudicator inventory")
        reviewer_ids.add(reviewer["reviewer_id"])
        records = {}
        for row in reviewer["rows"]:
            if (type(row) is not dict or set(row) != {"task_id", "source_group",
                    "support_decidable", "removed_decidable"}
                    or row["task_id"] in records or type(row["support_decidable"]) is not bool
                    or type(row["removed_decidable"]) is not bool):
                raise ValueError("invalid label-free sufficiency judgments")
            records[row["task_id"]] = row
        if set(records) != set(ids):
            raise ValueError("adjudicator cannot omit a task")
        reviewer_rows.append(records)
    counts = defaultdict(int)
    roots = defaultdict(lambda: defaultdict(int))
    for source, obs in zip(plan["rows"], observed["rows"], strict=True):
        task, root = source["task_id"], source["source_group"]
        if any(v[task]["source_group"] != root for v in reviewer_rows):
            raise ValueError("reviewer changed original source identity")
        if (type(obs) is not dict or obs.get("task_id") != task
                or obs.get("source_group") != root
                or obs.get("original_input_sha256") != hashlib.sha256(source["evidence"].encode()).hexdigest()
                or type(obs.get("observations")) is not dict
                or set(obs["observations"]) != set(CONDITIONS)):
            raise ValueError("original Reader conditions or task order changed")
        probabilities = {}
        for condition, content in _condition_texts(source).items():
            entry = obs["observations"][condition]
            if (type(entry) is not dict or set(entry) != {"logits", "probability", "evidence_sha256"}
                    or entry["evidence_sha256"] != hashlib.sha256(content.encode()).hexdigest()
                    or type(entry["probability"]) not in (int, float)
                    or not math.isfinite(entry["probability"])
                    or abs(_p1(entry["logits"]) - entry["probability"]) > 1e-8):
                raise ValueError("Reader probability or actual evidence identity was changed")
            probabilities[condition] = entry["probability"]
        counts["total_candidates"] += 1
        roots[root]["total_candidates"] += 1
        a, b = (v[task] for v in reviewer_rows)
        if (a["support_decidable"], a["removed_decidable"]) != (
                b["support_decidable"], b["removed_decidable"]):
            counts["reviewer_disagreements"] += 1
            roots[root]["reviewer_disagreements"] += 1
            continue
        if not a["support_decidable"]:
            counts["support_not_judged_decidable"] += 1
            continue
        counts["reviewer_claimed_support_decidable"] += 1
        y = labels["labels"][task]
        support_ok = int(probabilities["support_candidate"] >= 0.5) == y
        ordinary_ok = int(probabilities["ordinary_retrieval"] >= 0.5) == y
        none_ok = int(probabilities["no_evidence"] >= 0.5) == y
        for name, passed in (("support_correct", support_ok), ("ordinary_correct", ordinary_ok),
                             ("no_evidence_correct", none_ok)):
            counts[name] += int(passed)
            roots[root][name] += int(passed)
        if not support_ok:
            counts["candidate_reader_or_representation_blocker"] += 1
        elif not ordinary_ok:
            counts["candidate_retrieval_gap"] += 1
        if support_ok and ordinary_ok and not none_ok:
            counts["candidate_evidence_utility"] += 1
        if not a["removed_decidable"]:
            counts["removed_premise_unanswerable_claims"] += 1
            # This is *only* a sensitivity measurement. Binary logits have no
            # abstain action, so do not count this as accuracy or hallucination.
            if abs(probabilities["premise_removed"] - probabilities["support_candidate"]) < 0.05:
                counts["removed_premise_low_sensitivity"] += 1
    for key in ("total_candidates", "reviewer_disagreements", "support_not_judged_decidable",
                "reviewer_claimed_support_decidable", "support_correct", "ordinary_correct",
                "no_evidence_correct", "candidate_reader_or_representation_blocker",
                "candidate_retrieval_gap", "candidate_evidence_utility",
                "removed_premise_unanswerable_claims", "removed_premise_low_sensitivity"):
        counts[key] += 0
    result = {"schema": RESULT, "plan_id": plan["plan_id"],
        "observation_id": observed["observation_id"], "replay_id": replay["replay_id"],
        "review_id": reviews["review_id"], "original_owner_label_sha256": digest(labels),
        "tasks": n, "source_roots": len(groups), "counts": dict(sorted(counts.items())),
        "root_counts": {hashlib.sha256((plan["plan_id"] + "|root|" + k).encode()).hexdigest():
                        dict(sorted(v.items())) for k, v in sorted(roots.items())},
        "adjudicator_identity_cryptographically_authenticated": False,
        "semantic_sufficiency_independently_certified": False,
        "reader_capacity_or_retrieval_winner_verified": False,
        "full_question_accuracy_established": False,
        "premise_removed_original_binary_label_valid": False,
        "future_window_generalization_established": False,
        "production_authorized": False, "authority": "DENY_ALL",
        "decision": "DESCRIPTIVE_HOLD_NO_GO"}
    result["result_id"] = digest(result)
    return result


def _strict_pairs(pairs):
    out = {}
    for k, value in pairs:
        if k in out:
            raise ValueError("duplicate JSON field")
        out[k] = value
    return out


def _read_file(path, expected_sha):
    if not os.path.isabs(path) or not _sha(expected_sha):
        raise ValueError("absolute data path and independently pinned SHA required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > MAX_FILE:
            raise ValueError("unsafe input file")
        with os.fdopen(os.dup(fd), "rb") as reader:
            raw = reader.read(MAX_FILE + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or len(raw) > MAX_FILE or
                (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) !=
                (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size) or
                hashlib.sha256(raw).hexdigest() != expected_sha):
            raise ValueError("original file SHA or file-descriptor snapshot drifted")
        return json.loads(raw, object_pairs_hook=_strict_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    for k in ("plan", "observed", "replay", "labels", "reviews"):
        parser.add_argument("--" + k, required=True)
        parser.add_argument("--" + k + "-sha256", required=True)
    args = parser.parse_args()
    inputs = [_read_file(getattr(args, k), getattr(args, k + "_sha256"))
              for k in ("plan", "observed", "replay", "labels", "reviews")]
    result = attribute(*inputs)
    if os.path.lexists(args.output):
        raise ValueError("never overwrite a prior attribution report")
    with open(args.output, "x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, separators=(",", ":"), allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())


if __name__ == "__main__":
    main()
