"""Bounded native32 uniformization diagnostic without changing frozen code.

Reuses the original benchmark's seeds, inputs, state checks and 3e-5 mass gate.
Both N=8 schedules run first. Any failure prevents wider follow-up. Passing this
inference stress does not qualify native32 training or change the formal policy.
"""

import time
_ENTRY = time.perf_counter()
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import resource
from types import SimpleNamespace
import torch
from .model import ModelConfig, SmallHCSN
from .benchmark import compare, json_safe, long_rollout, timed_pass


def short_vjp(width, seed):
    torch.manual_seed(seed+width)
    reference = SmallHCSN(ModelConfig(neurons=width, backend="dense", precision="float64"))
    with torch.no_grad():
        reference.raw_cost.fill_(.23)
        for parameter in reference.parameters():
            parameter.copy_(parameter.float().double())
    inputs = (torch.randn(6, 4, 6, dtype=torch.float32)*.3).double()
    margin = torch.linspace(.28, .82, width, dtype=torch.float32)[None].expand(4, -1).double()
    candidate = SmallHCSN(replace(reference.config, backend="uniformized", precision="native32"))
    candidate.load_state_dict(reference.state_dict())
    a, a_cost = timed_pass(reference, inputs, margin)
    b, b_cost = timed_pass(candidate, inputs, margin)
    complete = all(row["all_outputs_states_gradients_finite"] and not row["missing_trainable_gradients"]
                   for row in (a_cost, b_cost))
    return {"neurons": width, "status": "measured" if complete else "failed", "steps": 6, "batch": 4,
            "control_schedule": "slow_every=2", "reference": "FP64 dense", "candidate": "native32 uniformized",
            "reference_cost": a_cost, "candidate_cost": b_cost,
            "errors": compare(a, b), "gradient_scope": "one declared scalar-loss VJP over all trainable parameters and input coordinates; not a full Jacobian"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=4107)
    parser.add_argument("--budget-seconds", type=float, default=105.)
    args = parser.parse_args()
    if args.output.exists() or not 60 <= args.budget_seconds <= 105:
        parser.error("fresh output and a 60..105 second process budget required")
    torch.set_num_threads(1)
    deadline = _ENTRY+args.budget_seconds
    settings = SimpleNamespace(seed=args.seed, long_width=8, long_steps=512, feature_normalization="none")
    report = {"schema": "hcsn-native32-uniformized-diagnostic-v1", "torch": torch.__version__, "threads": 1,
        "device": "cpu", "seed": args.seed, "long_model_seed": args.seed+500, "long_input_seed": args.seed+501,
        "probability_balance_threshold": 3e-5, "probability_renormalization": False,
        "initial_rollouts": [], "wider_rollouts": [], "short_vjp": [],
        "scope": "same original long_rollout implementation and inputs; only native32 backend changes from dense to uniformized",
        "continuation_policy": "run both N8 schedules; stop wider follow-up after any incomplete/failed rollout",
        "formal_training_precision_policy_changed": False,
        "training_qualification": "not established by these no-grad rollouts and short VJPs",
        "energy_joules": None, "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("model.py", "benchmark.py", "native32_uniformized_diagnostic.py")}}
    initial_deadline = min(deadline, time.perf_counter()+55.)
    for schedule in ("fixed_after_first", "slow_every_2"):
        report["initial_rollouts"].append(long_rollout(settings, schedule, "native32", "uniformized", initial_deadline))
    passed = all(row["status"] == "completed" and row["completed_steps"] == 512 for row in report["initial_rollouts"])
    report["initial_n8_both_completed"] = passed
    if not passed:
        report["extension_status"] = "not_run_after_initial_failure_or_budget_censoring"
    else:
        report["extension_status"] = "running"
        for width in (32, 64):
            settings.long_width = width
            row = long_rollout(settings, "slow_every_2", "native32", "uniformized", deadline)
            report["wider_rollouts"].append(row)
            if row["status"] != "completed" or row["completed_steps"] != 512:
                report["extension_status"] = "stopped_after_wider_failure_or_budget_censoring"
                break
        else:
            report["extension_status"] = "rollouts_completed"
            for width in (8, 32, 64):
                if time.perf_counter() >= deadline:
                    report["short_vjp"].append({"neurons": width, "status": "budget_not_run"})
                    break
                try:
                    row = short_vjp(width, args.seed)
                except (FloatingPointError, RuntimeError, ValueError) as exc:
                    row = {"neurons": width, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
                report["short_vjp"].append(row)
                if row["status"] == "failed":
                    report["extension_status"] = "stopped_after_short_vjp_failure"
                    break
    report["worker_cpu_through_report_seconds"] = time.process_time()
    report["worker_script_wall_seconds"] = time.perf_counter()-_ENTRY
    report["process_peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(json_safe(report), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "initial_n8_both_completed": passed,
        "extension_status": report["extension_status"], "worker_cpu_seconds": report["worker_cpu_through_report_seconds"],
        "initial_rollouts": [{key: row.get(key) for key in ("schedule", "status", "completed_steps", "failed_attempted_step", "max_mass_error")}
                             for row in report["initial_rollouts"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
