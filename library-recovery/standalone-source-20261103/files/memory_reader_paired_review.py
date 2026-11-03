"""Separate-source postseal paired Reader comparison; research-only diagnostic."""
from collections import defaultdict
from pathlib import Path
import json
import sys

from memory_reader_causal_panel import (
    ARMS, ORIGINAL_SHA, MODEL_SHA, SCHEMA, digest, load_plan, read, strict,
    token_f1, write,
)


def score(original_path, plan_dir, run_dir, out_path):
    plan, ph = load_plan(plan_dir)
    raw_original = read(original_path, maximum=8*1024*1024)
    if digest(raw_original) != ORIGINAL_SHA:
        raise ValueError("original LoCoMo source identity mismatch")
    data = strict(raw_original)
    if not isinstance(data, list) or len(data) != 10:
        raise ValueError("unknown original family population")
    families = {d["sample_id"]: d for d in data}
    if len(families) != 10:
        raise ValueError("original family collision")
    journal_raw = read(Path(run_dir) / "journal.json")
    journal = strict(journal_raw)
    seal = strict(read(Path(run_dir) / "seal.json"))
    if (seal != {"schema": SCHEMA, "plan_sha256": ph,
                 "journal_sha256": digest(journal_raw), "model_sha256": MODEL_SHA,
                 "attempts": len(plan["requests"]), "arms": list(ARMS),
                 "generation_end_checked": True, "production_accepted": False}
        or not isinstance(journal, list) or len(journal) != len(plan["requests"])):
        raise ValueError("reader answers are not fully sealed")
    byq = defaultdict(dict)
    costs = {a: {"model_seconds": 0.0, "input_tokens": 0, "generated": 0,
                 "missing": 0} for a in ARMS}
    seen = set()
    for request, row in zip(plan["requests"], journal, strict=True):
        qid, arm = request["question_id"], request["arm"]
        if (not isinstance(row, dict) or row.get("request_id") != request["request_id"]
            or row.get("question_id") != qid or row.get("arm") != arm
            or row.get("plan_sha256") != ph or row.get("reader_model_sha256") != MODEL_SHA
            or row.get("evidence_ids") != [v["source_id"] for v in request["evidence"]]
            or (qid, arm) in seen or row.get("status") not in ("succeeded", "unavailable", "failed")):
            raise ValueError("unregistered, duplicate, reordered or altered model response")
        seen.add((qid, arm))
        if row["status"] == "succeeded" and not isinstance(row.get("answer"), str):
            raise ValueError("successful response missing decoded text")
        byq[qid][arm] = row
        costs[arm]["model_seconds"] += row.get("seconds", 0.0)
        costs[arm]["input_tokens"] += row.get("input_tokens", 0)
        costs[arm]["generated"] += int(row["status"] == "succeeded")
        costs[arm]["missing"] += int(row["status"] != "succeeded")
    common = []
    for qid, arms in byq.items():
        if set(arms) != set(ARMS):
            raise ValueError("missing paired reader arm")
        family = qid.split("/")[0]
        index = int(qid.rsplit("q", 1)[1])
        label = families[family]["qa"][index].get("answer")
        if not isinstance(label, str) or not label.strip():
            continue
        if any(arms[a]["status"] != "succeeded" for a in ARMS):
            continue
        common.append({"family": family, "qid": qid,
                       "f1": {a: token_f1(arms[a]["answer"], label) for a in ARMS}})
    if len(common) < 1:
        raise ValueError("no jointly scoreable questions")
    means = {a: round(sum(r["f1"][a] for r in common) / len(common), 9) for a in ARMS}
    changes = {}
    for control in (a for a in ARMS if a != "graph"):
        differences = [row["f1"]["graph"]-row["f1"][control] for row in common]
        changes[control] = {"mean_delta": round(sum(differences)/len(differences), 9),
                            "wins": sum(v > 1e-9 for v in differences),
                            "losses": sum(v < -1e-9 for v in differences),
                            "ties": sum(abs(v) <= 1e-9 for v in differences)}
    for c in costs.values():
        c["model_seconds"] = round(c["model_seconds"], 4)
    report = {"schema": SCHEMA + ".paired-postseal.research.v1",
              "journal_sha256": digest(journal_raw), "plan_sha256": ph,
              "original_source_sha256": ORIGINAL_SHA,
              "planned_questions": plan["planned_questions"],
              "same_scorable_questions": len(common), "same_denominator_f1": means,
              "graph_comparisons": changes, "model_cost_by_arm": costs,
              "privileged_annotated_not_independently_sufficient": True,
              "model_worker_separate_process": True,
              "statistical_superiority_claim": False,
              "semantic_citation_precision": None,
              "production_accepted": False}
    write(out_path, report)
    return report


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("usage: ORIGINAL PLAN_DIR RUN_DIR NEW_REPORT")
    print(json.dumps(score(*sys.argv[1:]), sort_keys=True, indent=2))
