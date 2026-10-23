"""Independently reconstruct LoCoMo contexts and support scores from original data.

This verifier deliberately imports none of the experiment modules. It checks
recorded observations, not the quality of source annotations or production trust.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import statistics


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_row_scoring(row, expected, selected, status, category):
    """Independently validate every recorded gold/support/abstention score."""
    accepted = row["accepted"]
    require(type(accepted) is bool and accepted == bool(selected),
            "retrieval acceptance does not match delivered source references")
    require(type(row["gold_evidence_count"]) is int
            and row["gold_evidence_count"] == len(expected),
            "gold evidence denominator changed")
    chosen = set(selected)
    hits = len(expected & chosen)
    scorable = status == "scorable"
    expected_scores = {
        "support_recall": hits / len(expected) if scorable else None,
        "all_support_recalled": int(expected <= chosen) if scorable else None,
        "any_support_recalled": int(hits > 0) if scorable else None,
    }
    for name, value in expected_scores.items():
        actual = row[name]
        if value is not None:
            if name == "support_recall":
                require(type(actual) is float, "support_recall must be a float")
            else:
                require(type(actual) is int, f"{name} must be an integer indicator")
        require(actual == value, f"{name} changed from original evidence")
    answerability = int(accepted == (category != 5))
    require(type(row["answerability_screen_correct"]) is int
            and row["answerability_screen_correct"] == answerability,
            "answerability scoring changed")


def audit(source, directory):
    root = Path(directory)
    plan = json.loads((root / "plan.json").read_bytes())
    selection = json.loads((root / "selection.json").read_bytes())
    report = json.loads((root / "report.json").read_bytes())
    data = Path(source).read_bytes()
    require(digest(data) == plan["source_sha256"] == "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4", "source byte pin")
    require(digest((root / "plan.json").read_bytes()) == selection["plan_sha256"] == report["plan_sha256"], "plan binding")
    require(digest((root / "selection.json").read_bytes()) == report["selection_sha256"], "selection binding")
    require(plan["created_unix_ns"] < selection["frozen_unix_ns"], "plan was not frozen before selection")
    for name, expected in plan["code_sha256"].items():
        require(digest((Path(__file__).parent / name).read_bytes()) == expected, "generating source changed")
    original = json.loads(data)
    source_groups = {row["sample_id"] for row in original}
    split_groups = [group for groups in plan["partitions"].values() for group in groups]
    require(len(split_groups) == len(set(split_groups)) == 10 and set(split_groups) == source_groups, "conversation partitions overlap")
    query_map, frames, image_refs = {}, {}, {}
    for item in original:
        group, conversation = item["sample_id"], item["conversation"]
        for key, turns in conversation.items():
            if not key.startswith("session_") or key.endswith("_date_time"):
                continue
            for turn in turns:
                ref = (group, turn["dia_id"])
                require(ref not in frames, "duplicate original dialogue ID")
                frames[ref] = f"[{turn['dia_id']} | {key} | {conversation[key + '_date_time']} | {turn['speaker']}]\n{turn['text']}\n"
                image_refs[ref] = bool(turn.get("img_url"))
        for index, question in enumerate(item["qa"]):
            query_map[f"{group}:qa:{index:04d}"] = (group, question)
    require(set(plan["query_ids"]) == set(query_map) and len(query_map) == 1986, "complete original question census")
    rows, seen = [], set()
    for entry in report["prediction_inventory"]:
        stored = (root / entry["file"]).read_bytes()
        require(len(stored) == entry["stored_bytes"] and digest(stored) == entry["sha256"], "retained ledger bytes")
        raw = gzip.decompress(stored)
        require(len(raw) == entry["original_bytes"] and digest(raw) == entry["original_sha256"], "uncompressed ledger bytes")
        entries = json.loads(raw)
        require(len(entries) == entry["rows"], "ledger row count")
        for row in entries:
            group, question = query_map[row["query_id"]]
            key = (row["query_id"], row["arm"])
            require(key not in seen and row["arm"] in plan["arms"], "duplicate/unregistered question arm")
            seen.add(key)
            selected = row["selected_ids"]
            require(len(selected) == len(set(selected)) <= plan["max_turns"], "selected turn budget or duplicate")
            require(row["selected_turns"] == len(selected), "reported turn count")
            context = "".join(frames[(group, ref)] for ref in selected).encode()
            require(len(context) == row["context_bytes"] <= plan["max_context_utf8_bytes"], "actual UTF-8 context budget")
            require(digest(context) == row["context_sha256"], "delivered context identity")
            require(digest(question["question"].encode()) == row["query_sha256"], "question identity")
            require(row["group"] == group and row["category"] == question["category"], "source/annotation identity")
            expected = set(question.get("evidence", []))
            unresolved = [ref for ref in question.get("evidence", []) if (group, ref) not in frames]
            status = "adversarial" if question["category"] == 5 else "unresolved" if unresolved else "missing" if not expected else "scorable"
            require(row["annotation_status"] == status and row["unresolved_evidence"] == unresolved, "annotation was silently repaired or excluded")
            verify_row_scoring(row, expected, selected, status, question["category"])
            image = any(image_refs.get((group, ref), False) for ref in expected)
            require(row["evidence_has_image"] == image, "image-dependent evidence slice")
            rows.append(row)
    require(len(seen) == len(query_map) * len(plan["arms"]), "missing question arm")
    for split, groups in {**plan["partitions"], "full_census": list(source_groups)}.items():
        for arm in plan["arms"]:
            subset = [r for r in rows if r["arm"] == arm and r["group"] in groups]
            scored = [r for r in subset if r["support_recall"] is not None]
            metric = report["results"][split][arm]["overall"]
            require(len(subset) == metric["planned_questions"] and len(scored) == metric["scorable_support_questions"], "reported denominator")
            require(statistics.fmean(r["all_support_recalled"] for r in scored) == metric["all_support_recalled"], "reported all-evidence mean")
            grouped = defaultdict(list)
            for row in scored:
                grouped[row["group"]].append(row["all_support_recalled"])
            require(abs(statistics.fmean(statistics.fmean(v) for v in grouped.values()) - metric["group_macro_all_support"]) < 1e-15, "reported conversation macro mean")
    return {"schema": "hepta.locomo-source-retrieval-independent-audit.v1", "passed": True,
            "source_sha256": digest(data), "report_sha256": digest((root / "report.json").read_bytes()),
            "audit_source_sha256": digest(Path(__file__).read_bytes()),
            "questions_verified": len(query_map), "question_arm_rows_verified": len(rows),
            "contexts_reconstructed_from_original_turns": len(rows), "max_turns": max(r["selected_turns"] for r in rows),
            "max_context_bytes": max(r["context_bytes"] for r in rows),
            "no_experiment_module_imported": True, "new_retrieval_or_model_calls": 0,
            "human_semantic_adjudication": False, "independent_production_signature": False,
            "production_activation_allowed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.source, args.directory)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))
