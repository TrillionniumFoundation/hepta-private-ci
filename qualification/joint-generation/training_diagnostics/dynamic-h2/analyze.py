"""Descriptive, conditional TRAIN headroom from saved H2 artifacts; no model execution."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics


SEEDS = (11, 23, 47)
PATHS = ("NC-full", "NC-go", "NC-stop", "N-full")
REFERENCE = 73435.296875
PRICE = .02
HORIZON = 100000
BUILD_SECONDS = {"NC": 8.537556029, "N": 8.307966292}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def priced(cpu_ns):
    return PRICE * cpu_ns / REFERENCE


def mean(values):
    return statistics.fmean(float(value) for value in values)


def seed_summary(seed, arrays, reports):
    full, low, delta, static = (arrays[f"s{seed}_{name}"] for name in
                              ("NC_full", "NC_low", "NC_delta", "N_full"))
    n = len(full)
    if n != 3072 or any(len(value) != n for value in (low, delta, static)):
        raise ValueError("all original TRAIN rows required")
    if max(abs(float(a) - float(b) - float(c)) for a, b, c in zip(full, low, delta)) > 1e-12:
        raise ValueError("saved raw gain mismatch")
    timings = {}
    for path in PATHS:
        costs = [reports[(repeat, seed, path)]["cost"] for repeat in range(3)]
        timings[path] = {
            "service_cpu_ns_per_row": [cost["cpu_ns"] / n for cost in costs],
            "prepare_cpu_ns": [cost["prepare_cpu_ns"] for cost in costs],
            "complete_runtime_cpu_ns_per_horizon_request": [
                cost["cpu_ns"] / n + cost["prepare_cpu_ns"] / HORIZON for cost in costs]}
    signed_deltas = [a - b for a, b in zip(timings["NC-go"]["service_cpu_ns_per_row"],
                                         timings["NC-stop"]["service_cpu_ns_per_row"])]
    signed_median = statistics.median(signed_deltas)
    marginal_cpu = max(0., signed_median)
    c = priced(marginal_cpu)
    runtime_cost = {path: priced(statistics.median(
        timings[path]["complete_runtime_cpu_ns_per_horizon_request"])) for path in PATHS}
    actual_overhead = [a - b for a, b in zip(
        timings["NC-go"]["complete_runtime_cpu_ns_per_horizon_request"],
        timings["NC-full"]["complete_runtime_cpu_ns_per_horizon_request"])]
    build = {key: priced(value * 1e9 / (3 * HORIZON)) for key, value in BUILD_SECONDS.items()}
    h_continue = mean(max(c - float(g), 0.) for g in delta)
    h_stop = mean(max(float(g) - c, 0.) for g in delta)
    oracle_raw = mean(float(lo) + (float(g) if float(g) > c else 0.) for lo, g in zip(low, delta))
    oracle_proxy_net = mean(float(lo) + max(float(g) - c, 0.) for lo, g in zip(low, delta))
    oracle_proxy_net -= runtime_cost["NC-stop"] + build["NC"]
    n_net = mean(static) - runtime_cost["N-full"] - build["N"]
    nc_net = mean(full) - runtime_cost["NC-full"] - build["NC"]
    content_gap = mean(float(a) - float(b) for a, b in zip(static, full))
    runtime_gap_proxy = runtime_cost["NC-stop"] + c - runtime_cost["N-full"]
    gap_decomposition = h_continue - content_gap - runtime_gap_proxy - (build["NC"] - build["N"])
    if abs((oracle_proxy_net - n_net) - gap_decomposition) > 1e-12:
        raise ValueError("conditional headroom decomposition mismatch")
    signed_c = priced(signed_median)
    signed_oracle = mean(float(lo) + max(float(g) - signed_c, 0.) for lo, g in zip(low, delta))
    signed_oracle -= runtime_cost["NC-stop"] + build["NC"]
    return {
        "seed": seed, "rows": n, "physical_sources": 192, "all_timing_samples": timings,
        "signed_go_minus_stop_cpu_ns_per_row": signed_deltas,
        "signed_median_marginal_cpu_ns_per_row": signed_median,
        "zero_clamped_marginal_cpu_ns_per_row": marginal_cpu,
        "new_wave_service_price_c": c,
        "runtime_utility_cost": runtime_cost, "historical_build_utility_cost": build,
        "NC_full_raw": mean(full), "NC_low_raw": mean(low), "N_full_raw": mean(static),
        "content_gap_N_minus_NC": content_gap,
        "oracle_stop_rows": sum(float(g) <= c for g in delta),
        "oracle_continue_fraction": mean(float(g) > c for g in delta),
        "oracle_raw": oracle_raw,
        "free_label_oracle_raw": mean(max(float(f), float(l)) for f, l in zip(full, low)),
        "free_label_oracle_raw_minus_N_full": mean(
            max(float(f), float(l)) - float(nv) for f, l, nv in zip(full, low, static)),
        "oracle_headroom_vs_own_continue_proxy": h_continue,
        "oracle_headroom_vs_own_stop_proxy": h_stop,
        "oracle_headroom_vs_best_constant_proxy": min(h_continue, h_stop),
        "mandatory_route_overhead_vs_direct_NC_full_proxy": runtime_cost["NC-stop"] + c - runtime_cost["NC-full"],
        "measured_go_minus_direct_NC_full_runtime_cpu_ns_per_row_pairs": actual_overhead,
        "measured_go_minus_direct_NC_full_runtime_cpu_ns_per_row_paired_median": statistics.median(actual_overhead),
        "measured_go_minus_direct_NC_full_runtime_utility_cost_paired_median": priced(statistics.median(actual_overhead)),
        "oracle_proxy_complete_net": oracle_proxy_net,
        "direct_NC_full_complete_net": nc_net, "direct_N_full_complete_net": n_net,
        "oracle_proxy_net_minus_direct_N_full": oracle_proxy_net - n_net,
        "oracle_proxy_net_minus_direct_NC_full": oracle_proxy_net - nc_net,
        "decomposition": {"routing_headroom": h_continue, "minus_content_gap": -content_gap,
            "minus_runtime_gap_proxy": -runtime_gap_proxy,
            "minus_build_gap": -(build["NC"] - build["N"]), "sum": gap_decomposition},
        "signed_price_sensitivity_oracle_minus_N_full": signed_oracle - n_net,
        "go_proxy_vs_measured_go_cost_difference": runtime_cost["NC-stop"] + c - runtime_cost["NC-go"],
        "limits": "Oracle sees unavailable labels/outcomes. New-wave signed/zero-clamped median CPU "
            "and constant marginal-mixture assumptions are descriptive, not certified request-level or "
            "complete-system upper bounds. Direct static is T11-selected NDU/full, not every static policy."
    }


def analyze(directory):
    import numpy as np
    directory = Path(directory)
    diagnostic = read(directory / "diagnostic.json")
    calls = diagnostic["service_calls"]
    if len(calls) != 36:
        raise ValueError("complete fixed wave of 36 calls required")
    reports = {}
    for call in calls:
        path = directory / call["file"]
        if sha(path) != call["sha256"]:
            raise ValueError("retained service report hash mismatch")
        report = read(path)
        key = (call["repeat"], call["seed"], call["path"])
        if key in reports or key[0] not in range(3) or key[1] not in SEEDS or key[2] not in PATHS:
            raise ValueError("duplicate or unknown service identity")
        if len(report["per_row_cost"]["cpu_ns"]) != 3072 or report["budget_violations"] != 0:
            raise ValueError("missing original TRAIN rows or service budget violation")
        reports[key] = report
    with np.load(directory / "content-values.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    rows = [seed_summary(seed, arrays, reports) for seed in SEEDS]
    return {"schema": "hepta.dynamic-train-headroom-h2-analysis.v1", "qualification_eligible": False,
        "seeds": rows, "mean_oracle_proxy_minus_N_full": mean(
            row["oracle_proxy_net_minus_direct_N_full"] for row in rows),
        "mean_content_gap_N_minus_NC": mean(row["content_gap_N_minus_NC"] for row in rows),
        "mean_free_label_oracle_raw_minus_N_full": mean(
            row["free_label_oracle_raw_minus_N_full"] for row in rows),
        "mean_oracle_headroom_vs_own_continue_proxy": mean(
            row["oracle_headroom_vs_own_continue_proxy"] for row in rows),
        "scientific_benefit_confirmed": False,
        "boundary": "This is an exploratory TRAIN diagnostic of existing T11 weights, actual old rowwise "
            "service and a conditional label-aware proxy oracle. No policy fitted or timing/seed discarded. "
            "It neither confirms dynamic benefit nor rules out every model/task family; old r2/CORE failures "
            "and H1 prices remain unchanged. Static NDU receives every applicable optimization in future work."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x") as handle:
        json.dump(analyze(args.run), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
