"""Learned continuation for existing shared recurrence, not a new NDU subject.

Finite correctness-minus-transition-cost profile only. The critic learns on
training traces; inference sees only the current recurrent state and logits.
No tool effect, heldout label, future hidden state or production grant enters
its execution API. Stopped rows leave the actual recurrent microbatch.
"""

from dataclasses import dataclass
import hashlib
import json
import math

import torch
from torch import nn

from development_ablation import PhaseClock, RecurrentClassifier, labels_checked
from development_tensors import checked_tensor, parameter_digest


def check_request(model, tokens, horizon):
    if (type(model) is not RecurrentClassifier or type(horizon) is not int
            or not 1 <= horizon <= model.recurrence.maximum_depth):
        raise ValueError("bounded existing recurrent model required")
    checked_tensor(tokens, 3, "observed tokens")
    if (not 1 <= len(tokens) <= 32 or not 1 <= tokens.shape[1] <= 1024
            or tokens.shape[2] != model.recurrence.width
            or tokens.dtype != model.output.weight.dtype
            or model.output.weight.device.type != 'cpu'):
        raise ValueError("incompatible recurrent input")


def current_features(state, logits):
    # No next-depth output or terminal truth is available here.
    return torch.cat((state.detach().double(), logits.detach().double().softmax(-1),
                      torch.ones(len(state), 1, dtype=torch.float64)), dim=1)


@dataclass(frozen=True)
class TrainingTrace:
    states: torch.Tensor
    logits: torch.Tensor
    model_digest: str
    cost: dict


@torch.no_grad()
def collect_training_trace(model, tokens, *, horizon):
    check_request(model, tokens, horizon)
    clock = PhaseClock()
    state = torch.zeros(len(tokens), tokens.shape[-1], dtype=tokens.dtype)
    mask = torch.ones(tokens.shape[:2], dtype=torch.bool)
    states, logits = [], []
    for _ in range(horizon):
        state, _ = model.recurrence(tokens, mask, state, depth=1)
        states.append(state.clone())
        logits.append(model.output(state).clone())
    return TrainingTrace(torch.stack(states, 1), torch.stack(logits, 1), parameter_digest(model),
                         {**clock.finish(), "cell_transitions": len(tokens)*horizon})


class ContinuationCritic(nn.Module):
    """Separate linear conditional-advantage fit at each nonterminal depth.

    Advantages are projected to [-1,1], not confidence intervals. They are fitted
    estimates, not a proof of optimal stopping. Plain Python is not a trust boundary.
    """

    def __init__(self, weights, model_digest, unit_cost):
        super().__init__()
        checked_tensor(weights, 2, 'critic coefficients')
        if (weights.dtype != torch.float64 or not 1 <= len(weights) <= 31
                or type(model_digest) is not str or len(model_digest) != 64
                or any(c not in '0123456789abcdef' for c in model_digest)
                or type(unit_cost) not in (int, float) or not math.isfinite(unit_cost)
                or not 0 <= unit_cost <= 1):
            raise ValueError('invalid continuation profile')
        self.register_buffer('weights', weights.detach().clone())
        self.model_digest, self.unit_cost = model_digest, unit_cost
        self.horizon = len(weights) + 1

    def forward(self, state, logits, *, depth):
        if type(depth) is not int or not 1 <= depth < self.horizon:
            raise ValueError('invalid continuation depth')
        features = current_features(state, logits)
        if features.shape[1] != self.weights.shape[1]:
            raise ValueError('critic feature width mismatch')
        values = features @ self.weights[depth-1]
        if not torch.isfinite(values).all():
            raise ValueError('nonfinite continuation estimate')
        return values.clamp(-1, 1)

    def identity(self):
        raw = json.dumps({'parameters': parameter_digest(self), 'model': self.model_digest,
                          'horizon': self.horizon, 'unit_cost': self.unit_cost,
                          'profile': 'correctness_minus_transition_cost'}, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()


def fit_continuation(trace, labels, *, unit_cost, ridge=0.01):
    """Backward fitted policy evaluation on TRAIN traces only.

    V_D = observed terminal correctness. At d, regress V_(d+1)-cost-correct_d
    onto current features, then use the fitted action to select the training
    return for the preceding depth. This estimates a bounded policy, not a
    pathwise hindsight oracle. No validation/test rows may fit coefficients.
    """
    if (type(trace) is not TrainingTrace or type(unit_cost) not in (int, float)
            or not math.isfinite(unit_cost) or not 0 <= unit_cost <= 1
            or type(ridge) not in (int, float) or not math.isfinite(ridge) or not 0 < ridge <= 1):
        raise ValueError('invalid training profile')
    checked_tensor(trace.states, 3, 'training states')
    checked_tensor(trace.logits, 3, 'training logits')
    n, horizon, width = trace.states.shape
    if (not 1 <= n <= 4096 or not 2 <= horizon <= 32 or not 1 <= width <= 512
            or trace.logits.shape[:2] != (n, horizon) or not 2 <= trace.logits.shape[-1] <= 128):
        raise ValueError('invalid trace shapes')
    labels_checked(labels, n, trace.logits.shape[-1])
    clock = PhaseClock()
    correct = (trace.logits.argmax(-1) == labels[:, None]).double().detach()
    future = correct[:, -1].clone()
    weights, losses = [], []
    for d in reversed(range(horizon-1)):
        features = current_features(trace.states[:, d], trace.logits[:, d])
        target = future - unit_cost - correct[:, d]
        matrix = features.T @ features + ridge * torch.eye(features.shape[1], dtype=torch.float64)
        weight = torch.linalg.solve(matrix, features.T @ target)
        if not torch.isfinite(weight).all():
            raise ValueError('invalid fitted critic')
        estimate = (features @ weight).clamp(-1, 1)
        losses.append(float(((estimate-target)**2).mean()))
        future = torch.where(estimate > 0, future-unit_cost, correct[:, d])
        weights.append(weight)
    critic = ContinuationCritic(torch.stack(list(reversed(weights))), trace.model_digest, unit_cost)
    return critic, {**clock.finish(), 'training_examples': n, 'fits': horizon-1,
                    'training_mse_by_depth': list(reversed(losses)), 'critic_identity': critic.identity(),
                    'training_trace_work': trace.cost, 'production_authorized': False}


@torch.no_grad()
def run_stopping(model, tokens, *, horizon, mode, threshold=0.0, critic=None):
    """Fixed, confidence and learned arms pay their OWN actual recurrent work.

    Full model-identity checking is deliberately inside timing, even though a
    future immutable product owner could amortize it. No partial computation
    is reported as success on failure; this is a side-effect-free research run.
    """
    clock = PhaseClock()
    check_request(model, tokens, horizon)
    if (mode not in ('fixed', 'confidence', 'learned') or type(threshold) not in (int, float)
            or not math.isfinite(threshold) or not -1 <= threshold <= 1):
        raise ValueError('invalid stopping control')
    if mode == 'learned':
        if (type(critic) is not ContinuationCritic or critic.horizon != horizon
                or critic.model_digest != parameter_digest(model)
                or critic.weights.shape[1] != model.recurrence.width + model.output.out_features + 1):
            raise ValueError('stale or incompatible critic')
    elif critic is not None or (mode == 'confidence' and threshold < 0):
        raise ValueError('unexpected critic or invalid confidence')
    state = torch.zeros(len(tokens), tokens.shape[-1], dtype=tokens.dtype)
    output = torch.empty(len(tokens), model.output.out_features, dtype=tokens.dtype)
    active = torch.arange(len(tokens))
    depths = torch.zeros(len(tokens), dtype=torch.long)
    executions, critic_rows = [], 0
    for depth in range(1, horizon+1):
        executions.append(tuple(active.tolist()))
        part = tokens[active]
        state_new, _ = model.recurrence(part, torch.ones(part.shape[:2], dtype=torch.bool), state[active], depth=1)
        logits = model.output(state_new)
        if not torch.isfinite(logits).all():
            raise ValueError('nonfinite recurrent output')
        state[active], output[active], depths[active] = state_new, logits, depth
        if depth == horizon:
            break
        if mode == 'learned':
            keep = critic(state_new, logits, depth=depth) > threshold
            critic_rows += len(active)
        elif mode == 'confidence':
            keep = logits.softmax(-1).max(-1).values < threshold
        else:
            keep = torch.ones(len(active), dtype=torch.bool)
        active = active[keep]
        if len(active) == 0:
            break
    return {'logits': output.clone(), 'depths': depths.clone(), 'executed_rows_by_depth': tuple(executions),
            'cell_transitions': sum(map(len, executions)), 'critic_rows': critic_rows,
            **clock.finish(), 'production_authorized': False}
