"""Sealed conditional-specialist study; preserve every V9/V10 control.

No task-ID oracle, fresh Encoder, persistent service or production acceptance.
The full existing upstream replayers remain mandatory before feature reuse.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
import time

import torch
from safetensors.torch import load, save

from cell_anchor_consolidation import EXTRA_ARMS as ANCHORS
from cell_anchor_study import evaluated_logits, load_base, review as review_anchors
from cell_conditional_gate import (CONDITIONAL_TOLERANCE, GATE_ARMS, LEARNED, OFFSETS,
                                   calibrate, conditional_logits, fit_gates)
from cell_consolidation import ARMS, metrics, select_retained, training_partition
from cell_consolidation_study import source_features
from development_study import prepare_views
from development_study_data import digest, phase, write_once
from development_study_replay import read_bytes, record

ALL_ARMS = ARMS + ANCHORS + GATE_ARMS


def implementation():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}


def load_references(rows, features, origin, baseline, anchor_run):
    hidden = [{k: v for k, v in r.items() if k != 'label' or phase(r) != 'held_out'} for r in rows]
    report = review_anchors(hidden, features, origin, baseline, anchor_run, score_held_out=False)
    teachers, config, source = load_base(hidden, features, origin, baseline)
    selection, selection_sha = record(Path(anchor_run)/'selection.json')
    run, run_sha = record(Path(anchor_run)/'run.json')
    if run_sha != report['run_sha256'] or selection_sha != run['selection_sha256']:
        raise ValueError('anchor reference changed after review')
    anchors = {}
    for n in ANCHORS:
        raw = read_bytes(Path(anchor_run)/f'{n}.safetensors', 1_048_576)
        if hashlib.sha256(raw).hexdigest() != selection['checkpoints'][n]:
            raise ValueError('anchor checkpoint changed after review')
        anchors[n] = load(raw)
    source.update(anchor_run_sha256=run_sha, anchor_selection_sha256=selection_sha,
                  anchor_costs=selection['costs'])
    return teachers, anchors, config, source


def score_rows(logits, rows, ids, config):
    return {n: metrics(v, torch.tensor([rows[i]['label'] for i in ids]),
        [rows[i]['source_group'] for i in ids], config) for n, v in logits.items()}


def tensor_file(folder, name, tensors):
    raw = save({k: v.detach().contiguous() for k, v in tensors.items()})
    with (folder/f'{name}.safetensors').open('xb') as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


def execute(rows, features, origin, baseline, anchor_run, output):
    start = time.process_time_ns(), time.perf_counter_ns()
    teachers, anchors, config, source = load_references(rows, features, origin, baseline, anchor_run)
    inputs, _ = prepare_views(rows)
    truth = {r['sample_id']: r['label'] for r in rows if phase(r) in ('base', 'adapt')}
    folder = Path(output); folder.mkdir(parents=True, exist_ok=False)
    plan_sha = write_once(folder/'plan.json', {'schema': 'hepta.cell.conditional-plan.v1',
        'source': source, 'config': asdict(config), 'arms': ALL_ARMS, 'offsets': OFFSETS,
        'conditional_tolerance': CONDITIONAL_TOLERANCE, 'input_digest': digest(inputs),
        'implementation': implementation(), 'torch': torch.__version__,
        'threads': torch.get_num_threads(), 'production_authorized': False})
    try:
        candidates, mean, scale, costs, partition = fit_gates(inputs, truth, features, config,
            {n: teachers[n] for n in ('frozen', 'new_only')})
        # Seal actual trained gates before calibration labels enter offset selection.
        trained = {n: tensor_file(folder, 'unshifted_'+n, candidates[n]) for n in LEARNED}
        cal_ids = [i for i, r in enumerate(rows) if phase(r) == 'calibration']
        x = (features[cal_ids]-mean)/scale
        inherited = evaluated_logits(teachers, anchors, x, config.classes)
        reference = score_rows(inherited, rows, cal_ids, config)['frozen']
        calibration_start = time.process_time_ns(), time.perf_counter_ns()
        grid = {}
        for n in LEARNED:
            candidates[n], grid[n] = calibrate(candidates[n], x,
                torch.tensor([rows[i]['label'] for i in cal_ids]),
                [rows[i]['source_group'] for i in cal_ids], reference, config, n)
        costs['calibration'] = {'cpu_ns': time.process_time_ns()-calibration_start[0],
            'wall_ns': time.perf_counter_ns()-calibration_start[1],
            'offset_candidates': len(LEARNED)*len(OFFSETS),
            'candidate_forward_rows': len(cal_ids)*len(LEARNED)*len(OFFSETS)}
        inventory = {n: tensor_file(folder, n, candidates[n]) for n in GATE_ARMS}
        cal_logits = {**inherited, **{n: conditional_logits(t, x, config, n) for n, t in candidates.items()}}
        scores = score_rows(cal_logits, rows, cal_ids, config)
        decision = select_retained(scores, config, extra_arms=ANCHORS+GATE_ARMS)
        selection_sha = write_once(folder/'selection.json', {**decision, 'calibration_metrics': scores,
            'grid': grid, 'partition': partition, 'costs': costs, 'checkpoints': inventory,
            'unshifted_checkpoints': trained})
        # Held-out gold has no role in this output-producing boundary.
        ids = [i for i, r in enumerate(rows) if phase(r) in ('calibration', 'held_out')]
        x = (features[ids]-mean)/scale
        logits = {**evaluated_logits(teachers, anchors, x, config.classes),
                  **{n: conditional_logits(t, x, config, n) for n, t in candidates.items()}}
        predictions = [{'arm': n, 'sample_id': inputs[i]['sample_id'],
            'input_fingerprint': inputs[i]['input_fingerprint'], 'logits': v}
            for n in ALL_ARMS for i, v in zip(ids, logits[n].tolist())]
        result = {'schema': 'hepta.cell.conditional-run.v1', 'plan_sha256': plan_sha,
            'selection_sha256': selection_sha, 'predictions_sha256': write_once(folder/'predictions.json', predictions),
            'current_encoder_calls': 0, 'cpu_ns': time.process_time_ns()-start[0],
            'wall_ns': time.perf_counter_ns()-start[1], 'production_authorized': False}
        write_once(folder/'run.json', result)
        return result
    except Exception as error:
        write_once(folder/'FAILED.json', {'error_type': type(error).__name__, 'message': str(error)})
        raise


def reconstructed(t, x, teachers, config, rule):
    """Independent affine and log-normalization formula, no fitter/forward call."""
    d, k = x.shape[1], config.classes
    shapes = {'weight': (k, d), 'bias': (k,)}
    if rule in LEARNED:
        shapes.update(gate_weight=((1,) if rule == 'gate_score_memory' else (d,)), gate_bias=(1,))
    if set(t) != set(shapes) or any(v.dtype != torch.float32 or v.device.type != 'cpu'
            or tuple(v.shape) != shapes[n] or not torch.isfinite(v).all() for n, v in t.items()):
        raise ValueError('invalid independent conditional tensor inventory')
    expected_w, expected_b = torch.empty(k, d), torch.empty(k)
    for columns, name in ((list(config.old_classes), 'frozen'),
                          ([i for i in range(k) if i not in config.old_classes], 'new_only')):
        u = teachers[name]
        expected_w[columns] = (u['readout.weight'].double()*u['gamma'].double())[columns].float()
        expected_b[columns] = (u['readout.bias'].double()+u['readout.weight'].double()@u['beta'].double())[columns].float()
    if not torch.equal(t['weight'], expected_w) or not torch.equal(t['bias'], expected_b):
        raise ValueError('frozen conditional specialist rows changed')
    raw = x @ t['weight'].T + t['bias']
    if not torch.isfinite(raw).all():
        raise ValueError('nonfinite reconstructed specialist')
    if rule == 'conditional_concat':
        return raw
    gate_input = x
    if rule == 'gate_score_memory':
        old = list(config.old_classes); new = [i for i in range(k) if i not in old]
        gate_input = (torch.logsumexp(raw[:, new], -1)-torch.logsumexp(raw[:, old], -1))[:, None]
    g = gate_input@t['gate_weight']+t['gate_bias'][0] if rule in LEARNED else torch.zeros(len(x))
    if not torch.isfinite(g).all(): raise ValueError('nonfinite reconstructed gate')
    result = torch.empty_like(raw)
    for columns, signed in ((list(config.old_classes), g),
                            ([i for i in range(k) if i not in config.old_classes], -g)):
        block = raw[:, columns]
        conditional = block-torch.logsumexp(block, -1, keepdim=True)
        values = conditional-torch.logaddexp(torch.zeros_like(signed), signed)[:, None]
        recovered = values-torch.logsumexp(values, -1, keepdim=True)
        if not torch.isfinite(values).all() or float((recovered-conditional).abs().max()) > CONDITIONAL_TOLERANCE:
            raise ValueError('conditional odds lost during reconstruction')
        result[:, columns] = values
    return result


def close_tree(saved, computed):
    """Same metrics, independent record validation; numeric tolerance is explicit."""
    if isinstance(computed, dict):
        if not isinstance(saved, dict) or set(saved) != set(computed): raise ValueError('record keys changed')
        for k in computed: close_tree(saved[k], computed[k])
    elif isinstance(computed, (list, tuple)):
        if not isinstance(saved, (list, tuple)) or len(saved) != len(computed): raise ValueError('record length changed')
        for a, b in zip(saved, computed): close_tree(a, b)
    elif type(computed) is float:
        if type(saved) not in (float, int) or not math.isfinite(saved) or abs(saved-computed) > 1e-6:
            raise ValueError('record numeric value changed')
    elif type(saved) is not type(computed) or saved != computed:
        raise ValueError('record value changed')


def review(rows, features, origin, baseline, anchor_run, output):
    folder = Path(output)
    if (folder/'FAILED.json').exists(): raise ValueError('failed conditional run')
    teachers, anchors, config, source = load_references(rows, features, origin, baseline, anchor_run)
    run, run_sha = record(folder/'run.json'); plan, plan_sha = record(folder/'plan.json')
    selection, sel_sha = record(folder/'selection.json'); preds, pred_sha = record(folder/'predictions.json', 16_777_216)
    inputs, _ = prepare_views(rows)
    if (run['schema'] != 'hepta.cell.conditional-run.v1' or plan['schema'] != 'hepta.cell.conditional-plan.v1'
            or run['current_encoder_calls'] != 0 or run['production_authorized'] is not False
            or plan['production_authorized'] is not False or plan['source'] != source
            or plan['input_digest'] != digest(inputs) or digest(plan['config']) != digest(asdict(config))
            or plan['arms'] != list(ALL_ARMS) or plan['offsets'] != list(OFFSETS)
            or plan['implementation'] != implementation() or plan['conditional_tolerance'] != CONDITIONAL_TOLERANCE
            or (plan_sha, sel_sha, pred_sha) != (run['plan_sha256'], run['selection_sha256'], run['predictions_sha256'])):
        raise ValueError('conditional protocol, source or sealed records changed')
    truth = {r['sample_id']: r['label'] for r in rows if phase(r) in ('base', 'adapt')}
    old, new, memory = training_partition(inputs, truth, config)
    if selection['partition'] != {'old': old, 'new': new, 'memory': memory}: raise ValueError('gate training membership changed')
    mean, scale = features[old].mean(0), features[old].std(0, unbiased=False).clamp_min(1e-6)
    ids = [i for i, r in enumerate(rows) if phase(r) in ('calibration', 'held_out')]
    x = (features[ids]-mean)/scale
    cal = [j for j, i in enumerate(ids) if phase(rows[i]) == 'calibration']
    held = [j for j, i in enumerate(ids) if phase(rows[i]) == 'held_out']
    logits = evaluated_logits(teachers, anchors, x, config.classes)
    if (set(selection['checkpoints']) != set(GATE_ARMS) or set(selection['unshifted_checkpoints']) != set(LEARNED)
            or set(selection['costs']['arms']) != set(GATE_ARMS) or set(selection['grid']) != set(LEARNED)):
        raise ValueError('conditional control census mismatch')
    for n in GATE_ARMS:
        raw = read_bytes(folder/f'{n}.safetensors', 1_048_576)
        if hashlib.sha256(raw).hexdigest() != selection['checkpoints'][n]: raise ValueError('conditional checkpoint changed')
        t = load(raw); logits[n] = reconstructed(t, x, teachers, config, n)
        cost = selection['costs']['arms'][n]; count = sum(v.numel() for v in t.values())
        expected = {'trainable_parameters': (2 if n == 'gate_score_memory' else features.shape[1]+1) if n in LEARNED else 0,
            'deployed_parameters': count, 'deployed_weight_bytes': count*4,
            'steps': config.steps if n in LEARNED else 0, 'sample_presentations': config.steps*32 if n in LEARNED else 0}
        if n in LEARNED:
            rr = old if n == 'gate_all_old' else memory
            expected.update(replay_indices=rr, replay_feature_bytes=len(rr)*features.shape[1]*4,
                            optimizer_moment_bytes=(2 if n == 'gate_score_memory' else features.shape[1]+1)*8,
                            fitting_feature_bytes=(len(rr)+len(new))*(1 if n == 'gate_score_memory' else features.shape[1])*4)
            original = read_bytes(folder/f'unshifted_{n}.safetensors', 1_048_576)
            if hashlib.sha256(original).hexdigest() != selection['unshifted_checkpoints'][n]: raise ValueError('unshifted gate changed')
            unshifted = load(original); reconstructed(unshifted, x[cal], teachers, config, n)
            reference = score_rows({'frozen': logits['frozen'][cal]}, rows, [ids[j] for j in cal], config)['frozen']
            candidate, grid = calibrate(unshifted, x[cal], torch.tensor([rows[ids[j]]['label'] for j in cal]),
                [rows[ids[j]]['source_group'] for j in cal], reference, config, n)
            if any(not torch.equal(t[k], candidate[k]) for k in t): raise ValueError('calibrated gate is not reproducible')
            close_tree(selection['grid'][n], grid)
        for key, value in expected.items(): close_tree(cost[key], value)
    c = selection['costs']
    if (c['current_encoder_calls'] != 0 or c['total_steps'] != len(LEARNED)*config.steps
            or c['calibration']['offset_candidates'] != len(LEARNED)*len(OFFSETS)
            or c['calibration']['candidate_forward_rows'] != len(cal)*len(LEARNED)*len(OFFSETS)):
        raise ValueError('false gate computation census')
    expected = [{'arm': n, 'sample_id': inputs[i]['sample_id'], 'input_fingerprint': inputs[i]['input_fingerprint'], 'logits': v}
                for n in ALL_ARMS for i, v in zip(ids, logits[n].tolist())]
    if type(preds) is not list or len(preds) != len(expected): raise ValueError('conditional prediction census mismatch')
    maximum = 0.
    for p, e in zip(preds, expected):
        if (type(p) is not dict or set(p) != set(e) or any(p[k] != e[k] for k in e if k != 'logits')
                or type(p['logits']) is not list or any(type(v) not in (int, float) for v in p['logits'])):
            raise ValueError('conditional prediction identity changed')
        a, b = torch.tensor(p['logits']), torch.tensor(e['logits'])
        if a.shape != b.shape or not torch.isfinite(a).all(): raise ValueError('invalid stored conditional logits')
        delta = float((a-b).abs().max()); maximum = max(delta, maximum)
        if delta > 1e-5 or a.argmax() != b.argmax(): raise ValueError('conditional logits do not reconstruct')
    scores = {part: score_rows({n: v[js] for n, v in logits.items()}, rows, [ids[j] for j in js], config)
              for part, js in (('calibration', cal), ('held_out', held))}
    decision = select_retained(scores['calibration'], config, extra_arms=ANCHORS+GATE_ARMS)
    for k, v in decision.items(): close_tree(selection[k], v)
    close_tree(selection['calibration_metrics'], scores['calibration'])
    labels = [rows[ids[j]]['label'] for j in held]
    errors = {}
    for n, v in logits.items():
        predicted = v[held].argmax(1).tolist()
        errors[n] = {key: sum(condition(y, p) for y, p in zip(labels, predicted)) for key, condition in {
            'old_to_new': lambda y, p: y in config.old_classes and p not in config.old_classes,
            'new_to_old': lambda y, p: y not in config.old_classes and p in config.old_classes,
            'old_within_group_wrong': lambda y, p: y in config.old_classes and p in config.old_classes and y != p,
            'new_within_group_wrong': lambda y, p: y not in config.old_classes and p not in config.old_classes and y != p}.items()}
    return {'schema': 'hepta.cell.conditional-review.v1', 'run_sha256': run_sha, **decision,
        'scores': scores, 'held_out_error_decomposition': errors, 'prediction_rows': len(preds),
        'unique_held_out_inputs': len(held), 'max_abs_logit_error': maximum, 'argmax_reversals': 0,
        'current_encoder_calls': 0, 'global_no_forgetting_established': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-run', 'dataset', 'consolidation-run', 'anchor-run', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--review-run', type=Path)
    args = parser.parse_args(); torch.set_num_threads(2)
    rows, features, origin = source_features(args.source_run, args.dataset)
    if args.review_run:
        write_once(args.output, review(rows, features, origin, args.consolidation_run, args.anchor_run, args.review_run))
    else:
        execute(rows, features, origin, args.consolidation_run, args.anchor_run, args.output)
