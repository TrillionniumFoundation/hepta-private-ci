"""New five-action admission evidence; old native qualification is never reused.

Development uses only the historical forecast fit/selection sources. The model
is a linear correctness head on the frozen 32-coordinate H1 value encoder.
Fresh calibration and verification are separate immutable stages.
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

from ...abc_next.value import features, load_controller
from ...abc_followup.native.forecast import Q
from .common import SHARED, TEACHER, sha, write


CONFIG = {'seed': 261025731, 'steps': 1200, 'batch_size': 512,
          'learning_rate': .01, 'weight_decay': .001, 'hidden': 32,
          'old_prefix_node': 2, 'calibration_bins': 3,
          'maximum_ece': .03, 'maximum_far': .004999,
          'minimum_id_acceptance': .25, 'minimum_confidence': .75}


def development_examples(data, teacher):
    if data['role'] not in ('forecast_fit', 'forecast_calibration'):
        raise ValueError('Only original development roles may fit the new admission head')
    public = data['features'][:, 2]
    head = teacher.one
    x = features(public, teacher.mode)
    with torch.no_grad():
        hidden = head.network[:2]((x - head.mean) / head.scale)
    metric = data['metrics']['primary']['joint_fact_correct']
    labels = torch.cat((metric[:, 2:3], metric[:, 9:13]), 1)
    return hidden, labels


def fit(output):
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    torch.set_num_threads(1)
    paths = [SHARED / f'abc4-control-runs/development-001/seed-17/{role}/data.pt'
             for role in ('fit', 'selection')]
    write(output / 'registration.json', {'config': CONFIG, 'teacher_sha256': sha(TEACHER),
          'input_sha256': {str(p): sha(p) for p in paths}, 'source_sha256': sha(__file__),
          'fit_roles': ['forecast_fit'], 'selection_roles': ['forecast_calibration'],
          'new_sources_read': False, 'formal_old_holdout_used_for_fitting': False})
    teacher = load_controller(TEACHER)
    if teacher.hidden != 32 or teacher.mode != 'enriched':
        raise ValueError('Frozen teacher architecture changed')
    datasets = [torch.load(p, map_location='cpu', weights_only=True) for p in paths]
    x, y = development_examples(datasets[0], teacher)
    sx, sy = development_examples(datasets[1], teacher)
    with torch.random.fork_rng():
        torch.manual_seed(CONFIG['seed'])
        head = nn.Linear(32, 5)
    optimizer = torch.optim.AdamW(head.parameters(), lr=CONFIG['learning_rate'],
                                   weight_decay=CONFIG['weight_decay'])
    rng = torch.Generator().manual_seed(CONFIG['seed'] + 1)
    trace = []
    for step in range(CONFIG['steps']):
        ids = torch.randint(len(x), (CONFIG['batch_size'],), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        loss = F.binary_cross_entropy_with_logits(head(x[ids]), y[ids])
        loss.backward()
        optimizer.step()
        if (step + 1) % 200 == 0:
            trace.append({'step': step + 1, 'loss': float(loss.detach())})
    with torch.no_grad():
        probability = head(sx).sigmoid().numpy()
        selection_loss = float(F.binary_cross_entropy_with_logits(head(sx), sy))
    # Fixed development-only bin cuts; fresh calibration estimates only bin rates.
    id_rows = np.asarray(datasets[1]['views']) != 'both_missing'
    cuts = np.quantile(probability[id_rows].reshape(-1), [1 / 3, 2 / 3]).tolist()
    value = {'schema': 'hepta.next.native-admission-predictor.v1', 'config': CONFIG,
             'weight': head.weight.detach().double().tolist(), 'bias': head.bias.detach().double().tolist(),
             'cuts': cuts, 'teacher_sha256': sha(TEACHER), 'state_prefix': 'initialize_then_refine_image',
             'action_order': ['stop', 'refine_semantic', 'refine_image', 'refine_text', 'couple'],
             'target': 'actual primary observer joint_fact_correct', 'trace': trace,
             'selection_BCE': selection_loss, 'selection_raw_acceptance': float((probability[id_rows] >= .75).mean()),
             'fitting_sources': 256, 'selection_sources': 128,
             'wall_ns': time.perf_counter_ns() - began}
    write(output / 'predictor.json', value)
    write(output / 'predictor-freeze.json', {'predictor_sha256': sha(output / 'predictor.json'),
          'registration_sha256': sha(output / 'registration.json'), 'frozen_unix_ns': time.time_ns()})
    print(json.dumps({k: value[k] for k in ('selection_BCE', 'selection_raw_acceptance', 'cuts', 'wall_ns')}))


def probabilities(predictor, hidden):
    raw = np.asarray(hidden) @ np.asarray(predictor['weight']).T + np.asarray(predictor['bias'])
    return 1. / (1. + np.exp(-np.clip(raw, -80., 80.)))


def ece(p, y):
    bins = np.minimum((np.asarray(p) * 10).astype(int), 9)
    return sum(float(np.mean(bins == b) * abs(np.mean(p[bins == b]) - np.mean(y[bins == b])))
               for b in range(10) if np.any(bins == b))


def calibrated(calibration, raw, absent):
    group = np.searchsorted(calibration['cuts'], raw, side='right')
    probability = np.asarray(calibration['probabilities'])[group]
    probability[np.asarray(absent, dtype=bool)] = calibration['absent_probability']
    q24 = np.floor(probability * Q + .5).astype(np.int64)
    confidence = 1_000_000 - np.minimum(np.abs(Q - q24) * 1_000_000 // Q, 1_000_000)
    return confidence / 1e6


def statistics(calibration, data):
    p = calibrated(calibration, data['raw_probability'], data['absent'])
    y, absent = data['y'], data['absent'].astype(bool)
    accept = p >= CONFIG['minimum_confidence']
    # Each writer is an independent unit, even if many views/draws were collected.
    writers = np.unique(data['writer'][absent])
    false = sum(bool(accept[(data['writer'] == writer) & absent].any()) for writer in writers)
    from scipy.stats import beta
    upper = 1. if false == len(writers) else float(beta.ppf(.95, false + 1, len(writers) - false))
    return {'rows': len(p), 'writers': len(np.unique(data['writer'])), 'ood_writers': len(writers),
            'ECE_ID': ece(p[~absent], y[~absent]), 'ECE_all': ece(p, y),
            'ID_acceptance': float(accept[~absent].mean()), 'OOD_false_writers': int(false),
            'OOD_FAR': false / len(writers), 'OOD_upper95': upper,
            'Brier': float(np.mean((p - y) ** 2)),
            'by_action': {str(a): {'ECE': ece(p[data['action'] == a], y[data['action'] == a]),
                                   'acceptance': float(accept[(data['action'] == a) & ~absent].mean())}
                          for a in range(5)}}


def calibrate(predictor_path, data_path, output):
    output.mkdir(parents=True, exist_ok=False)
    predictor = json.loads(predictor_path.read_text())
    with np.load(data_path, allow_pickle=False) as archive:
        data = {k: archive[k] for k in archive.files}
    group = np.searchsorted(predictor['cuts'], data['raw_probability'], side='right')
    id_rows = ~data['absent'].astype(bool)
    probabilities_ = []
    for k in range(3):
        labels = data['y'][id_rows & (group == k)]
        if not len(labels):
            raise ValueError('Empty fixed calibration bin')
        probabilities_.append(float(labels.mean()))
    absent_y = data['y'][~id_rows]
    if not len(absent_y):
        raise ValueError('Missing registered OOD calibration rows')
    result = {'schema': 'hepta.next.native-admission-calibration.v1',
              'predictor_sha256': sha(predictor_path), 'data_sha256': sha(data_path),
              'cuts': predictor['cuts'], 'probabilities': probabilities_,
              'absent_probability': float(absent_y.mean()), 'algorithm': 'fixed 3 pooled ID bins plus observed-absent bin',
              'no_bound_relaxation': True}
    result['calibration'] = statistics(result, data)
    write(output / 'calibration.json', result)
    write(output / 'calibrator-freeze.json', {'predictor_sha256': sha(predictor_path),
          'calibration_sha256': sha(output / 'calibration.json'), 'frozen_unix_ns': time.time_ns()})
    print(json.dumps(result['calibration']))


def verify(calibration_path, data_path, output):
    calibration = json.loads(calibration_path.read_text())
    with np.load(data_path, allow_pickle=False) as archive:
        data = {k: archive[k] for k in archive.files}
    result = statistics(calibration, data)
    before = calibration['calibration']
    max_ece = max(before['ECE_ID'], before['ECE_all'], result['ECE_ID'], result['ECE_all'])
    max_far = max(before['OOD_FAR'], result['OOD_FAR'])
    result['gates'] = {
        'calibration_and_verification_point_ece': max_ece <= .03,
        'calibration_and_verification_point_far': max_far <= .004999,
        'calibration_and_verification_id_nonvacuity': min(before['ID_acceptance'], result['ID_acceptance']) >= .25,
        'verification_ood_writer_upper95': result['OOD_upper95'] <= .004999}
    result.update(schema='hepta.next.native-admission-verification.v1',
                  study_qualified=all(result['gates'].values()),
                  native_measured_ece_ppm=math.ceil(max_ece * 1e6),
                  native_measured_false_acceptance_ppm=math.ceil(max_far * 1e6),
                  calibration_sha256=sha(calibration_path), data_sha256=sha(data_path),
                  old_qualification_inherited=False, production_authority=False)
    write(output, result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('fit'); p.add_argument('--output', type=Path, required=True)
    for name in ('calibrate', 'verify'):
        p = sub.add_parser(name)
        p.add_argument('--predictor' if name == 'calibrate' else '--calibration', type=Path, required=True)
        p.add_argument('--data', type=Path, required=True)
        p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'fit': fit(args.output)
    elif args.command == 'calibrate': calibrate(args.predictor, args.data, args.output)
    else: verify(args.calibration, args.data, args.output)
