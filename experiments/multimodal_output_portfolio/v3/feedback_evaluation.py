"""Execute causal four-modality feedback streams and score only after emission."""

import hashlib
import time

import numpy as np
import torch

from feedback_control import tensor_digest
from feedback_model import weight_hashes
from metrics import score_outputs, summarize
from model import MODALITIES, encode, mac_counts


class CausalInnovations:
    """Draws one branch at a time. The policy never receives this object."""
    def __init__(self, seed, probabilities):
        self.rng = np.random.default_rng(seed)
        self.probabilities = np.asarray(probabilities)
        self.draws = []

    def draw(self, bank):
        branch = int(self.rng.choice(3, p=self.probabilities))
        self.draws.append(branch)
        return bank[branch].copy()


@torch.inference_mode()
def rollout_feedback(model, raw_text, policy, targets, noise_seed, probabilities,
                     arm, static_depth=None, native=None):
    """Model inputs contain only raw text, public policy and fresh innovations."""
    started, cpu = time.perf_counter(), time.process_time()
    if weight_hashes(model)['all'] != policy.receipt['model_weight_sha256']:
        raise ValueError('feedback policy belongs to another model checkpoint')
    conditions = encode(model.base, 'text', raw_text)[0]
    count = len(conditions)
    profile = model.cost_profile()
    model.reset_costs()
    outputs = {name: [] for name in MODALITIES}
    receipts = []
    max_match_error = 0.
    for row, value in enumerate(conditions):
        condition = int(value)
        q = np.eye(8, dtype=np.float32)[[condition]]
        innovations = CausalInnovations(noise_seed + 97 * row, probabilities)
        initial = innovations.draw(policy.banks[0])
        if arm == 'clean_no_disturbance_reference':
            initial = np.zeros(64, dtype=np.float32)
        budget = profile['anchor'] + profile['emit_all'] + model.max_refinements * profile['refinement']
        state = model.initialize(q, initial, budget_macs=budget)
        feedback = model.feedback(state)
        controlled = static_depth is None
        if native is not None and controlled:
            native.begin(condition, tensor_digest(feedback['latent']), profile, model.max_refinements)
        trace = []
        while True:
            if controlled:
                observed = policy.observe(condition, feedback)
                max_match_error = max(max_match_error, observed['latent_match_max_error'])
                action = native.choose(observed) if native is not None else observed['action']
            else:
                action = 'emit' if state.depth >= static_depth else 'refine'
                observed = {'depth': state.depth, 'action': action,
                            'latent_sha256': tensor_digest(feedback['latent'])}
            trace.append({**observed, 'residual_rms': float(feedback['residual_rms'][0]),
                          'remaining_before': int(feedback['remaining_macs'])})
            if action == 'emit':
                emitted = model.emit(state)
                hashes = {name: tensor_digest(value) for name, value in emitted.items()}
                if native is not None and controlled:
                    native.emitted(hashes)
                    if native.remaining != budget - state.receipt['linear_macs']:
                        raise AssertionError('native and generator final budgets disagree')
                for name, value in emitted.items():
                    outputs[name].append(value.numpy().copy())
                break
            # Future innovation is drawn only after the actual REFINE choice.
            state = model.refine_step(state, innovations.draw(policy.banks[state.depth + 1]))
            feedback = model.feedback(state)
            if native is not None and controlled:
                native.refined(tensor_digest(feedback['latent']))
                if native.remaining != budget - state.receipt['linear_macs']:
                    raise AssertionError('native and generator refinement budgets disagree')
        if not state.sealed or state.receipt['linear_macs'] > budget:
            raise AssertionError('generation output contract failed')
        receipts.append({'condition': condition, 'depth': state.depth,
                         'linear_macs': state.receipt['linear_macs'] + mac_counts(model.base)['encoder']['text'],
                         'noise_branches': innovations.draws, 'output_sha256': hashes,
                         'remaining': budget - state.receipt['linear_macs'],
                         'feedback_events': state.receipt['feedback_events'], 'trace': trace})
    outputs = {name: np.concatenate(value, axis=0) for name, value in outputs.items()}
    # Caller attaches evaluator truth and scoring; no truth argument entered this loop.
    expected = sum(r['linear_macs'] for r in receipts)
    actual = model.work_receipt()['linear_macs'] + count * mac_counts(model.base)['encoder']['text']
    if expected != actual:
        raise AssertionError('online actual forward count differs from per-world cost')
    observed_actions = {}
    for record in receipts:
        for event in record['trace']:
            observed_actions.setdefault((record['condition'], event['depth']), set()).add(event['action'])
    summary = {'examples': count, 'wall_seconds': time.perf_counter() - started,
               'process_cpu_seconds': time.process_time() - cpu,
               'linear_macs': actual, 'mean_linear_macs': actual / count,
               'depth_counts': {str(d): sum(r['depth'] == d for r in receipts)
                                for d in range(model.max_refinements + 1)},
               'max_latent_match_error': max_match_error, 'budget_violations': 0,
               'condition_depth_groups_with_both_actions': sum(len(actions) == 2 for actions in observed_actions.values()),
               'all_four_outputs': True, 'native_controlled': native is not None and controlled,
               'output_sha256': {k: hashlib.sha256(v.tobytes()).hexdigest() for k, v in outputs.items()}}
    return outputs, receipts, summary


def score_feedback(outputs, receipts, truth, targets):
    scores = score_outputs(outputs, truth, targets)
    scores['linear_macs'] = np.asarray([r['linear_macs'] for r in receipts], dtype=np.float64)
    scores['depth'] = np.asarray([r['depth'] for r in receipts], dtype=np.float64)
    return scores, summarize(scores)
