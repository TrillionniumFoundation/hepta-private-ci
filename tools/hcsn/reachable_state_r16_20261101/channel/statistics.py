"""Predeclared paired-fit channel contrasts and separately scoped CPU accounts."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

from .features import KINDS


def contrast(values):
    values = np.asarray(values)
    mean = float(values.mean())
    radius = float(t.ppf(.975, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
    permutations = np.array(list(itertools.product((-1, 1), repeat=len(values))))
    null = permutations @ values / len(values)
    probability = float(np.mean(np.abs(null) >= abs(mean) - 1e-15))
    return dict(per_fit=values.tolist(), mean=mean, t95=[mean - radius, mean + radius],
                exact_two_sided_sign_flip_p=probability)


def summarize(directory):
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    rows = [json.loads((directory / f"{seed}_{domain}/RESULT.json").read_text())
            for seed in protocol["fit_seeds"] for domain in protocol["domains"]]
    if any(row["development"] or row["count"] != protocol["episodes_per_fit_domain"] for row in rows):
        raise ValueError("Confirmation must contain exactly the full registered new namespace")
    if len({row["source_commit"] for row in rows}) != 1 or len({row["source_manifest_sha256"] for row in rows}) != 1:
        raise ValueError("Mixed source identities")
    tests, averages, costs = {}, {}, {}
    for domain in protocol["domains"]:
        selected = [row for row in rows if row["domain"] == domain]
        averages[domain] = {}
        costs[domain] = {}
        for kind in KINDS:
            averages[domain][kind] = {name: float(np.mean([row["arms"][kind][name] for row in selected]))
                                      for name in ("mean_utility", "mean_reward", "mean_fee")}
            cold = np.mean([sum(row["preparation"][kind][name] for name in
                                  ("law_restore_cpu_seconds", "common_transition_preparation_cpu_seconds", "channel_preparation_cpu_seconds"))
                            + row["shared_input_decode_cpu_seconds"] for row in selected])
            warm = np.mean([row["arms"][kind]["online_cpu_seconds"] / row["count"] for row in selected])
            feature = np.mean([row["arms"][kind]["feature_cpu_seconds"] / (6 * row["count"]) for row in selected])
            costs[domain][kind] = dict(mean_cold_cpu_seconds=float(cold), mean_online_cpu_seconds=float(warm),
                                      mean_feature_cpu_per_query=float(feature),
                                      reused_current_cpu={str(n): float(cold + n * warm) for n in (1, 100, 1000, 10000)})
        for reference in ("stop_value", "ordinary_dual"):
            key = f"{domain}:value_risk-minus-{reference}"
            tests[key] = contrast([row["arms"]["value_risk"]["mean_utility"] - row["arms"][reference]["mean_utility"] for row in selected])
    order = sorted(tests, key=lambda key: tests[key]["exact_two_sided_sign_flip_p"])
    adjusted = 0.
    for rank, key in enumerate(order):
        adjusted = max(adjusted, min(1., (len(order) - rank) * tests[key]["exact_two_sided_sign_flip_p"]))
        tests[key]["holm_p"] = adjusted
        tests[key]["gain_gate"] = bool(tests[key]["mean"] >= .001 and tests[key]["t95"][0] > 0 and adjusted < .05)
    historical = {row["seed"]: row["historical_training"] for row in rows}
    return dict(schema="hcsn-r16-channel-statistics-v1", independent_unit="paired fit; n=8",
                source_commit=rows[0]["source_commit"], source_manifest_sha256=rows[0]["source_manifest_sha256"],
                worlds=sum(row["count"] for row in rows), arms=averages, tests=tests,
                gain_gate=all(row["gain_gate"] for row in tests.values()), current_costs=costs,
                historical_training=list(historical.values()),
                measured_worker_cpu_seconds=sum(row["measured_worker_cpu_seconds"] for row in rows),
                scope="Frozen one-action policies; inherited fitting separately reported, current costs are not full life-cycle or energy costs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.input)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(gain_gate=result["gain_gate"], worlds=result["worlds"], tests=result["tests"]), indent=2))
