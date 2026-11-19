"""Independent complete-state checks with changing delay, reset and rewards."""

from fractions import Fraction as F
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch

from .differentiable import Physics, Work, advance, initial, intervene, refractory
from .reference_timevarying import Law, solve

ENDS = (F(13, 100), F(36, 100), F(81, 100))
DELAYS = (F(23, 100), F(7, 100), F(19, 100))
torch.set_num_threads(1)


def tensor_laws(theta):
    laws = []
    for j, (end, delay) in enumerate(zip(ENDS, DELAYS)):
        a, b = theta[0] * (1 + .2*j), theta[1] * (1.2 - .15*j)
        lower = torch.stack((theta[2]*(1 - .2*j), theta[3]*(1 + .3*j)))
        upper = theta.new_tensor([.05 + .01*j, .08 - .01*j])
        q = torch.stack((torch.stack((-a-lower[0]-upper[0], a)),
                         torch.stack((b, -b-lower[1]-upper[1]))))
        reset = torch.sigmoid(theta[4] + .4*j)
        p = Physics(q, lower, upper, torch.stack((reset, 1-reset)),
                    torch.stack((theta[5]+.05*j, theta[6]-.07*j)),
                    theta[7]+.1*j, theta[8]*(1-.1*j), theta[9]*(1., 2., .4)[j], delay)
        laws.append((end, p))
    active = torch.stack((theta.new_tensor([.6, .4]), theta[10:12],
                          theta.new_tensor([.3, -.8])))
    return laws, active


def numerical_laws(theta):
    laws = []
    for j, (end, delay) in enumerate(zip(ENDS, DELAYS)):
        a, b = theta[0]*(1+.2*j), theta[1]*(1.2-.15*j)
        lo = np.array([theta[2]*(1-.2*j), theta[3]*(1+.3*j)])
        hi = np.array([.05+.01*j, .08-.01*j])
        q = np.array([[-a-lo[0]-hi[0], a], [b, -b-lo[1]-hi[1]]])
        reset = 1/(1+math.exp(-theta[4]-.4*j))
        laws.append(Law(end, delay, q, lo, hi, np.array([reset, 1-reset]),
                        np.array([theta[5]+.05*j, theta[6]-.07*j]), theta[7]+.1*j,
                        theta[8]*(1-.1*j), theta[9]*(1., 2., .4)[j]))
    return laws, np.array([[.6, .4], theta[10:12], [.3, -.8]])


def fields(state, work=None):
    row = torch.cat((state.active, state.upper[:, None], state.hits[:, None],
                     state.occupation[:, None], state.discounted_hits[:, None],
                     state.value[:, None]), dim=1)
    return torch.cat((row.flatten(), refractory(state, work), state.discount_factor.reshape(1)))


def reference(theta, **kwargs):
    laws, active = numerical_laws(theta)
    result = solve(laws, active, **kwargs)
    return np.r_[result["state"].ravel(), result["waiting"], result["discount_factor"]], result


def candidate(theta):
    laws, active = tensor_laws(theta)
    work, state = Work(), initial(active)
    for end, physics in laws:
        state = advance(state, physics, end, work)
    return state, work


def scalar_sweep():
    """Elementary integrals include a swept atom and a zero-discount epoch."""
    ends, rates, rhos = (.17, .43, .61), (2., 4., 1.), (0., .35, .09)
    rewards, costs = (.4, -.2, .7), (.8, -.3, .6)
    fraction = torch.tensor(.25, dtype=torch.float64, requires_grad=True)
    state = initial(torch.tensor([[1.], [-.7], [.3]], dtype=torch.float64))
    amplitude, discount, hit, occupation, discounted_hit, value = 1., 1., 0., 0., 0., 0.
    left = 0.
    for j, end in enumerate(ends):
        scalar = lambda x: torch.tensor(x, dtype=torch.float64)
        p = Physics(scalar([[-rates[j]]]), scalar([rates[j]]), scalar([0.]),
                    scalar([1.]), scalar([rewards[j]]), scalar(0.),
                    scalar(costs[j]), scalar(rhos[j]), F(2))
        if j == 1:
            state = intervene(state, p, fraction.reshape(1))
            swept = amplitude*float(fraction.detach())
            hit += swept
            discounted_hit += discount*swept
            value += discount*costs[j]*swept
            amplitude -= swept
        duration = end-left
        ordinary = -math.expm1(-rates[j]*duration)/rates[j]
        discounted = -math.expm1(-(rates[j]+rhos[j])*duration)/(rates[j]+rhos[j])
        hit += amplitude*(-math.expm1(-rates[j]*duration))
        occupation += amplitude*ordinary
        discounted_hit += discount*amplitude*rates[j]*discounted
        value += discount*amplitude*(rewards[j]+costs[j]*rates[j])*discounted
        amplitude *= math.exp(-rates[j]*duration)
        discount *= math.exp(-rhos[j]*duration)
        state = advance(state, p, F(str(end)))
        left = end
    row = np.array([amplitude, 0., hit, occupation, discounted_hit, value])
    expected = np.r_[(np.array([1., -.7, .3])[:, None]*row).ravel(),
                     np.array([1., -.7, .3])*hit, discount]
    error = float(np.max(np.abs(fields(state).detach().numpy()-expected)))
    observed, = torch.autograd.grad(state.active[0, 0], (fraction,))
    expected_gradient = -math.exp(-sum(r*(right-left) for r, left, right in
                                      zip(rates, (0., *ends[:-1]), ends)))
    gradient_error = abs(float(observed)-expected_gradient)
    if error > 2e-12 or gradient_error > 2e-12:
        raise AssertionError("piecewise scalar/sweep closed-form disagreement")
    return {"full_field_max_error": error, "swept_fraction_gradient_error": gradient_error,
            "zero_discount_epoch": True, "signed_reward_epochs": True}


def cold(input_path, output_path):
    record = torch.load(input_path, weights_only=False)
    state = record["state"]
    for end, physics in record["continuation"]:
        state = advance(state, physics, end)
    with output_path.open("xb") as stream:
        torch.save({"fields": fields(state).detach(), "state": state}, stream)


def main(output):
    started = time.perf_counter()
    theta = torch.tensor([.7, .3, .6, .2, -.2, .4, .7, .5, .8, .15, -.3, .8],
                         dtype=torch.float64, requires_grad=True)
    raw = theta.detach().numpy()
    report = {"schema": "hcsn-timevarying-complete-state-check-v1", "scalar_sweep": scalar_sweep()}
    state, work = candidate(theta)
    observed = fields(state, work)
    expected, oracle = reference(raw)
    tighter, tight_oracle = reference(raw, rtol=2e-12, atol=2e-14)
    error = float(np.max(np.abs(observed.detach().numpy()-tighter)))
    refinement = float(np.max(np.abs(expected-tighter)))
    if error > 3e-9 or refinement > 3e-10:
        raise AssertionError("event-time delayed ODE or refinement disagreement")
    laws, active = tensor_laws(theta)
    balance = state.active.sum(1)+state.upper+refractory(state)-active.sum(1)
    if float(balance.detach().abs().max()) > 2e-11:
        raise AssertionError("probability or signed-content balance")
    report["changing_laws"] = {"full_field_max_error": error,
        "oracle_refinement_max_difference": refinement,
        "balance_max_error": float(balance.detach().abs().max()),
        "oracle_segments": oracle["segments"], "oracle_rhs_evaluations": oracle["rhs_evaluations"],
        "tighter_rhs_evaluations": tight_oracle["rhs_evaluations"],
        "tensor_exponential_actions": work.exponentials,
        "largest_matrix_order": work.largest_dimension, "complete_state_bytes": state.tensor_bytes(),
        "overlapping_return_window": [.23, .36]}
    weights = np.linspace(-.4, .9, len(expected))
    gradient, = torch.autograd.grad(observed @ theta.new_tensor(weights), (theta,))
    differences = []
    for i in range(len(raw)):
        plus, minus = raw.copy(), raw.copy()
        plus[i] += 1e-6
        minus[i] -= 1e-6
        plus_value, _ = reference(plus, rtol=2e-12, atol=2e-14)
        minus_value, _ = reference(minus, rtol=2e-12, atol=2e-14)
        differences.append(float(weights @ (plus_value-minus_value)/(2e-6)))
    gradient_error = float(np.max(np.abs(gradient.detach().numpy()-differences)))
    if gradient_error > 3e-7:
        raise AssertionError("twelve-parameter independent-ODE gradient disagreement")
    report["gradients"] = {"tensor_ad": gradient.detach().tolist(), "independent_ode_fd": differences,
                           "maximum_absolute_error": gradient_error, "epsilon": 1e-6,
                           "delay_schedule_differentiated": False}
    intermediate = advance(initial(active), laws[0][1], ENDS[0])
    intermediate = advance(intermediate, laws[1][1], F(29, 100))
    with (output/"COLD_INPUT.pt").open("xb") as stream:
        torch.save({"state": intermediate, "continuation": laws[1:]}, stream)
    result = subprocess.run([sys.executable, "-m", __spec__.name, "--cold",
                             str(output/"COLD_INPUT.pt"), str(output/"COLD_OUTPUT.pt")],
                            capture_output=True, timeout=30, check=False)
    (output/"cold.stdout").write_bytes(result.stdout)
    (output/"cold.stderr").write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError("fresh-process continuation failed")
    restored = torch.load(output/"COLD_OUTPUT.pt", weights_only=False)
    cold_error = float((restored["fields"]-observed.detach()).abs().max())
    if cold_error > 3e-11:
        raise AssertionError("fresh-process variable-law continuation disagreement")
    report["cold_continuation"] = {"maximum_absolute_error": cold_error,
                                  "past_autograd_restored": False, "child_exit_code": result.returncode}
    with (output/"RAW.npz").open("xb") as stream:
        np.savez(stream, theta=raw, candidate=observed.detach().numpy(),
                 oracle=expected, tighter_oracle=tighter, gradient=gradient.detach().numpy(),
                 finite_difference=np.array(differences), cold=restored["fields"].numpy())
    report.update(all_declared_checks_pass=True, model_training_calls=0,
                  old_c2_and_n256_gates_changed=False, body_wall_seconds=time.perf_counter()-started)
    with (output/"RESULT.json").open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--cold":
        cold(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main(Path(sys.argv[1]))
