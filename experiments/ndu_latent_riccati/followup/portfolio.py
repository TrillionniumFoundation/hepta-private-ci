"""P0/P1 research-only Cell-direction portfolio and P2 masked-logit primitives.

A *paired, previously observed calibration window* supplies the loss scenarios.
The solver is an exact optimum only on its finite allocation grid. Loss mixing
is a proxy; every claimed output effect must be re-scored on decoded raw output.
No function grants authority, signs evidence, or consumes heldout truth.
"""

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import json
import math

import numpy as np


class PortfolioRejected(ValueError):
    """Fail-closed on malformed, mismatched or unsupported candidate evidence."""


@dataclass(frozen=True)
class CellAsset:
    asset_id: str
    payload_digest: str
    protocol: str
    domain_digest: str
    scenario_losses: tuple[float, ...]
    conditional_utility_delta: float
    variable_cost: float
    fixed_activation_cost: float
    cap_ticks: int


@dataclass(frozen=True)
class Budget:
    grid: int = 4
    max_cells: int = 3
    cost_limit: float = 1.0
    cvar90_limit: float = 10.0
    risk_aversion: float = 1.0
    cvar_price: float = 0.0


def cvar90(losses):
    x = np.asarray(losses, dtype=np.float64)
    if x.ndim != 1 or x.size < 4 or not np.isfinite(x).all():
        raise PortfolioRejected('invalid CVaR scenarios')
    # Empirical upper-tail CVaR integrates exactly 10% of the probability mass.
    # Averaging ceil(0.1*n) worst values underprices tail risk when n*0.1
    # is fractional (e.g. [0]*10+[10] would incorrectly be valued at 5).
    descending = np.sort(x)[::-1]
    tail_mass = 0.1 * len(descending)
    count = math.floor(tail_mass)
    fractional = tail_mass - count
    upper_loss = float(descending[:count].sum(dtype=np.float64))
    if fractional:
        upper_loss += fractional * float(descending[count])
    return upper_loss / tail_mass


def _validate(baseline, cells, budget, calibration_digest, objective_digest):
    base = np.asarray(baseline, dtype=np.float64)
    if base.ndim != 1 or base.size < 4 or not np.isfinite(base).all() or np.min(base) < 0:
        raise PortfolioRejected('invalid, unavailable, or negative baseline losses')
    if not calibration_digest or not objective_digest:
        raise PortfolioRejected('missing calibration/objective identity')
    if not 1 <= budget.grid <= 16 or not 0 <= budget.max_cells <= 4:
        raise PortfolioRejected('unsupported allocation grid or active set')
    if (not 0 <= len(cells) <= 4 or
            (budget.grid + 1) ** len(cells) > 100000):
        raise PortfolioRejected('reference-search capacity exceeded')
    limits = (budget.cost_limit, budget.cvar90_limit,
              budget.risk_aversion, budget.cvar_price)
    if any(not math.isfinite(x) or x < 0 for x in limits):
        raise PortfolioRejected('invalid budget/risk profile')
    ids = set()
    payloads = set()
    protocol = None
    domain = None
    for c in cells:
        if not c.asset_id or not c.payload_digest or not c.protocol or not c.domain_digest:
            raise PortfolioRejected('missing Cell identity/protocol/domain')
        if c.asset_id in ids or c.payload_digest in payloads:
            raise PortfolioRejected('duplicate ID or relabelled Cell payload')
        ids.add(c.asset_id)
        payloads.add(c.payload_digest)
        if protocol is not None and c.protocol != protocol:
            raise PortfolioRejected('cross-protocol vector mixing')
        if domain is not None and c.domain_digest != domain:
            raise PortfolioRejected('cross-snapshot vector mixing')
        protocol, domain = c.protocol, c.domain_digest
        if c.protocol not in ('latent_velocity_v1', 'masked_logits_v1'):
            raise PortfolioRejected('unknown or atomic output protocol')
        if not 0 <= c.cap_ticks <= budget.grid:
            raise PortfolioRejected('invalid Cell cap')
        if any(not math.isfinite(x) or x < 0 for x in (
            c.variable_cost, c.fixed_activation_cost)):
            raise PortfolioRejected('invalid Cell cost')
        if not math.isfinite(c.conditional_utility_delta):
            raise PortfolioRejected('invalid utility estimate')
        losses = np.asarray(c.scenario_losses, dtype=np.float64)
        if losses.shape != base.shape or not np.isfinite(losses).all() or np.min(losses) < 0:
            raise PortfolioRejected('unpaired/missing semantic evidence')
    return base


def _evaluate(base, ordered, ticks, budget):
    grid = budget.grid
    allocation = np.asarray(ticks, dtype=np.float64) / grid
    w_base = 1 - sum(ticks) / grid
    mixture = w_base * base
    variable_cost = 0.0
    fixed_cost = 0.0
    expected_gain = 0.0
    for weight, cell in zip(allocation, ordered):
        mixture = mixture + weight * np.asarray(cell.scenario_losses)
        variable_cost += weight * cell.variable_cost
        if weight > 0:
            fixed_cost += cell.fixed_activation_cost  # One-time, never fractionalized.
        expected_gain += weight * cell.conditional_utility_delta
    total_cost = variable_cost + fixed_cost
    var = float(np.mean((mixture - mixture.mean()) ** 2))
    tail = cvar90(mixture)
    score = expected_gain - total_cost - .5 * budget.risk_aversion * var - budget.cvar_price * tail
    return {'score': score, 'tail': tail, 'variance': var,
            'mean_proxy_loss': float(mixture.mean()), 'cost': total_cost,
            'utility_delta': expected_gain, 'no_change_ticks': grid - sum(ticks)}


def select_shadow_portfolio(baseline_losses, assets, budget, *,
                            calibration_digest, objective_digest):
    """Exact *grid* maximum for <=4 compatible fractional Cell directions.

    Scenario losses are paired external calibration measurements, not claims that
    latent-space mixtures preserve scalar losses. A generated-output evaluator
    must independently verify the selected mixture on untouched future worlds.
    """
    cells = sorted(tuple(assets), key=lambda c: c.asset_id)
    base = _validate(baseline_losses, cells, budget, calibration_digest, objective_digest)
    best = None
    for ticks in product(range(budget.grid + 1), repeat=len(cells)):
        if (sum(ticks) > budget.grid or sum(x > 0 for x in ticks) > budget.max_cells or
                any(x > c.cap_ticks for x, c in zip(ticks, cells))):
            continue
        result = _evaluate(base, cells, ticks, budget)
        if result['cost'] > budget.cost_limit + 1e-12 or result['tail'] > budget.cvar90_limit + 1e-12:
            continue
        if best is None or (result['score'] > best[0]['score'] + 1e-12) or (
            abs(result['score'] - best[0]['score']) <= 1e-12 and ticks < best[1]):
            best = result, ticks
    if best is None:
        raise PortfolioRejected('no feasible allocation, including NoChange')
    result, ticks = best
    receipt = {'schema': 'hepta-ndu-mgp-grid-shadow-v1', 'authority': 'DENY_ALL',
               'calibration_digest': calibration_digest, 'objective_digest': objective_digest,
               'protocol': cells[0].protocol if cells else 'latent_velocity_v1',
               'domain_digest': cells[0].domain_digest if cells else '',
               'grid': budget.grid,
               'allocations': [{'id': c.asset_id, 'payload_digest': c.payload_digest, 'ticks': tick}
                               for c, tick in zip(cells, ticks) if tick],
               **result}
    canonical = json.dumps(receipt, sort_keys=True, separators=(',', ':'), allow_nan=False)
    receipt['replay_digest'] = sha256(canonical.encode()).hexdigest()
    return receipt



def empirical_grid_frontier(baseline_losses, assets, budget, *,
                            calibration_digest, objective_digest, max_points=256):
    """All nondominated feasible *grid-proxy* points, never a global latent frontier.

    A point dominates another when it has at least as much utility and no
    greater variance, CVaR90 or physical cost, with one strict improvement.
    This is a finite shadow report, not a stochastic-control certificate.
    """
    if not 1 <= max_points <= 1024:
        raise PortfolioRejected('invalid frontier bound')
    cells = sorted(tuple(assets), key=lambda c: c.asset_id)
    base = _validate(baseline_losses, cells, budget, calibration_digest, objective_digest)
    def dominates(left, right):
        weak = (left['utility_delta'] >= right['utility_delta'] - 1e-12
                and left['variance'] <= right['variance'] + 1e-12
                and left['tail'] <= right['tail'] + 1e-12
                and left['cost'] <= right['cost'] + 1e-12)
        strict = (left['utility_delta'] > right['utility_delta'] + 1e-12
                  or left['variance'] < right['variance'] - 1e-12
                  or left['tail'] < right['tail'] - 1e-12
                  or left['cost'] < right['cost'] - 1e-12)
        return weak and strict
    frontier = []
    for ticks in product(range(budget.grid + 1), repeat=len(cells)):
        if (sum(ticks) > budget.grid or sum(x > 0 for x in ticks) > budget.max_cells or
                any(x > c.cap_ticks for x, c in zip(ticks, cells))):
            continue
        row = _evaluate(base, cells, ticks, budget)
        if row['cost'] > budget.cost_limit + 1e-12 or row['tail'] > budget.cvar90_limit + 1e-12:
            continue
        point = {'ticks': tuple(ticks), **row}
        if any(dominates(previous, point) for previous in frontier):
            continue
        frontier = [previous for previous in frontier if not dominates(point, previous)]
        frontier.append(point)
        if len(frontier) > max_points:
            raise PortfolioRejected('frontier capacity exceeded; do not silently truncate')
    frontier.sort(key=lambda p: (p['variance'], p['tail'], -p['utility_delta'], p['cost'], p['ticks']))
    return frontier


def verify_shadow_receipt(receipt, baseline_losses, assets, budget, *,
                          calibration_digest, objective_digest):
    expected = select_shadow_portfolio(baseline_losses, assets, budget,
                                      calibration_digest=calibration_digest,
                                      objective_digest=objective_digest)
    if receipt != expected:
        raise PortfolioRejected('receipt replay mismatch')
    return True


def continuous_direction_step(flow, z, context, t, dt, cell_heads, weights):
    """Differentiable Euler step. Weights must have been independently admitted.

    Cell heads consume only current state/context; no hidden truth or output labels.
    Base flow runs even when all Cell weights are zero. No high-dimensional tensor
    is passed through native fixed-Q24 NDU receipts.
    """
    import torch
    if not 0 < dt <= 1 or len(cell_heads) != len(weights):
        raise PortfolioRejected('invalid flow step')
    if len(z.shape) != 2 or len(context) != len(z):
        raise PortfolioRejected('invalid state/context')
    if not all(math.isfinite(float(w)) and 0 <= float(w) <= 1 for w in weights):
        raise PortfolioRejected('invalid fractional weights')
    if sum(float(w) for w in weights) > 1 + 1e-7:
        raise PortfolioRejected('overallocated Cell controls')
    velocity = flow(z, t, context)
    if velocity.shape != z.shape:
        raise PortfolioRejected('invalid base flow shape')
    for head, weight in zip(cell_heads, weights):
        direction = head(z, context)
        if direction.shape != velocity.shape or not torch.isfinite(direction).all():
            raise PortfolioRejected('invalid Cell direction')
        velocity = velocity + weight * direction
    if not torch.isfinite(velocity).all():
        raise PortfolioRejected('nonfinite combined velocity')
    return z + dt * velocity



def new_low_rank_cell_head(latent_dim=7, condition_dim=32, rank=8):
    """Zero-initialized, trainable adapter; uses one shared generative backbone.

    Returned module uses a state_dict rather than a separate full model; zero
    initialization guarantees no-change forward parity before training.
    """
    import torch
    from torch import nn
    if latent_dim < 1 or condition_dim < 1 or not 1 <= rank <= 64:
        raise PortfolioRejected('unsupported low-rank Cell shape')
    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.down = nn.Linear(latent_dim + condition_dim, rank)
            self.up = nn.Linear(rank, latent_dim, bias=False)
            nn.init.zeros_(self.up.weight)
        def forward(self, z, context):
            return self.up(self.down(torch.cat((z, context), -1)).tanh())
    return Head()


def generate_with_cells(flow, decoder, context, encoder_estimate, noise,
                        cell_heads, weight_schedule):
    """Decode actual raw outputs after a time-varying Cell-portfolio rollout.

    The encoder estimate is public inference context, never the hidden label.
    The schedule may be supplied by a shadow controller, but this function has
    no independent authorization or claims about output loss. Decoder is the
    same frozen Decoder object for all comparison arms.
    """
    import torch
    if (context.ndim != 2 or context.shape[1] != 32 or
            encoder_estimate.shape != (len(context), 6) or
            noise.shape != (len(context), 7) or not weight_schedule):
        raise PortfolioRejected('invalid shared-encoder flow initialization')
    z = torch.cat((encoder_estimate + 0.5 * noise[:, :6], noise[:, 6:]), -1)
    steps = len(weight_schedule)
    if steps > 64:
        raise PortfolioRejected('unbounded flow rollout')
    for k, weights in enumerate(weight_schedule):
        z = continuous_direction_step(flow, z, context, k / steps, 1 / steps,
                                      cell_heads, weights)
    outputs = decoder(z)
    if not isinstance(outputs, dict) or not outputs:
        raise PortfolioRejected('decoder did not emit raw output dictionary')
    if not all(torch.isfinite(value).all() for value in outputs.values()):
        raise PortfolioRejected('nonfinite decoded output')
    return {'latent': z, 'decoded': outputs, 'steps': steps}



def supervised_cell_update(flow, decoder, cell_heads, optimizer, context,
                           encoder_estimate, noise, weight_schedule,
                           targets, externally_fixed_loss):
    """P0 training-only Cell adapter update, not NDU joint training.

    The flow/decoder remain frozen, and the optimizer must contain only Cell
    weights. Ground truth enters an external training loss after the complete
    decoded forward pass; it is NEVER passed into the rollout or Cell heads.
    """
    import torch
    if any(p.requires_grad for module in (flow, decoder) for p in module.parameters()):
        raise PortfolioRejected('trainable foundation/decoder in frozen Cell-only update')
    cell_params = [p for cell in cell_heads for p in cell.parameters() if p.requires_grad]
    allowed = {id(p) for p in cell_params}
    optimizer_params = [p for group in optimizer.param_groups for p in group['params']]
    if (not allowed or len(allowed) != len(cell_params) or
            {id(p) for p in optimizer_params} != allowed or
            len(optimizer_params) != len(cell_params)):
        raise PortfolioRejected('optimizer is not exclusively bound to Cell parameters')
    optimizer.zero_grad(set_to_none=True)
    predicted = generate_with_cells(flow, decoder, context, encoder_estimate,
                                    noise, cell_heads, weight_schedule)['decoded']
    loss = externally_fixed_loss(predicted, targets)
    if not isinstance(loss, torch.Tensor) or loss.numel() != 1 or not torch.isfinite(loss).all():
        raise PortfolioRejected('nonfinite or non-scalar external training loss')
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(cell_params, max_norm=1.)
    if not torch.isfinite(norm):
        raise PortfolioRejected('nonfinite Cell training gradient')
    optimizer.step()
    return {'loss': float(loss.detach()), 'gradient_norm': float(norm.detach()),
            'updated_parameter_tensors': len(cell_params)}


def masked_logit_step(logits, deltas, weights, mask, n_unmask):
    """P2 compatibility primitive, not a trained masked Diffusion LLM.

    Continuous weights modify aligned vocabulary logits; discrete unmasking is
    a single atomic plan chosen from the resulting distribution, never a mixture
    of incompatible token plans. Already visible tokens remain unchanged.
    """
    import torch
    if logits.ndim != 3 or mask.shape != logits.shape[:2] or mask.dtype != torch.bool:
        raise PortfolioRejected('invalid logits or mask')
    if not isinstance(n_unmask, int) or n_unmask < 0:
        raise PortfolioRejected('invalid unmask count')
    if len(deltas) != len(weights) or sum(float(w) for w in weights) > 1 + 1e-7:
        raise PortfolioRejected('invalid logit allocation')
    result = logits.clone()
    for delta, weight in zip(deltas, weights):
        if delta.shape != logits.shape or not math.isfinite(float(weight)) or float(weight) < 0:
            raise PortfolioRejected('unaligned logit asset')
        result = result + weight * delta
    if not torch.isfinite(result).all():
        raise PortfolioRejected('invalid combined logits')
    confidence, tokens = result.softmax(-1).max(-1)
    selected = torch.zeros_like(mask)
    for b in range(len(mask)):
        allowed = torch.nonzero(mask[b], as_tuple=False).flatten().tolist()
        selected_positions = sorted(allowed, key=lambda i: (-float(confidence[b, i]), i))[:n_unmask]
        selected[b, selected_positions] = True
    return tokens, selected
