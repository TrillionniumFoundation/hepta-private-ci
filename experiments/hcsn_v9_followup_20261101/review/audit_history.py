"""Independently check full accepted-history storage and its frozen outputs."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory):
    checks, failures = 0, []

    def check(ok, name):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 25:
            failures.append(name)

    protocol = json.loads((directory / "PROTOCOL.json").read_text())
    summary = json.loads((directory / "SUMMARY.json").read_text())
    suffix = "/experiments/hcsn_v9_followup_20261101/persistent_av/history_reference.py"
    original = next(p for p in protocol["source_sha256"] if p.endswith(suffix))
    root, oldroot = directory.resolve().parents[3], Path(original[:-len(suffix)])
    for path, expected in protocol["source_sha256"].items():
        check(digest(root / Path(path).relative_to(oldroot)) == expected, "frozen history source")
    for task in ("async_av", "av_binding"):
        frozen = json.loads((directory / task / "FROZEN.json").read_text())
        for model in frozen["models"]:
            stem = "history-" + str(model["seed"])
            report = json.loads((directory / task / (stem + "-fit.json")).read_text())
            check(digest(directory / task / (stem + "-selected.pt")) == model["sha256"] == report["selected_sha256"], "selected history weight")
            check(report["selected_epoch"] == min(report["history"], key=lambda r: r["validation_bce"])["epoch"], "history validation-only selection")
            check(report["future_slot_mutation_causality_checks"] == 6, "six executed future mutation controls retained")
    with gzip.open(directory / "TRACES.jsonl.gz", "rt") as stream:
        traces = list(map(json.loads, stream))
    check(len(traces) == summary["executions"] == 144, "complete history execution inventory")
    groups, appends = defaultdict(list), 0
    for trace in traces:
        run = trace["execution"]
        accepted = [event for event in run["events"] if event.get("status") == "accepted"]
        history = trace["history"]
        check(len(history) == trace["requests"] == len(accepted) == run["requested_observations"], "one append per accepted request")
        check(len(history) <= 6 and len({r["event_id"] for r in history}) == len(history), "bounded unique history events")
        rows, levels, previous = [], {"audio": 0, "video": 0}, 0
        for append, event in zip(history, accepted):
            _, modality, level = event["action"].split(":")
            levels[modality] = int(level)
            current = max(levels.values())
            row = append["row"]
            check(len(row) == 41 and all(math.isfinite(v) for v in row), "41 finite accepted features")
            check(append["content_fingerprint"] == event["after"], "history bound to accepted cache fingerprint")
            check(append["global_source_increment"] == current - previous == row[-1], "history uses actual global source time only")
            check(row[38:40] == [levels["audio"]/3, levels["video"]/3], "history prefixes follow accepted actions")
            if rows:
                offset = 16 if modality == "audio" else 0
                check(row[offset:offset+16] == rows[-1][offset:offset+16], "unobserved modality unchanged in appended cache")
            rows.append(row)
            encoded = json.dumps([append["content_fingerprint"], rows], separators=(",", ":"), allow_nan=False).encode()
            check(append["digest"] == list(hashlib.sha256(encoded).digest()), "digest binds complete ordered accepted history")
            previous = current
            appends += 1
        output = run["output"]
        predicted = max(range(len(output["probabilities"])), key=output["probabilities"].__getitem__)
        check(trace["correct"] == (predicted == trace["label"]), "history prediction scoring")
        check(math.isclose(trace["utility"], float(trace["correct"]) - run["observation_fee"] - run["latency_fee"] - run["deadline_penalty"], abs_tol=1e-12), "history complete realized fees")
        groups[trace["task"], trace["policy"]].append(trace)
    recomputed = []
    for group in summary["groups"]:
        rows = groups[group["task"], group["policy"]]
        values = {"accuracy": statistics.mean(r["correct"] for r in rows), "mean_utility": statistics.mean(r["utility"] for r in rows), "mean_requests": statistics.mean(r["requests"] for r in rows)}
        check(len(rows) == group["runs"] and all(math.isclose(v, group[k], abs_tol=1e-12) for k, v in values.items()), "history group arithmetic")
        recomputed.append({"task": group["task"], "policy": group["policy"], **values})
    return {"checks": checks, "all_checks_passed": not failures, "failed_examples": failures,
            "executions": len(traces), "accepted_history_appends": appends, "groups": recomputed,
            "limits": "Stored chronological accepted snapshots and digest arithmetic; no independent neural replay, strongest-family qualification or new recording admission"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
