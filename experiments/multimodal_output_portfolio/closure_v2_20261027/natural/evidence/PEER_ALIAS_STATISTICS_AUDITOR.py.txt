"""Recompute both estimands under the separately sealed source-only graph."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from .peer_natural import close, read, sha


def run(workspace, seal_path, sensitivity_path, output):
    seal, reported = read(seal_path), read(sensitivity_path)
    if sha(seal_path) != reported["source_only_seal_sha256"] or not reported["posthoc_diagnostic_not_new_qualification"]:
        raise ValueError("Alias sensitivity did not use the sealed source-only graph")
    if not seal["sealed_ns"] < reported["analyzed_ns"]:
        raise ValueError("Alias mapping was not sealed before group-outcome analysis")
    metrics = ["quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return"]
    original = read(workspace / "natural-v2-runs/document-qualification-001/ROWS.json")
    replication = read(workspace / "natural-v2-runs/document-replication-001/ROWS.json")
    reports = {}
    for name, expected in reported["result"].items():
        rows = original if name.startswith("first") else replication
        excluded = set()
        mapping = seal["physical_component"]
        if name == "replication_no_prior_physical":
            excluded = set(seal["replication_with_prior_source_overlap"]["physical"])
        elif name == "replication_no_prior_corporate_family":
            excluded = set(seal["replication_with_prior_source_overlap"]["corporate_family"])
            mapping = seal["corporate_family_component"]
        by_source = defaultdict(lambda: defaultdict(list))
        for row in rows:
            if row["id"] not in excluded and row["arm"] in {"original_rules", "rule_residual"}:
                by_source[row["id"]][row["arm"]].append([row[key] for key in metrics])
        clusters = defaultdict(list)
        for identity in sorted(by_source):
            group = by_source[identity]
            if any(len(group[arm]) != 2 for arm in ("original_rules", "rule_residual")):
                raise ValueError("Alias subset changed experimental repetitions")
            clusters[mapping[identity]].append(np.mean(group["rule_residual"], axis=0) - np.mean(group["original_rules"], axis=0))
        order = sorted(clusters)
        if order != expected["ordered_component_ids"] or len(by_source) != expected["documents"]:
            raise ValueError("Alias partition membership or cluster count differs")
        weights = np.array([len(clusters[key]) for key in order])
        means = np.asarray([np.mean(clusters[key], axis=0) for key in order])
        rng = np.random.default_rng(2844)
        selected = rng.integers(len(order), size=(5000, len(order)))
        maximum = 0.
        for kind, baseline in expected["estimands"].items():
            if kind == "equal_weight_per_audited_entity":
                point, draws = means.mean(0), means[selected].mean(1)
            else:
                point = np.average(means, weights=weights, axis=0)
                draws = (means[selected] * weights[selected, None]).sum(1) / weights[selected].sum(1)[:, None]
            interval = np.quantile(draws, [.0125, .9875], axis=0)
            for index, metric in enumerate(metrics):
                maximum = max(maximum, close(point[index], baseline[metric]["difference"]), close(interval[:, index], baseline[metric]["CI97_5"]))
        reports[name] = {"documents": len(by_source), "entities": len(order), "estimands_recomputed": 2,
            "maximum_statistic_discrepancy": maximum}
    result = {"passed": True, "source_seal_sha256": sha(seal_path), "sensitivity_sha256": sha(sensitivity_path),
        "reports": reports, "model_reruns": 0, "original_qualification_gates_unchanged": True,
        "source_entity_resolution_and_sensitivity_remain_posthoc": True}
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("workspace", "seal", "sensitivity", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.seal, args.sensitivity, args.output)
