"""One full-HX-parameterized finite regenerative content model.

The matrix exponential is exact for this finite CTMC, not for the original
continuous first-passage process. Recovery and content retention are extensions.
"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "PROTOCOL.json").read_text())
SOURCE = ROOT.parent / "calibrated_operator_r11_20261031/numerics/kernel.py"
SPEC = importlib.util.spec_from_file_location("hcsn_r11_full_hx", SOURCE)
HX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HX)
DTYPE = torch.float64


class FinancialOutputs(torch.autograd.Function):
    """First-order bridge to the existing full ten-input analytic Jacobian."""

    @staticmethod
    def forward(ctx, theta, log_distance):
        values, jacobian = HX.evaluate(
            theta.detach().cpu().numpy(), float(log_distance.detach()),
            coordinate="log_distance", mode="float64",
        )
        ctx.save_for_backward(torch.as_tensor(jacobian, dtype=theta.dtype))
        return torch.as_tensor(values, dtype=theta.dtype)

    @staticmethod
    def backward(ctx, grad_output):
        (jacobian,) = ctx.saved_tensors
        gradient = grad_output @ jacobian
        return gradient[:9], gradient[9]


def initial_raw():
    lower = np.array(PROTOCOL["physical_lower"])
    upper = np.array(PROTOCOL["physical_upper"])
    ratio = (np.array([0.25, 0.012, 1.0]) - lower) / (upper - lower)
    return torch.tensor(np.log(ratio / (1 - ratio)), dtype=DTYPE)


def physical_parameters(raw):
    lower = raw.new_tensor(PROTOCOL["physical_lower"])
    upper = raw.new_tensor(PROTOCOL["physical_upper"])
    fitted = lower + (upper - lower) * raw.sigmoid()
    theta = raw.new_tensor(PROTOCOL["baseline_financial_parameters"])
    theta = theta.index_copy(0, torch.tensor([2, 5, 6]), fitted)
    return theta


def model_terms(raw_parameters=None, n_active=8, recovery=0.35,
                retention=0.75, prices=True, theta=None):
    """Return row generator, initial joint law, and declared task payoff arrays."""
    if theta is None:
        theta = physical_parameters(raw_parameters if raw_parameters is not None
                                    else initial_raw())
    nphase, dim = n_active + 2, 2 * (n_active + 2)
    spacing = PROTOCOL["log_upper"] / n_active
    x = (torch.arange(n_active, dtype=DTYPE) + 0.5) * spacing
    boundary = FinancialOutputs.apply(theta, theta.new_tensor(0.2))[0]
    reset_x = torch.log(theta.new_tensor(PROTOCOL["reset_asset"]) / boundary)
    reset = torch.softmax(-0.5 * ((x - reset_x) / 0.1) ** 2, dim=0)
    mu = theta[0] - theta[1] - theta[2].square() / 2
    diffusion = theta[2].square() / (2 * spacing ** 2)
    up = diffusion + torch.relu(mu) / spacing
    down = diffusion + torch.relu(-mu) / spacing
    off = theta.new_zeros((dim, dim))
    for bit in range(2):
        offset = bit * nphase
        for phase in range(n_active):
            i = offset + phase
            if phase + 1 < n_active:
                off[i, i + 1] = up
            off[i, i - 1 if phase else offset + n_active] = down
        off[offset + n_active, offset + n_active + 1] = 2 / recovery
        for new_bit in range(2):
            chance = retention * float(bit == new_bit) + (1 - retention) / 2
            start = new_bit * nphase
            off[offset + n_active + 1, start:start + n_active] = (
                2 / recovery * chance * reset
            )
    q = off - torch.diag(off.sum(dim=1))
    phase_prior = torch.cat((reset, theta.new_zeros(2)))
    prior = torch.cat((phase_prior / 2, phase_prior / 2))
    result = {"Q": q, "prior": prior, "boundary": boundary,
              "theta": theta, "reset": reset, "grid": x}
    if prices:
        outputs = torch.stack([FinancialOutputs.apply(theta, z) for z in x])
        equity = torch.cat((outputs[:, 1], theta.new_zeros(2)))
        debt = outputs[:, 4]
        principal_flow = theta[8] / theta[6]
        costs = torch.cat((0.03 + 0.03 * torch.relu(principal_flow - debt)
                           / principal_flow, theta.new_full((2,), 0.06)))
        bonus = 0.05 * equity / (theta[8] + equity)
        rewards = theta.new_zeros((dim, 2))
        for bit in range(2):
            rewards[bit*nphase:(bit+1)*nphase, :] = bonus[:, None]
            rewards[bit*nphase:(bit+1)*nphase, bit] += 1
        result.update(answer_rewards=rewards, read_cost=costs.repeat(2),
                      financial_outputs=outputs)
    return result


def emission_matrix(logits=None, n_active=8):
    if logits is None:
        likelihood = torch.tensor(
            [[0.45, 0.25, 0.15, 0.07, 0.05, 0.03],
             [0.03, 0.05, 0.07, 0.15, 0.25, 0.45]], dtype=DTYPE,
        )
    else:
        likelihood = torch.softmax(logits, dim=-1)
    active = torch.cat((likelihood, likelihood.new_zeros((2, 1))), dim=1)
    recovery = likelihood.new_zeros((2, 7))
    recovery[:, 6] = 1
    return torch.cat([torch.cat((active[b].repeat(n_active, 1), recovery))
                      for b in range(2)])


def as_numpy(terms):
    return {key: value.detach().cpu().numpy() for key, value in terms.items()}


def true_model(n_active=8):
    theta = torch.tensor(PROTOCOL["baseline_financial_parameters"], dtype=DTYPE)
    with torch.no_grad():
        terms = as_numpy(model_terms(theta=theta, n_active=n_active))
        terms["emission"] = emission_matrix(n_active=n_active).numpy()
    return terms


def bayes_step(prior, transition, emission, tokens, observed):
    """Generic HMM calculation, shared by the independent causal teacher."""
    predicted = prior @ transition
    likelihood = np.where(observed[:, None], emission[:, tokens].T, 1.0)
    weighted = predicted * likelihood
    evidence = weighted.sum(axis=1, keepdims=True)
    if np.any(evidence <= 0):
        raise ValueError("Zero-probability evidence")
    return weighted / evidence
