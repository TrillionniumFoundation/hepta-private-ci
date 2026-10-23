"""Matched generator forwards, separate supervised and recursive utility credit."""

from copy import deepcopy
import time

import numpy as np
import torch

from feedback_control import build_tree, physical_weights, selected_utility
from feedback_model import weight_hashes


def train_pair(warm, targets, seed, settings):
    models, receipts = {}, {}
    for mode in ('supervised', 'ndu'):
        model = deepcopy(warm).requires_grad_(False)
        model.refinement.requires_grad_(True)
        model.reset_costs()
        initial = weight_hashes(model)
        optimizer = torch.optim.AdamW(model.refinement.parameters(),
            lr=settings['ndu_learning_rate'], weight_decay=settings['weight_decay'])
        history = []
        wall, cpu = time.perf_counter(), time.process_time()
        steps = settings['matched_supervised_steps'] if mode == 'supervised' else settings['ndu_steps']
        for step in range(steps):
            _, losses, _ = build_tree(model, targets, seed, settings['noise_scale'])
            probabilities = settings['nominal_branch_probabilities']
            utility, decisions = selected_utility(losses, probabilities, settings['gamma'],
                                                  settings['cost_penalty_per_refinement'])
            if mode == 'ndu':
                objective = -utility
            else:
                objective = torch.stack([(loss * torch.as_tensor(physical_weights(probabilities, d),
                                  dtype=loss.dtype)).sum(-1).mean()
                                  for d, loss in enumerate(losses)]).mean()
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            squared = sum(float(p.grad.detach().double().square().sum())
                          for p in model.refinement.parameters() if p.grad is not None)
            gradient = np.sqrt(squared)
            if not np.isfinite(gradient) or not torch.isfinite(objective):
                raise RuntimeError('nonfinite genuine training objective or gradient')
            torch.nn.utils.clip_grad_norm_(model.refinement.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            history.append({'step': step + 1, 'objective': float(objective.detach()),
                            'initial_recursive_utility': float(utility.detach()),
                            'refinement_objective_gradient_l2': float(gradient),
                            'auxiliary_anchor_gradient': 0.,
                            'root_refine_fraction_of_support': float(decisions[0].double().mean())})
        model.eval().requires_grad_(False)
        final = weight_hashes(model)
        frozen = [key for key in initial if key not in ('all', 'refinement')]
        if any(initial[key] != final[key] for key in frozen):
            raise AssertionError('frozen source checkpoint changed')
        receipt = {'mode': mode, 'steps': steps, 'initial_hashes': initial, 'final_hashes': final,
                   'history': history, 'cost': model.work_receipt(),
                   'wall_seconds': time.perf_counter() - wall, 'process_cpu_seconds': time.process_time() - cpu,
                   'gradient_is_utility_only': mode == 'ndu', 'auxiliary_loss_used': False,
                   'frozen_source': True, 'finite_support_training_not_open_domain': True}
        models[mode], receipts[mode] = model, receipt
    if receipts['supervised']['initial_hashes'] != receipts['ndu']['initial_hashes']:
        raise AssertionError('training arms have different initial checkpoint')
    if receipts['supervised']['cost'] != receipts['ndu']['cost']:
        raise AssertionError('training forward examples/MACs are not matched')
    return models, receipts
