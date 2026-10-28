"""Independent expected-gradient oracle for conditional image LAX + text LR."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from ..unified_20261028.gradient_oracle import check_actual_generator
from .fullpath_lax import surrogate


SIGMA = .7


def delivered_loss(image_bit, text_bit, gamma):
    utility = .05 + .4 * image_bit + .3 * text_bit + .2 * image_bit * text_bit
    actual_cost = .03 + .13 * (image_bit != text_bit)
    value = utility - actual_cost
    return -value if gamma == 0 else math.expm1(-gamma * value) / gamma


def analytic(theta, gamma):
    mu, eta = theta[0] + .3 * theta[1], theta[1] - .2 * theta[0]
    p = 1 / (1 + math.exp(-eta))
    q = .5 * math.erfc(-mu / (SIGMA * math.sqrt(2)))
    normal_derivative = math.exp(-.5 * (mu / SIGMA) ** 2) / (SIGMA * math.sqrt(2 * math.pi))
    losses = [[delivered_loss(i, t, gamma) for t in (0, 1)] for i in (0, 1)]
    value = sum((p if t else 1 - p) * ((1 - q) * losses[0][t] + q * losses[1][t]) for t in (0, 1))
    image_derivative = normal_derivative * sum((p if t else 1 - p) * (losses[1][t] - losses[0][t]) for t in (0, 1))
    text_derivative = p * (1 - p) * ((1 - q) * (losses[0][1] - losses[0][0]) + q * (losses[1][1] - losses[1][0]))
    return value, np.asarray([image_derivative - .2 * text_derivative, .3 * image_derivative + text_derivative])


def integrated_actual_surrogate(theta_value, gamma, negative=None):
    theta = torch.tensor(theta_value, dtype=torch.float64, requires_grad=True)
    mu, eta = theta[0] + .3 * theta[1], theta[1] - .2 * theta[0]
    mu_value, p = float(mu.detach()), float(eta.detach().sigmoid())
    abscissa, quadrature = np.polynomial.legendre.leggauss(96)
    objective = theta.sum() * 0
    probability_mass = 0.0
    # Split at the actual hard codec threshold. Smooth integrands on each
    # interval integrate independently of the production score implementation.
    for lower, upper in ((mu_value - 12 * SIGMA, 0.0), (0.0, mu_value + 12 * SIGMA)):
        for node, weight in zip(abscissa, quadrature):
            x = lower + (node + 1) * (upper - lower) / 2
            probability = weight * (upper - lower) / 2 * math.exp(-.5 * ((x - mu_value) / SIGMA) ** 2) / (SIGMA * math.sqrt(2 * math.pi))
            for token in (0, 1):
                joint = probability * (p if token else 1 - p)
                held = theta.new_tensor([x])
                path = mu + (held - mu).detach()
                proxy = lambda z: .2 + .1 * token + (.3 - .2 * token) * z + (.4 + .1 * token) * z.square()
                actual = theta.new_tensor([delivered_loss(x > 0, token, gamma)])
                image_baseline = theta.new_tensor([delivered_loss(mu_value > 0, token, gamma)])
                text_baseline = theta.new_tensor([delivered_loss(x > 0, p >= .5, gamma)])
                image_lp = torch.distributions.Normal(mu, SIGMA).log_prob(held)
                text_lp = torch.nn.functional.logsigmoid(eta if token else -eta).reshape(1)
                c_sample = proxy(path)
                if negative == "omit_pathwise":
                    c_sample = c_sample.detach()
                if negative == "self_image_baseline":
                    image_baseline = actual
                objective = objective + joint * surrogate(actual, image_baseline, text_baseline,
                    c_sample, proxy(mu).reshape(1), image_lp, text_lp)
                probability_mass += joint
    got = torch.autograd.grad(objective, theta)[0].detach().numpy()
    if abs(probability_mass - 1) > 2e-12:
        raise AssertionError("Independent Gaussian integration lost probability mass")
    return got


def run(output):
    torch.set_num_threads(1)
    cases = []
    for theta in ((.17, -.4), (-.4, .3)):
        for gamma in (0.0, 2.0):
            _, exact = analytic(theta, gamma)
            actual = integrated_actual_surrogate(theta, gamma)
            finite = []
            for index in (0, 1):
                left, right = list(theta), list(theta)
                left[index] -= 1e-5; right[index] += 1e-5
                finite.append((analytic(right, gamma)[0] - analytic(left, gamma)[0]) / 2e-5)
            if max(abs(actual - exact)) > 2e-10 or max(abs(np.asarray(finite) - exact)) > 2e-9:
                raise AssertionError("Actual LAX/autograd estimator differs from exact delivered-outcome gradient")
            missing = integrated_actual_surrogate(theta, gamma, "omit_pathwise")
            self_baseline = integrated_actual_surrogate(theta, gamma, "self_image_baseline")
            if max(abs(missing - exact)) < .01 or max(abs(self_baseline - exact)) < .01:
                raise AssertionError("Negative controls do not detect the intended estimator errors")
            cases.append({"theta": theta, "gamma": gamma, "exact_gradient": exact.tolist(),
                          "integrated_actual_surrogate_gradient": actual.tolist(), "finite_difference": finite,
                          "max_absolute_error": float(max(abs(actual - exact))),
                          "missing_pathwise_error": float(max(abs(missing - exact))),
                          "self_dependent_image_baseline_error": float(max(abs(self_baseline - exact)))})
    density = check_actual_generator("experiments.multimodal_output_portfolio.closure_20261028.fullpath_model")
    package = Path(__file__).resolve().parent
    report = {"schema": "hepta.ndu.conditional-lax-independent-oracle.v1", "passed": True,
              "torch_version": torch.__version__, "joint_step_codec_cases": cases,
              "actual_production_density_and_parameter_gradients": density,
              "source_sha256": {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                                for name in ("fullpath_model.py", "fullpath_lax.py", "fullpath_oracle.py")},
              "scope": "independent mathematical/production primitive check; not capability, optimization or runtime-cost evidence",
              "reference": "https://arxiv.org/abs/1711.00123"}
    with Path(output).open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "max_LAX_error": max(row["max_absolute_error"] for row in cases),
                      "production_density_checked": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
