"""Audit actual trained raw-boundary loss gradients on fixed development cases.

This checks differentiation of the implemented projected network, not continuum
accuracy, every training visit, learning benefit, or formal confirmation.
"""

import time
STARTED, CPU_STARTED = time.perf_counter(), time.process_time()

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import platform

import torch
from torch import nn

from qualification.hcsn_boundary_factorial.run import (
    ARMS, ROOT, TASKS, FactorialModel, batch, source_identity, tensor_digest,
)

STEPS = (.001, .0003, .0001)


def checked_bytes(path, expected, identities):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024**2:
        raise ValueError("bounded regular evidence file required")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"SHA256 mismatch: {path.name}")
    identities[str(path.resolve())] = digest
    return data


def admit(pilot, summary_sha256, identities):
    summary = json.loads(checked_bytes(pilot / "SUMMARY.json", summary_sha256, identities))
    if summary["schema"] != "hcsn-boundary-factorial-pilot-v1":
        raise ValueError("unexpected pilot summary schema")
    recorded = summary["source_before"]
    required = {"qualification/hcsn_boundary_factorial/run.py",
                "qualification/hcsn_differentiable/network.py",
                "qualification/hcsn_differentiable/operator.py",
                "qualification/hcsn_memory_controls/generate.py"}
    current = source_identity()
    if (recorded != summary["source_after"] or not required <= recorded.keys()
            or any(current.get(name) != digest for name, digest in recorded.items())):
        raise ValueError("recorded training source does not match the executing source")
    for name, digest in recorded.items():
        checked_bytes(ROOT / name, digest, identities)
    plan = json.loads(checked_bytes(pilot / "PLAN.json", None, identities))
    if plan != summary["configuration"]:
        raise ValueError("plan differs from source-bound summary configuration")
    data = json.loads(checked_bytes(pilot / "DATA.json", summary["data_sha256"], identities))
    selected = [next((row for row in data["development"] if row["task"] == task), None)
                for task in TASKS]
    if any(row is None for row in selected) or len({row["id"] for row in selected}) != len(TASKS):
        raise ValueError("one first development episode per task is required")
    runs = [r for r in summary["runs"] if r["status"] == "completed" and r["arm"].endswith("b1")]
    if any(type(r["seed"]) is not int or r["arm"] not in ARMS for r in runs):
        raise ValueError("invalid completed arm identity")
    identities_in_roster = {(r["seed"], r["arm"]) for r in runs}
    seeds = summary["configuration"]["seeds"]
    expected = {(seed, arm) for seed in seeds for arm in ("c0_b1", "c1_b1")}
    if (any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds)
            or len(identities_in_roster) != len(runs) or not identities_in_roster <= expected):
        raise ValueError("completed arms do not match the declared seed/arm roster")
    if any(r["model_configuration"]["seed"] != r["seed"]
           or r["model_configuration"]["arm"] != r["arm"] for r in runs):
        raise ValueError("model configuration differs from run seed/arm identity")
    return summary, selected, runs


def load_model(pilot, run, data_sha256, identities):
    directory = pilot / f"seed{run['seed']}-{run['arm']}"
    result = json.loads(checked_bytes(directory / "result.json", None, identities))
    if result != run:
        raise ValueError("arm result differs from pinned summary")
    data = checked_bytes(directory / "checkpoint.pt", run["checkpoint_sha256"], identities)
    retained = torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)
    if (retained["schema"] != "hcsn-boundary-factorial-checkpoint-v1"
            or retained["configuration"] != run["model_configuration"]
            or retained["data_sha256"] != data_sha256
            or retained["saved_after_failed_attempt"]
            or retained["completed_optimizer_updates"] != run["actual_optimizer_updates"]):
        raise ValueError("checkpoint identity or completed training counters differ")
    model = FactorialModel(**retained["configuration"])
    model.load_state_dict(retained["model"], strict=True)
    if tensor_digest(model.state_dict()) != run["final_model_sha256"]:
        raise ValueError("final model tensor digest differs")
    return model.eval()


def audit_episode(model, episode):
    start, cpu_start = time.perf_counter(), time.process_time()
    record = dict(episode_id=episode["id"], task=episode["task"], status="started",
                  forward_attempts=0, forward_completed=0, backward_attempts=0,
                  backward_completed=0, fd=[], no_gradient_clipping=True)
    parameter = model.network.layers[0].physics.raw_log_boundary
    original = parameter.detach().clone()
    before = tensor_digest(model.state_dict())
    x, dt, valid, y = batch([episode])

    def forward(trace):
        record["forward_attempts"] += 1
        result = model(x, dt, valid, trace=trace)
        record["forward_completed"] += 1
        loss = nn.functional.cross_entropy(result.predictions[y >= 0], y[y >= 0])
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("nonfinite original cross-entropy loss")
        return result, loss

    def span(values):
        if not bool(torch.isfinite(values).all()):
            raise FloatingPointError("nonfinite state diagnostic")
        return [float(values.min()), float(values.max())]

    try:
        if not parameter.requires_grad or parameter.numel() != 1 or not bool((y >= 0).any()):
            raise ValueError("one learned boundary coordinate and scored positions required")
        result, loss = forward(True)
        record["backward_attempts"] += 1
        derivative, = torch.autograd.grad(loss, parameter)
        record["backward_completed"] += 1
        analytic = float(derivative)
        if not math.isfinite(analytic):
            raise FloatingPointError("nonfinite AD loss derivative")
        physics = {name: float(value.detach()) for name, value in
                   vars(model.network.layers[0].physics()).items()}
        grid = model.network.layers[0].operator.grid
        probability = torch.cat([states[0]["probability"].detach() for states in result.trace])
        content = torch.cat([states[0]["content_mass"].detach() for states in result.trace])
        record.update(loss=float(loss.detach()), ad=analytic, raw_log_boundary=float(original),
            physical_parameters=physics,
            physical_reset_margin=math.log(physics["absolute_reset"]) - physics["log_boundary"],
            dt_range=span(dt[valid]), event_positions=int(valid.sum()),
            scored_positions=int((y >= 0).sum()), posterior_probability_range=span(probability),
            posterior_first_cell_range=span(probability[:, 0]),
            posterior_tail_range=span(probability[:, grid.active_cells]),
            posterior_refractory_range=span(probability[:, grid.active_count:].sum(-1)),
            maximum_posterior_mass_error=float((probability.sum(-1) - 1).abs().max()),
            signed_content_mass_range=span(content),
            expected_interval_events_range=span(result.expected_events.detach()))
        del result, loss
        for step in STEPS:
            values, physical_boundaries = [], []
            for sign in (-1., 1.):
                with torch.no_grad():
                    parameter.copy_(original + sign * step)
                    _, loss = forward(False)
                    values.append(float(loss))
                    physical_boundaries.append(float(model.network.layers[0].physics().log_boundary))
            finite = (values[1] - values[0]) / (2 * step)
            record["fd"].append(dict(step=step, losses=values, derivative=finite,
                physical_log_boundaries=physical_boundaries,
                absolute_error=abs(finite - analytic),
                relative_error=abs(finite - analytic) / abs(analytic) if analytic else None))
        tolerance = 2e-6 + 2e-3 * abs(analytic)
        spread = max(r["derivative"] for r in record["fd"]) - min(r["derivative"] for r in record["fd"])
        record.update(absolute_error_limit=tolerance, fd_step_spread=spread,
            fd_step_spread_limit=4e-6 + 4e-3 * abs(analytic),
            absolute_tolerance_floor_dominates=2e-6 >= 2e-3 * abs(analytic))
        passed = (all(r["absolute_error"] <= tolerance for r in record["fd"])
                  and spread < record["fd_step_spread_limit"])
        record["status"] = "passed" if passed else "failed"
    except Exception as error:
        record.update(status="error", error_type=type(error).__name__, error_message=str(error))
    finally:
        with torch.no_grad():
            parameter.copy_(original)
        record["model_unchanged"] = tensor_digest(model.state_dict()) == before
        if not record["model_unchanged"]:
            record["status"] = "model_changed"
        record.update(wall_seconds=time.perf_counter() - start,
                      cpu_seconds=time.process_time() - cpu_start)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve previous attempts; choose a new output")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    identities, cases = {}, []
    report = dict(schema="hcsn-trained-boundary-gradient-audit-v1", status="error",
        scope="Final trained checkpoints, first development episode per task; implemented projected-network loss only.",
        steps=list(STEPS), absolute_error_rule="2e-6 + 2e-3 * abs(AD)",
        step_stability_rule="spread < 4e-6 + 4e-3 * abs(AD)",
        continuum_domain_qualified=False, whole_training_trajectory_qualified=False,
        formal_confirmation_accessed=False, numerical_qualification=False,
        product_adoption=False, physical_energy_joules=None,
        python=platform.python_version(), torch=torch.__version__, host=platform.node(),
        machine=platform.machine(), device="cpu", dtype="float64", cases=cases)
    try:
        checked_bytes(Path(__file__), None, identities)
        summary, selected, runs = admit(args.pilot, args.summary_sha256, identities)
        report.update(summary_sha256=args.summary_sha256, data_sha256=summary["data_sha256"],
            selected_episode_ids=[row["id"] for row in selected],
            completed_boundary_arms=len(runs), expected_boundary_arms=2 * len(summary["configuration"]["seeds"]),
            expected_cases=len(runs) * len(selected), input_pilot_status=summary["status"])
        for run in runs:
            model = load_model(args.pilot, run, summary["data_sha256"], identities)
            for episode in selected:
                case = audit_episode(model, episode)
                case.update(seed=run["seed"], arm=run["arm"],
                            model_sha256=run["final_model_sha256"],
                            checkpoint_sha256=run["checkpoint_sha256"],
                            completed_optimizer_updates=run["actual_optimizer_updates"])
                cases.append(case)
                print(json.dumps({key: case[key] for key in
                                  ("seed", "arm", "episode_id", "status")}), flush=True)
        expected = {(seed, arm) for seed in summary["configuration"]["seeds"]
                    for arm in ("c0_b1", "c1_b1")}
        report["complete_boundary_arm_roster"] = {(r["seed"], r["arm"]) for r in runs} == expected
        report["status"] = ("passed_selected_cases" if cases
                            and len(cases) == report["expected_cases"]
                            and report["complete_boundary_arm_roster"]
                            and all(c["status"] == "passed" for c in cases) else "HOLD")
    except Exception as error:
        report.update(status="error", error_type=type(error).__name__, error_message=str(error))
    finally:
        report["inputs_sha256"] = identities
        report["inputs_unchanged"] = all(Path(p).is_file()
            and hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in identities.items())
        if not report["inputs_unchanged"]:
            report["status"] = "inputs_changed"
        report["cost"] = {key: sum(c[key] for c in cases) for key in
                         ("forward_attempts", "forward_completed", "backward_attempts", "backward_completed")}
        report["cost"].update(process_wall_seconds=time.perf_counter() - STARTED,
                              process_cpu_seconds=time.process_time() - CPU_STARTED,
                              scope="process import, input verification, model loads and all audit calls; excludes final JSON write")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write(chr(10))
    print(json.dumps({"status": report["status"], "cases": len(cases), "cost": report["cost"]}))
    return 0 if report["status"] == "passed_selected_cases" else 1


if __name__ == "__main__":
    raise SystemExit(main())
