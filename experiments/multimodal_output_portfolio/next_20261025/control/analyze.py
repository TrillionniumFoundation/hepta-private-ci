"""Writer-cluster paired inference, parity and selected-action calibration."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

import numpy as np

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.control.analysis import ce, interval
from .run import POLICIES


def identity(row):
    return tuple(row[k] for k in ("seed", "case", "view", "draw", "policy"))


def run(directory):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    completion = json.loads((directory / "completion.json").read_text())
    for name, digest in completion["files_sha256"].items():
        if file_sha(directory / name) != digest: raise ValueError("Closed evidence changed: " + name)
    registration = json.loads((directory / "registration.json").read_text())
    spec = registration["spec"]
    with gzip.open(directory / "requests.jsonl.gz", "rt") as stream:
        original = list(map(json.loads, stream))
    rows = {identity(r): r for r in original}
    with gzip.open(directory / "scored.jsonl.gz", "rt") as stream:
        scored = list(map(json.loads, stream))
    if len(rows) != len(original) or len(scored) != len(rows) or {identity(r) for r in scored} != set(rows):
        raise ValueError("Repeated/missing request or score")
    for r in scored: rows[identity(r)].update(r)
    seeds, count, draws, policies = spec["seeds"], spec["source"]["pairs"], spec["draws"], spec["policies"]
    from ...v7.data import VIEWS
    expected = {(s, c, v, d, p) for s in seeds for c in range(count) for v in VIEWS for d in range(draws) for p in policies}
    if set(rows) != expected: raise ValueError("Registered finite census differs")
    failures = [r for r in rows.values() if r["status"] != "completed"]
    if failures:
        write_json(directory / "analysis.json", {"status": "blocked_by_execution_failure", "requests": len(rows), "failures": failures})
        return
    commits = Counter()
    with gzip.open(directory / "commitments.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            key = identity(row); index = commits[key]
            if row["decision_index"] != index or any(row[k] != v for k, v in rows[key]["decisions"][index].items()):
                raise ValueError("Durable pre-innovation commitment differs")
            commits[key] += 1
    if set(commits) != set(rows) or any(commits[k] != len(v["decisions"]) for k, v in rows.items()):
        raise ValueError("Incomplete durable commitment census")
    compiled_parity, feedback_initial_parity, cost_access = 0, 0, 0
    for s, c, v, d in ((s, c, v, d) for s in seeds for c in range(count) for v in VIEWS for d in range(draws)):
        old, new = rows[s, c, v, d, "cached_teacher"], rows[s, c, v, d, "compiled_teacher"]
        if (old["path"], old["output_sha256"], [x["public_sha256"] for x in old["decisions"]]) != (new["path"], new["output_sha256"], [x["public_sha256"] for x in new["decisions"]]):
            raise ValueError("Exact implementation changed an action or actual output")
        compiled_parity += 1
        fresh, stale = rows[s, c, v, d, "fresh_feedback"], rows[s, c, v, d, "stale_feedback"]
        if (fresh["decisions"][0]["action"], fresh["decisions"][0]["public_sha256"]) != (stale["decisions"][0]["action"], stale["decisions"][0]["public_sha256"]):
            raise ValueError("Feedback comparison does not share root action/state")
        feedback_initial_parity += 1
        if fresh["path"] != old["path"] or fresh["output_sha256"] != old["output_sha256"]:
            raise ValueError("Equal-access fresh policy differs from teacher function")
        for decision in (*fresh["decisions"], *stale["decisions"]):
            if not decision["new_draft_delivered"] or not decision["both_heads_actually_executed"]:
                raise ValueError("Feedback access or computation omitted")
            cost_access += 1
    if spec["source"]["kind"] == "historical_development":
        cluster_ids = list(range(count)); cluster_scope = "historical source pair; no new independent sources"
    else:
        allocation = json.loads(Path(spec["source"]["allocation"]).read_text())
        cluster_ids = allocation["roles"]["control"]["pair_writer_ids"]
        cluster_scope = "Held-out QMNIST writer, all pairs/views/draws and fixed seed panel remain together"
    if len(cluster_ids) != count: raise ValueError("Writer cluster census differs")
    clusters = sorted(set(cluster_ids)); cluster_map = np.asarray([clusters.index(x) for x in cluster_ids])
    sizes = np.bincount(cluster_map, minlength=len(clusters)).astype(float)
    shape = (len(policies), len(seeds), count, len(VIEWS), draws)
    utility, success, secondary, wall_cost, cpu_cost = (np.empty(shape) for _ in range(5))
    detail, calibration = {}, {}
    for pi, policy in enumerate(policies):
        work, selected = Counter(), []
        for si, s in enumerate(seeds):
            for c in range(count):
                for vi, v in enumerate(VIEWS):
                    for d in range(draws):
                        r = rows[s, c, v, d, policy]; index = pi, si, c, vi, d
                        utility[index] = r["scores"]["primary"]["utility"]
                        success[index] = r["scores"]["primary"]["joint_fact_correct"]
                        secondary[index] = r["scores"]["secondary"]["utility"]
                        wall_cost[index], cpu_cost[index] = r["wall_ns"] / 1e6, r["cpu_ns"] / 1e6
                        work.update(r["work"])
                        if "stop_scores" in r:
                            step = r["decisions"][-1]
                            actual = np.exp(-2 * (utility[index] - .002 * (step["action"] != "stop"))) - np.exp(-2 * r["stop_scores"]["primary"]["utility"])
                            selected.append((c, step["predicted_action_minus_stop_moment"], actual, step["action"] != "stop"))
        detail[policy] = {"CE": ce(utility[pi]), "success": float(success[pi].mean()),
            "secondary_CE": ce(secondary[pi]), "mean_wall_ms": float(wall_cost[pi].mean()),
            "mean_cpu_ms": float(cpu_cost[pi].mean()), "wall_p50_p95_p99_max_ms": np.quantile(wall_cost[pi], [.5, .95, .99, 1.]).tolist(),
            "work": dict(work), "per_seed": {str(s): {"CE": ce(utility[pi, i]), "success": float(success[pi, i].mean()),
                "mean_wall_ms": float(wall_cost[pi, i].mean())} for i, s in enumerate(seeds)}}
        calibration[policy] = selected
    rng = np.random.default_rng(spec["inference"]["bootstrap_seed"])
    bw = rng.multinomial(len(clusters), np.full(len(clusters), 1 / len(clusters)), size=spec["inference"]["replicates"])
    denominators = bw @ sizes
    def means(values):
        per_pair = values.mean(axis=(1, 3, 4))
        sums = np.stack([per_pair[:, cluster_map == i].sum(-1) for i in range(len(clusters))], -1)
        return sums @ bw.T / denominators
    def ces(values):
        shift = (-2 * values).max(axis=(1, 2, 3, 4))
        return -(np.log(means(np.exp(-2 * values - shift[:, None, None, None, None]))) + shift[:, None]) / 2
    boots = [ces(utility), means(success), means(wall_cost), means(cpu_cost), ces(secondary)]
    contrasts = {}
    comparisons = (("compiled_teacher", "cached_teacher"), ("fresh_feedback", "stale_feedback"),
                   ("cached_teacher", "strong_nonfeedback"), ("cached_teacher", "fixed_allocation"))
    for candidate, reference in comparisons:
        a, b = policies.index(candidate), policies.index(reference)
        estimates = (ce(utility[a]) - ce(utility[b]), success[a].mean() - success[b].mean(),
                     wall_cost[a].mean() - wall_cost[b].mean(), cpu_cost[a].mean() - cpu_cost[b].mean(), ce(secondary[a]) - ce(secondary[b]))
        contrast = {name: interval(point, samples[a] - samples[b], spec["inference"]["level"]) for name, point, samples in zip(
            ("raw_CE", "success", "mean_wall_ms", "mean_cpu_ms", "secondary_CE"), estimates, boots)}
        contrast["original_replacement_family_pass"] = contrast["raw_CE"]["lower"] >= -.005 and contrast["success"]["lower"] >= -.005 and contrast["mean_wall_ms"]["upper"] < 0
        contrast["quality_superiority_family_pass"] = contrast["raw_CE"]["lower"] > 0 and contrast["success"]["lower"] >= 0
        for clock, costs in (("wall", wall_cost), ("cpu", cpu_cost)):
            points, samples = [], []
            for price in spec["inference"]["prices"]:
                value = utility - price * costs; boot = ces(value)
                points.append(ce(value[a]) - ce(value[b])); samples.append(boot[a] - boot[b])
            radius = float(np.quantile(np.max(np.abs(np.stack(samples) - np.asarray(points)[:, None]), axis=0), .95))
            contrast[clock + "_price_curve"] = [{"price": price, "estimate": point, "simultaneous_lower": point - radius,
                "simultaneous_upper": point + radius} for price, point in zip(spec["inference"]["prices"], points)]
        contrasts[candidate + "_minus_" + reference] = contrast
    for policy, selected in calibration.items():
        if not selected: continue
        arr = np.asarray(selected); group = cluster_map[arr[:, 0].astype(int)]
        sums = np.stack([arr[group == i, 2].sum() for i in range(len(clusters))])
        counts = np.bincount(group, minlength=len(clusters))
        boot = (bw @ sums) / np.maximum(bw @ counts, 1)
        bins = []
        for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.)):
            keep = (arr[:, 1] >= lo) & (arr[:, 1] < hi)
            bins.append({"range": [lo, hi], "n": int(keep.sum()), "predicted": float(arr[keep, 1].mean()) if keep.any() else None,
                         "realized": float(arr[keep, 2].mean()) if keep.any() else None})
        detail[policy]["selected_H1_calibration"] = {"n": len(arr), "nonstop_n": int(arr[:, 3].sum()),
            "prediction_bias": float((arr[:, 1] - arr[:, 2]).mean()), "MSE": float(((arr[:, 1] - arr[:, 2]) ** 2).mean()),
            "realized_action_minus_stop_moment": interval(arr[:, 2].mean(), boot), "bins": bins,
            "two_action_hindsight_moment_regret": float(np.maximum(arr[:, 2], 0).mean()),
            "scope": "Selected H1 action versus actual same-state stop, after durable choice; outcome-noise diagnostics, no uniform conditional guarantee. Hindsight regret uses private realized outcomes and is not attainable online."}
    result = {"schema": "hepta.next.exact-control-analysis.v1", "status": "completed", "requests": len(rows), "failures": 0,
        "source_pairs": count, "writer_clusters": len(clusters), "new_source_pairs": completion["new_source_pairs"], "cluster_scope": cluster_scope,
        "training_seeds": seeds, "seed_scope": "Conditional on this fixed trained-seed panel; not independent observations or training-seed population inference",
        "compiled_exact_pairs": compiled_parity, "feedback_shared_initial_pairs": feedback_initial_parity, "feedback_equal_access_decisions": cost_access,
        "policies": detail, "contrasts": contrasts, "protocol_sha256": registration["protocol_sha256"],
        "registration_sha256": file_sha(directory / "registration.json"),
        "nominal_intervals": True, "finite_sample_coverage_guaranteed": False, "all_raw_failures_and_timing_outliers_retained": True,
        "analysis_wall_ns": time.perf_counter_ns() - wall, "analysis_cpu_ns": time.process_time_ns() - cpu}
    write_json(directory / "analysis.json", result)
    print(json.dumps({"requests": len(rows), "clusters": len(clusters), "policies": {p: {k: detail[p][k] for k in ("CE", "success", "mean_wall_ms")} for p in policies},
                      "contrasts": {k: {m: v[m] for m in ("raw_CE", "success", "mean_wall_ms")} for k, v in contrasts.items()}}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--directory", type=Path, required=True)
    a = p.parse_args(); run(a.directory)
