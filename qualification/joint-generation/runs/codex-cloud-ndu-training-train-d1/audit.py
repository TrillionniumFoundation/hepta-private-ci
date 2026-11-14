"""Post-run artifact/cost audit and descriptive summaries; no data construction."""

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model import JointModel

started = time.process_time()
out = Path(__file__).resolve().parent
r = json.loads((out / "result.json").read_text())
checks = []
for arm, system in r["systems"].items():
    ledger = system["ledger"]
    assert ledger["consumed_units"] == sum(x["consumed_units"] for x in ledger["stages"].values())
    assert ledger["consumed_units"] <= 12_000_000_000
    assert system["cpu_seconds"] <= 10
    for key, candidate in system["candidates"].items():
        seed = int(key.split("-")[1])
        base = JointModel.load(out / f"base-{seed}.npz")
        model = JointModel.load(out / f"final-{arm}-{key}.npz")
        assert model.digest() == candidate["digest"]
        for name in ("decoder", "decoder_bias"):
            np.testing.assert_array_equal(model.params[name], base.params[name])
        assert all(value > 0 for value in candidate["parameter_delta_l2"].values())
        for prefix, steps in (("final", candidate["steps"]), ("matched", 128)):
            with np.load(out / f"{prefix}-{arm}-{key}.adam.npz", allow_pickle=False) as saved:
                assert len(saved.files) == 18
                assert all(np.isfinite(saved[name]).all() for name in saved.files)
                assert all(int(saved[name]) == steps for name in saved.files if name.endswith(".clock"))
        assert candidate["service"]["budget_violations"] == 0
        assert candidate["service"]["maximum_forwards_per_request"] == 1
        checks.append(f"{arm}/{key}: digest, immutable decoder, six updates, Adam clocks, service cap")
summary = {"all_integrity_and_budget_checks_passed": True, "checks": checks, "seeds": [],
           "mean_same_sampler_N_minus_A": {}, "base_gradients": []}
for kind in ("iid", "stratified"):
    for phase in ("matched_N_minus_A", "final_N_minus_A"):
        summary["mean_same_sampler_N_minus_A"][f"{kind}/{phase}"] = {
            metric: float(np.mean([x[phase][metric] for x in r["contrasts"][kind]]))
            for metric in ("task_utility", "joint_success")}
for seed in (11, 23, 47):
    row = {"seed": seed, "N_strat_minus_additive_upper_envelope": {}, "same_sampler": {}}
    n = r["systems"]["N"]["candidates"][f"stratified-{seed}"]
    for metric in ("task_utility", "joint_success", "greedy_joint_success"):
        best = max(r["systems"]["A"]["candidates"][f"{kind}-{seed}"]["train"][metric]
                   for kind in ("iid", "stratified"))
        row["N_strat_minus_additive_upper_envelope"][metric] = n["train"][metric] - best
    row["N_strat_minus_additive_upper_envelope"]["complete_cpu_net"] = n["train_complete_cpu_net"] - max(
        r["systems"]["A"]["candidates"][f"{kind}-{seed}"]["train_complete_cpu_net"]
        for kind in ("iid", "stratified"))
    for kind in ("iid", "stratified"):
        nn, aa = (r["systems"][arm]["candidates"][f"{kind}-{seed}"] for arm in ("N", "A"))
        row["same_sampler"][kind] = {"complete_cpu_net_N_minus_A": nn["train_complete_cpu_net"] - aa["train_complete_cpu_net"],
            "greedy_joint_N_minus_A": nn["train"]["greedy_joint_success"] - aa["train"]["greedy_joint_success"]}
        assert nn["matched"]["stream_sha256"] == aa["matched"]["stream_sha256"]
    summary["seeds"].append(row)
    g = r["bases"][str(seed)]["gradient"]
    summary["base_gradients"].append({"seed": seed,
        "N_variance_reduction_fraction": 1 - g["objectives"]["N"]["samplers"]["stratified"]["variance_trace"] / g["objectives"]["N"]["samplers"]["iid"]["variance_trace"],
        "A_variance_reduction_fraction": 1 - g["objectives"]["A"]["samplers"]["stratified"]["variance_trace"] / g["objectives"]["A"]["samplers"]["iid"]["variance_trace"],
        "risk_vs_raw_gradient_cosine": g["risk_vs_raw_utility_cosine"],
        "cache_reference_error": g["cached_log_domain_max_error"]})
summary["scope"] = "TRAIN-only descriptive audit; endpointwise additive upper envelope is not confirmatory selection"
summary["analysis_cpu_seconds_excluding_output_write"] = time.process_time() - started
with (out / "audit.json").open("x") as stream:
    json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
print(json.dumps(summary, indent=2))
