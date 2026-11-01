"""Frozen paired-fit analysis; no successful-subset or secondary rescue."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

from .campaign import PROTOCOL, canonical, digest, write_new


def contrast(values):
    x = np.asarray(values, dtype=float)
    if x.shape != (8,) or not np.isfinite(x).all():
        raise ValueError("All eight finite fit-level differences are required")
    mean, se = float(x.mean()), float(x.std(ddof=1) / np.sqrt(8))
    critical = float(t.ppf(.975, 7))
    signs = np.array(list(itertools.product((-1, 1), repeat=8)))
    p = float(np.mean(np.abs((signs * x).mean(1)) >= abs(mean) - 1e-14))
    return dict(mean=mean, confidence_interval_95=[mean - critical * se, mean + critical * se],
                two_sided_sign_flip_p=p, per_fit=x.tolist())


def summarize(folder, output):
    folder, output = Path(folder), Path(output)
    workers = {}
    publication = set()
    total_worlds, checked_archives = 0, 0
    for seed, domain in itertools.product(PROTOCOL["fit_seeds"], PROTOCOL["domains"]):
        worker = folder / f"{seed}_{domain}"
        if (worker / "FAILURE.json").exists():
            raise RuntimeError("A failed worker makes the registered comparison incomplete")
        result = json.loads((worker / "RESULT.json").read_text())
        if (result["development"] or result["count"] != PROTOCOL["episodes_per_fit_domain"]
                or result["completed"] != result["count"] or result["seed"] != seed
                or result["domain"] != domain or set(result["arms"]) != set(PROTOCOL["arms"])):
            raise RuntimeError("Worker scope/count/arms mismatch")
        for archive in result["archives"]:
            path = worker / archive["file"]
            if digest(path) != archive["sha256"] or path.stat().st_size != archive["bytes"]:
                raise RuntimeError("Raw evidence hash/size mismatch")
            checked_archives += 1
        publication.add((result["freeze_commit"], result["source_manifest"]))
        workers[seed, domain] = result
        total_worlds += result["count"]
    if len(publication) != 1:
        raise RuntimeError("Worker source freezes differ")
    contrasts, primary, compression = {}, {}, {}
    for domain in PROTOCOL["domains"]:
        means = {name: np.array([workers[seed, domain]["arms"][name]["mean_utilities"]
                                for seed in PROTOCOL["fit_seeds"]]) for name in PROTOCOL["arms"]}
        comparisons = {"B-A": means["B"] - means["A"], "D-C": means["D"] - means["C"],
                       "C-A": means["C"] - means["A"], "D-B": means["D"] - means["B"],
                       "interaction": (means["D"] - means["C"]) - (means["B"] - means["A"])}
        comparisons.update({"D-" + mode: means["D"] - means[mode]
                            for mode in ("factorized", "block2", "block4", "block5")})
        contrasts[domain] = {name: contrast(value) for name, value in comparisons.items()}
        primary[domain] = dict(contrasts[domain]["D-B"])
    ordering = sorted(PROTOCOL["domains"], key=lambda d: primary[d]["two_sided_sign_flip_p"])
    previous = 0.
    for rank, domain in enumerate(ordering):
        adjusted = min(1., max(previous, (2 - rank) * primary[domain]["two_sided_sign_flip_p"]))
        previous = adjusted
        primary[domain]["holm_p"] = adjusted
        primary[domain]["passes"] = (primary[domain]["mean"] >= .01
                                     and primary[domain]["confidence_interval_95"][0] > 0
                                     and adjusted < .05)
    critical = float(t.ppf(1 - .05 / 12, 7))
    for mode in ("block2", "block4", "block5"):
        rows = {}
        for domain in PROTOCOL["domains"]:
            records = [workers[seed, domain] for seed in PROTOCOL["fit_seeds"]]
            guard = {}
            for metric in ("utilities", "rewards"):
                delta = np.array([r["arms"][mode]["mean_" + metric]
                                  - r["arms"]["D"]["mean_" + metric] for r in records])
                lower = float(delta.mean() - critical * delta.std(ddof=1) / np.sqrt(8))
                guard[metric] = dict(mean=float(delta.mean()), simultaneous_lower=lower,
                                     passes=lower > -.01, per_fit=delta.tolist())
            costs = {}
            for actor in (mode, "D"):
                costs[actor] = dict(
                    online_cpu=sum(r["arms"][actor]["online_cpu"] for r in records),
                    full_cpu_at_1000_uses=sum(
                        r["arms"][actor]["preparation_cpu"] + 1000 * (
                            r["arms"][actor]["online_cpu"] + r["arms"][actor]["checkpoint_cpu"]
                        ) / r["count"] for r in records))
            ratio = {key: costs[mode][key] / costs["D"][key] for key in costs[mode]}
            rows[domain] = dict(quality_guard=guard, measured_costs=costs, cost_ratios=ratio,
                                passes=all(g["passes"] for g in guard.values()) and max(ratio.values()) <= .90)
        compression[mode] = dict(domains=rows, passes=all(r["passes"] for r in rows.values()))
    aggregate = {domain: {name: {
        "utility": float(np.mean([workers[s, domain]["arms"][name]["mean_utilities"] for s in PROTOCOL["fit_seeds"]])),
        "reward": float(np.mean([workers[s, domain]["arms"][name]["mean_rewards"] for s in PROTOCOL["fit_seeds"]])),
        "online_cpu_seconds": sum(workers[s, domain]["arms"][name]["online_cpu"] for s in PROTOCOL["fit_seeds"]),
        "checkpoint_cpu_seconds": sum(workers[s, domain]["arms"][name]["checkpoint_cpu"] for s in PROTOCOL["fit_seeds"])
    } for name in PROTOCOL["arms"]} for domain in PROTOCOL["domains"]}
    summary = dict(schema="hcsn-r16-statistics-v1", complete_workers=len(workers), fresh_worlds=total_worlds,
                   independent_unit="Eight inherited fitted seeds, not individual queries", checked_archives=checked_archives,
                   freeze_commit=next(iter(publication))[0], source_manifest=next(iter(publication))[1],
                   primary=primary, primary_passes=all(r["passes"] for r in primary.values()),
                   paired_contrasts=contrasts, compression=compression, arm_aggregates=aggregate,
                   same_matrix_identical_worlds=sum(r["same_matrix_identical_worlds"] for r in workers.values()),
                   research_cpu_seconds=sum(r["process_cpu_seconds"] for r in workers.values()),
                   world_generation_cpu_seconds=sum(r["world_generation_cpu"] for r in workers.values()),
                   cost_limitations=["Process CPU on this host, not deployment energy or throughput",
                                     "Array compression still lifts to 40-state propagation/planning",
                                     "1000-use estimate excludes historical fitting from a different host; inherited costs remain in every raw receipt",
                                     "No production restart or network acceptance"])
    write_new(output, summary)
    print(canonical(dict(fresh_worlds=total_worlds, primary=primary,
                         compression_passes={m: r["passes"] for m, r in compression.items()})))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.run, args.output)
