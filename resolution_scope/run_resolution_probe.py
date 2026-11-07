"""Numerical-only pretraining resolution selection for the declared FV pilot."""

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import time
import traceback

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch

from qualification.hcsn_regenerative import fixed_renewal
from qualification.hcsn_regenerative.distribution import DistributionGrid, DistributionState
from qualification.hcsn_regenerative.distribution_manifest import digest, source_map as fv_source_map
from qualification.hcsn_regenerative.distribution_operator import DistributionOperator
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset
from .resolution_reference import (
    DISCOUNT, ENDPOINT, INITIAL, MARGIN, MU, REFRACTORY, SIGMA, crosscheck, direct,
)


LEVELS = ((16, 8), (64, 16), (128, 32))
SCHEDULES = dict(unequal=(.025, .05, .075, .1)*16, equal=(.0625,)*64)


def source_map():
    result = fv_source_map()
    result["qualification/hcsn_regenerative/fixed_renewal.py"] = hashlib.sha256(Path(fixed_renewal.__file__).read_bytes()).hexdigest()
    for name in ("run_resolution_probe.py", "resolution_reference.py", "RESOLUTION_PROTOCOL.md"):
        result["resolution_scope/"+name] = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    return result


def grid_for(active, phase):
    return DistributionGrid(tuple(float(v) for v in np.linspace(0., ENDPOINT, active+1)),
                            tuple(float(v) for v in np.linspace(0., REFRACTORY, phase+1)), 1.)


def aggregate(state):
    return np.r_[state.active.detach().cpu().numpy().reshape(16, -1).sum(-1),
                 float(state.tail.cpu()), state.refractory.detach().cpu().numpy().reshape(8, -1).sum(-1)]


def run_level(active, phase, dtype, device, reference):
    grid = grid_for(active, phase)
    bank = {}
    for dt in sorted(set(SCHEDULES["unequal"]+SCHEDULES["equal"])):
        bank[dt] = DistributionOperator(TensorDiffusion(MU, SIGMA, DISCOUNT), TensorReset(MARGIN, REFRACTORY),
                                        grid, dt, dtype=dtype, device=device, quadrature_order=32)
    rows = []
    for name, schedule in SCHEDULES.items():
        started = time.monotonic()
        state = DistributionState.point(grid, INITIAL, dtype=dtype, device=device)
        rewards = dict(expected_hits=0., expected_discounted_hits=0., discounted_active_time=0.)
        trace = []
        for step, dt in enumerate(schedule):
            discount = math.exp(-DISCOUNT*state.physical_elapsed)
            flow = bank[dt].advance(state)
            rewards["expected_hits"] += float(flow.expected_hits.cpu())
            rewards["expected_discounted_hits"] += discount*float(flow.expected_discounted_hits.cpu())
            rewards["discounted_active_time"] += discount*float(flow.discounted_active_time.cpu())
            state = flow.state
            trace.append(dict(step=step+1, elapsed=[state.elapsed.numerator, state.elapsed.denominator],
                              active=float(state.active_probability.cpu()), tail=float(state.tail.cpu()),
                              phase=float(state.refractory.sum().cpu()), mass_residual=float(flow.mass_residual.cpu())))
        if state.elapsed != Fraction(4):
            raise ValueError("the declared schedule did not reach exactly four physical seconds")
        mass = aggregate(state)
        l1 = float(np.abs(mass-np.asarray(reference["mass"])).sum())
        reward_error = {key: abs(value-reference[key]) for key, value in rewards.items()}
        hit_relative = reward_error["expected_hits"]/reference["expected_hits"]
        rows.append(dict(status="measured", active_cells=active, phase_cells=phase, dtype=str(dtype), device=device,
                         schedule=name, steps=len(schedule), physical_time=state.physical_elapsed,
                         common_bin_mass=mass.tolist(), state_l1_error=l1, rewards=rewards,
                         reward_abs_errors=reward_error, hit_relative_error=hit_relative,
                         passes_state_l1=l1 <= .02, passes_hit_relative=hit_relative <= .03,
                         passes_configuration=l1 <= .02 and hit_relative <= .03,
                         terminal_mass_residual=float(state.total_mass.cpu())-1,
                         cumulative_active_projection_distance=float(state.projection_active_distance_sum.cpu()),
                         cumulative_phase_projection_time=float(state.projection_phase_time_sum.cpu()),
                         trace=trace, execution_wall_seconds=time.monotonic()-started))
    discrepancy = dict(active_cells=active, phase_cells=phase, dtype=str(dtype),
                       state_l1_same_time_schedule_difference=float(np.abs(
                           np.asarray(rows[0]["common_bin_mass"])-np.asarray(rows[1]["common_bin_mass"])).sum()),
                       reward_same_time_schedule_differences={key: abs(rows[0]["rewards"][key]-rows[1]["rewards"][key])
                                                              for key in rows[0]["rewards"]})
    diagnostics = {str(dt): dict(identity=operator.checkpoint_identity(), diagnostics=operator.diagnostics)
                   for dt, operator in bank.items()}
    return rows, discrepancy, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain every attempt; output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    started, cpu = time.monotonic(), time.process_time()
    sources = source_map()
    checks = crosscheck()
    verified = all(check["pass_"] for check in checks)
    reference = direct(4.) if verified else None
    rows, discrepancies, constructions, errors = [], [], [], []
    if verified:
        for active, phase in LEVELS:
            for dtype in (torch.float64, torch.float32):
                try:
                    group, difference, diagnostics = run_level(active, phase, dtype, args.device, reference)
                    rows.extend(group)
                    discrepancies.append(difference)
                    constructions.append(dict(active_cells=active, phase_cells=phase, dtype=str(dtype), operators=diagnostics))
                except Exception as error:
                    errors.append(dict(active_cells=active, phase_cells=phase, dtype=str(dtype),
                                       error=repr(error), traceback=traceback.format_exc()))
    eligibility = []
    for active, phase in LEVELS:
        selected = [row for row in rows if row["active_cells"] == active and row["phase_cells"] == phase]
        eligible = verified and len(selected) == 4 and all(row["passes_configuration"] for row in selected)
        eligibility.append(dict(active_cells=active, phase_cells=phase, eligible=eligible,
                                maximum_state_l1_error=max((r["state_l1_error"] for r in selected), default=None),
                                maximum_hit_relative_error=max((r["hit_relative_error"] for r in selected), default=None)))
    recommendation = next((row for row in eligibility if row["eligible"]), None)
    unchanged = sources == source_map()
    complete = verified and len(rows) == 12 and not errors and unchanged
    receipt = dict(schema="hcsn-pretraining-resolution-scope-v1", status="complete" if complete else "failed",
                   sources=sources, source_set_sha256=digest(sources), source_unchanged=unchanged,
                   physical_parameters=dict(mu=MU, sigma=SIGMA, discount=DISCOUNT, margin=MARGIN, refractory=REFRACTORY,
                                            initial=INITIAL, endpoint=ENDPOINT, tail_rate=1.),
                   thresholds=dict(common_bin_state_l1=.02, cumulative_hit_relative=.03, reference_crosscheck_abs=2e-8),
                   reference_crosscheck=checks, direct_reference=reference, rows=rows,
                   same_time_schedule_discrepancies=discrepancies, eligibility=eligibility,
                   smallest_eligible_configuration=recommendation, construction=constructions, errors=errors,
                   torch=str(torch.__version__), device=args.device, task_dataset_reads=0, task_optimizer_updates=0,
                   selection_basis="Numerical process approximation only; no task outcomes consulted",
                   wall_seconds=time.monotonic()-started, process_cpu_seconds=time.process_time()-cpu,
                   physical_energy_joules=None, global_approximation_claim=False,
                   finished_utc=datetime.now(timezone.utc).isoformat())
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=receipt["status"], measured_rows=len(rows), eligibility=eligibility,
                          recommended=recommendation, wall_seconds=receipt["wall_seconds"])))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
