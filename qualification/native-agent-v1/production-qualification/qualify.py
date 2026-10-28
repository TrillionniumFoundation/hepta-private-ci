#!/usr/bin/env python3
"""Freeze a complete matrix, optionally run fixture controls, and retain all held gates."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

from contracts import CONTROLS, SCHEMA, canonical, digest, preflight, validate
from fixture_adapter import OWNER_SCOPE, run_lane
from statistics_gate import summarize


def save_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def run(plan, corpus, output, execute=False):
    validate(plan, corpus)
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    # This directory is write-once. Its in-progress evidence is never reopened
    # as a resumable run; retained unknown effects require original-owner repair.
    frozen = {"schema": SCHEMA, "frozen_at_ns": time.time_ns(), "plan": plan, "corpus": corpus,
        "plan_sha256": hashlib.sha256(canonical(plan)).hexdigest(),
        "corpus_sha256": hashlib.sha256(canonical(corpus)).hexdigest(),
        "harness_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": sys.version, "execution_requested": execute}
    save_new(output / "FROZEN.json", frozen)
    checks = preflight(plan)
    save_new(output / "PREFLIGHT.json", {"status": "held" if checks else "ready_for_fixture_controls",
        "reasons": checks, "production_owner_adapter": "held", "does_not_launch_processes": True})
    rows, lane_records = [], []
    for lane in plan["lane_order"]:
        if execute and not checks:
            try:
                record, actual = run_lane(plan, lane, output)
            except (OSError, ValueError, KeyError, TypeError) as error:
                record, actual = {"lane": lane, "status": "failed", "reasons": [str(error)]}, {}
        else:
            record, actual = {"lane": lane, "status": "held", "reasons": checks or ["preflight only"]}, {}
        lane_records.append(record)
        for case in corpus["cases"]:
            for repeat in range(plan["repeats"]):
                row = {"group": plan["group"], "mode": plan["mode"], "lane": lane,
                    "case": case["id"], "repeat": repeat, "status": "held", "wall_ms": None,
                    "owner_scope": OWNER_SCOPE, "reasons": ["production adapter and independent oracle not implemented"]}
                if case["id"] in CONTROLS:
                    name = f"{repeat:02}-{CONTROLS[case['id']]}"
                    raw = actual.get(name)
                    if raw is not None:
                        row.update(status="passed" if raw["adapter_passed"] else "failed", wall_ms=raw["adapter_wall_ms"],
                            reasons=[] if raw["adapter_passed"] else ["raw case or provenance/audit failed"],
                            raw_report=record["report"], raw_row=name, usage=raw.get("result", {}).get("usage"),
                            model_calls=raw.get("result", {}).get("model_calls"), tool_calls=raw.get("result", {}).get("tool_calls"))
                    else:
                        row.update(status="held" if record["status"] == "held" else "not_run",
                            reasons=record.get("reasons", ["lane aborted before this planned case"]))
                rows.append(row)
        # Preserve completed lane evidence even when a later lane fails.
        save_new(output / (lane + "-RESULT.json"), {"lane": record, "rows": [r for r in rows if r["lane"] == lane]})
    report = summarize(plan, corpus, rows)
    report.update(frozen_sha256=digest(output / "FROZEN.json"), lanes=lane_records, rows=rows)
    save_new(output / "REPORT.json", report)
    print(json.dumps({"report": str(output / "REPORT.json"), "statuses": report["statuses"],
        "production_qualification": report["production_qualification"]}))
    return 2  # Held is a distinct non-success gate, even if every control passed.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("corpus.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-fixture-controls", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(json.loads(args.plan.read_text()), json.loads(args.corpus.read_text()),
        args.output, args.execute_fixture_controls))
