"""Recompute summaries of sealed full-model timings and stream recovery."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import numpy as np


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    completion, suite, registration = (read(source / name) for name in
        ("COMPLETE.json", "SUITE_EXECUTION.json", "REGISTRATION.json"))
    if suite["exit_code"] or completion["source_changed_during_run"]:
        raise AssertionError("Runtime experiment did not complete with fixed sources")
    paths = [source / name for name in ("COMPLETE.json", "SUITE_EXECUTION.json", "REGISTRATION.json")]
    cases, ratios = [], []
    for record in completion["records"]:
        folder = source / Path(record["path"]).name
        execution, result = (read(folder / name) for name in ("EXECUTION.json", "RESULT.json"))
        paths.extend(folder / name for name in ("EXECUTION.json", "RESULT.json"))
        if execution != record["execution"] or execution["exit_code"]:
            raise AssertionError("Per-worker execution does not match suite ledger")
        if folder.name == "recovery":
            recovery = result
            continue
        if len(result["forward"]) != 3 or len(result["optimizer_step"]) != 3:
            raise AssertionError("Unexpected repeat count")
        for key, claimed in (("forward", "forward_cpu_median"), ("optimizer_step", "optimizer_cpu_median")):
            measured = [row["cpu_seconds"] for row in result[key]]
            if min(measured) <= 0 or statistics.median(measured) != result[claimed]:
                raise AssertionError("Timing statistic differs from raw repetitions")
        cases.append(result)
    expected = {(name, b, t) for name in registration["models"] for b, t in registration["configurations"]}
    if {(row["model"], row["batch"], row["length"]) for row in cases} != expected or len(cases) != len(expected):
        raise AssertionError("Incomplete runtime matrix")
    child_cpu = sum(row["execution"]["child_cpu_seconds"] for row in completion["records"])
    if child_cpu != completion["complete_workers_cpu_seconds"] or child_cpu > suite["complete_child_cpu_seconds"]:
        raise AssertionError("Nested CPU accounting differs")
    for batch, length in registration["configurations"]:
        subset = {row["model"]: row for row in cases if row["batch"] == batch and row["length"] == length}
        for name, baseline in subset.items():
            ratios.append(dict(batch=batch, length=length, comparison=name,
                free_dual_forward_ratio=subset["distribution_free_dual"]["forward_cpu_median"] / baseline["forward_cpu_median"],
                free_dual_optimizer_ratio=subset["distribution_free_dual"]["optimizer_cpu_median"] / baseline["optimizer_cpu_median"]))
    recovery_dir = source / "recovery"
    contract, resume_cost = (read(recovery_dir / name) for name in ("CHECKPOINT.json", "RESUME_COST.json"))
    paths.extend(recovery_dir / name for name in ("CHECKPOINT.json", "RESUME_COST.json", "RESUME_EXECUTION.json"))
    if contract["writer_pid"] == resume_cost["pid"] or contract["writer_pid"] != resume_cost["writer_pid"]:
        raise AssertionError("No distinct resume process")
    for stem in ("logits", "state"):
        with np.load(recovery_dir / ("uninterrupted_" + stem + ".npz"), allow_pickle=False) as a:
            with np.load(recovery_dir / ("resumed_" + stem + ".npz"), allow_pickle=False) as b:
                if set(a.files) != set(b.files) or any(not np.array_equal(a[k], b[k]) for k in a.files):
                    raise AssertionError("Fresh-process recovery arrays differ")
        paths.extend(recovery_dir / (prefix + stem + ".npz") for prefix in ("uninterrupted_", "resumed_"))
    config = contract["full_model_config"]
    expected_floats = recovery["batch"] * (1 + config["depth"] * (
        config["width"] + config["physical_channels"] * (config["grid_cells"] + config["refractory_stages"] + 1)))
    expected_bytes = 4 * expected_floats
    if any(value != expected_bytes for value in recovery["persistent_state_bytes_by_step"]):
        raise AssertionError("Persistent inference state allocation differs from declared state")
    result = dict(schema="hcsn-runtime-independent-summary.v1", status="passed", cases=cases,
        runtime_ratios=ratios, recovery=recovery, recovery_writer_pid=contract["writer_pid"],
        recovery_resume_pid=resume_cost["pid"], state_float32_values=expected_floats,
        expected_persistent_state_bytes=expected_bytes,
        complete_runtime_suite_cpu_seconds=suite["complete_child_cpu_seconds"],
        nested_workers_cpu_seconds=child_cpu,
        input_sha256={str(path.relative_to(source)): digest(path) for path in paths},
        analysis_source_sha256=digest(__file__),
        scope="Randomly initialized synthetic timing models; successful selected content002 checkpoint used only for streaming/recovery. CPU medians are not equal-quality throughput, energy, GPU or foundation-model measurements.")
    (output / "SUMMARY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = ["# Full-model CPU work and cross-process recovery", "",
        "All 14 registered timing configurations and the selected-model recovery fixture completed. Three timed repetitions follow declared warmups. Optimizer timing includes zeroing gradients, forward, cross entropy, backward, clipping, Adam.step and the finite-output check. Imports and setup are included separately in each complete worker receipt.", "",
        "## Measured CPU seconds per complete optimizer step", "",
        "| Model | B=4, T=32 | B=4, T=128 |", "| --- | ---: | ---: |"]
    for name in registration["models"]:
        values = [next(row["optimizer_cpu_median"] for row in cases if row["model"] == name and row["length"] == t)
                  for t in (32, 128)]
        lines.append(f"| {name} | {values[0]:.6f} | {values[1]:.6f} |")
    dual_gate = next(row for row in ratios if row["length"] == 128 and row["comparison"] == "two_gates")
    transformer = next(row for row in ratios if row["length"] == 128 and row["comparison"] == "transformer")
    lines += ["", f"At B=4,T=128, the distributional free-dual step takes **{dual_gate['free_dual_optimizer_ratio']:.2f}×** the ordinary two-gate CPU and **{transformer['free_dual_optimizer_ratio']:.2f}×** the small Transformer CPU. These measurements do not support a whole-model CPU speed advantage. The earlier prepared-operator microbenchmark compares two implementations of the distributional kernel; it cannot be transferred to a different backbone comparison.", "",
        "These are small, random-weight, synthetic CPU microbenchmarks on a shared host. The baseline Transformer calls PyTorch SDPA; there is no fused HCSN GPU kernel or hardware energy measurement. The main content study separately evaluates equal training-CPU budgets. Timing alone does not establish a quality-cost frontier.", "",
        "## Selected-model streaming and recovery", "",
        "The trained checkpoint is bound to successful summary, selection, source/data/protocol identities, complete worker exit and the full physical model configuration. Merely matching NPZ tensor shapes is insufficient; an ordinary-feature checkpoint is explicitly rejected.", "",
        f"The selected MNIST free-dual seed9201 model runs 256 synthetic steps at B=2, saves after step113 with nonzero refractory mass, and resumes 143 steps in a distinct Python process (PID {contract['writer_pid']} → {resume_cost['pid']}). Every suffix logit and final tensor is bitwise equal to uninterrupted execution.", "",
        f"Full-sequence versus step-by-step logits differ by at most **{recovery['full_vs_stream_max_absolute_logit_error']:.3e}**, with {recovery['full_vs_stream_argmax_disagreements']} argmax disagreements. Maximum probability mass error is **{recovery['max_probability_mass_error']:.3e}**. The checkpoint contains **{expected_bytes} bytes** of persistent float32 state at every step: elapsed time plus content, full spatial/phase probabilities and physical boundary. This excludes weights, output history, optimizer/BPTT storage and any baseline KV cache.", "",
        "For B streams, D layers, content width W, C physical channels, S spatial cells and R phases, the measured layout is 4B[1+D(W+C(S+R+1))] bytes. Constant persistent state does not prove constant training memory or sufficient long-context recall: training stores time-indexed operators and autograd state.", "",
        f"Complete suite CPU is **{suite['complete_child_cpu_seconds']:.6f} s**. Its **{child_cpu:.6f} s** worker total includes nested resume and must not be added again. The separately measured model/state load component excludes interpreter startup and source checks; no production restart-latency claim is made.", ""]
    (output / "REPORT.md").write_text("\n".join(lines))
    execution = dict(whole_analysis_self_cpu_seconds=time.process_time(), source_sha256=digest(__file__),
                     summary_sha256=digest(output / "SUMMARY.json"), report_sha256=digest(output / "REPORT.md"))
    (output / "EXECUTION.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(status="passed", configurations=len(cases), persistent_state_bytes=expected_bytes,
                         free_dual_over_gates_t128=dual_gate["free_dual_optimizer_ratio"],
                         free_dual_over_transformer_t128=transformer["free_dual_optimizer_ratio"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)
