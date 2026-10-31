"""Immediate-output correctness for H2 root and every reachable H1 child.

Only historical fit/selection data are opened by development. Two independent
linear heads use the frozen teacher's public first-layer encodings. Calibration
has fixed horizon/action-specific bins, never a hindsight best-child label.
"""

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ...abc_followup.native.forecast import Q, quantize
from ...abc_next.value import features, load_controller
from ..native.qualification import ece
from .common import SHARED, TEACHER, sha, write


ACTIONS = ('stop', 'refine_semantic', 'refine_image', 'refine_text', 'couple')
ID_VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted')
CONFIG = {'seed': 261026731, 'steps': 1200, 'batch_size': 512,
          'learning_rate': .01, 'weight_decay': .001, 'hidden': 32,
          'state_nodes': 'H2 root plus all four reachable H1 children',
          'target': 'immediate emitted-output joint_fact_correct after each action',
          'calibration_bins': 3, 'calibration_strata': 'horizon and action',
          'cut_source': 'forecast_fit only; fixed before fresh calibration',
          'maximum_ece': .03, 'maximum_far': .004999,
          'minimum_id_acceptance': .25, 'minimum_confidence': .75,
          'new_calibration_writers': 100, 'new_qualification_writers': 1000,
          'old_pilot_calibration': 'even forecast_calibration case IDs',
          'old_pilot_verification': 'odd forecast_calibration case IDs'}


def development_examples(data, teacher):
    if data['role'] not in ('forecast_fit', 'forecast_calibration'):
        raise ValueError('Only historical development roles may train admission')
    public = data['features']
    metric = data['metrics']['primary']['joint_fact_correct']
    if public.shape[1:] != (5, 763) or metric.shape[1:] != (21,):
        raise ValueError('Wrong historical counterfactual tree shape')
    hidden, moments, labels = [], [], []
    for node in range(5):
        head = teacher.two if node == 0 else teacher.one
        x = features(public[:, node], teacher.mode)
        with torch.no_grad():
            h = head.network[:2]((x - head.mean) / head.scale)
            h = torch.from_numpy(quantize(h.double().numpy()) / Q).float()
            hidden.append(h)
            moments.append(head(x))
        labels.append(metric[:, :5] if node == 0 else
                      torch.cat((metric[:, node:node + 1], metric[:, 5 + 4 * (node - 1):9 + 4 * (node - 1)]), 1))
    return torch.stack(hidden, 1), torch.stack(labels, 1), torch.stack(moments, 1)


def probabilities(predictor, hidden, horizon):
    if horizon not in (1, 2):
        raise ValueError('Exactly H1 or H2 is supported')
    layer = predictor['heads'][horizon - 1]
    raw = np.asarray(hidden) @ np.asarray(layer['weight']).T + np.asarray(layer['bias'])
    return 1. / (1. + np.exp(-np.clip(raw, -80., 80.)))


def calibrated(calibration, raw, absent, horizon, action):
    raw, absent, horizon, action = np.broadcast_arrays(raw, absent, horizon, action)
    result = np.empty(raw.shape, dtype=np.float64)
    for h in (1, 2):
        for a in range(5):
            selected = (horizon == h) & (action == a)
            stratum = calibration['strata'][h - 1][a]
            group = np.searchsorted(stratum['cuts'], raw[selected], side='right')
            values = np.asarray(stratum['probabilities'])[group]
            values = np.where(absent[selected], stratum['absent_probability'], values)
            result[selected] = values
    if np.any(~np.isin(horizon, (1, 2))) or np.any(~np.isin(action, range(5))):
        raise ValueError('Unknown horizon or action')
    q24 = np.floor(result * Q + .5).astype(np.int64)
    confidence = 1_000_000 - np.minimum(np.abs(Q - q24) * 1_000_000 // Q, 1_000_000)
    return confidence / 1e6


def fit_calibration(predictor, data):
    strata = []
    for h in (1, 2):
        group = []
        for a in range(5):
            keep = (data['horizon'] == h) & (data['action'] == a)
            absent = data['absent'].astype(bool)
            cuts = predictor['cuts'][h - 1][a]
            bins = np.searchsorted(cuts, data['raw_probability'], side='right')
            labels = [data['y'][keep & ~absent & (bins == b)] for b in range(3)]
            absent_y = data['y'][keep & absent]
            if not len(absent_y) or any(not len(y) for y in labels):
                raise ValueError('Empty fixed horizon/action calibration bin')
            group.append({'cuts': cuts, 'probabilities': [float(y.mean()) for y in labels],
                          'absent_probability': float(absent_y.mean()),
                          'calibration_bin_counts': [len(y) for y in labels]})
        strata.append(group)
    return {'schema': 'hepta.next.native-h2-admission-calibration.v1', 'strata': strata,
            'algorithm': 'fixed three ID bins per horizon/action and one public-absence bin',
            'target': CONFIG['target'], 'no_bound_relaxation': True}


def statistics(calibration, data, *, writer_bound=True):
    p = calibrated(calibration, data['raw_probability'], data['absent'], data['horizon'], data['action'])
    y, absent = data['y'], data['absent'].astype(bool)
    accept = p >= CONFIG['minimum_confidence']
    writers = np.unique(data['writer'][absent])
    false = sum(bool(accept[(data['writer'] == writer) & absent].any()) for writer in writers)
    from scipy.stats import beta
    upper = 1. if false == len(writers) else float(beta.ppf(.95, false + 1, len(writers) - false))
    grouped = {}
    for h in (1, 2):
        for a in range(5):
            keep = (data['horizon'] == h) & (data['action'] == a) & ~absent
            grouped[f'H{h}:{ACTIONS[a]}'] = {'rows': int(keep.sum()), 'ECE_ID': ece(p[keep], y[keep]),
                                           'ID_acceptance': float(accept[keep].mean())}
    return {'rows': len(p), 'independent_units': len(np.unique(data['writer'])),
            'ood_units': len(writers), 'unit_is_writer': writer_bound,
            'ECE_ID': ece(p[~absent], y[~absent]), 'ECE_all': ece(p, y),
            'ID_acceptance': float(accept[~absent].mean()), 'OOD_false_units': int(false),
            'OOD_FAR': false / len(writers), 'OOD_upper95': upper,
            'Brier': float(np.mean((p - y) ** 2)), 'by_horizon_action': grouped}


def old_arrays(data, hidden, labels, predictor):
    permitted = np.isin(data['views'], (*ID_VIEWS, 'both_missing'))
    arrays = {key: [] for key in ('raw_probability', 'y', 'absent', 'writer', 'pair', 'action', 'horizon', 'node')}
    for node in range(5):
        horizon = 2 if node == 0 else 1
        raw = probabilities(predictor, hidden[:, node].numpy(), horizon)
        for a in range(5):
            values = {'raw_probability': raw[:, a], 'y': labels[:, node, a].numpy(),
                      'absent': np.asarray(data['views']) == 'both_missing',
                      'writer': np.asarray(data['cases']), 'pair': np.asarray(data['cases']),
                      'action': np.full(len(raw), a), 'horizon': np.full(len(raw), horizon),
                      'node': np.full(len(raw), node)}
            for key, value in values.items():
                arrays[key].append(value[permitted])
    return {key: np.concatenate(values) for key, values in arrays.items()}


def selected_diagnostics(data, hidden, labels, moments, predictor, calibration):
    selected = {'ndu': [], 'correctness': []}
    permitted = np.isin(data['views'], ID_VIEWS)
    for i in np.flatnonzero(permitted):
        for policy in selected:
            node = 0
            for step in range(2):
                horizon = 2 if node == 0 else 1
                raw = probabilities(predictor, hidden[i, node].numpy(), horizon)
                p = calibrated(calibration, raw, False, horizon, np.arange(5))
                eligible = [a for a in range(5) if p[a] >= .75 and not (horizon == 1 and a == 1)]
                if not eligible:
                    break
                priority = (1, 0, 2, 4, 3)
                a = min(eligible, key=lambda a: (float(moments[i, node, a]), a)) if policy == 'ndu' else max(eligible, key=lambda a: (p[a], priority[a]))
                selected[policy].append((p[a], float(labels[i, node, a]), horizon, a))
                if horizon == 1 or a == 0:
                    break
                node = a
    result = {}
    for policy, rows in selected.items():
        values = np.asarray(rows).reshape(-1, 4)
        result[policy] = {'selected_steps': len(rows), 'ECE': ece(values[:, 0], values[:, 1]) if len(rows) else None,
                          'scope': 'actual old counterfactual tree visited by this admission-masked policy',
                          'by_horizon': {str(h): {'steps': int((values[:, 2] == h).sum()),
                                        'ECE': ece(values[values[:, 2] == h, 0], values[values[:, 2] == h, 1])
                                        if np.any(values[:, 2] == h) else None} for h in (1, 2)}}
    return result


def fit(output):
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    torch.set_num_threads(1)
    paths = [SHARED / f'abc4-control-runs/development-001/seed-17/{role}/data.pt' for role in ('fit', 'selection')]
    write(output / 'registration.json', {'config': CONFIG, 'teacher_sha256': sha(TEACHER),
          'input_sha256': {str(p): sha(p) for p in paths}, 'source_sha256': sha(__file__),
          'new_sources_read': False, 'old_H1_qualification_inherited': False})
    teacher = load_controller(TEACHER)
    if teacher.hidden != 32 or teacher.mode != 'enriched':
        raise ValueError('Exact qualified teacher architecture changed')
    datasets = [torch.load(p, map_location='cpu', weights_only=True) for p in paths]
    x, y, _ = development_examples(datasets[0], teacher)
    sx, sy, sm = development_examples(datasets[1], teacher)
    layers, cuts, traces = [], [], []
    id_fit = np.isin(datasets[0]['views'], ID_VIEWS)
    for h in (1, 2):
        hx, hy = (x[:, 1:].flatten(0, 1), y[:, 1:].flatten(0, 1)) if h == 1 else (x[:, 0], y[:, 0])
        with torch.random.fork_rng():
            torch.manual_seed(CONFIG['seed'] + h)
            head = nn.Linear(32, 5)
        optimizer = torch.optim.AdamW(head.parameters(), lr=CONFIG['learning_rate'], weight_decay=CONFIG['weight_decay'])
        rng = torch.Generator().manual_seed(CONFIG['seed'] + 10 + h)
        trace = []
        for step in range(CONFIG['steps']):
            ids = torch.randint(len(hx), (CONFIG['batch_size'],), generator=rng)
            optimizer.zero_grad(set_to_none=True)
            loss = F.binary_cross_entropy_with_logits(head(hx[ids]), hy[ids])
            loss.backward(); optimizer.step()
            if (step + 1) % 200 == 0:
                trace.append({'step': step + 1, 'BCE': float(loss.detach())})
        layer = {'weight': head.weight.detach().double().tolist(), 'bias': head.bias.detach().double().tolist()}
        layers.append(layer); traces.append(trace)
        with torch.no_grad():
            raw = head(hx).sigmoid().numpy()
        keep = np.repeat(id_fit, 4) if h == 1 else id_fit
        cuts.append([np.quantile(raw[keep, a], [1 / 3, 2 / 3]).tolist() for a in range(5)])
    predictor = {'schema': 'hepta.next.native-h2-admission-predictor.v1', 'config': CONFIG,
                 'heads': layers, 'cuts': cuts, 'teacher_sha256': sha(TEACHER),
                 'action_order': ACTIONS, 'head_order': ['H1', 'H2'], 'target': CONFIG['target'],
                 'trace': traces, 'new_trainable_parameters': 330}
    arrays = old_arrays(datasets[1], sx, sy, predictor)
    cal = {key: value[arrays['pair'] % 2 == 0] for key, value in arrays.items()}
    verification = {key: value[arrays['pair'] % 2 == 1] for key, value in arrays.items()}
    calibration = fit_calibration(predictor, cal)
    before, after = statistics(calibration, cal, writer_bound=False), statistics(calibration, verification, writer_bound=False)
    gates = {'old_split_point_ECE': max(before['ECE_ID'], before['ECE_all'], after['ECE_ID'], after['ECE_all']) <= .03,
             'old_split_nonvacuity': min(before['ID_acceptance'], after['ID_acceptance']) >= .25,
             'old_split_zero_OOD_false_source_pairs': before['OOD_false_units'] == after['OOD_false_units'] == 0}
    selected = selected_diagnostics(datasets[1], sx, sy, sm, predictor, calibration)
    write(output / 'predictor.json', predictor)
    write(output / 'old-pilot-calibration.json', calibration)
    result = {'schema': 'hepta.next.native-h2-old-development.v1', 'status': 'completed',
              'predictor_sha256': sha(output / 'predictor.json'), 'registration_sha256': sha(output / 'registration.json'),
              'old_calibration': before, 'old_verification': after, 'old_feasibility_gates': gates,
              'new_source_candidate_admitted': all(gates.values()), 'selected_policy_calibration': selected,
              'selected_diagnostic_is_not_independent_qualification': True,
              'insufficient_old_units_for_FAR_bound_not_relaxed': True,
              'planned_1000writer_zero_error_upper95': 1 - .05 ** (1 / 1000),
              'new_sources_opened': False, 'wall_ns': time.perf_counter_ns() - began,
              'production_authority': False}
    write(output / 'development.json', result)
    print(json.dumps(result), flush=True)


def calibrate(predictor_path, data_path, output):
    output.mkdir(parents=True, exist_ok=False)
    predictor = json.loads(predictor_path.read_text())
    with np.load(data_path, allow_pickle=False) as archive:
        data = {k: archive[k] for k in archive.files}
    result = fit_calibration(predictor, data)
    result.update(predictor_sha256=sha(predictor_path), data_sha256=sha(data_path))
    result['calibration'] = statistics(result, data)
    write(output / 'calibration.json', result)
    write(output / 'calibrator-freeze.json', {'predictor_sha256': sha(predictor_path),
          'calibration_sha256': sha(output / 'calibration.json'), 'frozen_unix_ns': time.time_ns()})
    print(json.dumps(result['calibration']), flush=True)


def verify(calibration_path, data_path, output):
    calibration = json.loads(calibration_path.read_text())
    with np.load(data_path, allow_pickle=False) as archive:
        data = {k: archive[k] for k in archive.files}
    result = statistics(calibration, data)
    before = calibration['calibration']
    max_ece = max(before['ECE_ID'], before['ECE_all'], result['ECE_ID'], result['ECE_all'])
    max_far = max(before['OOD_FAR'], result['OOD_FAR'])
    result['gates'] = {'calibration_and_verification_point_ece': max_ece <= .03,
                       'calibration_and_verification_point_far': max_far <= .004999,
                       'calibration_and_verification_id_nonvacuity': min(before['ID_acceptance'], result['ID_acceptance']) >= .25,
                       'verification_ood_writer_upper95': result['OOD_upper95'] <= .004999}
    result.update(schema='hepta.next.native-h2-admission-verification.v1',
                  study_qualified=all(result['gates'].values()),
                  native_measured_ece_ppm=math.ceil(max_ece * 1e6),
                  native_measured_false_acceptance_ppm=math.ceil(max_far * 1e6),
                  calibration_sha256=sha(calibration_path), data_sha256=sha(data_path),
                  old_qualification_inherited=False, production_authority=False)
    write(output, result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('fit'); p.add_argument('--output', type=Path, required=True)
    for command in ('calibrate', 'verify'):
        p = sub.add_parser(command)
        p.add_argument('--predictor' if command == 'calibrate' else '--calibration', type=Path, required=True)
        p.add_argument('--data', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'fit': fit(args.output)
    elif args.command == 'calibrate': calibrate(args.predictor, args.data, args.output)
    else: verify(args.calibration, args.data, args.output)
