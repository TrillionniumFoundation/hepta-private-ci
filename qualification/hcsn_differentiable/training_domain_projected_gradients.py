"""Audit partial Jacobians of the QPR flow at recorded training states.

The existing continuum-U audit holds a recorded posterior fixed. Here the
implemented interval transport/readouts are differentiated with the recorded
prior fixed. This is not a full transition-matrix Jacobian, differentiation
through a learned filter, a training-loss audit, or continuum error control.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from .contract import GridSpec, PhysicalParameters
from .operator import DifferentiableDistributionOperator
from .training_domain import read_trace, source_hashes


PARAMETERS = ("log_boundary", "mu", "sigma", "absolute_reset", "discount")
READOUTS = ("expected_events", "discounted_events", "discounted_active_time", "call", "margin")
LIMITS = {"absolute_tolerance": 1e-7, "relative_tolerance": 5e-4,
          "relative_steps": [2e-5, 1e-5], "maximum_output_coordinates": 8192}


def _flow_vector(operator, prior, dt, values):
    """Transport the fixed recorded law and return all its physical outputs."""
    flow = operator.advance(prior, prior[..., None], dt, PhysicalParameters(*values))
    return torch.cat((flow.probability, torch.stack(
        [getattr(flow, name) for name in READOUTS], dim=-1)), dim=-1).flatten()


def audit_visit(visit, *, deadline=math.inf):
    """Reverse AD and two-step central FD at one exact recorded prior.

    No matrix cache crosses perturbations. A central stencil that crosses the
    declared physical domain fails; no one-sided substitute is silently used.
    """
    def check_time():
        if time.perf_counter() >= deadline:
            raise TimeoutError("projected-gradient audit wall budget exhausted")

    check_time()
    grid = GridSpec(**visit["grid"])
    config = visit["operator"]
    operator = DifferentiableDistributionOperator(
        grid, active_reward=config["active_reward"], hit_reward=config["hit_reward"],
        terminal_reward=config["terminal_reward"], reset_enabled=config["reset_enabled"])
    if operator.configuration() != config:
        raise ValueError("recorded operator configuration does not match this source")
    prior = torch.tensor(visit["prior"], dtype=torch.float64)
    dt = torch.tensor(visit["dt"], dtype=torch.float64)
    if (prior.ndim != 2 or prior.shape[1] != grid.state_count or not len(prior)
            or dt.shape != prior.shape[:1] or not bool(torch.isfinite(prior).all())
            or bool((prior < 0).any()) or bool((prior.sum(-1) - 1).abs().gt(5e-11).any())):
        raise ValueError("normalized retained FP64 prior and matching durations required")
    width = grid.state_count + len(READOUTS)
    if len(prior) * width > LIMITS["maximum_output_coordinates"]:
        raise ValueError("visit exceeds the declared Jacobian output-coordinate budget")
    numbers = [visit["parameters"][name] for name in PARAMETERS]
    values = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in numbers)

    def evaluate(parameters):
        check_time()
        return _flow_vector(operator, prior, dt, parameters)

    # The custom log-CDF supports first-order reverse AD. No forward-mode,
    # double-backward JVP, or higher-order derivative is used here.
    with torch.enable_grad():
        output = evaluate(values)
        expected = torch.tensor(visit["expected_events"], dtype=torch.float64)
        if expected.shape != dt.shape or not bool(torch.isfinite(expected).all()):
            raise ValueError("finite recorded event counts must match the prior batch")
        actual_events = output.reshape(len(prior), width)[:, grid.state_count]
        replay_error = float((actual_events.detach() - expected).abs().max())
        if replay_error > 5e-11:
            raise ValueError("recorded event replay exceeds 5e-11")
        derivatives = []
        for component in output:
            check_time()
            gradient = (torch.autograd.grad(component, values, retain_graph=True, allow_unused=True)
                        if component.requires_grad else (None,) * len(values))
            derivatives.append(torch.stack([
                value.new_zeros(()) if derivative is None else derivative
                for value, derivative in zip(values, gradient)]))
        ad = torch.stack(derivatives).detach()
    differences, steps = [], []
    with torch.no_grad():
        for factor in LIMITS["relative_steps"]:
            columns, actual_steps = [], []
            for index, value in enumerate(numbers):
                step = factor * max(1., abs(value))
                low = [v.detach().clone() for v in values]
                high = [v.detach().clone() for v in values]
                low[index] -= step
                high[index] += step
                columns.append((evaluate(high) - evaluate(low)) / (2 * step))
                actual_steps.append(step)
            differences.append(torch.stack(columns, dim=-1))
            steps.append(actual_steps)
    check_time()
    coarse, fine = differences
    if not all(bool(torch.isfinite(v).all()) for v in (ad, coarse, fine)):
        raise FloatingPointError("nonfinite AD or finite-difference Jacobian")
    atol, rtol = LIMITS["absolute_tolerance"], LIMITS["relative_tolerance"]
    error, stability = (ad - fine).abs(), (coarse - fine).abs()
    scale = atol + rtol * torch.maximum(ad.abs(), fine.abs())
    stability_scale = atol + rtol * torch.maximum(coarse.abs(), fine.abs())
    rows = []
    for parameter_index, name in enumerate(PARAMETERS):
        ratios = error[:, parameter_index] / scale[:, parameter_index]
        worst = int(ratios.argmax())
        offset = worst % width
        ordinary_relative = []
        for deviation, reference in zip(error[:, parameter_index], fine[:, parameter_index]):
            deviation, reference = float(deviation), abs(float(reference))
            ratio = deviation / reference if reference else math.inf
            ordinary_relative.append(ratio if math.isfinite(ratio) else None)
        rows.append({
            "parameter": name, "finite_difference_steps": [s[parameter_index] for s in steps],
            "maximum_absolute_error": float(error[:, parameter_index].max()),
            "maximum_tolerance_ratio": float(ratios.max()),
            "maximum_step_stability_ratio": float((stability[:, parameter_index] / stability_scale[:, parameter_index]).max()),
            "ordinary_relative_errors": ordinary_relative,
            "worst_coordinate": {"batch_offset": worst // width,
                                 "quantity": f"probability[{offset}]" if offset < grid.state_count else READOUTS[offset - grid.state_count],
                                 "ad": float(ad[worst, parameter_index]),
                                 "fd": float(fine[worst, parameter_index])},
        })
    return {
        "status": "passed_projected_gradient_fixture" if bool((error <= scale).all() and (stability <= stability_scale).all()) else "HOLD",
        "output_layout": {"batch": len(prior), "probability_states": grid.state_count, "readouts": list(READOUTS)},
        "derivative_coordinates": ad.numel(), "parameters": rows,
        "recorded_event_replay_verified": True, "maximum_event_replay_error": replay_error,
        "ad": ad.tolist(), "fd_coarse": coarse.tolist(), "fd_fine": fine.tolist(),
        "scope": "Partial Jacobian of implemented flow from a fixed recorded prior; no filter/loss/continuum claim.",
    }


def audit_projected_trace(path, *, max_records=16, max_wall_seconds=120.):
    if type(max_records) is not int or not 1 <= max_records <= 256:
        raise ValueError("max_records must be in [1,256]")
    if (isinstance(max_wall_seconds, bool) or not isinstance(max_wall_seconds, (int, float))
            or not math.isfinite(max_wall_seconds) or not 0 < max_wall_seconds <= 3600):
        raise ValueError("max_wall_seconds must be a finite real in (0,3600]")
    started = time.perf_counter()
    before, auditor_before = source_hashes(), hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    header, visits, footer, trace_digest = read_trace(path)
    matches = (header["sources"] == before and footer.get("sources_after") == header["sources"]
               and footer.get("source_unchanged") is True)
    report = {
        "schema": "hcsn-recorded-projected-gradient-audit-v1", "trace_sha256": trace_digest,
        "data_sha256": header["data_sha256"], "configuration_sha256": header["configuration_sha256"],
        "trace_summary": footer, "source_matches_trace": matches, "limits": LIMITS,
        "auditor_sha256": auditor_before, "max_wall_seconds": max_wall_seconds,
        "wall_budget_scope": "Checked before each forward and reverse coordinate; one native operation is not preempted.",
        "scientific_admission": "HOLD_NO_GO", "full_numerical_admission": "HOLD_NO_GO",
        "formal_training_replays": 0,
        "gradient_scope": "Five physical parameters; all flow outputs for a fixed recorded prior.",
        "relative_error_scope": "Absolute-plus-relative gate; not a relative rare-tail gradient certificate. Undefined ordinary relative errors are null.",
        "not_qualified": ["raw-to-physical parameterization", "observation filtering", "end-to-end task loss",
                          "whole training trajectory", "continuum accuracy", "energy or adoption"],
        "visits": [],
    }
    if matches:
        for visit in visits[:max_records]:
            row = {key: visit[key] for key in ("index", "episode_id", "update_index", "model_sha256")}
            try:
                row.update(audit_visit(visit, deadline=started + max_wall_seconds))
            except Exception as error:
                row.update(status="error", error_type=type(error).__name__, detail=str(error))
            report["visits"].append(row)
            if time.perf_counter() - started >= max_wall_seconds:
                break
    unchanged = (before == source_hashes()
                 and auditor_before == hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    wall_seconds = time.perf_counter() - started
    complete = (matches and bool(visits) and not footer["truncated"]
                and len(report["visits"]) == len(visits))
    passed = bool(report["visits"]) and all(v["status"] == "passed_projected_gradient_fixture" for v in report["visits"])
    report.update(audited_records=len(report["visits"]), complete_retained_coverage=complete,
                  source_unchanged_during_audit=unchanged, wall_seconds=wall_seconds,
                  wall_budget_exhausted=wall_seconds >= max_wall_seconds,
                  status="passed_recorded_projected_gradients"
                  if complete and passed and unchanged and wall_seconds < max_wall_seconds else "HOLD")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=16)
    parser.add_argument("--max-wall-seconds", type=float, default=120.)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("retain prior evidence and choose a new output path")
    torch.set_num_threads(1)
    report = audit_projected_trace(args.trace, max_records=args.max_records, max_wall_seconds=args.max_wall_seconds)
    report["torch"] = torch.__version__
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "audited_records", "scientific_admission")}))
    return 0 if report["status"] == "passed_recorded_projected_gradients" else 1


if __name__ == "__main__":
    raise SystemExit(main())
