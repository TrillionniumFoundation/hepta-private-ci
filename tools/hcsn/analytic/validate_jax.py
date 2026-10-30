"""Actual AD and dtype audit of the full He--Xiong JAX kernel.

python analytic/validate_jax.py; writes only jax_validation_results.json.
No existing NumPy validation evidence is changed by this script.
"""

from dataclasses import replace, asdict
from pathlib import Path
import hashlib
import json
import math
import platform
import time

import numpy as np
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp

if __package__:
    from . import jax_hx as kernel
    from .hx_model import HXModel, Parameters
    from .hx_reference import green_equity, boundary_from_quadrature
    from .run_validation import parameter_cases
else:
    import jax_hx as kernel
    from hx_model import HXModel, Parameters
    from hx_reference import green_equity, boundary_from_quadrature
    from run_validation import parameter_cases


ROOT = Path(__file__).resolve().parent


def fields_x(x, theta):
    f, g = kernel.first_hit_x(x, theta[6], theta)
    return jnp.stack([kernel.equity_x(x, theta), f, g], axis=-1)


def asset_fields(theta):
    b = kernel.boundary(theta)
    f, g = kernel.risk_asset_constant_extension(jnp.asarray(100., theta.dtype), theta[6], theta)
    return jnp.stack([b, kernel.equity_asset(jnp.asarray(100., theta.dtype), theta), f, g])


values_jit = jax.jit(fields_x)
state_jit = jax.jit(jax.vmap(jax.jacfwd(fields_x, argnums=0), in_axes=(0, None)))
parameter_jit = jax.jit(jax.jacfwd(asset_fields))
boundary_jit = jax.jit(kernel.boundary)
equity_slope = jax.jit(jax.grad(kernel.equity_x, argnums=0))
raw_slope = jax.jit(jax.grad(kernel.equity_raw_x, argnums=0))
taylor_slope = jax.jit(jax.grad(kernel.equity_taylor_x, argnums=0))


def supported_cases():
    cases, rejected = [], []
    for name, p in parameter_cases():
        try:
            kernel.validate_parameters(p)
            cases.append((name, p))
        except ValueError:
            rejected.append(name)
    cases.append(("lower_liquidity_limit", replace(Parameters(), liquidity=1e-4)))
    return cases, rejected


def reference_fields(x, model):
    f, g = model.first_hit(x, model.p.maturity)
    return np.stack([model.equity(x), f, g], axis=-1)


def check_values_and_state(dtype):
    xs = np.array([0., 1e-8, 1e-5, .001, .01, .1, .5, 1., 2.])
    derivative_xs = np.array([.001, .01, .1, 1.])
    cases, rejected = supported_cases()
    rows = []
    for name, p in cases:
        theta = jnp.asarray(kernel.validate_parameters(p), dtype=dtype)
        model = HXModel(p)
        actual = np.asarray(values_jit(jnp.asarray(xs, dtype=dtype), theta), dtype=float)
        ref = reference_fields(xs, model)
        value_error = np.max(abs(actual-ref), axis=0)
        derivatives = np.asarray(state_jit(jnp.asarray(derivative_xs, dtype=dtype), theta), dtype=float)
        h = 1e-4
        ref_derivatives = (reference_fields(derivative_xs-2*h, model)
            -8*reference_fields(derivative_xs-h, model)
            +8*reference_fields(derivative_xs+h, model)
            -reference_fields(derivative_xs+2*h, model))/(12*h)
        gradient_error = np.max(abs(derivatives-ref_derivatives)/np.maximum(1., abs(ref_derivatives)), axis=0)
        threshold = min(1e-4, 1e-3*model.s)
        at = jnp.asarray(threshold, dtype=dtype)
        join_value = float(abs(kernel.equity_taylor_x(at, theta)-kernel.equity_raw_x(at, theta)))
        join_slope = float(abs(taylor_slope(at, theta)-raw_slope(at, theta)))
        b_error = abs(float(boundary_jit(theta))-model.boundary)
        e0 = float(kernel.equity_x(jnp.asarray(0., dtype=dtype), theta))
        e1 = float(equity_slope(jnp.asarray(0., dtype=dtype), theta))
        tight_pass = bool(b_error < 5e-7 and value_error[0] < 1e-5
            and max(value_error[1:]) < 1e-9 and max(gradient_error) < 2e-5
            and abs(e0) < 1e-12 and abs(e1) < 1e-12 and join_value < 1e-6 and join_slope < 1e-5)
        rows.append(dict(name=name, parameters=asdict(p), boundary_abs_error=b_error,
                         output_names=["equity", "F", "G"], log_distances=xs.tolist(),
                         actual_values=actual.tolist(), reference_values=ref.tolist(),
                         max_abs_errors=value_error.tolist(), derivative_locations=derivative_xs.tolist(),
                         ad_state_derivatives=derivatives.tolist(), fd_state_derivatives=ref_derivatives.tolist(),
                         scaled_state_derivative_errors=gradient_error.tolist(),
                         equity_at_boundary=e0, equity_x_derivative_at_boundary=e1,
                         taylor_raw_join_value_gap=join_value, taylor_raw_join_derivative_gap=join_slope,
                         scientific_float64_tolerances_passed=tight_pass))
        print(str(dtype), name, "Eerr", value_error[0], "derivative", max(gradient_error), flush=True)
    return dict(rows=rows, rejected_original_cases=rejected,
                all_scientific_tolerances_passed=all(r["scientific_float64_tolerances_passed"] for r in rows))


def independent_asset_fields(parameters):
    model = HXModel(parameters)
    b = boundary_from_quadrature(model)
    x = math.log(100/b)
    f, g = model.first_hit(x, parameters.maturity)
    return np.array([b, green_equity(model, x, b), float(f), float(g)])


def check_parameters(dtype):
    p = Parameters()
    theta = jnp.asarray(kernel.validate_parameters(p), dtype=dtype)
    actual = np.asarray(parameter_jit(theta), dtype=float)
    reference, halving = [], []
    for name in kernel.NAMES:
        value = getattr(p, name)
        h = max(abs(value), .01)*1e-4
        def central(step):
            plus = independent_asset_fields(replace(p, **{name: value+step}))
            minus = independent_asset_fields(replace(p, **{name: value-step}))
            return (plus-minus)/(2*step)
        full, half = central(h), central(h/2)
        reference.append(half)
        halving.append(abs(full-half)/np.maximum(1., abs(half)))
    reference = np.asarray(reference).T
    error = abs(actual-reference)/np.maximum(1., abs(reference))
    return dict(parameter_names=list(kernel.NAMES), output_names=["boundary", "equity_at_V100", "F", "G"],
                automatic_jacobian=actual.tolist(), independent_fd_jacobian=reference.tolist(),
                scaled_errors=error.tolist(), maximum_scaled_error=float(error.max()),
                fd_halving_max_scaled_change=float(np.max(halving)),
                passed=bool(error.max() < 2e-6))


def check_cross_boundary():
    theta = jnp.asarray(kernel.validate_parameters(Parameters()), dtype=jnp.float64)
    b = float(boundary_jit(theta))
    equity_grad = jax.jit(jax.grad(kernel.equity_asset, argnums=0))
    risk_grad = jax.jit(jax.jacfwd(lambda v: jnp.stack(kernel.risk_asset_constant_extension(v, theta[6], theta))))
    rows = []
    for shift in [-1e-4, -1e-6, 0., 1e-6, 1e-4]:
        v = jnp.asarray(b*(1+shift), jnp.float64)
        rows.append(dict(relative_asset_shift=shift, V=float(v), E=float(kernel.equity_asset(v, theta)),
                         dE_dV=float(equity_grad(v, theta)), risk_derivatives=np.asarray(risk_grad(v)).tolist()))
    f_slope_x = float(jax.grad(lambda x: kernel.first_hit_x(x, theta[6], theta)[0])(0.))
    return dict(rows=rows, analytic_right_F_V_derivative=f_slope_x/b,
                constant_extension_left_F_V_derivative=0.,
                risk_is_C1=False, equity_boundary_derivative_passed=bool(abs(rows[2]["dE_dV"]) < 1e-12),
                note="E is the financial limited-liability extension; F/G constant extension has a real derivative jump, not a smooth-pasting put.")


def main():
    start = time.perf_counter()
    original_hash = hashlib.sha256((ROOT/"validation_results.json").read_bytes()).hexdigest()
    evidence = dict(schema="hepta.hcsn.jax_hx.v1", environment=dict(python=platform.python_version(),
                    jax=jax.__version__, numpy=np.__version__, backend=jax.default_backend()),
                    parameter_names=list(kernel.NAMES), lower_bounds=list(kernel.LOWER), upper_bounds=list(kernel.UPPER),
                    source="https://www.princeton.edu/~wxiong/papers/rollover.pdf",
                    original_validation_json_sha256=original_hash,
                    gradient_method="Unmodified JAX AD of full equations and explicitly documented local Taylor evaluation; no custom JVP/VJP")
    evidence["float64"] = check_values_and_state(jnp.float64)
    evidence["float32"] = check_values_and_state(jnp.float32)
    evidence["parameter_gradients_float64"] = check_parameters(jnp.float64)
    evidence["parameter_gradients_float32"] = check_parameters(jnp.float32)
    evidence["cross_boundary"] = check_cross_boundary()
    bad = jnp.asarray(kernel.validate_parameters(Parameters())).at[5].set(0.)
    evidence["unsupported_liquidity_returns_nan"] = bool(np.isnan(float(boundary_jit(bad)))
        and np.isnan(float(kernel.equity_asset(100., bad))))
    evidence["all_float64_checks_passed"] = bool(evidence["float64"]["all_scientific_tolerances_passed"]
        and evidence["parameter_gradients_float64"]["passed"]
        and evidence["cross_boundary"]["equity_boundary_derivative_passed"]
        and evidence["unsupported_liquidity_returns_nan"])
    evidence["elapsed_seconds_including_compilation"] = time.perf_counter()-start
    evidence["new_source_sha256"] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                    for name in ["jax_hx.py", "validate_jax.py"]}
    assert hashlib.sha256((ROOT/"validation_results.json").read_bytes()).hexdigest() == original_hash
    (ROOT/"jax_validation_results.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps({"all_float64_checks_passed": evidence["all_float64_checks_passed"],
                      "float64_parameter_error": evidence["parameter_gradients_float64"]["maximum_scaled_error"],
                      "float32_parameter_error": evidence["parameter_gradients_float32"]["maximum_scaled_error"],
                      "elapsed": evidence["elapsed_seconds_including_compilation"]}, indent=2))
    if not evidence["all_float64_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
