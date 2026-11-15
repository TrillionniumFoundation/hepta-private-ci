"""Source-bound independent numerical audit of the new regenerative tensors."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import traceback

import numpy as np
import scipy
import torch

from qualification.hcsn_regenerative import process as reference
from qualification.hcsn_regenerative import tensor
from qualification.hcsn_regenerative.audit import (
    five_point_derivative, hit_integral, pde_value, survivor_integral,
)


BASE = dict(x=.35, horizon=1.4, mu=-.1, sigma=.3, discount=.15)
RESET = dict(margin=.25, refractory=.11, hit_reward=1.)
REWARDS = dict(active_reward=.4, terminal_reward=.2)
EDGES = [0., .2, .5, 1., 2.]


def source_map():
    root = Path(__file__).resolve().parents[2]
    files = list((root / "qualification/hcsn_regenerative").glob("*.py"))
    files += list((root / "qualification/hcsn_regenerative/tests").glob("*.py"))
    files += [root / "qualification/hcsn/reference.py", root / "qualification/hcsn/population.py",
              root / "qualification/hcsn_regenerative/TENSOR_PROTOCOL.md"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def ref_values(case):
    p = reference.KilledDiffusion(case["mu"], case["sigma"], case["discount"])
    r = reference.ResetRule(**RESET)
    return reference.finite_horizon_value(p, r, case["x"], case["horizon"], **REWARDS)


def make(case, dtype, device, gradients=False):
    inputs = {k: torch.tensor(v, dtype=dtype, device=device, requires_grad=gradients)
              for k, v in case.items()}
    p = tensor.TensorDiffusion(inputs["mu"], inputs["sigma"], inputs["discount"])
    return p, tensor.TensorReset(**RESET), inputs


def objective_reference(case):
    p = reference.KilledDiffusion(case["mu"], case["sigma"], case["discount"])
    v = ref_values(case)
    k = p.transition(case["x"], case["horizon"], EDGES)
    return v.regenerative + .3*v.single_cycle + .2*k.hit + .1*k.survivor_bins[1]


def run(device, sink=None):
    checks, records, limitations = [], {}, []
    if sink is not None:
        # Preserve every completed observation if a later case raises.
        sink.update(checks=checks, records=records, limitations=limitations)

    def check(name, observed, expected, atol, rtol=0.):
        a, b = float(observed), float(expected)
        error = abs(a-b)
        tolerance = atol+rtol*abs(b)
        checks.append(dict(name=name, observed=a, oracle=b, absolute_error=error,
                           tolerance=tolerance, passed=math.isfinite(error) and error <= tolerance))

    cases = {
        "central": BASE,
        "near_boundary": dict(BASE, x=1e-5, horizon=.7),
        "short_time": dict(BASE, x=1e-4, horizon=1e-4),
        "low_noise": dict(BASE, x=.12, horizon=.8, mu=-.2, sigma=.05),
        "positive_drift": dict(BASE, x=.4, horizon=1.2, mu=.2),
        "far_tail": dict(BASE, x=4., horizon=.5),
        "strong_negative_drift": dict(BASE, mu=-2., sigma=.05, discount=.01),
    }
    value_records = []
    records["values_and_positive_integrals"] = value_records
    for name, case in cases.items():
        oracle = ref_values(case)
        for dtype, tol in ((torch.float64, 2e-8), (torch.float32, 3e-4)):
            p, r, z = make(case, dtype, device)
            value = tensor.finite_horizon_value(p, r, z["x"], z["horizon"], **REWARDS)
            row = dict(case=name, parameters=case, dtype=str(dtype), oracle=asdict(oracle), values={})
            for field in ("single_cycle", "regenerative", "expected_discounted_hits",
                          "active_probability", "active_time"):
                got = float(getattr(value, field).detach().cpu())
                row["values"][field] = got
                check(f"value:{name}:{dtype}:{field}", got, getattr(oracle, field), tol)
            hit = float(p.hit_probability(z["x"], z["horizon"]).cpu())
            hit_oracle = hit_integral(case["x"], case["horizon"], case["mu"], case["sigma"]).value
            survival = float(p.survival(z["x"], z["horizon"]).cpu())
            surv_oracle = survivor_integral(case["x"], case["horizon"], case["mu"], case["sigma"])
            check(f"risk:{name}:{dtype}", hit, hit_oracle, tol)
            check(f"survival:{name}:{dtype}", survival, surv_oracle, tol)
            row.update(first_hit=hit, first_hit_oracle=hit_oracle, survival=survival)
            if hit == 0 and hit_oracle > 0:
                limitations.append(dict(case=name, dtype=str(dtype), limitation="tail_underflow",
                                         relative_tail_accuracy_qualified=False,
                                         log_risk_gradient_qualified=False))
            value_records.append(row)
    records["values_and_positive_integrals"] = value_records

    gradients = []
    records["value_risk_state_gradients"] = gradients
    for name in ("central", "positive_drift", "low_noise"):
        case = cases[name]
        oracles = {}
        for field, point in case.items():
            f = lambda value: objective_reference(dict(case, **{field: value}))
            full = five_point_derivative(f, point, 1e-4)
            half = five_point_derivative(f, point, 5e-5)
            check(f"oracle_step:{name}:{field}", full, half, 1e-6, 1e-4)
            oracles[field] = (full, half)
        for dtype, atol, rtol in ((torch.float64, 2e-5, 2e-4), (torch.float32, 3e-3, 3e-3)):
            p, r, z = make(case, dtype, device, True)
            v = tensor.finite_horizon_value(p, r, z["x"], z["horizon"], **REWARDS)
            k = p.transition(z["x"], z["horizon"], EDGES)
            loss = v.regenerative+.3*v.single_cycle+.2*k.hit+.1*k.survivor_bins[1]
            loss.backward()
            for field in z:
                observed = float(z[field].grad.cpu())
                full, half = oracles[field]
                check(f"autodiff:{name}:{dtype}:{field}", observed, half, atol, rtol)
                gradients.append(dict(case=name, dtype=str(dtype), parameter=field,
                                      autodiff=observed, finite_difference=full,
                                      finite_difference_half=half))
    records["value_risk_state_gradients"] = gradients

    for dtype in (torch.float64, torch.float32):
        log_v = torch.tensor(math.log(2.)+.35, dtype=dtype, device=device, requires_grad=True)
        log_b = torch.tensor(math.log(2.), dtype=dtype, device=device, requires_grad=True)
        p, r, z = make(BASE, dtype, device)
        value = tensor.finite_horizon_value(p, r, log_v-log_b, z["horizon"], **REWARDS)
        value.regenerative.backward()
        oracle = five_point_derivative(lambda x: ref_values(dict(BASE, x=x)).regenerative, BASE["x"], 5e-5)
        check(f"boundary:{dtype}:log_v", log_v.grad.cpu(), oracle, 3e-3)
        check(f"boundary:{dtype}:log_b", log_b.grad.cpu(), -oracle, 3e-3)

    # The forward reference integrates the renewal convolution independently.
    # The candidate's temporal quadrature is refined without changing the model.
    state_rows = []
    records["successor_refinement"] = state_rows
    p_ref = reference.KilledDiffusion(BASE["mu"], BASE["sigma"], BASE["discount"])
    r_ref = reference.ResetRule(**RESET)
    oracle = reference.regenerative_transition(p_ref, r_ref, BASE["x"], BASE["horizon"], EDGES)
    expected = [*oracle.active_bins, oracle.upper_tail, *oracle.refractory_bins]
    for dtype in (torch.float64, torch.float32):
        p, r, z = make(BASE, dtype, device)
        for order in (32, 64, 128):
            try:
                state = tensor.regenerative_transition(p, r, z["x"], z["horizon"], EDGES,
                                                        quadrature_order=order)
                vector = torch.cat((state.active_bins, state.upper_tail.reshape(1), state.refractory_bins))
                got = vector.detach().cpu().tolist()
                state_rows.append(dict(dtype=str(dtype), order=order, values=got, oracle=expected,
                                       maximum_error=max(abs(a-b) for a, b in zip(got, expected))))
                if order == 128:
                    for i, (a, b) in enumerate(zip(got, expected)):
                        check(f"successor:{dtype}:{i}", a, b, 3e-4)
                    check(f"successor_mass:{dtype}", vector.sum().detach().cpu(), 1., 3e-4)
            except (ValueError, FloatingPointError) as error:
                state_rows.append(dict(dtype=str(dtype), order=order, rejected=str(error)))
                if order == 128:
                    checks.append(dict(name=f"successor:{dtype}:unresolved", passed=False, error=str(error)))
        fine_edges = [0., .1, .2, .35, .5, .75, 1., 1.5, 2.]
        coarse = p.transition(z["x"], z["horizon"], EDGES)
        fine = p.transition(z["x"], z["horizon"], fine_edges)
        for i in range(4):
            check(f"spatial_projection:{dtype}:{i}", fine.survivor_bins[2*i:2*i+2].sum().cpu(),
                  coarse.survivor_bins[i].cpu(), 3e-6)
    records["successor_refinement"] = state_rows

    def state_reference(case):
        p = reference.KilledDiffusion(case["mu"], case["sigma"], case["discount"])
        result = reference.regenerative_transition(p, r_ref, case["x"], case["horizon"], EDGES)
        return (sum(w*v for w, v in zip((.1, .4, .7, 1.), result.active_bins))
                +.2*result.upper_tail+.3*sum(result.refractory_bins)+.1*result.expected_hits)

    state_gradient_oracles = {}
    for field, point in BASE.items():
        f = lambda value: state_reference(dict(BASE, **{field: value}))
        full = five_point_derivative(f, point, 1e-4)
        half = five_point_derivative(f, point, 5e-5)
        check(f"state_oracle_step:{field}", full, half, 1e-6, 1e-4)
        state_gradient_oracles[field] = (full, half)
    state_gradients = []
    records["regenerative_state_gradients"] = state_gradients
    for dtype, atol, rtol in ((torch.float64, 2e-5, 2e-4), (torch.float32, 3e-3, 3e-3)):
        p, r, z = make(BASE, dtype, device, True)
        state = tensor.regenerative_transition(p, r, z["x"], z["horizon"], EDGES, quadrature_order=128)
        weights = torch.tensor([.1, .4, .7, 1.], dtype=dtype, device=device)
        loss = ((state.active_bins*weights).sum()+.2*state.upper_tail
                +.3*state.refractory_bins.sum()+.1*state.expected_hits)
        derivatives = torch.autograd.grad(loss, list(z.values()), allow_unused=True)
        for (field, _), gradient in zip(z.items(), derivatives):
            # The undiscounted state law is independent of q. A disconnected
            # q derivative is exactly zero, not a missing neural gradient.
            got = 0. if gradient is None and field == "discount" else float(gradient.cpu())
            full, half = state_gradient_oracles[field]
            check(f"regenerative_state_gradient:{dtype}:{field}", got, half, atol, rtol)
            state_gradients.append(dict(dtype=str(dtype), parameter=field, autodiff=got,
                                        finite_difference=full, finite_difference_half=half))
    records["regenerative_state_gradients"] = state_gradients

    pde_rows = []
    records["independent_time_and_space_pde_refinement"] = pde_rows
    exact = ref_values(BASE).regenerative
    for dx in (.02, .01):
        for dt in (.004, .002):
            pde = pde_value(**BASE, **RESET, **REWARDS, space_step=dx, time_step=dt, domain=3.)
            pde_rows.append(dict(**asdict(pde), absolute_value_error=abs(pde.regenerative-exact)))
    check("independent_pde_fine", pde_rows[-1]["regenerative"], exact, .02)
    records["independent_time_and_space_pde_refinement"] = pde_rows
    return checks, records, limitations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain old attempts; output already exists")
    torch.set_num_threads(1)
    before = source_map()
    started, cpu = time.monotonic(), time.process_time()
    report = dict(schema="hcsn.regenerative.tensor.audit.v1",
                  experiment_id="hcsn-regenerative-tensor-20261107-1631115f163f-v1",
                  started_utc=datetime.now(timezone.utc).isoformat(), source_files_sha256=before,
                  python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                  scipy=scipy.__version__, device=args.device, physical_energy_joules=None,
                  energy_reason="No full-machine physical energy receipt supplied",
                  production_activation=False, external_task_gain_established=False)
    try:
        run(args.device, report)
        report["passed"] = sum(row["passed"] for row in report["checks"])
        report["failed"] = len(report["checks"])-report["passed"]
        report["status"] = "bounded_tensor_checks_pass" if not report["failed"] else "numerical_gate_failed"
    except Exception:
        report.update(status="audit_error", error=traceback.format_exc())
    report.update(wall_seconds=time.monotonic()-started, process_cpu_seconds=time.process_time()-cpu,
                  source_unchanged=before == source_map(), finished_utc=datetime.now(timezone.utc).isoformat())
    if not report["source_unchanged"]:
        report["status"] = "source_changed"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "wall_seconds", "process_cpu_seconds")}))
    return 0 if report["status"] == "bounded_tensor_checks_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
