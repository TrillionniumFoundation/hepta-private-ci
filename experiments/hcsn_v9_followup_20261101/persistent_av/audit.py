"""Independent standard-library raw arithmetic/continuity auditor."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def audit(directory):
    checks, zero_dt, persistent, executions = 0, 0, 0, 0
    same_heads = {}
    for task in ("async_av", "av_binding"):
        frozen = json.loads((directory / f"{task}-FROZEN.json").read_text())
        for model in frozen["models"]:
            path = directory / task / f"{model['family']}-{model['seed']}-selected.pt"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == model["sha256"]
            checks += 1
        inputs = json.loads((directory / task / "INPUTS.json").read_text())
        for path, expected in inputs["sources"].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
            checks += 1
    rows = []
    with gzip.open(directory / "TRACES.jsonl.gz", "rt") as stream:
        for line in stream:
            trace = json.loads(line)
            result = trace["execution"]
            executions += 1
            accepted = [e for e in result["events"] if e.get("status") == "accepted"]
            assert len(accepted) == result["requested_observations"] == trace["requests"]
            assert trace["correct"] == (result["output"]["predicted_class"] == trace["label"])
            expected = (trace["correct"] - result["observation_fee"] - result["latency_fee"]
                        - result["deadline_penalty"])
            assert abs(trace["utility"] - expected) < 1e-12
            assert abs(result["observation_fee"] - trace["requests"] * .02) < 1e-12
            updates = trace["core_updates"]
            if trace["family"] == "direct":
                assert not updates
            else:
                assert len(updates) == len(accepted)
                last = [0.0] * 32
                for update, event, source in zip(updates, accepted, result["source_window_updates"], strict=True):
                    assert update["before"] == last
                    assert update["event"] == source["accepted_event_id"]
                    assert update["content_fingerprint"] == event["after"]
                    assert update["global_source_increment"] == source["global_source_increment"]
                    zero_dt += update["global_source_increment"] == 0 and update["after"] != last
                    persistent += any(last)
                    last = update["after"]
                    checks += 4
            if trace["policy"] == "fixed":
                key = trace["task"], trace["index"]
                p = result["output"]["probabilities"]
                assert key not in same_heads or same_heads[key] == p
                same_heads[key] = p
                assert trace["requests"] == 6
            checks += 6
            rows.append({k: trace[k] for k in ("task", "index", "seed", "family", "policy", "actor",
                                             "label", "correct", "requests", "utility", "head_parity")})
    summary = json.loads((directory / "SUMMARY.json").read_text())
    assert rows == summary["rows"] and executions == summary["executions"]
    assert zero_dt > 0 and persistent > 0
    return {"status": "passed", "executions": executions, "checks": checks,
            "zero_dt_updates_that_change_state": zero_dt, "updates_consuming_nonzero_prior_state": persistent,
            "scope": "Saved arithmetic, identity, causal-update continuity and shared fixed-head parity; "
                     "not independent neural numerical replay or scientific adoption"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run)
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
