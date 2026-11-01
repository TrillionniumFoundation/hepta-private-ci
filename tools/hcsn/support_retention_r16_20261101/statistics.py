"""Frozen paired-fit statistics; no successful-subset estimates for invalid arms."""

import itertools
import json

import numpy as np
from scipy.stats import t

from .study import HERE, save, verify


def interval(values, quantile=.975):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    half = float(t.ppf(quantile, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
    return dict(mean=mean, lower=mean - half, upper=mean + half, fits=values.tolist())


def signflip(values):
    values = np.asarray(values)
    distribution = np.asarray(list(itertools.product((-1, 1), repeat=len(values)))) @ values / len(values)
    return float(np.mean(np.abs(distribution) >= abs(values.mean()) - 1e-15))


def summarize():
    verify()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    rows = {(seed, domain): json.loads((HERE / "results" / f"summary_{seed}_{domain}.json").read_text())
            for seed in protocol["fits"] for domain in protocol["domains"]}
    processes = json.loads((HERE / "results/PROCESS_SUMMARY.json").read_text())
    if not processes["all_exited_zero"]:
        raise RuntimeError("Incomplete campaign; no successful-worker summary")
    arms = list(next(iter(rows.values()))["arms"])
    invalid = [arm for arm in arms if any(not row["arms"][arm]["valid"] for row in rows.values())]
    identity_ok = all(row["counts"]["hmm_trace_mismatches"] == 0 for row in rows.values())
    proc = {(r["fit"], r["domain"]): r for r in processes["processes"]}
    means, core, compression, costs = {}, {}, {}, {}
    for domain in protocol["domains"]:
        selected = [rows[seed, domain] for seed in protocol["fits"]]
        means[domain] = {arm: None if arm in invalid else {
            metric: float(np.mean([r["arms"][arm][metric] for r in selected]))
            for metric in ("utility", "reward", "cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
            for arm in arms}
        if not any(arm in invalid for arm in ("A", "B", "C", "D")):
            core[domain] = {}
            for label, left, right in (("B-A", "B", "A"), ("D-C", "D", "C"),
                                       ("C-A", "C", "A"), ("D-B", "D", "B")):
                differences = [r["arms"][left]["utility"] - r["arms"][right]["utility"] for r in selected]
                core[domain][label] = interval(differences)
                core[domain][label]["signflip_p"] = signflip(differences)
            core[domain]["interaction"] = interval([
                (r["arms"]["D"]["utility"] - r["arms"]["C"]["utility"])
                - (r["arms"]["B"]["utility"] - r["arms"]["A"]["utility"]) for r in selected])
        if not any(arm in invalid for arm in ("anchored", "D")):
            compression[domain] = {metric: interval([
                r["arms"]["anchored"][metric] - r["arms"]["D"][metric] for r in selected], .9875)
                for metric in ("utility", "reward")}
            costs[domain] = {}
            for uses in (1, 100, 1000, 10000):
                total = {arm: 0. for arm in ("D", "anchored")}
                for seed in protocol["fits"]:
                    row = rows[seed, domain]
                    investment = row["costs"]["inherited_training_cpu_seconds"] + sum(
                        proc[seed, d]["cpu_total_seconds"] for d in protocol["domains"])
                    for arm in total:
                        total[arm] += investment + row["arms"][arm]["preparation_cpu_seconds"] + uses * row["arms"][arm]["cpu_seconds"]
                costs[domain][str(uses)] = dict(cpu_seconds=total, ratio=total["anchored"] / total["D"])
            costs[domain]["online_ratio"] = means[domain]["anchored"]["cpu_seconds"] / means[domain]["D"]["cpu_seconds"]
    if len(core) == 2:
        ordered = sorted(core, key=lambda domain: core[domain]["D-B"]["signflip_p"])
        previous = 0.
        for rank, domain in enumerate(ordered):
            adjusted = min(1., max(previous, (2 - rank) * core[domain]["D-B"]["signflip_p"]))
            core[domain]["D-B"]["holm_p"] = adjusted
            previous = adjusted
    gain_gate = identity_ok and len(core) == 2 and all(
        c["D-B"]["mean"] >= .01 and c["D-B"]["lower"] > 0 and c["D-B"]["holm_p"] < .05 for c in core.values())
    noninferior = identity_ok and len(compression) == 2 and all(
        c[metric]["lower"] > -.01 for c in compression.values() for metric in ("utility", "reward"))
    cost_gate = noninferior and all(c["online_ratio"] <= .9 and c["1000"]["ratio"] <= .9 for c in costs.values())
    failures = [dict(fit=row["fit"], domain=row["domain"], **failure) for row in rows.values() for failure in row["failures"]]
    result = dict(schema="hcsn-support-retention-r16-statistics-v1", fits=len(protocol["fits"]),
        episodes=sum(row["episodes"] for row in rows.values()), invalid_global=invalid,
        original_2x2=core, arm_means=means, compression_minus_D=compression, reuse_cost=costs,
        gates=dict(same_matrix_hmm=identity_ok, original_core_gain=gain_gate,
                   anchored_quality_noninferiority=noninferior, anchored_quality_guarded_cost=cost_gate),
        failures=failures, attempts={arm: sum(row["counts"]["attempts"][arm] for row in rows.values()) for arm in arms},
        valid_attempts={arm: sum(row["counts"]["valid"][arm] for row in rows.values()) for arm in arms},
        cost_scope="Complete confirmation child CPU plus original frozen all-search training and separately prepared models. Development/audits reported separately, not whole-project cost. No joules/GPU/media/production cost.",
        costs=dict(complete_confirmation_cpu_seconds=processes["complete_child_cpu_seconds"],
                   inherited_training_cpu_seconds=sum(rows[seed,"iid"]["costs"]["inherited_training_cpu_seconds"] for seed in protocol["fits"])),
        all_blockers_closed=False, production_activation=False)
    save(HERE / "results/SUMMARY.json", result)
    print(json.dumps(dict(gates=result["gates"], costs=result["costs"], invalid=invalid)))


if __name__ == "__main__":
    summarize()
