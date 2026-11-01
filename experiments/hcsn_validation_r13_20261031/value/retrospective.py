"""Already-seen R12 records: algebraic regression diagnosis, never fresh data."""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

from .run import BASE, REPO, inherited, sha, write


def diagnose(output):
    root = inherited.BASE/"evidence/confirmation_01"
    results, inputs = [], {}
    paths = sorted(root.glob("*/*/RESULT.json"))
    if len(paths) != 48:
        raise ValueError("The inherited fixed matrix is incomplete")
    for path in paths:
        original = json.loads(path.read_text())
        inputs[str(path.relative_to(REPO))] = sha(path)
        states = {}
        for part in original["evidence_parts"]["states"]:
            raw = path.parent/part["file"]
            if sha(raw) != part["sha256"]:
                raise ValueError("Original state evidence changed")
            inputs[str(raw.relative_to(REPO))] = sha(raw)
            with gzip.open(raw, "rt") as stream:
                for line in stream:
                    value = json.loads(line)
                    states[tuple(value["history"])] = value
        for name in original["policies"]:
            empty, saved = {}, 0.
            for history, value in sorted(states.items(), key=lambda pair:len(pair[0]), reverse=True):
                row = value["policies"][name]
                empty[history] = row["chosen"] == "STOP" or (row["chosen"] == "SKIP" and empty[history+(-1,)])
                if row["chosen"] == "SKIP" and empty[history]:
                    saved += row["occupancy"]*original["config"]["skip_cost"]
            base = original["policies"][name]["exact"]["return"]
            results.append(dict(family=original["family"], seed=original["seed"], config=original["config"]["name"],
                controller=name, original_return=base, algebraic_saved_fee=saved, algebraic_guarded_return=base+saved,
                initial_stop=original["initial_stop"]))
    groups = {}
    for family in ("ordinary", "analytic"):
        for name in original["policies"]:
            chosen = [r for r in results if r["family"] == family and r["controller"] == name]
            groups[family+"/"+name] = {k:float(np.mean([r[k] for r in chosen]))
                for k in ("original_return", "algebraic_saved_fee", "algebraic_guarded_return")}
            for key in ("original_return", "algebraic_guarded_return"):
                groups[family+"/"+name][key+"_below_stop"] = sum(r[key] < r["initial_stop"]-2e-10 for r in chosen)
    write(output, dict(scope="Retrospective algebra on already-seen R12 raw state records; no fresh claim and no new actor timing.",
          cases=48, rows=results, groups=groups, input_sha256=inputs))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if BASE not in args.output.resolve().parents:
        parser.error("Output must stay within R13 value")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    diagnose(args.output)
