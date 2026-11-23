"""Paired outcome differences on six held-out actors, with seeds averaged inside actors."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np


def compare(evidence):
    records = [json.loads(p.read_text()) for p in sorted((evidence / "confirm").glob("*.json"))
               if not p.name.endswith(".cost.json")]
    index = {(r["mode"], r["method"], r["seed"]): r for r in records}
    if len(index) != 27:
        raise ValueError("all 27 primary models are required")
    seeds = sorted({key[2] for key in index})
    sample = next(iter(index.values()))
    actors = sorted(sample["chosen"]["per_actor"])
    if len(actors) != 6:
        raise ValueError("paired six-actor expectation")
    weights = np.asarray(list(itertools.product(range(len(actors)), repeat=len(actors))))
    result = []
    for (left, right), method in itertools.product(
            (("qvi", "fixed"), ("qvi", "learned"), ("learned", "fixed")), ("keep", "bp", "wsp")):
        deltas = []
        decisions_changed = []
        for seed in seeds:
            a, b = index[left, method, seed], index[right, method, seed]
            if a["query_id"] != b["query_id"] or a["actor"] != b["actor"]:
                raise ValueError("unpaired queries")
            l, r = a["chosen"], b["chosen"]
            deltas.append([l["per_actor"][actor] - r["per_actor"][actor] for actor in actors])
            decisions_changed.append(sum(x != y for x, y in zip(
                zip(l["exit_prefix"], l["terminal_action"]), zip(r["exit_prefix"], r["terminal_action"]))))
        actor_means = np.mean(deltas, axis=0)
        boot = np.mean(actor_means[weights], axis=1)
        result.append(dict(left=left, right=right, method=method, seeds=seeds,
                           seed_deltas=np.mean(deltas, axis=1).tolist(),
                           decisions_changed_over_48=decisions_changed,
                           mean_utility_delta=float(actor_means.mean()), actor_mean_deltas=actor_means.tolist(),
                           actor_resampling_percentiles_2p5_97p5=np.quantile(boot, [.025, .975]).tolist()))
    return dict(actors=actors, comparisons=result,
                uncertainty="Descriptive equal-actor cluster bootstrap on six actors, all 6^6 resamples, seeds paired inside actor. Not independent-seed replications or corrected significance tests.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.evidence), ensure_ascii=False, allow_nan=False, indent=2))
