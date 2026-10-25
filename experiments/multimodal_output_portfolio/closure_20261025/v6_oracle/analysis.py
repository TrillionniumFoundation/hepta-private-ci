"""Source-cluster uncertainty and explicit infeasible finite-oracle headroom."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import numpy as np

from .engine import paths
from .registry import sha, write_json
from .run import HISTORICAL, SETTINGS, ce


def run(directory, protocol_path):
    protocol = json.loads(Path(protocol_path).read_text())
    complete = json.loads((directory / "completion.json").read_text())
    if complete["source_pairs"] != 64 or complete["policy_requests"] != 1280:
        raise ValueError("Incomplete registered census")
    for name, field in (("endpoints.jsonl.gz", "endpoints_sha256"), ("policies.jsonl.gz", "policies_sha256"), ("utilities.npz", "utilities_sha256")):
        if sha(directory / name) != complete[field]:
            raise ValueError("Closed evidence changed")
    with gzip.open(directory / "policies.jsonl.gz", "rt") as stream:
        rows = list(map(json.loads, stream))
    names = list(protocol["selected"]) + list(HISTORICAL)
    keyed = {(r["policy"], r["case"], r["draw"]): r for r in rows}
    if len(keyed) != len(rows) or set(keyed) != {(p, c, d) for p in names for c in range(64) for d in range(2)}:
        raise ValueError("Missing or duplicate policy request")
    with gzip.open(directory / "endpoints.jsonl.gz", "rt") as stream:
        endpoints = list(map(json.loads, stream))
    nodes = {(r["mode"], r["case"], r["draw"], tuple(r["path"])): r for r in endpoints}
    expected = {(m, c, d, p) for m in ("full", "allocation") for c in range(64) for d in range(2) for p in paths(m)}
    if len(nodes) != len(endpoints) or set(nodes) != expected:
        raise ValueError("Finite tree missing or duplicate endpoints")
    # Every score is attached to durable media; recheck every output digest.
    for row in [*rows, *endpoints]:
        for kind, name in row["output_paths"].items():
            if sha(directory / row["output_directory"] / name) != row["output_hashes"][kind]:
                raise ValueError("Serialized media identity changed")
    values, depths, measured_ms, details = {}, {}, {}, {}
    for name in names:
        rs = [keyed[name, c, d] for c in range(64) for d in range(2)]
        values[name] = np.array([r["metrics"]["utility"] for r in rs]).reshape(64, 2)
        depths[name] = np.array([len(r["actions"]) for r in rs]).reshape(64, 2)
        measured_ms[name] = np.array([r["whole_request_wall_ns"] / 1e6 for r in rs]).reshape(64, 2)
        details[name] = {"feasible": True, "paths": dict(Counter(",".join(r["actions"]) or "stop" for r in rs)),
                         "mean_whole_request_wall_ms": float(measured_ms[name].mean())}
    table = np.load(directory / "utilities.npz")
    for mode in ("full", "allocation"):
        reconstructed = np.array([nodes[mode, c, d, p]["metrics"]["utility"]
                                  for c in range(64) for d in range(2) for p in paths(mode)]).reshape(64, 2, len(paths(mode)))
        if not np.array_equal(reconstructed, table[mode]):
            raise ValueError("Numeric utility table differs from actual scored output rows")
    common = set(paths("allocation"))
    for space, mode in (("full", "full"), ("common_allocation", "full"), ("historical_allocation", "allocation")):
        indices = [i for i, p in enumerate(paths(mode)) if space != "common_allocation" or p in common]
        utility = table[mode][:, :, indices]
        lengths = np.array([len(paths(mode)[i]) for i in indices])
        for objective, price in (("raw", 0.), ("depth_adjusted", SETTINGS["continuation_price"])):
            best = (utility - price * lengths).argmax(2)
            name = f"oracle_{space}_{objective}"
            values[name] = np.take_along_axis(utility, best[:, :, None], 2).squeeze(2)
            depths[name] = lengths[best]
            details[name] = {"feasible": False, "candidate_count": len(indices),
                             "selection": objective, "scope": SETTINGS["oracle_scope"]}
    rng = np.random.default_rng(SETTINGS["bootstrap_seed"])
    weights = rng.multinomial(64, np.full(64, 1 / 64), size=SETTINGS["bootstrap_replicates"]) / 64
    def bootstrap_ce(x):
        z = -2 * x
        shift = z.max()
        moments = np.exp(z - shift).mean(1)
        return -(np.log(weights @ moments) + shift) / 2
    boots = {}
    for name, utility in values.items():
        net = utility - SETTINGS["continuation_price"] * depths[name]
        details[name].update(mean_utility=float(utility.mean()), CE=ce(utility), depth_adjusted_CE=ce(net),
                             mean_continuation_depth=float(depths[name].mean()))
        boots[name] = (bootstrap_ce(utility), bootstrap_ce(net))
    contrasts = {}
    for reference, candidate in (
            ("strong_fixed_ce", "risk_aware_recursive"),
            ("strong_common_allocation_ce", "strong_fixed_ce"),
            ("strong_historical_allocation_ce", "strong_fixed_ce"),
            ("strong_fixed_ce", "oracle_full_raw"),
            ("risk_aware_recursive", "oracle_full_raw"),
            ("oracle_common_allocation_raw", "oracle_full_raw"),
            ("strong_fixed_ce", "oracle_full_depth_adjusted")):
        record = {}
        for index, field in enumerate(("CE", "depth_adjusted_CE")):
            draws = boots[candidate][index] - boots[reference][index]
            record[field] = {"estimate": details[candidate][field] - details[reference][field],
                             "percentile_95_interval": np.quantile(draws, [.025, .975]).tolist()}
        contrasts[candidate + " minus " + reference] = record
    result = {"schema": "hepta.closure.original-v6-finite-headroom.v1", "status": "completed",
        "identity": complete["identity"], "source_pairs": 64, "view_source_counts": complete["view_source_counts"],
        "draws_per_source": 2, "independent_generator_seeds": 1, "endpoint_outputs": len(nodes),
        "feasible_policy_requests": len(rows), "actual_media_files_verified": 2 * (len(nodes) + len(rows)),
        "common_initial_allocation_is_subset_of_full": True, "details": details, "contrasts": contrasts,
        "bootstrap": {"unit": "source pair; both initial-noise draws retained together, policies paired",
                      "replicates": 2000, "intervals": "unadjusted descriptive 95%; no familywise guarantee"},
        "whole_collection_wall_ns": complete["wall_ns"], "whole_collection_cpu_ns": complete["cpu_ns"],
        "whole_process_peak_rss_bytes": complete["process_peak_rss_bytes"],
        "scope": SETTINGS["oracle_scope"], "oracle_cost_scope": SETTINGS["cost_scope"],
        "no_conclusion_about": ["new training seeds", "audio", "video", "general NDU/FBSDE global optimum", "production qualification"]}
    write_json(directory / "analysis.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.directory, args.protocol), sort_keys=True))
