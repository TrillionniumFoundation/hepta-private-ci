"""Opt-in preparation of the exact addressed model's consumed CTMC tensors.

This adapter fuses the two dense exponentials, vectorizes last-observed policy
indices, and omits two value solves that AddressedModel never consumes. It is
only an audit context: the original numerical backend and model stay unchanged.
"""

from contextlib import contextmanager
from unittest.mock import patch

import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2.distribution_kernel import (
    Grid, initial_probability, make_flow, remap_operator)
from experiments.hcsn_four_stage_flow_20261031.marked_flow import assemble
from experiments.hcsn_four_stage_flow_20261031.models import ContentModel, STATES


def prepare(model, encoded, dt, observed):
    """Return P/T/remap/initial, the complete addressed-model dependency set."""
    batch, steps = dt.shape
    control = model.control(encoded).double()
    control = F.pad(control, (0, 0, 1, 0))
    indices = torch.arange(1, steps + 1, device=dt.device)
    after_index = torch.where(observed, indices, 0).cummax(1).values
    before_index = F.pad(after_index[:, :-1], (1, 0))
    rows = torch.arange(batch, device=dt.device)[:, None]
    before, after = control[rows, before_index], control[rows, after_index]
    physical = model.physical.double()
    sigma = .15 + .4 * torch.sigmoid(physical[0])
    tau = .15 + .7 * torch.sigmoid(physical[1])
    eta = torch.sigmoid(physical[3])
    decay = .05 * torch.sigmoid(physical[4])
    if model.intervention == "no_marks":
        eta = eta * 0 + 1
    boundary = .6 + .8 * torch.sigmoid(before[..., 0])
    mu = .05 + .9 * torch.sigmoid(before[..., 1] + physical[2])
    grid = Grid(cells=4, lower=-1.5, refractory_stages=1)
    flow = make_flow(mu, sigma, boundary, -.5, tau, grid)
    matrices = assemble(flow)
    q, r = matrices["Q"], matrices["R"]
    content_q = q - (1 - eta) * r - decay * torch.eye(
        STATES, dtype=q.dtype, device=q.device)
    # Same dense matrix exponential, same precision, same generators. No
    # truncation, normalization, rounding repair, or alternate physics.
    scaled = torch.cat((q, content_q), 0) * dt.double().repeat(2, 1)[..., None, None]
    probability_transition, content_transition = torch.matrix_exp(scaled).split(batch, 0)
    new_flow = make_flow(mu, sigma, .6 + .8 * torch.sigmoid(after[..., 0]), -.5, tau, grid)
    remap = remap_operator(boundary, new_flow)
    destination = F.one_hot(torch.tensor(4, device=q.device), STATES).double()
    event_map = remap["event_vector"][..., :, None] * destination
    content_remap = remap["transition"] - (1 - eta) * event_map
    initial_flow = make_flow(mu[:, 0], sigma, boundary[:, 0], -.5, tau, grid)
    return dict(P=probability_transition.float(), T=content_transition.float(),
                R=remap["transition"].float(), MR=content_remap.float(),
                initial=initial_probability(initial_flow, -.5).float())


@contextmanager
def addressed_only():
    """Use solely around AddressedModel calls in an isolated audit process.

    ContentModel itself also consumes J/G/b and must not use this adapter.
    The context restores the method even when a call raises an exception.
    """
    with patch.object(ContentModel, "_flow_matrices", prepare):
        yield
