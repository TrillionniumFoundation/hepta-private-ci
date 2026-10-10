"""Read-only complete-census replay; no model, judge or selection authority."""

import argparse
import json
from pathlib import Path

from bundle_census import summarize
from composition_evidence import ARCHIVE_SHA, LIMITS, parse_json, sha, write
from composition_policy import readiness
from composition_trial import capability_plan
from native import digest
from reviewed_bundle import strict_read


def collect(root, data, output):
    ready = parse_json((data / "READY.json").read_text())
    plan = strict_read(data / "plan.json", ready["plan_sha256"], 64 * 1024 * 1024)
    if plan["dataset_sha256"] != ARCHIVE_SHA or plan["frozen_counts"] != LIMITS:
        raise ValueError("wrong predeclared data census")
    # Wire JSON converts dataclass tuples to arrays; compare the canonical view.
    expected_plan = parse_json(json.dumps(capability_plan(plan), allow_nan=False))
    expected_ids = [c["question"]["identity"] for c in expected_plan["cases"]]
    results, sources = {}, set()
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        inv = parse_json((directory / "inventory.json").read_text())
        tier = inv["tier"]
        if tier not in ("135M", "360M", "1.7B") or tier in results:
            raise ValueError("extra or duplicated reader tier")
        source = (directory / "tested-commit.txt").read_text().strip()
        sources.add(source)
        base = directory / "execution"
        generated_plan = parse_json((base / "capability-plan.json").read_text())
        if generated_plan != expected_plan or digest(inv["inventory"]) != inv["inventory_digest"]:
            raise ValueError("different candidate evidence or model files")
        execution = parse_json((base / "capability/execution.json").read_text())
        if (execution["tested_commit"] != source
            or execution["reader_identity"] != inv["inventory_digest"]
            or execution["plan_sha256"] != sha((base / "capability-plan.json").read_bytes())
            or execution["labels_sha256"] != ready["labels_sha256"]):
            raise ValueError("wrong model/data/source execution receipt")
        raw = [parse_json(line) for line in (base / "capability/raw-answers.jsonl").read_text().splitlines()]
        scored = parse_json((base / "capability/scored-answers.json").read_text())
        if len(raw) != len(scored):
            raise ValueError("raw/scored census differs")
        for a, b in zip(raw, scored):
            if any(b.get(k) != v for k, v in a.items()):
                raise ValueError("post-hoc mutation of original model output")
        gate = readiness(scored, expected_ids, inv["inventory_digest"], digest(plan))
        result = parse_json((base / "result.json").read_text())
        if result["source_commit"] != source or result["gate"] != gate:
            raise ValueError("different readiness result")
        if result["optimizer_executed"] is not gate["development_ready"]:
            raise ValueError("learning bypassed its measured precondition")
        if not gate["development_ready"]:
            if (base / "learned-policy.json").exists() or result.get("transfer"):
                raise ValueError("rejected reader still trained or exposed final tasks")
        else:
            artifact = parse_json((base / "learned-policy.json").read_text())
            if (artifact != result["training"] or artifact["parameters"] != 8
                or not artifact["parameter_delta_squared_norm"] > 0
                or not 1 <= artifact["updates"] <= 256):
                raise ValueError("missing actual learned policy")
            transfer = [parse_json(line) for line in (base / "transfer-raw.jsonl").read_text().splitlines()]
            wanted = {(c["question"]["identity"], arm) for c in plan["cases"]
                      if c["phase"] in ("transfer", "retention") for arm in ("fixed", "learned")}
            if len(transfer) != len(wanted) or {(r["question_id"], r["arm"]) for r in transfer} != wanted:
                raise ValueError("missing frozen transfer task")
            if any(r.get("query_train_tokens", 0) != 0 for r in transfer):
                raise ValueError("query-time adaptation")
        summary = parse_json((base / "capability/report.json").read_text())
        if summary != summarize(scored, generated_plan):
            raise ValueError("summary differs from original scored census")
        if summary["raw_census"] != 72 or result["production_accepted"] is not False:
            raise ValueError("incomplete or improperly qualified diagnostic")
        results[tier] = dict(model=inv["repository"], revision=inv["revision"],
            capability=summary["summaries"], readiness=gate,
            optimizer_executed=result["optimizer_executed"], transfer=result.get("transfer"),
            actual_training=result.get("training"))
    if set(results) != {"135M", "360M", "1.7B"} or len(sources) != 1:
        raise ValueError("incomplete or mixed-source reader matrix")
    output_value = dict(source_commit=sources.pop(), plan_digest=digest(plan),
        data_sha256=ARCHIVE_SHA, readers=results, reader_size_is_not_memory_gain=True,
        minimal_sufficiency_certified=False, independent_review=False,
        semantic_citation_precision=None, production_accepted=False, superiority_claim=False)
    write(output, output_value)
    return output_value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "data", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    collect(args.root, args.data, args.output)
