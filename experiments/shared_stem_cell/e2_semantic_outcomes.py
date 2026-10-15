"""Independent semantic outcome readout for E2 multimodal Stem research.

Never trains models, selects a Stem, or authorizes production.
Prediction and target files are opened only in this evaluator process.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ARMS = ("text_only", "ocr_text", "unaligned_vision", "aligned_bridge", "native_multimodal")
CONDITIONS = ("text_sufficient", "vision_required", "visual_evidence_removed", "visual_evidence_swapped")

def _sha(data):
    return hashlib.sha256(data).hexdigest()

def _read_pinned(path, expected):
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("invalid SHA-256 pin")
    data = Path(path).read_bytes()
    if _sha(data) != expected:
        raise ValueError("file digest mismatch")
    def no_duplicates(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate JSON key")
            obj[k] = v
        return obj
    return json.loads(data, object_pairs_hook=no_duplicates)

def _entries(doc, kind):
    if not isinstance(doc, dict) or set(doc) != {"schema", "rows"}:
        raise ValueError("invalid document envelope")
    if doc["schema"] != "hepta.e2.semantic-" + kind + ".v1":
        raise ValueError("schema version mismatch")
    rows = doc["rows"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty or non-list rows")
    return rows

def evaluate(prediction_doc, target_doc):
    predictions = _entries(prediction_doc, "predictions")
    targets = _entries(target_doc, "targets")
    observed = {}
    for row in predictions:
        if not isinstance(row, dict) or set(row) != {"case_id", "arm", "answer", "source_sha256"}:
            raise ValueError("prediction row must be source-only")
        case, arm, answer, digest = (row[k] for k in ("case_id", "arm", "answer", "source_sha256"))
        if not isinstance(case, str) or not case or arm not in ARMS:
            raise ValueError("invalid prediction identity")
        if not isinstance(answer, str) or not answer:
            raise ValueError("invalid answer")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid source digest")
        key = (case, arm)
        if key in observed:
            raise ValueError("duplicate prediction")
        observed[key] = row
    target_map = {}
    groups_by_partition = defaultdict(set)
    for row in targets:
        expected = {"case_id", "group_id", "condition", "label", "source_sha256", "partition"}
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("invalid target row")
        case = row["case_id"]
        group = row["group_id"]
        condition = row["condition"]
        partition = row["partition"]
        if not all(isinstance(x, str) and x for x in (case, group, row["label"], partition)):
            raise ValueError("invalid target identity or label")
        if condition not in CONDITIONS or partition not in ("train", "future1", "future2", "future3"):
            raise ValueError("invalid condition or partition")
        if case in target_map:
            raise ValueError("duplicate target")
        target_map[case] = row
        groups_by_partition[partition].add(group)
    if "train" in groups_by_partition:
        raise ValueError("scoring TRAIN is prohibited")
    for i in range(1, 4):
        for j in range(i+1, 4):
            if groups_by_partition[f"future{i}"] & groups_by_partition[f"future{j}"]:
                raise ValueError("overlapping future source groups")
    required = {(case, arm) for case in target_map for arm in ARMS}
    if set(observed) != required:
        raise ValueError("missing or extra arm/case predictions")
    scores = defaultdict(lambda: {"correct": 0, "total": 0})
    differences = defaultdict(lambda: {"rescued": 0, "harmed": 0, "both_correct": 0, "both_wrong": 0})
    for case, target in target_map.items():
        correct = {}
        for arm in ARMS:
            prediction = observed[(case, arm)]
            if prediction["source_sha256"] != target["source_sha256"]:
                raise ValueError("source mismatch")
            yes = prediction["answer"] == target["label"]
            correct[arm] = yes
            key = (target["partition"], target["condition"], arm)
            scores[key]["total"] += 1
            scores[key]["correct"] += int(yes)
        for arm in ARMS[1:]:
            entry = differences[(target["partition"], target["condition"], arm)]
            entry["rescued" if correct[arm] and not correct["text_only"] else
                  "harmed" if correct["text_only"] and not correct[arm] else
                  "both_correct" if correct[arm] else "both_wrong"] += 1
    return {
        "schema": "hepta.e2.semantic-outcomes.v1",
        "production_accepted": False,
        "stem_selected": False,
        "authority": "DENY_ALL",
        "cases": len(target_map),
        "conditions": list(CONDITIONS),
        "scores": [
            {"partition": p, "condition": c, "arm": a, **v}
            for (p, c, a), v in sorted(scores.items())
        ],
        "paired_vs_text_only": [
            {"partition": p, "condition": c, "arm": a, **v}
            for (p, c, a), v in sorted(differences.items())
        ],
        "limitations": [
            "Exact-label accuracy only; labels and visual necessity need independent semantic review.",
            "Input SHA-256 pins are byte identities, not publisher or ground-truth authentication.",
            "No cost-adjusted model benefit, online latency, real pretrained forward, or causal win is implied.",
            "This readout alone cannot promote any Stem or grant FinalUse."
        ],
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--predictions", required=True)
    p.add_argument("--predictions-sha256", required=True)
    p.add_argument("--targets", required=True)
    p.add_argument("--targets-sha256", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    pred = _read_pinned(args.predictions, args.predictions_sha256)
    targets = _read_pinned(args.targets, args.targets_sha256)
    result = evaluate(pred, targets)
    output = Path(args.output)
    if output.exists():
        raise ValueError("refusing to replace an existing readout")
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
