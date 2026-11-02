"""Independent standard-library audit of historical persistent-AV execution logs."""

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

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 30:
            failures.append(label)

    def close(a, b):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)

    protocol = json.loads((directory / "PROTOCOL.json").read_text())
    summary = json.loads((directory / "SUMMARY.json").read_text())
    suffix = "/experiments/hcsn_v9_followup_20261101/persistent_av/candidate.py"
    candidate = next(p for p in protocol["source_sha256"] if p.endswith(suffix))
    original_root = Path(candidate[:-len(suffix)])
    current_root = directory.resolve().parents[3]
    for path, expected in protocol["source_sha256"].items():
        relative = Path(path).relative_to(original_root)
        check(digest(current_root / relative) == expected, "current source matches protocol: " + str(relative))
    check(protocol["scientific_confirmation"] is False, "historical role retained")
    check(protocol["four_cell_complete"] is False, "missing analytic AV role retained")
    for task in protocol["tasks"]:
        frozen = json.loads((directory / (task + "-FROZEN.json")).read_text())
        inputs = json.loads((directory / task / "INPUTS.json").read_text())
        check(len(inputs["train"]["source_ids"]) > 0 and len(inputs["validation"]["source_ids"]) > 0, "training identities retained")
        for record in frozen["models"]:
            stem = f"{record['family']}-{record['seed']}"
            path = directory / task / (stem + "-selected.pt")
            fitted = json.loads((directory / task / (stem + "-fit.json")).read_text())
            check(digest(path) == record["sha256"] == fitted["selected_sha256"], "selected frozen checkpoint")
            selected = min(fitted["history"], key=lambda r: r["validation_bce"])
            check(fitted["selected_epoch"] == selected["epoch"], "historical validation-only checkpoint choice")
            check((directory / task / (stem + "-final.pt")).is_file(), "final checkpoint retained")
    with gzip.open(directory / "TRACES.jsonl.gz", "rt") as stream:
        traces = [json.loads(line) for line in stream]
    check(len(traces) == summary["executions"] == len(summary["rows"]), "complete AV inventory")
    groups, updates, zero_dt_updates = defaultdict(list), 0, 0
    identities = set()
    for trace in traces:
        key = tuple(trace[k] for k in ("task", "index", "seed", "family", "policy"))
        check(key not in identities, "unique AV execution identity")
        identities.add(key)
        execution = trace["execution"]
        accepted = [e for e in execution["events"] if e.get("status") == "accepted"]
        check(len(accepted) == trace["requests"] == execution["requested_observations"], "all AV issued requests accepted")
        probabilities = execution["output"]["probabilities"]
        check(close(sum(probabilities), 1.) and min(probabilities) >= 0., "common head probability simplex")
        predicted = max(range(len(probabilities)), key=probabilities.__getitem__)
        check(execution["output"]["predicted_class"] == predicted, "common head predicted class")
        check(trace["correct"] == (predicted == trace["label"]), "historical label accuracy")
        check(close(trace["utility"], float(trace["correct"]) - execution["observation_fee"]
                    - execution["latency_fee"] - execution["deadline_penalty"]), "all realized AV fees")
        state = [0.]*32
        history = trace["core_updates"]
        if trace["family"] == "direct":
            check(not history, "no-core direct reference")
        else:
            check(len(history) == len(accepted), "persistent update once per accepted observation")
            for update in history:
                check(update["before"] == state, "state passed across actual AV accepts")
                check(len(update["after"]) == 32 and all(math.isfinite(x) for x in update["after"]), "finite 32-scalar state")
                check(update["global_source_increment"] >= 0., "causal global source increment")
                check(update["content_fingerprint"] != "", "content binding retained")
                if update["global_source_increment"] == 0. and update["before"] != update["after"]:
                    zero_dt_updates += 1
                state = update["after"]
                updates += 1
        groups[trace["task"], trace["family"], trace["policy"]].append(trace)
    recomputed = []
    for group in summary["groups"]:
        rows = groups[group["task"], group["family"], group["policy"]]
        values = {"accuracy": statistics.mean(r["correct"] for r in rows),
                  "mean_utility": statistics.mean(r["utility"] for r in rows),
                  "mean_requests": statistics.mean(r["requests"] for r in rows)}
        check(len(rows) == group["runs"], "group run count")
        check(all(close(group[k], v) for k, v in values.items()), "independent group mean arithmetic")
        recomputed.append({"task": group["task"], "family": group["family"], "policy": group["policy"], **values})
    return {"schema": "hcsn-v9-independent-av-review.v1", "checks": checks,
            "all_checks_passed": not failures, "failed_examples": failures, "executions": len(traces),
            "persistent_updates": updates, "zero_global_dt_content_updates": zero_dt_updates,
            "groups": recomputed, "scientific_confirmation": False,
            "limits": "Log arithmetic, checkpoint/source identities and state-chain audit; does not independently rerun neural matrices or re-establish strong frontend/new recording admission"}


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
