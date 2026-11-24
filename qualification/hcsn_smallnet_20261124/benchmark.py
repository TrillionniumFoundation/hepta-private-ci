"""Bounded CPU numerical/cost audit; timings are not a training speed claim.

Run with ``python -m qualification.hcsn_smallnet_20261124.benchmark --output X``.
Native float32 is a diagnostic arm and retains any failure. The long-run default
checks N=8; width scaling compares full forward/backward at N=8,32,64. The
uniformization backend is a dense action, not the upstream banded optimization.
"""

import time
_ENTRY_TIME = time.perf_counter()
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
import torch
from .model import ModelConfig, PopulationState, SmallHCSN

_IMPORT_SECONDS = time.perf_counter()-_ENTRY_TIME
_FIELDS = ("density", "boundary", "drift", "cost", "message")


def state_record(state):
    return {**{name: getattr(state, name).detach().cpu() for name in _FIELDS}, "step": state.step}


def restore_state(data, config):
    return PopulationState(*(data[name] for name in _FIELDS), data["step"], config)


def error(reference, actual):
    a, b = reference.detach().double(), actual.detach().double()
    delta = b-a
    return {"max_abs": float(delta.abs().max()),
            "relative_l2": float(torch.linalg.vector_norm(delta)/torch.linalg.vector_norm(a).clamp_min(1e-15)),
            "reference_abs_max": float(a.abs().max()), "finite": bool(torch.isfinite(b).all())}


def compare(reference, actual):
    metrics = {name: error(reference[name], actual[name]) for name in ("logits", "features", "input_gradient")}
    metrics["state"] = {name: error(reference["state"][name], actual["state"][name]) for name in _FIELDS}
    metrics["state_step_equal"] = reference["state"]["step"] == actual["state"]["step"]
    metrics["parameter_gradients"] = {name: error(reference["gradients"][name], actual["gradients"][name])
                                      for name in reference["gradients"] if name in actual["gradients"]}
    metrics["missing_gradient_names"] = sorted(set(reference["gradients"])-set(actual["gradients"]))
    if not metrics["missing_gradient_names"]:
        metrics["all_parameter_gradients"] = error(
            torch.cat([v.flatten() for v in reference["gradients"].values()]),
            torch.cat([actual["gradients"][k].flatten() for k in reference["gradients"]]))
    return metrics


def timed_pass(model, inputs, margin):
    model.zero_grad(set_to_none=True)
    x = inputs.to(model.input_drive.weight).detach().requires_grad_()
    state = model.initial_state(x.shape[1], margin)
    start = time.perf_counter()
    logits, features, final = model(x, return_features=True, state=state)
    loss = logits.square().mean()+.01*features.square().mean()+.03*final.density.square().mean()
    forward = time.perf_counter()-start
    start = time.perf_counter()
    loss.backward()
    backward = time.perf_counter()-start
    start = time.perf_counter()
    gradients = {name: value.grad.detach().clone() for name, value in model.named_parameters()
                 if value.requires_grad and value.grad is not None}
    missing = [name for name, value in model.named_parameters() if value.requires_grad and value.grad is None]
    record = {"logits": logits.detach(), "features": features.detach(), "state": state_record(final),
              "input_gradient": x.grad.detach(), "gradients": gradients}
    tensors = [record["logits"], record["features"], record["input_gradient"], *gradients.values(),
               *(record["state"][name] for name in _FIELDS)]
    return record, {"forward_s": forward, "backward_s": backward, "forward_backward_s": forward+backward,
        "capture_s": time.perf_counter()-start, "loss": float(loss.detach()),
        "all_outputs_states_gradients_finite": all(bool(torch.isfinite(v).all()) for v in tensors),
        "missing_trainable_gradients": missing, "diagnostics": model.last_diagnostics.copy()}


def width_case(width, args, deadline):
    torch.manual_seed(args.seed+width)
    config = ModelConfig(neurons=width, feature_normalization=args.feature_normalization)
    reference = SmallHCSN(config)
    # All trainable weights and inputs are representable in both float32/64.
    # Native32 additionally rounds physical buffers, explicitly part of its error.
    with torch.no_grad():
        reference.raw_cost.fill_(.23)
        for parameter in reference.parameters():
            parameter.copy_(parameter.float().double())
    inputs = (torch.randn(args.steps, args.batch, config.input_size, dtype=torch.float32)*.3).double()
    margin = torch.linspace(.28, .82, width, dtype=torch.float32)[None].expand(args.batch, -1).double()
    weights = {name: value.detach().clone() for name, value in reference.state_dict().items()}
    output = {"neurons": width, "batch": args.batch, "steps": args.steps, "config": asdict(config), "arms": []}
    baseline = None
    for precision, backend in (("float64", "dense"), ("mixed", "dense"),
                               ("mixed", "uniformized"), ("native32", "dense")):
        if time.perf_counter() >= deadline:
            output["arms"].append({"precision": precision, "backend": backend, "status": "budget_not_run"})
            continue
        started = time.perf_counter()
        model = reference if precision == "float64" else SmallHCSN(replace(config, precision=precision, backend=backend))
        model.load_state_dict(weights)
        row = {"precision": precision, "backend": backend, "construction_s": time.perf_counter()-started,
               "parameter_elements": sum(p.numel() for p in model.parameters()), "samples": []}
        try:
            for _ in range(args.repeats):
                record, sample = timed_pass(model, inputs, margin)
                row["samples"].append(sample)
            row["median_forward_backward_s"] = statistics.median(v["forward_backward_s"] for v in row["samples"])
            row["status"] = "measured"
            if baseline is None:
                baseline = record
            else:
                row["error_against_fp64_dense"] = compare(baseline, record)
        except (FloatingPointError, RuntimeError, ValueError) as exc:
            row.update(status="failed", error_type=type(exc).__name__, error=str(exc), diagnostics=model.last_diagnostics.copy())
        output["arms"].append(row)
    return output


def resumed_worker(input_path, output_path):
    saved = torch.load(input_path, map_location="cpu", weights_only=True)
    config = ModelConfig(**saved["config"])
    model = SmallHCSN(config)
    model.load_state_dict(saved["weights"])
    with torch.no_grad():
        logits, features, final = model(saved["tail"], state=restore_state(saved["state"], config), return_features=True)
    torch.save({"logits": logits, "features": features, "state": state_record(final)}, output_path)
    print(json.dumps({"restored_step": saved["state"]["step"], "final_step": final.step,
                      "worker_script_s": time.perf_counter()-_ENTRY_TIME, "torch": torch.__version__}))


def cold_continuation(seed, feature_normalization="none"):
    torch.manual_seed(seed)
    model = SmallHCSN(ModelConfig(feature_normalization=feature_normalization))
    inputs = torch.randn(6, 2, 6, dtype=torch.float64)*.3
    with torch.no_grad():
        logits, features, final = model(inputs, return_features=True)
        _, _, prefix = model(inputs[:3], return_features=True)
    with tempfile.TemporaryDirectory(prefix="hcsn-cold-check-") as directory:
        source, result = Path(directory)/"complete.pt", Path(directory)/"resumed.pt"
        torch.save({"config": asdict(model.config), "weights": model.state_dict(),
                    "state": state_record(prefix), "tail": inputs[3:]}, source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        checkpoint_bytes = source.stat().st_size
        started = time.perf_counter()
        child = subprocess.run([sys.executable, "-m", __package__+".benchmark", "--resume-input", str(source),
                                "--resume-output", str(result)], capture_output=True, text=True, timeout=25, check=False)
        wall = time.perf_counter()-started
        if child.returncode != 0 or not result.exists():
            return {"status": "failed", "return_code": child.returncode, "stdout": child.stdout, "stderr": child.stderr}
        loaded = torch.load(result, map_location="cpu", weights_only=True)
    errors = {"logits": error(logits[3:], loaded["logits"]), "features": error(features[3:], loaded["features"]),
              "state": {name: error(getattr(final, name), loaded["state"][name]) for name in _FIELDS}}
    exact = all(v["max_abs"] == 0 for v in [errors["logits"], errors["features"], *errors["state"].values()])
    return {"status": "passed" if exact and loaded["state"]["step"] == final.step else "mismatch",
            "method": "torch.save/load in a fresh Python subprocess with a newly constructed model",
            "split_step": 3, "slow_every": model.config.slow_every, "checkpoint_sha256": digest,
            "checkpoint_bytes": checkpoint_bytes,
            "errors": errors, "final_step": loaded["state"]["step"], "subprocess_wall_s": wall,
            "stdout": child.stdout, "stderr": child.stderr, "past_autograd_tape_preserved": False}


def long_rollout(args, schedule, precision, backend, deadline):
    started = time.perf_counter()
    config = ModelConfig(neurons=args.long_width, precision=precision, backend=backend,
                         slow_every=2 if schedule == "slow_every_2" else 10**9,
                         feature_normalization=args.feature_normalization)
    torch.manual_seed(args.seed+500)
    model = SmallHCSN(config)
    # Within each precision, the dense/uniformized arms start identically.
    generator = torch.Generator().manual_seed(args.seed+501)
    inputs = torch.randn(args.long_steps, 1, config.input_size, generator=generator, dtype=torch.float32)*.3
    inputs = inputs.to(model.input_drive.weight)
    state = model.initial_state(1, torch.linspace(.28, .82, config.neurons)[None])
    row = {"neurons": config.neurons, "batch": 1, "schedule": schedule, "precision": precision,
           "backend": backend, "requested_steps": args.long_steps, "completed_steps": 0,
           "max_mass_error": 0., "max_upper_projection_mass": 0., "all_fields_finite": True,
           "status": "running", "samples": []}
    with torch.no_grad():
        for step in range(args.long_steps):
            if time.perf_counter() >= deadline:
                row["status"] = "budget_censored"
                break
            try:
                logits, features, state = model(inputs[step:step+1], state=state, return_features=True)
                finite = all(bool(torch.isfinite(t).all()) for t in
                             (logits, features, *(getattr(state, name) for name in _FIELDS)))
                if not finite:
                    row["all_fields_finite"] = False
                    raise FloatingPointError("nonfinite complete output or state")
            except (FloatingPointError, RuntimeError, ValueError) as exc:
                row.update(status="failed", failed_attempted_step=step+1, error_type=type(exc).__name__,
                           error=str(exc), failure_diagnostics=model.last_diagnostics.copy())
                break
            row["completed_steps"] = step+1
            row["max_mass_error"] = max(row["max_mass_error"], model.last_diagnostics["mass_error"])
            row["max_upper_projection_mass"] = max(row["max_upper_projection_mass"],
                                                   model.last_diagnostics["upper_projection_mass_max"])
            if (step+1) % 64 == 0 or step+1 == args.long_steps:
                row["samples"].append({"step": state.step, **model.last_diagnostics})
        else:
            row["status"] = "completed"
    row["elapsed_s"] = time.perf_counter()-started
    row["control_updates"] = 0 if not row["completed_steps"] else 1+(row["completed_steps"]-1)//config.slow_every
    row["backpropagation_horizon"] = 0
    row["law_semantics"] = "new input content is written each step; controls frozen after step 0" if schedule == "fixed_after_first" else "local law updated every two absolute state steps"
    return row


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=4107)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--budget-seconds", type=float, default=105.)
    parser.add_argument("--long-steps", type=int, default=512)
    parser.add_argument("--long-width", type=int, choices=(8, 32, 64), default=8)
    parser.add_argument("--feature-normalization", choices=("none", "population"), default="none")
    parser.add_argument("--resume-input", type=Path)
    parser.add_argument("--resume-output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.resume_input:
        if not args.resume_output or args.resume_output.exists():
            parser.error("fresh resume output path required")
        resumed_worker(args.resume_input, args.resume_output)
        return
    if (args.output is None or args.output.exists() or not 4 <= args.steps <= 32 or not 1 <= args.batch <= 16
            or not 1 <= args.repeats <= 5 or not 128 <= args.long_steps <= 1024
            or not 30 <= args.budget_seconds <= 110):
        parser.error("fresh output and bounded benchmark arguments required")
    deadline = _ENTRY_TIME+args.budget_seconds
    report = {"schema": 1, "torch": torch.__version__, "python": sys.version, "device": "cpu", "threads": 1,
              "seed": args.seed, "import_s": _IMPORT_SECONDS, "budget_seconds": args.budget_seconds,
              "timing_scope": "in-process complete forward/loss/backward; no optimizer, data loading or remote supervisor startup",
              "precision_comparison": "identical float32-representable weights and inputs; physical buffers double except native32",
              "gradient_scope": "one declared scalar loss VJP over every trainable parameter and input coordinate; not a full Jacobian",
              "relative_l2_denominator_floor": 1e-15, "feature_normalization": args.feature_normalization,
              "nonsmooth_scope": "piecewise differentiable grid projection, symmetric generalized derivative at exact knots",
              "native32_is_diagnostic": True, "width_cases": [], "long_rollouts": []}
    started = time.perf_counter()
    for width in (8, 32, 64):
        report["width_cases"].append(width_case(width, args, deadline))
    report["width_benchmark_s"] = time.perf_counter()-started
    try:
        report["cold_continuation"] = (cold_continuation(args.seed+100, args.feature_normalization)
            if time.perf_counter()+25 < deadline else {"status": "budget_not_run"})
    except subprocess.TimeoutExpired as exc:
        report["cold_continuation"] = {"status": "failed", "error_type": "TimeoutExpired", "error": str(exc)}
    for schedule in ("fixed_after_first", "slow_every_2"):
        for precision, backend in (("mixed", "dense"), ("mixed", "uniformized"), ("native32", "dense")):
            report["long_rollouts"].append(long_rollout(args, schedule, precision, backend, deadline))
    report["worker_script_s"] = time.perf_counter()-_ENTRY_TIME
    report["max_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["supervisor_startup_s"] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(json_safe(report), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "worker_script_s": report["worker_script_s"],
          "width_arms": [[r["status"] for r in w["arms"]] for w in report["width_cases"]],
          "cold_continuation": report["cold_continuation"]["status"],
          "long_rollouts": [{k: r[k] for k in ("schedule", "precision", "backend", "completed_steps", "status")}
                            for r in report["long_rollouts"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
