"""Second development candidate: complete public features for correctness only.

The evaluated NDU teacher is unchanged. Normalizers are fit-source-only and
the new first layer belongs to the explicitly costed public encoder.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ...abc_followup.native.forecast import Q, quantize
from ...abc_next.value import load_controller
from .common import AREA, SHARED, TEACHER, sha, write
from .qualification import ID_VIEWS, ACTIONS, CONFIG, development_examples, old_arrays
from .qualification import fit_calibration, statistics, selected_diagnostics


FIT = {**CONFIG, 'candidate': 'full_public_correctness_64_v2', 'hidden': 64,
       'input': 'all 763 existing public features including remaining budget',
       'learning_rate': .003, 'weight_decay': .01, 'seed': 261026873,
       'steps': 1200, 'previous_candidate': 'development-001 failed old held-source ECE .0465078289',
       'teacher_updated': False, 'native_ABI_dimension': 103,
       'new_source_candidates_limit': 'No new-source access before old feasibility and prospective freeze'}


def hidden(predictor, public, horizon):
    encoder = predictor['encoder_heads'][horizon - 1]
    x = np.asarray(public, dtype=np.float32)
    normalized = (x - np.asarray(encoder['mean'], dtype=np.float32)) / np.asarray(encoder['scale'], dtype=np.float32)
    value = np.tanh(normalized @ np.asarray(encoder['weight'], dtype=np.float32).T + np.asarray(encoder['bias'], dtype=np.float32))
    return quantize(value.astype(np.float64)) / Q


def fit(output):
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter_ns()
    torch.set_num_threads(1)
    paths = [SHARED / f'abc4-control-runs/development-001/seed-17/{role}/data.pt' for role in ('fit', 'selection')]
    source_pins = {str(path.resolve()): sha(path) for path in (Path(__file__), AREA / 'qualification.py', AREA / 'common.py')}
    write(output / 'registration.json', {'config': FIT, 'teacher_sha256': sha(TEACHER),
          'input_sha256': {str(p): sha(p) for p in paths}, 'source_sha256': source_pins,
          'new_sources_read': False, 'previous_candidate_preserved': True,
          'old_H1_qualification_inherited': False})
    teacher = load_controller(TEACHER)
    if teacher.hidden != 32 or teacher.mode != 'enriched':
        raise ValueError('Exact evaluated teacher architecture changed')
    datasets = [torch.load(p, map_location='cpu', weights_only=True) for p in paths]
    _, y, _ = development_examples(datasets[0], teacher)
    _, sy, sm = development_examples(datasets[1], teacher)
    x, sx = datasets[0]['features'], datasets[1]['features']
    layers, encoders, cuts, traces = [], [], [], []
    id_fit = np.isin(datasets[0]['views'], ID_VIEWS)
    for h in (1, 2):
        hx, hy = (x[:, 1:].flatten(0, 1), y[:, 1:].flatten(0, 1)) if h == 1 else (x[:, 0], y[:, 0])
        mean, scale = hx.mean(0), hx.std(0, unbiased=False)
        scale = torch.where(scale > 1e-6, scale, torch.ones_like(scale))
        nx = (hx - mean) / scale
        with torch.random.fork_rng():
            torch.manual_seed(FIT['seed'] + h)
            head = nn.Sequential(nn.Linear(763, 64), nn.Tanh(), nn.Linear(64, 5))
        optimizer = torch.optim.AdamW(head.parameters(), lr=FIT['learning_rate'], weight_decay=FIT['weight_decay'])
        rng = torch.Generator().manual_seed(FIT['seed'] + 10 + h)
        trace = []
        for step in range(FIT['steps']):
            ids = torch.randint(len(nx), (FIT['batch_size'],), generator=rng)
            optimizer.zero_grad(set_to_none=True)
            loss = F.binary_cross_entropy_with_logits(head(nx[ids]), hy[ids])
            loss.backward(); optimizer.step()
            if (step + 1) % 200 == 0:
                trace.append({'step': step + 1, 'BCE': float(loss.detach())})
        layers.append({'weight': head[2].weight.detach().double().tolist(),
                       'bias': head[2].bias.detach().double().tolist()})
        encoders.append({'mean': mean.double().tolist(), 'scale': scale.double().tolist(),
                         'weight': head[0].weight.detach().double().tolist(),
                         'bias': head[0].bias.detach().double().tolist()})
        traces.append(trace)
        with torch.no_grad():
            raw = head(nx).sigmoid().numpy()
        keep = np.repeat(id_fit, 4) if h == 1 else id_fit
        cuts.append([np.quantile(raw[keep, a], [1 / 3, 2 / 3]).tolist() for a in range(5)])
    predictor = {'schema': 'hepta.next.native-h2-public-admission.v2', 'config': FIT,
                 'heads': layers, 'encoder_heads': encoders, 'cuts': cuts,
                 'teacher_sha256': sha(TEACHER), 'action_order': ACTIONS,
                 'head_order': ['H1', 'H2'], 'target': FIT['target'], 'trace': traces,
                 'new_trainable_parameters': 2 * (763 * 64 + 64 + 64 * 5 + 5)}
    projected = torch.stack([torch.from_numpy(hidden(predictor, sx[:, node].numpy(), 2 if node == 0 else 1))
                             for node in range(5)], 1)
    arrays = old_arrays(datasets[1], projected, sy, predictor)
    cal = {key: value[arrays['pair'] % 2 == 0] for key, value in arrays.items()}
    verification = {key: value[arrays['pair'] % 2 == 1] for key, value in arrays.items()}
    calibration = fit_calibration(predictor, cal)
    before = statistics(calibration, cal, writer_bound=False)
    after = statistics(calibration, verification, writer_bound=False)
    gates = {'old_split_point_ECE': max(before['ECE_ID'], before['ECE_all'], after['ECE_ID'], after['ECE_all']) <= .03,
             'old_split_nonvacuity': min(before['ID_acceptance'], after['ID_acceptance']) >= .25,
             'old_split_zero_OOD_false_source_pairs': before['OOD_false_units'] == after['OOD_false_units'] == 0}
    held = np.asarray(datasets[1]['cases']) % 2 == 1
    held_views = {'views': np.asarray(datasets[1]['views'])[held]}
    selected = selected_diagnostics(held_views, projected[held], sy[held], sm[held], predictor, calibration)
    write(output / 'predictor.json', predictor)
    write(output / 'old-pilot-calibration.json', calibration)
    np.savez_compressed(output / 'old-selection-predictions.npz', **arrays)
    result = {'schema': 'hepta.next.native-h2-old-development.v2', 'status': 'completed',
              'predictor_sha256': sha(output / 'predictor.json'), 'registration_sha256': sha(output / 'registration.json'),
              'old_calibration': before, 'old_verification': after, 'old_feasibility_gates': gates,
              'new_source_candidate_admitted': all(gates.values()), 'selected_policy_calibration': selected,
              'selected_policy_old_split': '64 held odd source pairs, excluding pilot calibration pairs',
              'selected_diagnostic_is_not_independent_qualification': True,
              'insufficient_old_units_for_FAR_bound_not_relaxed': True,
              'planned_1000writer_zero_error_upper95': 1 - .05 ** (1 / 1000),
              'new_sources_opened': False, 'wall_ns': time.perf_counter_ns() - began,
              'source_identity_unchanged': all(sha(path) == expected for path, expected in source_pins.items()),
              'production_authority': False}
    write(output / 'development.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    fit(parser.parse_args().output)
