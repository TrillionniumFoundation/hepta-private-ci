"""One causal controller, complete backend freeze, and actual stopping returns."""

import hashlib
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from experiments.hcsn_validation_r12_20261031.content.models import WIDTH


READ_FEE = .0025
TIME_FEE = .0005


class ValueController(nn.Module):
    """Exactly shared weights across all eight backends in one task/fit/mode.

    Inputs are predicted class probabilities and public time/budget/price only.
    No labels, raw future frames, architecture ID, teacher state or latent state.
    """

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(10, 24), nn.Tanh(), nn.Linear(24, 2))

    def forward(self, logits, elapsed, remaining, steps_left):
        prob = logits.softmax(-1)
        if prob.shape[-1] < 3:
            prob = F.pad(prob, (0, 3 - prob.shape[-1]))
        entropy = -(prob * prob.clamp_min(1e-8).log()).sum(-1, keepdim=True)
        largest = prob.topk(2, dim=-1).values
        scalar = [elapsed / 32, remaining / 32, steps_left / 32,
                  torch.full_like(elapsed, READ_FEE),
                  torch.full_like(elapsed, TIME_FEE)]
        features = torch.cat([prob, entropy, largest[..., :1] - largest[..., 1:2],
                              torch.stack(scalar, -1)], -1)
        return self.net(features)


def all_logits(model, x, dt):
    """All causal prefixes, including a real zero-observation STOP prediction."""
    encoded = model.encoder(x, dt)
    result = model.core(encoded, dt)
    states = result[0] if isinstance(result, tuple) else result
    zero = x.new_zeros((len(x), 1, WIDTH))
    return model.readout(torch.cat((zero, states), 1))


def public_times(dt):
    elapsed = torch.cat((dt.new_zeros((len(dt), 1)), dt.cumsum(1)), 1)
    remaining = elapsed[:, -1:] - elapsed
    left = torch.arange(dt.shape[1], -1, -1, device=dt.device, dtype=dt.dtype)
    return elapsed, remaining, left.expand(len(dt), -1)


def policy_values(controller, logits, dt):
    return controller(logits, *public_times(dt))


def realized_returns(logits, values, dt, labels):
    """Exact sample-path Q-pi labels; later choices use current causal scores.

    STOP is current actual correctness. READ consumes one new frame, pays its
    fee and follows the same controller afterward. Future observations/labels
    enter evaluator targets only, never features or executed action selection.
    """
    correct = (logits.detach().argmax(-1) == labels[:, None]).to(dt.dtype)
    choose_read = values.detach()[..., 1] > values.detach()[..., 0]
    choose_read[:, -1] = False
    following = correct[:, -1]
    targets = torch.stack((correct, correct), -1)
    for t in range(dt.shape[1] - 1, -1, -1):
        continuation = following - READ_FEE - TIME_FEE * dt[:, t]
        targets[:, t, 1] = continuation
        following = torch.where(choose_read[:, t], continuation, correct[:, t])
    return targets, choose_read, following


def replay(logits, values, dt, labels):
    """Vectorized evaluator of the causal policy; not an online cost estimate."""
    targets, choose_read, _ = realized_returns(logits, values, dt, labels)
    stop_at = (~choose_read).to(torch.int64).argmax(1)
    row = torch.arange(len(dt))
    elapsed = public_times(dt)[0]
    prediction = logits[row, stop_at].argmax(-1)
    accuracy = (prediction == labels).to(dt.dtype)
    cost = READ_FEE * stop_at + TIME_FEE * elapsed[row, stop_at]
    stopped = accuracy - cost
    full_prediction = logits[:, -1].argmax(-1)
    full_accuracy = (full_prediction == labels).to(dt.dtype)
    full_cost = READ_FEE * dt.shape[1] + TIME_FEE * dt.sum(1)
    initial = (logits[:, 0].argmax(-1) == labels).to(dt.dtype)
    # This is realized sample-path hindsight gap, not conditional expected regret.
    occupied = torch.arange(logits.shape[1])[None, :] <= stop_at[:, None]
    chosen_value = torch.gather(targets, -1, choose_read.long()[..., None]).squeeze(-1)
    hindsight = (targets.max(-1).values - chosen_value).clamp_min(0)
    action_errors = (values - targets).square()
    legal = torch.ones_like(action_errors, dtype=torch.bool)
    legal[:, -1, 1] = False
    return dict(value_utility=stopped, light_utility=full_accuracy-full_cost,
                value_accuracy=accuracy, light_accuracy=full_accuracy,
                initial_stop=initial, read_count=stop_at, terminal_prediction=prediction,
                initial_selected=(stop_at == 0), actual_fee=cost,
                occupied_mse=action_errors[occupied[..., None].expand_as(legal) & legal].mean(),
                root_mse=action_errors[:, 0].mean(),
                occupied_hindsight_gap=hindsight[occupied].mean(),
                root_hindsight_gap=hindsight[:, 0].mean(),
                score_margin=values[..., 1]-values[..., 0],
                realized_margin=targets[..., 1]-targets[..., 0],
                occupied=occupied)


def online_rollout(model, controller, x, dt, labels):
    """Execute READ/STOP with a raw observation boundary and real prefix calls.

    Only active rows' paid prefixes are passed to the model. Recomputing prefixes
    is a legal, unoptimized implementation; its actual CPU is charged in full.
    """
    batch, length, _ = x.shape
    prediction = torch.zeros(batch, dtype=torch.long)
    reads = torch.zeros(batch, dtype=torch.long)
    active = torch.arange(batch)
    times = public_times(dt)
    calls, processed = 0, 0
    for t in range(length + 1):
        if len(active) == 0:
            break
        if t == 0:
            current = model.readout(x.new_zeros((len(active), WIDTH)))
        else:
            # Data acquisition occurs here and only for an already chosen READ.
            current = model(x[active, :t], dt[active, :t])
            calls += 1
            processed += len(active) * t
        score = controller(current, *(v[active, t] for v in times))
        read = (score[:, 1] > score[:, 0]) if t < length else torch.zeros(len(active), dtype=torch.bool)
        done = active[~read]
        prediction[done] = current[~read].argmax(-1)
        reads[done] = t
        active = active[read]
    actual_time = times[0][torch.arange(batch), reads]
    fee = READ_FEE * reads + TIME_FEE * actual_time
    accuracy = (prediction == labels).float()
    return dict(prediction=prediction, reads=reads, utility=accuracy-fee,
                accuracy=accuracy, fee=fee, model_calls=calls,
                processed_prefix_tokens=processed)


def model_hash(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        a = tensor.detach().cpu().contiguous().numpy()
        digest.update(name.encode()); digest.update(str((a.shape, a.dtype.str)).encode())
        digest.update(a.tobytes())
    return digest.hexdigest()
