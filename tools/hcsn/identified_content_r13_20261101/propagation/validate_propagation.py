"""Run only independent propagation development checks, never task outcomes."""

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.integrate import fixed_quad
from scipy.linalg import expm
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from propagation.api import generator_numpy, generator_torch, grid_certificate, make_grid
from propagation.bounds import uniformization_terms
from propagation.finite_volume import reset_numpy
from propagation.renewal_bounds import first_hit_cdf, mixture_cdf_bounds, renewal_enclosure

torch.set_num_threads(1)


def write(name, payload):
    path = ROOT/name
    if path.exists():
        raise ValueError(f"Evidence is append-only: {name}")
    path.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n")


def physical_average(function, mean, width, order):
    from scipy.special import ndtr
    norm = ndtr((.8-mean)/width)-ndtr(-mean/width)
    return float(fixed_quad(lambda x: function(x)*np.exp(-.5*((x-mean)/width)**2)
                            /(np.sqrt(2*np.pi)*width*norm), 0, .8, n=order)[0])


def old_killed(n, mu, sigma):
    h = .8/n
    up, down = sigma*sigma/(2*h*h)+max(mu, 0)/h, sigma*sigma/(2*h*h)+max(-mu, 0)/h
    q = np.zeros((n, n))
    for i in range(n):
        q[i, i] = -down
        if i:
            q[i, i-1] = down
        if i+1 < n:
            q[i, i+1] = up
            q[i, i] -= up
    return q


def first_hit_checks(protocol):
    cfg = protocol["first_hit"]
    rows = []
    for case in protocol["physical_parameter_cases"]:
        mu, sigma = case["mu"], case["sigma"]
        models = []
        for h in cfg["near_steps"]:
            edges = make_grid(inner_step=h)
            terms = generator_numpy(sigma, mu, case["reset_x"], edges)
            n = len(edges)-1
            models.append(("R13_SG_expanded", h, edges, terms["Q"][:n, :n]))
        for n in (8, 64):
            models.append(("R12_upwind_reflect_0.8", .8/n, np.linspace(0, .8, n+1), old_killed(n, mu, sigma)))
        for dt in cfg["times"]:
            transitions = [(label, h, edges, expm(dt*q)) for label, h, edges, q in models]
            for mean in cfg["initial_gaussian_means"]:
                for width in cfg["initial_gaussian_widths"]:
                    reference = physical_average(lambda x: first_hit_cdf(x, dt, mu, sigma), mean, width, 320)
                    reference160 = physical_average(lambda x: first_hit_cdf(x, dt, mu, sigma), mean, width, 160)
                    lower, upper = mixture_cdf_bounds(np.array([dt]), mu, sigma, mean, width, bins=4096)
                    for label, h, edges, transition in transitions:
                        mass = reset_numpy(mean, width, edges)
                        value = 1-float(mass @ transition @ np.ones(len(mass)))
                        rows.append(dict(**case, mean=mean, width=width, dt=dt, model=label,
                            near_step=h, n_active=len(edges)-1, upper=float(edges[-1]),
                            first_hit=value, continuous_unbounded=reference,
                            signed_error=value-reference, quadrature_160_320_difference=abs(reference-reference160),
                            independent_endpoint_lower=float(lower[0]), independent_endpoint_upper=float(upper[0])))
    summaries = []
    for label, h in sorted(set((r["model"], r["near_step"]) for r in rows)):
        part = [r for r in rows if r["model"] == label and r["near_step"] == h]
        errors = np.array([abs(r["signed_error"]) for r in part])
        summaries.append(dict(model=label, near_step=h, contexts=len(part),
                              max_error=float(errors.max()), mean_error=float(errors.mean())))
    return dict(rows=rows, summary=summaries,
                max_quadrature_discrepancy=max(r["quadrature_160_320_difference"] for r in rows),
                scope="Unbounded continuum first-hit reference; errors include the frozen FV representation. Endpoint brackets separately qualify quadrature. No regenerative occupancy is mistaken for first-hit probability.")


def phase_joint(probability, n):
    p = probability.reshape(2, n+2)
    return np.c_[p[:, :n].sum(axis=1), p[:, n:]]


def renewal_checks(protocol):
    cfg = protocol["renewal"]
    rows = []
    for case in protocol["physical_parameter_cases"]:
        mu, sigma = case["mu"], case["sigma"]
        for dt in cfg["times"]:
            fv = []
            for h in (.025, .0125):
                edges = make_grid(inner_step=h)
                model = generator_numpy(sigma, mu, case["reset_x"], edges)
                n = len(edges)-1
                fv.append((h, edges, expm(dt*model["Q"])))
            for mean in cfg["initial_means"]:
                computed = []
                for h, edges, transition in fv:
                    n = len(edges)-1
                    initial = np.r_[reset_numpy(mean, cfg["initial_width"], edges), 0., 0., np.zeros(n+2)]
                    computed.append(dict(near_step=h, joint=phase_joint(initial @ transition, n).tolist()))
                for steps, bins in zip(cfg["clock_steps"], cfg["spatial_reset_bins"]):
                    envelope = renewal_enclosure(mu, sigma, case["reset_x"], mean,
                        cfg["initial_width"], dt, steps, bins,
                        recovery=cfg["recovery_mean"], retention=cfg["retention"],
                        cdf_padding=cfg["evaluated_cdf_padding"])
                    low, high = envelope["joint_lower"][:, :, -1], envelope["joint_upper"][:, :, -1]
                    for item in computed:
                        value = np.array(item["joint"])
                        item[f"max_enclosure_violation_{steps}"] = float(max(np.max(low-value), np.max(value-high), 0))
                    rows.append(dict(**case, initial_mean=mean, initial_width=cfg["initial_width"], dt=dt,
                        steps=steps, bins=bins, clock_step=envelope["clock_step"],
                        joint_lower=low.tolist(), joint_upper=high.tolist(),
                        max_joint_interval_width=float((high-low).max()),
                        phase_lower=envelope["phase_lower"][:, -1].tolist(),
                        phase_upper=envelope["phase_upper"][:, -1].tolist(),
                        content_weight_lower=float(envelope["content_weight_lower"][-1]),
                        content_weight_upper=float(envelope["content_weight_upper"][-1]),
                        probability_at_least_two_resets_lower=float(envelope["at_least_two_resets_lower"][-1]),
                        probability_at_least_two_resets_upper=float(envelope["at_least_two_resets_upper"][-1]),
                        fast_zero_cycle_mass=envelope["fast_zero_cycle_mass"],
                        fv_comparisons=[dict(v) for v in computed]))
    summary = []
    for steps in cfg["clock_steps"]:
        part = [r for r in rows if r["steps"] == steps]
        summary.append(dict(steps=steps, contexts=len(part),
            max_joint_interval_width=max(r["max_joint_interval_width"] for r in part),
            max_fv_enclosure_violation=max(v[f"max_enclosure_violation_{steps}"] for r in part for v in r["fv_comparisons"])))
    return dict(rows=rows, summary=summary,
        scope="Unbounded Brownian renewal reference, including all reset counts. These are mathematical enclosure formulas with float64 CDF evaluation and declared padding; no directed-rounding arithmetic claim. They enclose joint content/phase, not active position or arbitrary financial payoff.")


def gradient_and_generator_checks(protocol):
    edges = make_grid()
    records = []
    for sigma_value, reset_value in ((.3, .325), (.4, .25), (.15, .45), (np.sqrt(.12), .325)):
        raw = torch.tensor([sigma_value, reset_value], dtype=torch.float64, requires_grad=True)
        def objective(v):
            model = generator_torch(v[0], .06-v[0].square()/2, v[1], edges)
            reward = torch.linspace(0, 1, len(model["Q"]), dtype=torch.float64)
            return model["prior"] @ torch.matrix_exp(.45*model["Q"]) @ reward
        value = objective(raw)
        analytic = torch.autograd.grad(value, raw)[0].numpy()
        slopes = []
        for h in (1e-4, 1e-5, 1e-6):
            for i in range(2):
                shift = torch.zeros(2, dtype=torch.float64)
                shift[i] = h
                fd = float((objective(raw.detach()+shift)-objective(raw.detach()-shift))/(2*h))
                slopes.append(dict(index=i, step=h, finite_difference=fd, analytic=float(analytic[i]),
                    scaled_error=abs(fd-analytic[i])/max(1, abs(fd), abs(analytic[i]))))
        numpy_model = generator_numpy(sigma_value, .06-sigma_value**2/2, reset_value, edges)
        torch_model = generator_torch(raw[0], .06-raw[0].square()/2, raw[1], edges)
        q = numpy_model["Q"]
        off = q-np.diag(np.diag(q))
        records.append(dict(sigma=sigma_value, reset_mean=reset_value, value=float(value.detach()),
            min_offdiagonal=float(off.min()), row_sum_error=float(abs(q.sum(1)).max()),
            numpy_torch_error=float(abs(q-torch_model["Q"].detach().numpy()).max()),
            reset_mass_error=float(abs(numpy_model["reset"].sum()-1)), gradient_checks=slopes,
            uniformization=[dict(dt=dt, **uniformization_terms(q, dt)) for dt in (.05, .45, 2.1)]))
    sigma0 = np.sqrt(.12)
    critical = torch.tensor(sigma0, dtype=torch.float64, requires_grad=True)
    q_up = generator_torch(critical, .06-critical.square()/2,
                            critical.new_tensor(.325), edges)["Q"][0, 1]
    derivative = float(torch.autograd.grad(q_up, critical)[0])
    side_slopes = []
    center = float(q_up.detach())
    for step in (1e-5, 1e-6, 1e-7):
        y = [generator_numpy(s, .06-s*s/2, .325, edges)["Q"][0, 1] for s in (sigma0-step, sigma0+step)]
        side_slopes.append(dict(step=step, left=(center-y[0])/step, right=(y[1]-center)/step))
    return dict(grid=grid_certificate(edges), rows=records,
        smooth_drift=dict(critical_sigma=sigma0, analytic_sigma_derivative=derivative,
                          uniform_grid_limit=sigma0/.025**2-sigma0/(2*.025), one_sided=side_slopes),
        max_scaled_gradient_error=max(s["scaled_error"] for r in records for s in r["gradient_checks"]),
        runtime_file_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                            for name in protocol["frozen_model_files"]})


if __name__ == "__main__":
    started = time.perf_counter()
    protocol = json.loads((ROOT/"VALIDATION_PROTOCOL.json").read_text())
    for name, expected in protocol["frozen_model_files"].items():
        actual = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Frozen runtime file changed: {name}")
    action = sys.argv[1]
    function, filename = {
        "first_hit": (first_hit_checks, "FIRST_HIT.json"),
        "renewal": (renewal_checks, "RENEWAL.json"),
        "gradient": (gradient_and_generator_checks, "GENERATOR_GRADIENT.json")
    }[action]
    result = function(protocol)
    result["wall_seconds"] = time.perf_counter()-started
    write(filename, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows",)}, indent=2))
