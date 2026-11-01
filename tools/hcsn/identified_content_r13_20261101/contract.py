"""Full financial boundary and payoffs with a smooth identifiable CTMC map."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import torch

from propagation.api import generator_torch, grid_certificate, make_grid

ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT/'PROTOCOL.json').read_text())
R12 = ROOT.parent/'unified_cell_r12_20261031'
SPEC = importlib.util.spec_from_file_location('hcsn_r12_financial_bridge', R12/'contract.py')
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)
FinancialOutputs = BRIDGE.FinancialOutputs
DTYPE = torch.float64
EDGES = make_grid(**PROTOCOL['grid'])
N_ACTIVE, DIM = len(EDGES)-1, 2*(len(EDGES)+1)


def initial_raw():
    low, high = np.array(PROTOCOL['physical_lower']), np.array(PROTOCOL['physical_upper'])
    ratio = (np.array(PROTOCOL['physical_initial'])-low)/(high-low)
    return torch.tensor(np.log(ratio/(1-ratio)), dtype=DTYPE)


def physical_parameters(raw):
    low, high = raw.new_tensor(PROTOCOL['physical_lower']), raw.new_tensor(PROTOCOL['physical_upper'])
    fitted = low+(high-low)*raw.sigmoid()
    theta = raw.new_tensor(PROTOCOL['baseline_financial_parameters'])
    return theta.index_copy(0, torch.tensor(PROTOCOL['physical_indices']), fitted)


def model_terms(raw_parameters=None, prices=True, theta=None):
    if theta is None:
        theta = physical_parameters(initial_raw() if raw_parameters is None else raw_parameters)
    boundary = FinancialOutputs.apply(theta, theta.new_tensor(.2))[0]
    reset_x = torch.log(theta.new_tensor(PROTOCOL['reset_asset'])/boundary)
    mu = theta[0]-theta[1]-theta[2].square()/2
    result = generator_torch(theta[2], mu, reset_x, EDGES,
                             PROTOCOL['recovery'], PROTOCOL['retention'])
    result.update(boundary=boundary, theta=theta)
    if prices:
        outputs = torch.stack([FinancialOutputs.apply(theta, x) for x in result['centers']])
        equity = torch.cat((outputs[:, 1], theta.new_zeros(2)))
        flow = theta[8]/theta[6]
        costs = torch.cat((.03+.03*torch.relu(flow-outputs[:, 4])/flow,
                           theta.new_full((2,), .06)))
        bonus = .05*equity/(theta[8]+equity)
        rewards = bonus.repeat(2)[:, None].repeat(1, 2)
        rewards[:N_ACTIVE+2, 0] += 1
        rewards[N_ACTIVE+2:, 1] += 1
        result.update(answer_rewards=rewards, read_cost=costs.repeat(2), financial_outputs=outputs)
    return result


def emission_matrix(logits=None, likelihood=None):
    if likelihood is None:
        likelihood = torch.softmax(logits, -1)
    likelihood = torch.as_tensor(likelihood, dtype=DTYPE)
    active = torch.cat((likelihood, likelihood.new_zeros((2, 1))), 1)
    recovery = likelihood.new_zeros((2, 7))
    recovery[:, 6] = 1
    return torch.cat([torch.cat((active[b].repeat(N_ACTIVE, 1), recovery)) for b in range(2)])


def as_numpy(terms):
    return {k: v.detach().cpu().numpy() for k, v in terms.items()}


def true_model(likelihood):
    with torch.no_grad():
        terms = as_numpy(model_terms(theta=torch.tensor(PROTOCOL['baseline_financial_parameters'], dtype=DTYPE)))
        terms['emission'] = emission_matrix(likelihood=likelihood).numpy()
    return terms


bayes_step = BRIDGE.bayes_step
