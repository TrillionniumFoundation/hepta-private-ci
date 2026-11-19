"""Exact finite-tree feedback control, with observed-latent state binding.

Offline enumeration is paid and is exponential in the horizon. It is suitable
for this finite mechanism audit, not a scalable foundation-model controller.
The online decision matches the *current* latent to a compiled node; neither a
future innovation nor evaluator truth is an input to that decision.
"""

from dataclasses import dataclass
import hashlib
import time

import numpy as np
import torch

from feedback_model import external_loss_from_outputs, innovation_bank, weight_hashes
from risk import entropic_ce, robust_ce


def tensor_digest(value):
    return hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def noise_banks(seed, horizon, scale):
    return [innovation_bank(700000 + 101 * seed + depth, scale)[0]
            for depth in range(horizon + 1)]


def build_tree(model, targets, seed, scale=0.8):
    """Actually execute every latent edge and four-decoder exit, with gradients."""
    q = torch.eye(8, dtype=next(model.parameters()).dtype)
    banks = noise_banks(seed, model.max_refinements, scale)
    anchor = model.anchor_tensor(q)
    latents, losses = [], []
    for depth, bank in enumerate(banks):
        paths = 3 ** (depth + 1)
        qs = q.repeat_interleave(paths, dim=0)
        anchors = anchor.repeat_interleave(paths, dim=0)
        noise = np.tile(bank, (8 * (paths // 3), 1))
        if depth == 0:
            latent = model.initialize_tensor(qs, noise, anchor=anchors)
        else:
            previous = latents[-1].reshape(-1, 64).repeat_interleave(3, dim=0)
            latent = model.refine_tensor(qs, previous, noise, anchor=anchors)
        output = model.decode_tensor(latent)
        all_losses = external_loss_from_outputs(model, output, targets)
        classes = torch.arange(8).repeat_interleave(paths)
        loss = all_losses[torch.arange(8 * paths), classes].reshape(8, paths)
        latents.append(latent.reshape(8, paths, 64))
        losses.append(loss)
    return latents, losses, banks


def torch_ce(values, probabilities, gamma):
    probabilities = torch.as_tensor(probabilities, dtype=values.dtype, device=values.device)
    if gamma == 0:
        return (values * probabilities).sum(-1)
    floor = values.min(-1, keepdim=True).values
    return floor.squeeze(-1) - torch.log(
        (probabilities * torch.exp(-gamma * (values - floor))).sum(-1)) / gamma


def selected_utility(losses, probabilities, gamma, penalty):
    """Piecewise envelope derivative of the exact nominal STOP/REFINE problem."""
    values = -losses[-1]
    decisions = [None] * len(losses)
    decisions[-1] = torch.zeros_like(values, dtype=torch.bool)
    for depth in range(len(losses) - 2, -1, -1):
        stop = -losses[depth]
        continuation = torch_ce(values.reshape(8, -1, 3), probabilities, gamma) - penalty
        take = continuation > stop + 1e-12
        values = torch.where(take, continuation, stop)
        decisions[depth] = take
    return torch_ce(values, probabilities, gamma).mean(), decisions


def physical_weights(probabilities, depth):
    weights = np.asarray(probabilities, dtype=np.float64)
    for _ in range(depth):
        weights = np.multiply.outer(weights, probabilities).reshape(-1)
    return weights


@dataclass
class FeedbackPolicy:
    latents: list
    losses: list
    stop: list
    continuation: list
    actions: list
    values: list
    banks: list
    gamma: float
    penalty: float
    probabilities: np.ndarray
    ambiguity_rows: np.ndarray
    mode: str
    receipt: dict

    def observe(self, condition, feedback):
        """Bind a newly observed latent to the declared finite reachable support."""
        depth = feedback['depth']
        if type(condition) is not int or not 0 <= condition < 8 or not 0 <= depth < len(self.latents):
            raise ValueError('invalid observed generation state')
        latent = feedback['latent'].detach().cpu().numpy()
        if latent.shape != (1, 64) or not np.isfinite(latent).all():
            raise ValueError('single finite actual latent required')
        errors = np.max(np.abs(self.latents[depth][condition] - latent[0]), axis=1)
        index = int(errors.argmin())
        # GEMM batch-size roundoff is bounded, not silently treated as an unseen state.
        if errors[index] > 2e-5:
            raise ValueError('actual latent outside compiled finite support')
        return {'depth': depth, 'node': index, 'action': str(self.actions[depth][condition, index]),
                'stop_value': float(self.stop[depth][condition, index]),
                'continue_value': None if depth == len(self.latents) - 1 else
                    float(self.continuation[depth][condition, index]),
                'latent_match_max_error': float(errors[index]),
                'latent_sha256': tensor_digest(feedback['latent'])}


def compile_policy(model, targets, seed, gamma=2., penalty=.015, scale=.8,
                   probabilities=(.25, .5, .25), ambiguity_rows=None, mode='feedback'):
    if mode not in ('feedback', 'myopic', 'robust'):
        raise ValueError('unknown finite feedback mode')
    started, cpu = time.perf_counter(), time.process_time()
    before = model.work_receipt()['linear_macs']
    with torch.inference_mode():
        latent_tensors, loss_tensors, banks = build_tree(model, targets, seed, scale)
    latents = [x.numpy().copy() for x in latent_tensors]
    losses = [x.numpy().copy() for x in loss_tensors]
    stop = [-x for x in losses]
    continuation = [None] * len(losses)
    actions, values = [None] * len(losses), [None] * len(losses)
    values[-1] = stop[-1].copy()
    actions[-1] = np.full(values[-1].shape, 'emit', dtype='U6')
    rows = np.asarray(ambiguity_rows if ambiguity_rows is not None else [probabilities])
    for depth in range(len(losses) - 2, -1, -1):
        descendants = values[depth + 1].reshape(8, -1, 3)
        candidate = (robust_ce(descendants, rows, gamma) if mode == 'robust'
                     else entropic_ce(descendants, probabilities, gamma)) - penalty
        continuation[depth] = candidate
        decision_value = candidate
        if mode == 'myopic':
            decision_value = entropic_ce(stop[depth + 1].reshape(8, -1, 3), probabilities, gamma) - penalty
        take = decision_value > stop[depth] + 1e-12
        # Native executes the same myopic decision scores. Realized policy value is separate.
        if mode == 'myopic':
            continuation[depth] = decision_value
        actions[depth] = np.where(take, 'refine', 'emit')
        values[depth] = np.where(take, candidate, stop[depth])
    receipt = {'mode': mode, 'nodes': sum(x.size for x in losses),
               'model_weight_sha256': weight_hashes(model)['all'],
               'offline_forward_linear_macs': model.work_receipt()['linear_macs'] - before,
               'wall_seconds': time.perf_counter() - started, 'process_cpu_seconds': time.process_time() - cpu,
               'exact_finite_tree_only': True, 'online_latent_match_tolerance': 2e-5,
               'initial_nominal_utility': float(entropic_ce(values[0], probabilities, gamma).mean())}
    for array in (*latents, *losses, *stop, *actions, *values, *banks,
                  *(x for x in continuation if x is not None)):
        if isinstance(array, np.ndarray):
            array.flags.writeable = False
    return FeedbackPolicy(latents, losses, stop, continuation, actions, values, banks,
                          gamma, penalty, np.asarray(probabilities), rows.copy(), mode, receipt)


def choose_static_depth(policy):
    utilities = [float(entropic_ce(-loss, physical_weights(policy.probabilities, depth),
                                  policy.gamma).mean()) - depth * policy.penalty
                 for depth, loss in enumerate(policy.losses)]
    depth = int(np.argmax(utilities))
    return {'depth': depth, 'nominal_utilities': utilities,
            'criterion': 'same terminal entropic utility and per-refinement penalty; fixed before new noise draws'}


def audit_policy(policy):
    """Independent scalar recursion, using math.fsum/log rather than vector CE."""
    import math

    def ce(values, probabilities):
        if policy.gamma == 0:
            return math.fsum(float(p) * float(v) for p, v in zip(probabilities, values))
        minimum = min(values)
        return minimum - math.log(math.fsum(float(p) * math.exp(-policy.gamma * (v - minimum))
                                           for p, v in zip(probabilities, values))) / policy.gamma

    errors, mismatches = [], 0
    total = 0
    def solve(condition, depth, node):
        nonlocal mismatches, total
        stop = -float(policy.losses[depth][condition, node])
        total += 1
        if depth + 1 == len(policy.losses):
            value, action = stop, 'emit'
        else:
            children = [solve(condition, depth + 1, 3 * node + j) for j in range(3)]
            continuation = (min(ce(children, row) for row in policy.ambiguity_rows)
                            if policy.mode == 'robust' else ce(children, policy.probabilities)) - policy.penalty
            selection = continuation
            if policy.mode == 'myopic':
                selection = ce([-float(policy.losses[depth + 1][condition, 3 * node + j])
                                for j in range(3)], policy.probabilities) - policy.penalty
            action = 'refine' if selection > stop + 1e-12 else 'emit'
            value = continuation if action == 'refine' else stop
        errors.append(abs(value - float(policy.values[depth][condition, node])))
        mismatches += int(action != policy.actions[depth][condition, node])
        return value
    for condition in range(8):
        for root in range(3):
            solve(condition, 0, root)
    maximum = max(errors)
    if mismatches or maximum > 1e-10:
        raise AssertionError('independent finite-tree oracle mismatch')
    return {'states': total, 'policy_mismatches': mismatches, 'max_value_error': maximum,
            'independent_scalar_backup': True}
