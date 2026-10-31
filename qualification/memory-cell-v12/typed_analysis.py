"""Postprocess frozen typed task outputs; performs no fitting or selection."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np


def analyze(root):
    summary_path = root / "SUMMARY.json"
    summary = json.loads(summary_path.read_text())
    runs = [row for row in summary["runs"] if row["phase"] > 0]
    arms = {}
    for name in runs[0]["results"]:
        by_seed, work, paired = {}, Counter(), Counter()
        equal_outputs = 0
        for run in runs:
            directory = root / f"seed-{run['seed']}" / f"phase-{run['phase']}"
            trace = json.loads((directory / f"test-{name}.json").read_text())["trace"]
            full = json.loads((directory / "test-full_typed.json").read_text())["trace"]
            successes, count = by_seed.get(str(run["seed"]), (0, 0))
            by_seed[str(run["seed"])] = (successes + sum(row["success"] for row in trace), count + len(trace))
            work.update(run["results"][name]["metrics"]["work"])
            for observed, reference in zip(trace, full, strict=True):
                if observed["query_id"] != reference["query_id"]:
                    raise ValueError("paired query identities differ")
                equal_outputs += observed["output"] == reference["output"]
                paired["full_only"] += reference["success"] and not observed["success"]
                paired["control_only"] += observed["success"] and not reference["success"]
                if observed["receipt"]["evidence_reads"] > 2:
                    raise ValueError("evidence budget exceeded")
        successes = sum(row[0] for row in by_seed.values())
        count = sum(row[1] for row in by_seed.values())
        rates = [successes / total for successes, total in by_seed.values()]
        arms[name] = dict(correct=successes, evaluated=count, success=successes / count,
            by_seed={seed: dict(correct=good, evaluated=total, success=good / total)
                     for seed, (good, total) in by_seed.items()},
            between_seed_std=float(np.std(rates, ddof=1)), paired_with_full=dict(paired),
            outputs_identical_to_full=equal_outputs, work=dict(work))
    full = arms["full_typed"]
    for values in arms.values():
        values["full_minus_control"] = full["success"] - values["success"]
    result = dict(schema="hepta.memory.typed-analysis.v12",
        summary_sha256=hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        phases=[1, 2], unique_future_queries=full["evaluated"] // len(full["by_seed"]),
        repeated_seed_evaluations=full["evaluated"], arms=arms,
        interpretation=["Seeds rerun the same authored tasks; their 618 outputs are not 618 independent tasks.",
            "Event/semantic/procedure output equality: " + str(all(arms["without_" + kind]["outputs_identical_to_full"] == full["evaluated"]
                                                                    for kind in ("event", "semantic", "procedure"))),
            "Full minus BM25 aggregate success: " + str(full["success"] - arms["bm25_generic"]["success"]),
            "Observed gains against the single classifier or history control concern addressing, not a demonstrated need for four reader types.",
            "Typed caches exchange retained representation/setup work for query parsing; tiny wall-time differences do not establish a general efficiency gain."])
    (root / "ANALYSIS.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.root), sort_keys=True, indent=2))
