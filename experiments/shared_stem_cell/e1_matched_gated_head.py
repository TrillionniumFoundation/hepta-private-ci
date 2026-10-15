#!/usr/bin/env python3
"""Research-only equal-parameter Head probe on the ORIGINAL P0 feature bank.

The optional fixed projection is shared and charged, not a learned free adapter.
Original pretrained origin, future utility and production admission remain unproved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

SCHEMA = 'hepta.e1.matched-projected-gated-head.v1'
PROJECTED_WIDTH = 128
HIDDEN = 16
STEPS = 40
LR = 0.1
SEEDS = (41, 47, 53)
TEMPERATURES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
ARMS = ('frozen_additive', 'trained_additive', 'frozen_gated', 'trained_gated')
PARAMETERS = HIDDEN * (2 * PROJECTED_WIDTH + 3) + 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def state_digest(state):
    return digest(b''.join(k.encode() + b'\0' + v.detach().cpu().contiguous().numpy().tobytes()
                           for k, v in sorted(state.items())))


class MatchedHead(nn.Module):
    """Both alternatives have identical tensors; every tensor participates."""
    def __init__(self, kind):
        super().__init__()
        if kind not in ('additive', 'gated'):
            raise ValueError('unregistered Head architecture')
        self.kind = kind
        self.a = nn.Linear(PROJECTED_WIDTH, HIDDEN, dtype=torch.float32)
        self.b = nn.Linear(PROJECTED_WIDTH, HIDDEN, dtype=torch.float32)
        self.out = nn.Linear(HIDDEN, 1, dtype=torch.float32)

    def forward(self, x):
        a, b = self.a(x), self.b(x)
        hidden = (torch.tanh(a) * torch.sigmoid(b) if self.kind == 'gated'
                  else (torch.tanh(a) + torch.tanh(b)) / math.sqrt(2.0))
        return self.out(hidden).squeeze(-1)


def checked_inputs(features, train_idx, train_y, cal_idx, cal_y, blind_idx):
    if (not isinstance(features, np.ndarray) or features.dtype != np.float32
            or features.ndim != 2 or not 1 <= features.shape[0] <= 1024
            or features.shape[1] not in (256, 384, 768)
            or not np.isfinite(features).all() or np.abs(features).max() > 8):
        raise ValueError('expected bounded original FP32 feature matrix')
    groups = (train_idx, cal_idx, blind_idx)
    for idx in groups:
        if (type(idx) is not list or not idx or any(type(i) is not int for i in idx)
                or len(set(idx)) != len(idx) or min(idx) < 0 or max(idx) >= len(features)):
            raise ValueError('missing, duplicate or out-of-range source row')
    if any(set(groups[i]) & set(groups[j]) for i in range(3) for j in range(i)):
        raise ValueError('fit/calibration/blind row overlap')
    for idx, labels in ((train_idx, train_y), (cal_idx, cal_y)):
        if (type(labels) is not list or len(labels) != len(idx)
                or any(type(v) is not int or v not in (0, 1) for v in labels)
                or set(labels) != {0, 1}):
            raise ValueError('missing original binary TRAIN/CAL labels')
    if len(train_idx) < 24 or len(cal_idx) < 8:
        raise ValueError('insufficient original TRAIN/CAL rows')


def run_probe(features, train_idx, train_y, cal_idx, cal_y, blind_idx):
    """No held labels accepted. All Heads reuse one physically projected bank.

    This low-level numerical kernel does NOT certify the origin of its input.
    The CLI below first runs the original P0 source/numeric replay owner.
    """
    checked_inputs(features, train_idx, train_y, cal_idx, cal_y, blind_idx)
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        return _run(features, train_idx, train_y, cal_idx, cal_y, blind_idx)
    finally:
        torch.set_num_threads(old_threads)


def _run(features, train_idx, train_y, cal_idx, cal_y, blind_idx):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    input_digest = digest(features.tobytes(order='C'))
    # NumPy PCG64, independent of task labels, Head seed and evaluation scores.
    rng = np.random.Generator(np.random.PCG64(20261015))
    projection = (rng.standard_normal((features.shape[1], PROJECTED_WIDTH))
                  / math.sqrt(PROJECTED_WIDTH)).astype(np.float32)
    with torch.no_grad():
        projected = torch.from_numpy(features) @ torch.from_numpy(projection)
    # Materialize each split ONCE; all seeds and Heads read the same tensors.
    train_x = projected[train_idx]
    cal_x = projected[cal_idx]
    blind_x = projected[blind_idx]
    ty = torch.tensor(train_y, dtype=torch.float32)
    cy = torch.tensor(cal_y, dtype=torch.float32)
    shared_wall = (time.perf_counter_ns() - wall) / 1e6
    shared_cpu = (time.process_time_ns() - cpu) / 1e6
    tensors = {'shared_projection': projection}
    records = []
    for seed in SEEDS:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            initial = MatchedHead('gated')
        start_state = initial.state_dict()
        initial_sha = state_digest(start_state)
        for arm in ARMS:
            kind = arm.removeprefix('trained_').removeprefix('frozen_')
            # deepcopy consumes no random numbers and owns independent parameters.
            head = copy.deepcopy(initial)
            head.kind = kind
            training = arm.startswith('trained_')
            head.requires_grad_(training)
            if sum(p.numel() for p in head.parameters()) != PARAMETERS:
                raise ValueError('wrong physical Head parameter count')
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            if training:
                optimizer = torch.optim.SGD(head.parameters(), lr=LR)
                for _ in range(STEPS):
                    optimizer.zero_grad(set_to_none=True)
                    loss = nn.functional.binary_cross_entropy_with_logits(head(train_x), ty)
                    if not torch.isfinite(loss).item():
                        raise ValueError('nonfinite physical training loss')
                    loss.backward()
                    if any(p.grad is None or not torch.isfinite(p.grad).all().item()
                           for p in head.parameters()):
                        raise ValueError('missing/nonfinite physical gradient')
                    optimizer.step()
            fit_wall = (time.perf_counter_ns() - wall) / 1e6
            fit_cpu = (time.process_time_ns() - cpu) / 1e6
            final_sha = state_digest(head.state_dict())
            if (final_sha != initial_sha) != training:
                raise ValueError('frozen weights changed or trained weights did not change')
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            with torch.inference_mode():
                cal_logits = head(cal_x)
                losses = [float(nn.functional.binary_cross_entropy_with_logits(cal_logits / t, cy))
                          for t in TEMPERATURES]
                temp = TEMPERATURES[min(range(len(losses)), key=losses.__getitem__)]
                logits = head(blind_x)
                probabilities = torch.sigmoid(logits / temp)
                if not torch.isfinite(logits).all().item():
                    raise ValueError('nonfinite blind forecast')
            eval_wall = (time.perf_counter_ns()-wall)/1e6
            eval_cpu = (time.process_time_ns()-cpu)/1e6
            prefix = f'seed{seed}.{arm}'
            for key, value in head.state_dict().items():
                tensors[f'{prefix}.{key}'] = value.detach().cpu().numpy().copy()
            records.append({'seed': seed, 'arm': arm, 'parameter_count': PARAMETERS,
                            'initial_sha256': initial_sha, 'final_sha256': final_sha,
                            'optimizer_steps': STEPS if training else 0,
                            'training_row_exposures': len(train_idx) * STEPS if training else 0,
                            'temperature': temp, 'blind_logits': logits.tolist(),
                            'blind_probabilities': probabilities.tolist(),
                            'fit_wall_ms': fit_wall, 'fit_cpu_ms': fit_cpu,
                            'calibration_and_blind_wall_ms': eval_wall,
                            'calibration_and_blind_cpu_ms': eval_cpu})
    if digest(features.tobytes(order='C')) != input_digest:
        raise ValueError('original immutable feature bank changed')
    return {'schema': SCHEMA, 'source_width': int(features.shape[1]),
            'projected_width': PROJECTED_WIDTH, 'head_hidden_width': HIDDEN,
            'shared_projection': {'kind': 'fixed-PCG64-Gaussian-not-fitted', 'seed': 20261015,
                                  'coefficient_count': int(projection.size),
                                  'fp32_bytes': int(projection.nbytes),
                                  'linear_forward_macs': int(features.shape[0]*projection.size),
                                  'one_time_bank_wall_ms': shared_wall, 'one_time_bank_cpu_ms': shared_cpu,
                                  'projected_bank_bytes': int(projected.numel()*4),
                                  'split_buffer_bytes': int((train_x.numel()+cal_x.numel()+blind_x.numel())*4)},
            'train_indices': train_idx, 'calibration_indices': cal_idx, 'blind_indices': blind_idx,
            'input_features_sha256': input_digest, 'arms': records,
            'runtime': {'torch': torch.__version__, 'numpy': np.__version__, 'threads': 1},
            'additional_pretrained_loads': 0, 'additional_encoder_forwards': 0,
            'timing_is_counterbalanced': False, 'end_to_end_cost_equal': False,
            'native_representation_preserved': False, 'held_labels_accessed': False,
            'quality_scored': False, 'model_selection_permitted': False,
            'production_promotion_permitted': False, 'authority': 'DENY_ALL'}, tensors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('fit', 'blind', 'original-report', 'replay-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--model', choices=('granite_97m_r2', 'mmbert_small', 'embeddinggemma_2_text'), required=True)
    args = parser.parse_args()
    # Original owners remain the only entry path; no alternate loader/checkpoint.
    from p0_multirc_semantic_material import read, validate, canonical as source_canonical
    from p0_physical_replay_v5 import independent_numeric_replay
    from safetensors.numpy import load_file, save_file
    fit, blind, original = read(args.fit), read(args.blind), read(args.original_report)
    fit_rows, blind_rows = validate(fit, blind)
    prior = independent_numeric_replay(args.replay_dir, fit, blind, original, model=args.model)
    features = load_file(str(args.replay_dir/'features.safetensors'))['features_q24_fp32']
    # The original validate() is authoritative for source/label separation.
    train = [i for i, row in enumerate(fit_rows) if row['split']=='train' and row['condition']=='original']
    cal = [i for i, row in enumerate(fit_rows) if row['split']=='calibration' and row['condition']=='original']
    held = list(range(len(fit_rows), len(fit_rows)+len(blind_rows)))
    result, tensors = run_probe(features, train, [fit_rows[i]['label'] for i in train],
                               cal, [fit_rows[i]['label'] for i in cal], held)
    result.update({'original_numeric_replay': prior, 'model': args.model,
                   'original_report_sha256': digest(source_canonical(original)),
                   'original_fit_sha256': digest(source_canonical(fit)),
                   'original_blind_sha256': digest(source_canonical(blind)),
                   'blind_case_ids': [row['case_id'] for row in blind_rows],
                   'physical_model_origin_independently_authenticated': False,
                   'genuine_deployed_nochange_baseline': False})
    # Refuse a stale/reused output, including incomplete prior attempts.
    args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    weights = args.output_dir/'probe.safetensors'
    save_file(tensors, str(weights))
    with weights.open('rb') as stream:
        os.fsync(stream.fileno())
    result['probe_safetensors_sha256'] = digest(weights.read_bytes())
    with (args.output_dir/'COMMITTED.json').open('xb') as stream:
        stream.write(canonical(result)+b'\n'); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(args.output_dir, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
