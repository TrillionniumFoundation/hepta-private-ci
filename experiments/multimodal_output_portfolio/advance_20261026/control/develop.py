"""Actual fitting on historical finite trees; never opens new source allocations."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.value import load_controller
from ...next_20261025.native_h2.common import SHARED, TEACHER
from .features import DIM, FEATURE_SCHEMA, encode
from .model import ACTION_COST, GAMMA, RIDGES, choose, fit, terminal_tables


HERE = Path(__file__).parent
RAW_H2 = Path('/tmp/hepta-ndu-next-native-h2')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2); f.write('\n')


def load(role, predictor, calibration):
    path = SHARED / f'abc4-control-runs/development-001/seed-17/{role}/data.pt'
    data = torch.load(path, map_location='cpu', weights_only=True, mmap=True)
    expected = ('forecast_fit', 480, 256) if role == 'fit' else ('forecast_calibration', 448, 128)
    if (data['role'], data['pair_start'], data['pair_count']) != expected:
        raise ValueError('Unexpected historical source role')
    x, masks, confidence = [], [], []
    for node in range(5):
        features, allowed, p = encode(data['features'][:, node].numpy(), 2 if node == 0 else 1,
                                      predictor, calibration)
        x.append(features); masks.append(allowed); confidence.append(p)
    data['compact'] = np.stack(x, 1)
    data['admitted'] = np.stack(masks, 1)
    data['confidence'] = np.stack(confidence, 1)
    data['terminal'] = terminal_tables(data['metrics']['primary']['utility'].numpy())
    return data


def policy_paths(prediction, admitted):
    first = choose(prediction[:, 0], admitted[:, 0], remaining_decisions=2)
    second = np.full(len(first), -1, dtype=np.int64)
    paths = np.where(first < 0, -1, 0)
    steps = (first > 0).astype(int)
    for action in range(1, 5):
        ids = np.flatnonzero(first == action)
        if not len(ids): continue
        follow = choose(prediction[ids, action], admitted[ids, action])
        second[ids] = follow
        paths[ids] = np.where(follow < 0, -1, np.where(follow == 0, action, 5 + (action - 1) * 4 + follow - 1))
        steps[ids] += (follow > 0).astype(int)
    return paths, first, second, steps


def outcome(data, predictions):
    path, first, second, steps = policy_paths(predictions, data['admitted'])
    utility = data['metrics']['primary']['utility'].numpy()[np.arange(len(path)), np.maximum(path, 0)]
    success = data['metrics']['primary']['joint_fact_correct'].numpy()[np.arange(len(path)), np.maximum(path, 0)]
    utility = np.where(path < 0, -1., utility)
    success = np.where(path < 0, 0., success)
    ce = lambda values: float(-np.log(np.exp(-GAMMA * values).mean()) / GAMMA)
    return {'raw_CE': ce(utility), 'action_cost_CE': ce(utility - ACTION_COST * steps),
            'success': float(success.mean()), 'rejection_fraction': float((path < 0).mean()),
            'mean_continuation_actions': float(steps.mean())}, (path, first, second, steps)


def diagnostics(data, prediction, selection):
    path, first, second, steps = selection
    target = data['terminal'][:, 1:]
    predicted = prediction[:, 1:]
    actual_delta = target[..., 1:] - target[..., :1]
    predicted_delta = predicted[..., 1:] - predicted[..., :1]
    allowed = data['admitted'][:, 1:, 1:] & data['admitted'][:, 1:, :1]
    # Only defined executable action-minus-executable-stop comparisons enter
    # this diagnostic; rejected stops cannot serve as the ordinary baseline.
    eligible_error = (predicted_delta - actual_delta)[allowed]
    chosen_rows = np.flatnonzero((first > 0) & (second > 0))
    chosen_rows = chosen_rows[data['admitted'][chosen_rows, first[chosen_rows], 0]]
    if len(chosen_rows):
        root, child, act = chosen_rows, first[chosen_rows], second[chosen_rows]
        actual = data['terminal'][root, child, act] - data['terminal'][root, child, 0]
        forecast = prediction[root, child, act] - prediction[root, child, 0]
    else:
        actual, forecast = np.array([]), np.array([])
    return {'executable_H1_delta_count': int(allowed.sum()),
            'executable_H1_delta_MSE': float(np.mean(eligible_error ** 2)),
            'executable_H1_zero_delta_MSE': float(np.mean(actual_delta[allowed] ** 2)),
            'selected_nonstop_with_executable_stop': len(chosen_rows),
            'selected_actual_delta_mean': float(actual.mean()) if len(actual) else None,
            'selected_prediction_bias': float((forecast - actual).mean()) if len(actual) else None,
            'selected_delta_MSE': float(((forecast - actual) ** 2).mean()) if len(actual) else None}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    predictor_path = RAW_H2 / 'development-002/predictor.json'
    calibration_path = RAW_H2 / 'calibrator-001/calibration.json'
    predictor, calibration = (json.loads(p.read_text()) for p in (predictor_path, calibration_path))
    inputs = [predictor_path, calibration_path, TEACHER]
    inputs += [SHARED / f'abc4-control-runs/development-001/seed-17/{role}/data.pt' for role in ('fit', 'selection')]
    source_pins = {str(p.resolve()): sha(p) for p in HERE.glob('*.py')}
    registration = {'schema': 'hepta.advance.constrained-value-development.v1', 'started_unix_ns': time.time_ns(),
        'input_sha256': {str(p): sha(p) for p in inputs}, 'source_sha256': source_pins,
        'fixed_ridge_candidates': RIDGES, 'feature_schema': FEATURE_SCHEMA, 'feature_width': DIM,
        'source_roles': 'Only original seed17 forecast_fit[480,736) and forecast_calibration[448,576). Previously used roles are development, never new confirmation.',
        'backup': 'Other value-fold H1 action under fixed future correctness mask; actual held endpoint or no-admitted rejection(-1), then first-action cost. No hindsight best outcome.',
        'cross_fit_limit': 'The frozen admission predictor previously used some of these old sources. Only value heads exclude the held source fold; this is not an independent admission qualification.',
        'selection': 'Among candidates with raw_CE and strict success point no worse than same-mask old teacher, select least executable H1 delta MSE; if none passes, preserve least-MSE candidate as unadmitted research only.',
        'future_resource_law': 'No fitted stochastic tail law; actual native resource mask remains authoritative. Independent owner episode reset is required for the intended deployment comparison.',
        'new_sources_opened': False, 'production_authority': False}
    write(output / 'registration.json', registration)
    fitted = load('fit', predictor, calibration)
    models, audits = [], []
    for ridge in RIDGES:
        policy, report = fit(fitted['compact'], fitted['admitted'], fitted['terminal'], fitted['cases'], ridge)
        export = policy.export(); export.update(feature_schema=FEATURE_SCHEMA, ridge=ridge,
            predictor_sha256=sha(predictor_path), calibration_sha256=sha(calibration_path))
        path = output / f'ridge-{ridge}.json'; write(path, export)
        audit_path = output / f'ridge-{ridge}-backups.npz'
        np.savez_compressed(audit_path, cases=np.asarray(fitted['cases']),
            root_targets=report['root_actual_policy_targets'], future_actions=report['fold_future_choices'])
        models.append((ridge, policy, path))
        audits.append({'ridge': ridge, 'folds': report['folds'], 'backup_sha256': sha(audit_path),
                       'nonzero_numeric_prior_weights': [float(np.linalg.norm(np.asarray(h['weight'])[:, -3])) for h in export['heads']]})
    del fitted
    held = load('selection', predictor, calibration)
    teacher = load_controller(TEACHER)
    with torch.no_grad():
        baseline_prediction = np.stack([(teacher.two if node == 0 else teacher.one)(held['features'][:, node]).numpy()
                                        for node in range(5)], 1).astype(np.float64)
    baseline, baseline_selection = outcome(held, baseline_prediction)
    baseline_diagnostics = diagnostics(held, baseline_prediction, baseline_selection)
    records = []
    for ridge, policy, path in models:
        prediction = np.stack([policy.predict(held['compact'][:, node], 2 if node == 0 else 1)
                               for node in range(5)], 1)
        scores, selected = outcome(held, prediction)
        diag = diagnostics(held, prediction, selected)
        record = {'ridge': ridge, 'checkpoint': str(path.resolve()), 'checkpoint_sha256': sha(path),
                  'outcome': scores, 'diagnostics': diag,
                  'development_admitted': scores['raw_CE'] >= baseline['raw_CE'] and scores['success'] >= baseline['success']}
        # Native-compatible one-affine export is checked against fitted heads.
        exported = json.loads(path.read_text()); errors = []
        for node in range(5):
            layer = exported['heads'][1 if node == 0 else 0]
            exact = np.clip(held['compact'][:, node] @ np.asarray(layer['weight']).T + np.asarray(layer['bias']),
                            layer['minimum'], layer['maximum'])
            errors.append(float(np.abs(exact - prediction[:, node]).max()))
        record['max_export_prediction_error'] = max(errors)
        records.append(record)
    eligible = [i for i, r in enumerate(records) if r['development_admitted']]
    selected = min(eligible or range(len(records)), key=lambda i: (records[i]['diagnostics']['executable_H1_delta_MSE'], i))
    for p, h in source_pins.items():
        if sha(p) != h: raise ValueError('Development source changed while executing')
    result = {'schema': 'hepta.advance.constrained-value-development-result.v1', 'status': 'completed',
        'baseline_same_static_mask': baseline, 'baseline_diagnostics': baseline_diagnostics,
        'candidates': records, 'fit_audits': audits, 'selected_index': selected,
        'selected_development_admitted': bool(eligible), 'new_sources_opened': False,
        'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu,
        'registration_sha256': sha(output / 'registration.json'), 'production_authority': False}
    write(output / 'result.json', result); print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
