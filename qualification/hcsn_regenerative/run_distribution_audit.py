"""Independent direct-process and coupled-refinement audit of FV continuation."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import traceback

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch

from . import process as scalar
from .distribution import DistributionGrid, DistributionState, physical_time
from .distribution_manifest import digest, source_map
from .distribution_operator import DistributionOperator
from .tensor import TensorDiffusion, TensorReset


CONFIG = dict(candidate="hcsn-regenerative-distribution-fv-v1", mu=-.1, sigma=.3, discount=.15,
              margin=.25, refractory=.11, x=.35, endpoint=1.6, tail_rate=1., horizon=.32,
              levels=((32, 8, .08), (64, 16, .04), (128, 32, .02)), quadrature_order=32)


def make_grid(active, phase):
    return DistributionGrid(tuple(np.linspace(0., CONFIG["endpoint"], active+1)),
                            tuple(np.linspace(0., CONFIG["refractory"], phase+1)), CONFIG["tail_rate"])


def aggregate(state):
    """Nested-grid comparison at common bins; no probability rescaling."""
    active = state.active.detach().cpu().numpy().reshape(32, -1).sum(-1)
    phase = state.refractory.detach().cpu().numpy().reshape(8, -1).sum(-1)
    return np.concatenate((active, np.array([float(state.tail.cpu())]), phase))


def direct_reference():
    grid = make_grid(32, 8)
    process = scalar.KilledDiffusion(CONFIG["mu"], CONFIG["sigma"], CONFIG["discount"])
    reset = scalar.ResetRule(CONFIG["margin"], CONFIG["refractory"])
    state = scalar.regenerative_transition(process, reset, CONFIG["x"], CONFIG["horizon"], grid.active_edges,
                                           refractory_edges=grid.refractory_edges, tolerance=1e-11)
    value = scalar.finite_horizon_value(process, reset, CONFIG["x"], CONFIG["horizon"], tolerance=1e-11)
    return dict(mass=[*state.active_bins, state.upper_tail, *state.refractory_bins],
                expected_hits=state.expected_hits, expected_discounted_hits=value.expected_discounted_hits,
                discounted_active_time=value.active_time, quadrature_error=state.quadrature_error,
                value_quadrature_error=value.quadrature_error, mass_residual=state.mass_residual,
                renewal_tail_bound=state.renewal_tail_bound)


def level(active, phase, dt, dtype, device, reference):
    started = time.monotonic()
    grid = make_grid(active, phase)
    operator = DistributionOperator(TensorDiffusion(CONFIG["mu"], CONFIG["sigma"], CONFIG["discount"]),
                                    TensorReset(CONFIG["margin"], CONFIG["refractory"]), grid, dt,
                                    dtype=dtype, device=device, quadrature_order=CONFIG["quadrature_order"])
    state = DistributionState.point(grid, CONFIG["x"], dtype=dtype, device=device)
    ratio = physical_time(CONFIG["horizon"])/physical_time(dt)
    if ratio.denominator != 1:
        raise ValueError("audit schedule does not exactly cover its physical horizon")
    rewards = dict(expected_hits=0., expected_discounted_hits=0., discounted_active_time=0.)
    trace = []
    for _ in range(ratio.numerator):
        discount = math.exp(-CONFIG["discount"]*state.physical_elapsed)
        flow = operator.advance(state)
        rewards["expected_hits"] += float(flow.expected_hits.cpu())
        rewards["expected_discounted_hits"] += discount*float(flow.expected_discounted_hits.cpu())
        rewards["discounted_active_time"] += discount*float(flow.discounted_active_time.cpu())
        state = flow.state
        trace.append(dict(elapsed=[state.elapsed.numerator, state.elapsed.denominator],
                          active=float(state.active_probability.cpu()), tail=float(state.tail.cpu()),
                          phase=float(state.refractory.sum().cpu()), mass_residual=float(flow.mass_residual.cpu()),
                          active_projection_distance=float(flow.active_projection_distance_upper.cpu()),
                          phase_projection_time=float(flow.phase_projection_time_upper.cpu()),
                          tail_projection_distance=float(flow.tail_projection_distance_upper.cpu())))
    prediction = aggregate(state)
    return dict(status="pass", dtype=str(dtype), device=device, active_cells=active, phase_cells=phase, dt=dt,
                steps=ratio.numerator, common_bin_mass=prediction.tolist(),
                common_bin_l1_error=float(np.abs(prediction-np.asarray(reference["mass"])).sum()),
                rewards=rewards, reward_abs_errors={key: abs(value-reference[key]) for key, value in rewards.items()},
                terminal_mass_residual=float(state.total_mass.cpu())-1,
                cumulative_projection_active_distance=float(state.projection_active_distance_sum.cpu()),
                cumulative_projection_phase_time=float(state.projection_phase_time_sum.cpu()),
                clock_exact=state.elapsed == physical_time(CONFIG["horizon"]),
                state_sha256=digest(state.state_dict()), operator=operator.checkpoint_identity(),
                diagnostics=operator.diagnostics, transition_matrix_bytes=operator.matrix.numel()*operator.matrix.element_size(),
                trace=trace, wall_seconds=time.monotonic()-started)


def semigroup_defect(device):
    grid = make_grid(32, 8)
    process, reset = TensorDiffusion(-.1, .3, .15), TensorReset(.25, .11)
    long = DistributionOperator(process, reset, grid, .08, dtype=torch.float64, device=device)
    short = DistributionOperator(process, reset, grid, .04, dtype=torch.float64, device=device)
    mass = torch.zeros(grid.size, dtype=torch.float64, device=device)
    mass[6], mass[grid.active_size], mass[-1] = .6, .1, .3
    state = DistributionState(grid, mass)
    once = long.advance(state).state
    twice = short.advance(short.advance(state).state).state
    return dict(fixed_grid_cells=(32, 8), long_dt=.08, short_dt=.04,
                l1_difference=float((once.mass-twice.mass).abs().sum().cpu()),
                exact_semigroup_claim=False, same_elapsed=once.elapsed == twice.elapsed,
                explanation="Intermediate remapping changes the finite basis approximation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous attempts: output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA qualification requested without CUDA")
    if args.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started, cpu = time.monotonic(), time.process_time()
    source = source_map()
    reference = direct_reference()
    rows, checks = [], []
    for dtype in (torch.float32, torch.float64):
        group = []
        for active, phase, dt in CONFIG["levels"]:
            try:
                row = level(active, phase, dt, dtype, args.device, reference)
            except Exception as error:
                row = dict(status="failed", dtype=str(dtype), device=args.device, active_cells=active,
                           phase_cells=phase, dt=dt, error=repr(error), traceback=traceback.format_exc())
            rows.append(row)
            group.append(row)
        complete = all(row["status"] == "pass" for row in group)
        checks.append(dict(name=f"{dtype}:all_configurations_construct", pass_=complete))
        if complete:
            checks.extend((dict(name=f"{dtype}:fine_state_l1<=.04", pass_=group[-1]["common_bin_l1_error"] <= .04),
                           dict(name=f"{dtype}:coupled_refinement_improves", pass_=group[-1]["common_bin_l1_error"] < group[0]["common_bin_l1_error"]),
                           dict(name=f"{dtype}:fine_reward_abs<=.01", pass_=max(group[-1]["reward_abs_errors"].values()) <= .01),
                           dict(name=f"{dtype}:exact_physical_clocks", pass_=all(row["clock_exact"] for row in group))))
    try:
        defect = semigroup_defect(args.device)
        checks.append(dict(name="semigroup_comparison_equal_physical_duration", pass_=defect["same_elapsed"]))
    except Exception as error:
        defect = dict(error=repr(error), traceback=traceback.format_exc())
        checks.append(dict(name="semigroup_comparison_completed", pass_=False))
    checks.append(dict(name="source_unchanged", pass_=source == source_map()))
    passed = all(check["pass_"] for check in checks)
    result = dict(schema="hcsn.distribution-audit.v1", status="pass" if passed else "failed", config=CONFIG,
                  source_files_sha256=source, source_set_sha256=digest(source), device=args.device,
                  torch=str(torch.__version__), reference=reference, rows=rows, checks=checks,
                  semigroup_defect=defect, wall_seconds=time.monotonic()-started,
                  process_cpu_seconds=time.process_time()-cpu,
                  peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated() if args.device == "cuda" else None,
                  physical_energy_joules=None, energy_reason="No full-machine physical energy measurement supplied",
                  whole_parameter_domain_qualified=False, global_error_bound_qualified=False,
                  task_quality_evidence=False, finished_utc=datetime.now(timezone.utc).isoformat())
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=result["status"], checks=len(checks), passed=sum(c["pass_"] for c in checks))))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
