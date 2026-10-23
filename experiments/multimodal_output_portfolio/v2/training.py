"""Generator fine-tuning with matched forward work and explicit credit evidence."""

from collections import defaultdict
from copy import deepcopy
import hashlib
import math
import time

import numpy as np
import torch

from control import COSTS, next_preference
from controlled_model import ControlledOutputModel, external_loss_tensor, loss_table
from generation_control import GenerationPlanner
from model import WIDTH, NUM_CLASSES, _weight_hashes, mac_counts


def all_depth_macs(model, count):
    profile = mac_counts(model)
    return count * (NUM_CLASSES * WIDTH + 3 * 2 * WIDTH * WIDTH
                    + 4 * sum(profile['decoder'].values()))


def _gradient_norms(scalar, named_parameters):
    gradients = torch.autograd.grad(scalar, [p for _, p in named_parameters],
                                    retain_graph=True, allow_unused=True)
    squares = {name: 0.0 for name in (
        'initial_latent', 'refinement', 'decoders.text', 'decoders.audio',
        'decoders.image', 'decoders.video')}
    for (name, _), gradient in zip(named_parameters, gradients):
        if gradient is None:
            continue
        if not bool(torch.isfinite(gradient).all()):
            raise RuntimeError('nonfinite component gradient')
        group = '.'.join(name.split('.')[:2]) if name.startswith('decoders.') else name.split('.')[0]
        squares[group] += float(gradient.detach().double().square().sum())
    norms = {name: math.sqrt(value) for name, value in squares.items()}
    norms['all'] = math.sqrt(sum(squares.values()))
    norms['shared_refinement'] = math.hypot(norms['initial_latent'], norms['refinement'])
    norms['decoders'] = math.sqrt(sum(value for name, value in squares.items()
                                    if name.startswith('decoders.')))
    return norms


def _selected_policy_distribution(planner, roots, marginal, budget):
    """Use physical calibration probabilities, NOT risk-tilted gradient weights."""
    action_mass = {name: 0.0 for name in ('generate', 'audio', 'image', 'video')}
    immediate_depth_mass = np.zeros(4)
    terminal_mass = defaultdict(float)
    pending, root_decisions = [], []
    for root, probability in zip(roots, marginal):
        if probability <= 0:
            continue
        plan = planner.solve(root, budget, 0)
        name = 'generate' if plan.action == -1 else ('text', 'audio', 'image', 'video')[plan.action]
        action_mass[name] += float(probability)
        if plan.action == -1:
            immediate_depth_mass[plan.depth] += probability
        root_decisions.append({'text_report': root[0], 'probability': float(probability),
                               'action': name, 'depth': plan.depth,
                               'portfolio': plan.portfolio})
        pending.append((root, budget, 0, float(probability)))
    acquisition_count = 0.0
    while pending:
        observations, remaining, preference, mass = pending.pop()
        plan = planner.solve(observations, remaining, preference)
        if plan.action == -1:
            terminal_mass[(plan.depth, plan.portfolio)] += mass
            continue
        acquisition_count += mass
        cost = COSTS[plan.action] + planner.controller_cost
        for outcome, probability in enumerate(planner.model.predictive(observations, plan.action)):
            if probability > 0:
                child = list(observations)
                child[plan.action] = outcome
                pending.append((tuple(child), remaining - cost,
                                next_preference(preference, observations, outcome),
                                mass * float(probability)))
    depth_mass = np.zeros(4)
    for (depth, _), probability in terminal_mass.items():
        depth_mass[depth] += probability
    if not np.isclose(depth_mass.sum(), 1.0, rtol=0, atol=1e-10):
        raise RuntimeError('selected-policy terminal probability mass was not conserved')
    return {
        'probability_law': 'physical frozen calibration, not entropic derivative weights',
        'root_action_probabilities': action_mass,
        'immediate_commitment_depth_probabilities': immediate_depth_mass.tolist(),
        'reached_commitment_depth_probabilities': depth_mass.tolist(),
        'reached_committed_plan_probabilities': [
            {'depth': depth, 'portfolio': portfolio, 'probability': probability}
            for (depth, portfolio), probability in sorted(terminal_mass.items())],
        'expected_evidence_acquisitions': acquisition_count,
        'root_decisions': root_decisions,
    }


def train_ndu(base_model, calibration, targets, grid, seed, protocol, steps):
    """Reselect finite policies each update; differentiate that SAME external loss.

    This local selected-policy derivative requires stable maximizers and no
    metric ties. Diagnostics separate utility credit from anchor gradients and
    AdamW parameter decay. They do not prove an optimum across action switches.
    """
    return _train('ndu', base_model, calibration, targets, grid, seed, protocol, steps)


def train_matched_supervised(base_model, calibration, targets, grid, seed, protocol, steps):
    """Same warmup parent, optimizer, updates and dense Linear FORWARD work.

    Mean q-weighted prototype MSE differs from convex-target reconstruction by
    a parameter-independent variance term. It uses no calibration-dependent
    policy or utility. Total compute is NOT matched: recursive planning and
    backward arithmetic differ and their costs remain separately visible.
    """
    return _train('supervised', base_model, calibration, targets, grid, seed, protocol, steps)


def _train(kind, base_model, calibration, targets, grid, seed, protocol, steps):
    if (type(seed) is not int or not 0 <= seed < 2**32
            or type(steps) is not int or not 1 <= steps <= 10000):
        raise ValueError('bounded integer seed and positive training steps required')
    settings = deepcopy(protocol['joint_training'])
    if settings.get('optimizer', 'AdamW') != 'AdamW':
        raise ValueError('registered optimizer is AdamW')
    for key in ('learning_rate', 'weight_decay', 'gradient_norm_cap', 'anchor_weight'):
        value = settings[key]
        minimum_ok = value > 0 if key in ('learning_rate', 'gradient_norm_cap') else value >= 0
        if isinstance(value, bool) or not np.isfinite(value) or not minimum_ok:
            raise ValueError('invalid fixed optimizer setting: ' + key)
    model = deepcopy(base_model)
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(not name.startswith('encoders.'))
    model.train()
    parameters = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW([p for _, p in parameters],
        lr=settings['learning_rate'], weight_decay=settings['weight_decay'])
    initial = _weight_hashes(model)
    calibration_digest = hashlib.sha256(calibration.joint.tobytes()).hexdigest()
    marginal = calibration.joint.sum(axis=(0, 2, 3, 4))
    marginal /= marginal.sum()
    roots = [(text, -1, -1, -1) for text in range(9)]
    vertices = np.eye(8, dtype=np.float32)
    history, gradient_evidence, policy_evidence = [], [], []
    cost = {name: 0.0 for name in (
        'policy_compilation_wall_seconds', 'policy_compilation_process_cpu_seconds',
        'recursive_tensor_evaluation_wall_seconds', 'recursive_tensor_evaluation_process_cpu_seconds',
        'gradient_diagnostics_wall_seconds', 'gradient_diagnostics_process_cpu_seconds',
        'policy_diagnostics_wall_seconds', 'policy_diagnostics_process_cpu_seconds')}
    wall, cpu = time.perf_counter(), time.process_time()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        for step in range(steps):
            wrapper = ControlledOutputModel(model, copy_model=False)
            if kind == 'ndu':
                table = external_loss_tensor(wrapper, grid, targets)
                started_wall, started_cpu = time.perf_counter(), time.process_time()
                planner = GenerationPlanner(calibration, table.detach().cpu().numpy(), grid,
                    gamma=protocol['gamma'], penalty=protocol['penalty'],
                    controller_cost=protocol.get('costs', {}).get('controller_per_event', 1))
                for root, probability in zip(roots, marginal):
                    if probability > 0:
                        planner.solve(root, 12, 0)
                cost['policy_compilation_wall_seconds'] += time.perf_counter() - started_wall
                cost['policy_compilation_process_cpu_seconds'] += time.process_time() - started_cpu
                started_wall, started_cpu = time.perf_counter(), time.process_time()
                utility = sum(float(p) * planner.evaluate_policy_torch(table, root, 12, 0)
                              for p, root in zip(marginal, roots) if p > 0)
                primary = -utility
                cost['recursive_tensor_evaluation_wall_seconds'] += time.perf_counter() - started_wall
                cost['recursive_tensor_evaluation_process_cpu_seconds'] += time.process_time() - started_cpu
                entry = {'initial_recursive_utility': float(utility.detach())}
            else:
                table = loss_table(wrapper, grid, targets)
                weights = torch.as_tensor(np.asarray(grid), dtype=table.dtype, device=table.device)
                primary = (table * weights[None, :, :]).sum(dim=-1).mean()
                entry = {'expected_normalized_reconstruction': float(primary.detach())}
            anchor_table = loss_table(wrapper, vertices, targets)
            index = torch.arange(8, device=anchor_table.device)
            anchor = anchor_table[:, index, index].mean()
            objective = primary + settings['anchor_weight'] * anchor
            if not bool(torch.isfinite(objective)):
                raise RuntimeError('nonfinite generator training objective')
            if step in (0, steps - 1):
                started_wall, started_cpu = time.perf_counter(), time.process_time()
                primary_norms = _gradient_norms(primary, parameters)
                anchor_norms = _gradient_norms(anchor, parameters)
                diagnostic = {
                    'step': step + 1, 'position': 'before_optimizer_update',
                    'primary_component': 'negative_recursive_utility' if kind == 'ndu'
                                         else 'expected_normalized_reconstruction',
                    'primary_gradient_l2': primary_norms,
                    'unweighted_anchor_gradient_l2': anchor_norms,
                    'weighted_anchor_gradient_l2': {
                        name: settings['anchor_weight'] * value for name, value in anchor_norms.items()},
                    'excludes_optimizer_weight_decay': True,
                    'frozen_encoders_not_differentiated': True,
                }
                if kind == 'ndu':
                    diagnostic['negative_utility_gradient_l2'] = primary_norms
                gradient_evidence.append(diagnostic)
                cost['gradient_diagnostics_wall_seconds'] += time.perf_counter() - started_wall
                cost['gradient_diagnostics_process_cpu_seconds'] += time.process_time() - started_cpu
                if kind == 'ndu':
                    started_wall, started_cpu = time.perf_counter(), time.process_time()
                    policy_evidence.append({'step': step + 1,
                        'position': 'before_optimizer_update',
                        **_selected_policy_distribution(planner, roots, marginal, 12)})
                    cost['policy_diagnostics_wall_seconds'] += time.perf_counter() - started_wall
                    cost['policy_diagnostics_process_cpu_seconds'] += time.process_time() - started_cpu
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), settings['gradient_norm_cap'],
                                                  error_if_nonfinite=True)
            optimizer.step()
            history.append({'step': step + 1, **entry, 'anchor': float(anchor.detach()),
                            'regularized_objective': float(objective.detach()),
                            'gradient_norm_before_clip': float(norm)})
            if kind == 'ndu':
                del planner, utility
            del objective, primary, table, anchor_table, anchor
    model.eval().requires_grad_(False)
    final = _weight_hashes(model)
    if initial['encoders'] != final['encoders']:
        raise AssertionError('generator training mutated frozen encoders')
    if initial != _weight_hashes(base_model):
        raise AssertionError('generator training mutated the parent checkpoint')
    if calibration_digest != hashlib.sha256(calibration.joint.tobytes()).hexdigest():
        raise AssertionError('generator training mutated the calibration law')
    receipt = {
        'seed': seed, 'steps': steps, 'optimizer_steps': steps,
        'training_objective': 'recursive_ndu' if kind == 'ndu' else 'matched_supervised',
        'initial_hashes': initial, 'final_hashes': final,
        'groups_changed': {name: initial[name] != final[name] for name in initial},
        'history': history, 'gradient_evidence': gradient_evidence,
        'selected_policy_evidence': policy_evidence,
        'wall_seconds': time.perf_counter() - wall, 'process_cpu_seconds': time.process_time() - cpu,
        'separate_control_and_diagnostic_cost': cost,
        'forward_linear_macs': steps * all_depth_macs(model, len(grid) + 8),
        'forward_portfolio_examples': steps * (len(grid) + 8),
        'forward_initialization_batches': 2 * steps,
        'forward_refinement_batches': 6 * steps,
        'forward_four_decoder_bundles': 8 * steps,
        'gradient_diagnostic_autograd_calls': 2 * len(gradient_evidence),
        'calibration_initial_text_probabilities': marginal.tolist(),
        'calibration_sha256': calibration_digest,
        'target_budget': 12 if kind == 'ndu' else None,
        'encoders_and_calibration_frozen': True, 'parent_unchanged': True,
        'terminal_metric_matches_external_evaluation': kind == 'ndu',
        'gradient_scope': 'piecewise selected-policy recursive derivative' if kind == 'ndu'
                          else 'smooth q-weighted prototype reconstruction',
        'optimizer': settings,
        'matched_scope': 'optimizer updates and ideal dense Linear forward work only',
        'lifetime_compute_matched': False,
        'cost_exclusions': ['backward and optimizer FLOPs', 'nonlinear operations',
                            'controller arithmetic; measured CPU included'],
    }
    return model, receipt
