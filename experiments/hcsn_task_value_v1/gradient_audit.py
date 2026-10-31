"""Independent finite-difference and financial-tail audit helpers.

Finite differences diagnose the actual reoptimized value, not a frozen policy.
Their agreement is local numerical evidence, never a global differentiability
or continuum-error certificate. Quadrature error estimates are not bounds.
"""

import math
from dataclasses import replace

import numpy as np
from scipy.integrate import quad


def directional_audit(value, derivative, *, at=0.0, step=1e-4,
                      absolute_tolerance=2e-7, relative_tolerance=2e-5):
    """Compare a candidate derivative against two reoptimized FD scales.

    A persistent left/right jump is reported even if its central difference
    coincides with the proposed derivative. Coincident optimal actions can
    still pass when they have the same value derivative.
    """
    parameters = (at, step, absolute_tolerance, relative_tolerance)
    if (not all(math.isfinite(v) for v in parameters) or step <= 0
            or min(absolute_tolerance, relative_tolerance) <= 0
            or at + step / 2 == at or at - step / 2 == at):
        raise ValueError("Unresolved finite-difference parameters")
    center = np.asarray(value(at), dtype=float)
    proposed = np.asarray(derivative, dtype=float)
    if proposed.shape != center.shape or not np.all(np.isfinite(proposed)):
        raise ValueError("Derivative shape or finite domain invalid")
    samples = [np.asarray(value(at + offset * step), dtype=float)
               for offset in (-1, -0.5, 0.5, 1)]
    if not np.all(np.isfinite(center)) or any(
            item.shape != center.shape or not np.all(np.isfinite(item))
            for item in samples):
        raise ValueError("Finite-difference values changed shape or are nonfinite")
    minus, half_minus, half_plus, plus = samples
    coarse = (plus - minus) / (2 * step)
    fine = (half_plus - half_minus) / step
    left = (center - half_minus) / (step / 2)
    right = (half_plus - center) / (step / 2)
    if not all(np.all(np.isfinite(item)) for item in (coarse, fine, left, right)):
        raise ArithmeticError("Finite inputs produced unresolved difference quotients")
    jump = np.abs(right - left)
    coarse_jump = np.abs((plus - center) / step - (center - minus) / step)
    threshold = absolute_tolerance + relative_tolerance * np.maximum(
        1.0, np.maximum(np.abs(proposed), np.abs(fine)))
    persistent_jump = (jump > 8 * threshold) & (jump >= 0.75 * coarse_jump)
    converged = np.abs(fine - coarse) <= threshold
    agreement = np.abs(fine - proposed) <= threshold
    passed = bool(np.all(converged & agreement & ~persistent_jump))
    return {
        "status": "local_fd_consistent" if passed else "unresolved_or_nonsmooth",
        "passed": passed,
        "step": step,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "max_derivative_error": float(np.max(np.abs(fine - proposed))),
        "max_fd_scale_difference": float(np.max(np.abs(fine - coarse))),
        "max_left_right_difference": float(np.max(jump)),
        "persistent_jump_components": int(np.count_nonzero(persistent_jump)),
        "fine_difference": fine.tolist(),
        "left_difference": left.tolist(),
        "right_difference": right.tolist(),
        "proposed_derivative": proposed.tolist(),
    }


def equity_quadrature_reference(parameters, asset, boundary, *, tail_span=100.0):
    """Independent outer Green quadrature with the asset cashflow integrated.

    Uses the shared finite-maturity bond evaluator, so this checks the equity
    resolvent/tail only, not the bond formula independently. The payout term is
    integrated exactly as V-B*E[exp(-r*tau_B)]; payout=0 follows the existing
    reference's payout-down-to-zero transversality convention.
    """
    from ..hcsn_hx_unified_v3.hx import bond_value

    p = parameters
    if not (math.isfinite(asset) and math.isfinite(boundary)
            and asset > boundary > 0 and math.isfinite(tail_span)
            and 50 <= tail_span <= 150):
        raise ValueError("Reference requires positive interior state and resolved tail")
    x = math.log(asset / boundary)
    if not 0 < x < 500:
        raise ValueError("Reference log-distance outside its bounded audit range")
    a, z, eta = p.a, p.z, p.eta
    scale = max(1.0, p.principal, p.coupon)
    constant = (1 - p.tax_shield) * p.coupon + p.per_bond_principal
    normalizer = p.volatility ** 2 * z

    def integrand(y):
        if y < x:
            green = math.exp((-a-z)*(x-y)) * (-math.expm1(-2*z*y))
        else:
            green = math.exp((a-z)*(y-x)) * (-math.expm1(-2*z*x))
        debt = bond_value(p, boundary * math.exp(y), p.maturity, boundary)
        return green * ((debt - constant) / scale) / normalizer

    left, left_error = quad(integrand, 0, x, epsabs=1e-14,
                            epsrel=1e-14, limit=400)
    right, right_error = quad(integrand, x, x+tail_span, epsabs=1e-14,
                              epsrel=1e-14, limit=400)
    value = asset - boundary * math.exp(-p.gamma*x) + scale * (left+right)
    # Nonnegative coupons plus discounted terminal payment bound the bond.
    max_bond = p.per_bond_coupon/p.q + max(
        p.per_bond_principal, p.recovery*boundary/p.maturity)
    remainder = ((max_bond + abs(constant)) * math.exp(-eta*tail_span)
                 * (-math.expm1(-2*z*x)) / (normalizer*eta))
    return {
        "value": value,
        "quadrature_error_estimate_not_bound": scale*(left_error+right_error),
        "analytic_outer_tail_bound_excluding_roundoff": remainder,
        "tail_start": x+tail_span,
        "shared_inner_reference": "hx.bond_value",
    }


def audit_oracle_directions():
    """Independent reoptimization checks for coupled rewards and reset kernels."""
    from ..hcsn_hx_unified_v3.coupled_qvi import Rectangle, TwoCell
    from ..hcsn_hx_unified_v3.stopping import Stop
    from .oracle import build, solve_policy
    from .oracle_gradients import direction, one_sided_gradients

    cells = TwoCell(Stop(.12, .6, .3, .2, -.7, .6),
                    Stop(-.08, .8, .3, .45, -.55, .85))
    rect = Rectangle(-2., 3., 9, -2., 3., 9)
    baseline = build(cells, rect)
    x1 = np.r_[baseline.x1, [-.7, -.7]][:, None]
    x2 = np.r_[baseline.x2, [-.55, -.55]][None, :]
    running = .07*np.sin(x1)*np.cos(.7*x2)
    impulse1 = x1 + np.zeros_like(x2) - .2 + .11*np.tanh(x2)
    impulse2 = x2 + np.zeros_like(x1) - .45 - .08*np.tanh(x1)
    logits1 = -.7*(baseline.x1[None, :]+.7-.1*np.tanh(x2.T))**2
    logits2 = -.6*(baseline.x2[None, :]+.55+.1*np.sin(x1))**2

    def softmax(array):
        e = np.exp(array-array.max(axis=1, keepdims=True))
        return e/e.sum(axis=1, keepdims=True)

    kernel1, kernel2 = softmax(logits1), softmax(logits2)
    tilt1, tilt2 = np.cos(logits1), np.sin(logits2)
    dk1 = kernel1*(tilt1-(kernel1*tilt1).sum(axis=1, keepdims=True))
    dk2 = kernel2*(tilt2-(kernel2*tilt2).sum(axis=1, keepdims=True))
    d_running = .3*np.cos(x1+x2)
    specifications = (
        ("drift_first", {"drift": (1., 0.)}),
        ("diffusion_second", {"diffusion": (0., 1.)}),
        ("discount", {"discount": 1.}),
        ("refractory_first", {"refractory": (1., 0.)}),
        ("cost_second", {"cost": (0., 1.)}),
        ("running_reward", {"running": d_running}),
        ("impulse_first", {"impulse1": np.cos(x1+x2)}),
        ("reset_kernel_first", {"reset1": dk1}),
        ("reset_kernel_second", {"reset2": dk2}),
    )
    entries = []
    for name, tangent_args in specifications:
        def make(theta):
            updated = [cells.first, cells.second]
            for axis in (0, 1):
                changes = {}
                for key in ("drift", "diffusion", "refractory", "cost"):
                    changes[key] = getattr(updated[axis], key) + theta*tangent_args.get(key, (0., 0.))[axis]
                changes['discount'] = .3 + theta*tangent_args.get('discount', 0.)
                updated[axis] = replace(updated[axis], **changes)
            return build(TwoCell(*updated), rect, running=running+theta*tangent_args.get('running', 0.),
                         impulse1=impulse1+theta*tangent_args.get('impulse1', 0.)
                         -theta*tangent_args.get('cost', (0., 0.))[0],
                         impulse2=impulse2-theta*tangent_args.get('cost', (0., 0.))[1],
                         reset1=softmax(logits1+theta*tilt1) if 'reset1' in tangent_args else kernel1,
                         reset2=softmax(logits2+theta*tilt2) if 'reset2' in tangent_args else kernel2)

        model = make(0.)
        optimum = solve_policy(model)
        sensitivity = one_sided_gradients(model, optimum, direction(model, **tangent_args))
        audits = directional_audit(lambda theta: solve_policy(make(theta)).values,
                                   sensitivity.fixed)
        entries.append({'direction': name, **audits,
                        'tied_states': sensitivity.tie_states,
                        'tangent_left_right_gap': sensitivity.kink_norm,
                        'base_qvi_residual': optimum.qvi_residual})

    # Coordinate interpolation is a different reset contract from a dense kernel.
    model = baseline
    optimum = solve_policy(model)
    for axis in (0, 1):
        vector = (1., 0.) if axis == 0 else (0., 1.)
        sensitivity = one_sided_gradients(model, optimum, direction(model, reset=vector))

        def coordinate_value(theta):
            updated = [cells.first, cells.second]
            updated[axis] = replace(updated[axis], reset=updated[axis].reset+theta)
            return solve_policy(build(TwoCell(*updated), rect)).values

        audits = directional_audit(coordinate_value, sensitivity.fixed)
        entries.append({'direction': f'coordinate_reset_{axis+1}', **audits,
                        'tied_states': sensitivity.tie_states,
                        'tangent_left_right_gap': sensitivity.kink_norm,
                        'base_qvi_residual': optimum.qvi_residual})
    return entries


def audit_exact_kink():
    """A zero-reward base with a positive-only incentive to repeatedly FIRE1."""
    from ..hcsn_hx_unified_v3.coupled_qvi import Rectangle, TwoCell
    from ..hcsn_hx_unified_v3.stopping import Stop
    from .oracle import build, solve_policy
    from .oracle_gradients import direction, one_sided_gradients

    cells = TwoCell(Stop(.1, .6, .3, .2, -.7, .6),
                    Stop(-.1, .8, .3, .4, -.55, .85))
    rect = Rectangle(-2., 3., 9, -2., 3., 9)
    shape = (11, 11)
    zeros, ones = np.zeros(shape), np.ones(shape)

    def make(theta):
        return build(cells, rect, running=zeros, impulse1=theta*ones, impulse2=zeros)

    model = make(0.)
    optimum = solve_policy(model)
    derivatives = one_sided_gradients(model, optimum, direction(model, impulse1=ones))
    ratio = 1/(1+cells.first.discount*cells.first.refractory/2)
    exact = np.full(shape, 1/(1-ratio**2))
    exact[9, :] *= ratio
    exact[10, :] *= ratio**2
    step = 1e-4
    fd_right = solve_policy(make(step)).values/step
    fd_left = -solve_policy(make(-step)).values/step
    central_audit = directional_audit(lambda theta: solve_policy(make(theta)).values,
                                     derivatives.fixed, step=step)
    return {
        'right_vs_analytic_error': float(np.max(np.abs(derivatives.right-exact))),
        'left_vs_analytic_error': float(np.max(np.abs(derivatives.left))),
        'right_vs_one_sided_fd_error': float(np.max(np.abs(derivatives.right-fd_right))),
        'left_vs_one_sided_fd_error': float(np.max(np.abs(derivatives.left-fd_left))),
        'tied_states': derivatives.tie_states,
        'kink_norm': derivatives.kink_norm,
        'ordinary_derivative_audit': central_audit,
        'expected': 'Right derivative follows repeated reward; left is zero; ordinary derivative denied',
    }


def main():
    import argparse
    import hashlib
    import json
    import pathlib
    import sys
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    entries, kink = audit_oracle_directions(), audit_exact_kink()
    receipt = {'python': sys.version, 'directions': entries, 'exact_kink': kink,
               'scope': 'Finite CTMC, bounded cases, independent reoptimization and exact kink fixture',
               'wall_seconds': time.perf_counter()-started,
               'all_smooth_directions_passed': all(item['passed'] for item in entries)}
    receipt['kink_error_tolerance'] = 1e-7
    receipt['accepted'] = bool(receipt['all_smooth_directions_passed'] and
        max(kink[key] for key in ('right_vs_analytic_error', 'left_vs_analytic_error',
            'right_vs_one_sided_fd_error', 'left_vs_one_sided_fd_error')) < 1e-7
        and kink['kink_norm'] > 1e-4 and not kink['ordinary_derivative_audit']['passed'])
    files = ('oracle.py', 'oracle_gradients.py', 'gradient_audit.py')
    receipt['source_sha256'] = {name: hashlib.sha256(
        pathlib.Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files}
    (args.output/'oracle_gradients.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'smooth_directions': len(entries),
                      'all_smooth_directions_passed': receipt['all_smooth_directions_passed'],
                      'max_derivative_error': max(v['max_derivative_error'] for v in entries),
                      'kink_right_error': kink['right_vs_analytic_error'],
                      'kink_ordinary_derivative_denied': not kink['ordinary_derivative_audit']['passed']}))
    if not receipt['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
