#!/usr/bin/env python3
"""Independent integer Q24 adapter/Head oracle against 8 physical Rust runs.

The selected model still lacks A0 and future learning efficacy. This script
must NOT claim independent temporal-state parity or physical target-host SLO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from near_matched_capacity_design import choose
from matched_train import sha_file, unique_json, require

Q = 1 << 24
H = 8 * Q
ARMS = ('v2', 'v3', 'ssm', 'min_gru')
CAPS = (2048, 8192)
SCHEMA = 'hepta.neuron.near-matched-native-adapter-replay.v1'

def product(a: int, b: int) -> int:
    require(type(a) is int and type(b) is int, 'Q24 operands must be integers')
    magnitude = abs(a * b)
    quotient, rem = divmod(magnitude, Q)
    result = quotient + int(rem * 2 > Q or (rem * 2 == Q and quotient % 2))
    result = result if (a >= 0) == (b >= 0) else -result
    require(-(2**63) <= result < 2**63, 'native Q24 overflows i64')
    return result

def f32_q24(tensor) -> list[int]:
    return [int(round(float(x) * Q)) for x in tensor.reshape(-1).tolist()]

def physically_load(root: Path, row: dict) -> dict:
    from safetensors.torch import load
    import torch
    cap, arm, h, rank = (row['cap'], row['arm'], row['hidden_width'], row['rank'])
    require(type(cap) is int and cap in CAPS and arm in ARMS, 'invalid physical candidate')
    wanted = choose(32, arm, cap, max_rank=4)
    require(wanted is not None and h == wanted['private_temporal_width']
            and rank == wanted['min_gru_rank']
            and row['complete_realized_parameters'] == wanted['complete_proposed_private_parameters'],
            'physical tensor plan mismatch')
    require(row['weight_file'] == f'{cap}/{arm}.safetensors', 'foreign physical model path')
    path = root / row['weight_file']
    require(not path.is_symlink() and not path.parent.is_symlink(), 'symlinked weight artifact')
    sha_file(path, row['weight_sha256'])
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == row['weight_sha256'],
            'physical bytes changed between read and hash')
    loaded = load(data)
    shapes = wanted['unmaterialized_tensor_shapes']
    names = {
        'private_input_adapter.weight': 'adapter.weight',
        'private_input_adapter.bias': 'adapter.bias',
        'private_binary_head.weight': 'head.weight',
        'private_binary_head.bias': 'head.bias',
        'native_identity_projection.weight_q24': 'structure.projection',
    }
    translate = lambda name: names.get(name, name)
    required = {translate(name) for name in shapes}
    require(set(loaded) == required, 'extra/missing physical Adapter or Head tensor')
    for name, dimensions in shapes.items():
        exported = translate(name)
        t = loaded[exported]
        expected_dtype = torch.int64 if exported.startswith('temporal.') or exported=='structure.projection' else torch.float32
        require(list(t.shape) == dimensions and t.dtype == expected_dtype,
                'physical tensor dimension or dtype mismatch: ' + exported)
        if expected_dtype == torch.int64:
            if exported == 'structure.projection':
                require(bool((t == Q).all()), 'fake native Q24 identity projection')
            elif arm == 'v3' and exported == 'temporal.gate_bias' or (
                    arm == 'ssm' and exported == 'temporal.decay_per_step'):
                require(bool(((t >= 0) & (t <= Q)).all()), 'invalid nonnegative temporal parameter')
            else:
                require(bool((t.abs() <= Q).all()), 'invalid signed temporal Q24')
        else:
            require(bool(torch.isfinite(t).all()) and bool((t.abs() <= 8).all()),
                    'nonfinite/out-of-range F32 adapter or Head')
    require(sum(t.numel() for t in loaded.values()) == row['complete_realized_parameters'],
            'physical model scalars silently drifted')
    return loaded

def adapter(features: list[int], prediction: list[int], bank: dict, hidden: int) -> tuple[list[int], list[int]]:
    require(type(features) is list and type(prediction) is list
            and len(features) == len(prediction) == 32
            and all(type(v) is int and -H <= v <= H for v in features + prediction),
            'source feature does not match registered Q24 32D input')
    matrix = f32_q24(bank['adapter.weight'])
    bias = f32_q24(bank['adapter.bias'])
    require(len(matrix) == hidden * 32 and len(bias) == hidden,
            'physical Q24 Adapter projection shape mismatch')
    drive, projected_prediction = [], []
    for row in range(hidden):
        observed = bias[row]
        expect = 0
        for column in range(32):
            coefficient = matrix[row * 32 + column]
            observed += product(coefficient, features[column])
            expect += product(coefficient, prediction[column])
        drive.append(max(-H, min(H, observed)))
        projected_prediction.append(max(-H, min(H, expect)))
    return drive, projected_prediction

def head_logit(bank: dict, activation: list[int]) -> int:
    weights = f32_q24(bank['head.weight'])
    bias = f32_q24(bank['head.bias'])
    require(type(activation) is list and len(activation) == len(weights)
            and all(type(x) is int and -H <= x <= H for x in activation),
            'native Head activation does not match physical weights')
    return bias[0] + sum(product(w, x) for w, x in zip(weights, activation))

def verify(receipt: dict, trace: dict, row: dict, bank: dict, trace_sha: str) -> dict:
    require(type(receipt) is dict and receipt.get('schema') == SCHEMA
            and receipt.get('arm') == row['arm']
            and receipt.get('private_parameter_cap') == row['cap']
            and receipt.get('private_parameter_count') == row['complete_realized_parameters']
            and receipt.get('selected_private_weight_sha256') == row['weight_sha256']
            and receipt.get('trace_sha256') == trace_sha
            and receipt.get('width') == row['hidden_width']
            and receipt.get('shared_encoder_feature_width') == 32,
            'native original model/trace/size binding failed')
    for flag in ('production_qualification', 'ndu_eligible',
                 'trusted_target_host_attested',
                 'torch_f32_native_q24_prediction_parity_verified',
                 'native_q24_adapter_math_independently_verified'):
        require(receipt.get(flag) is False, 'invalid claimed authority/independence: ' + flag)
    require(receipt.get('native_q24_adapter_forward_invoked') is True
            and receipt.get('native_q24_kernel_invoked') is True
            and receipt.get('independent_empty_state_replay_equal') is True,
            'missing Rust Q24 adapter/kernel/replay invocation')
    steps = receipt.get('frontier')
    events = trace['events']
    require(type(steps) is list and len(steps) == len(events)
            and receipt.get('original_tick_count') == len(events),
            'incomplete physical native frontier')
    for idx, (source, native) in enumerate(zip(events, steps)):
        actual, expected = adapter(source['temporal_drive_q24'],
                                   source['prediction_q24'], bank, row['hidden_width'])
        require(native.get('sequence') == idx+1
                and native.get('adapted_drive_q24') == actual
                and native.get('adapted_prediction_q24') == expected,
                'independent physical integer Adapter mismatch')
        require(head_logit(bank, native.get('activation_q24')) ==
                native.get('quantized_head_logit_q24'),
                'independent physical integer Head logit mismatch')
        if idx:
            require(native.get('predecessor_sha256') == steps[idx-1].get('checkpoint_sha256'),
                    'native Q24 checkpoint predecessor drift')
    return {'arm': row['arm'], 'cap': row['cap'],
            'physical_weight_sha256': row['weight_sha256'],
            'verified_native_adapter_head_event_count': len(steps),
            'independent_integer_adapter_head_parity': True,
            'independent_temporal_kernel_parity': False,
            'ndu_eligible': False, 'production_qualification': False}

def run(binary: Path, binary_sha: str, root: Path, trace_path: Path, trace_sha: str) -> dict:
    sha_file(binary, binary_sha)
    sha_file(trace_path, trace_sha)
    trace = unique_json(trace_path.read_bytes())
    require(type(trace) is dict and trace.get('schema') ==
            'hepta.neuron.physical-q24-shadow-trace.v1'
            and type(trace.get('events')) is list
            and 1 <= len(trace['events']) <= 32, 'missing bounded original native trace')
    manifest_bytes = (root / 'training-receipt.json').read_bytes()
    require(0 < len(manifest_bytes) <= 1_000_000, 'invalid training producer report')
    trained = unique_json(manifest_bytes)
    require(trained.get('schema') == 'hepta.neuron.near-matched-physical-train.v1'
            and trained.get('source_class') == 'SYNTHETIC_FIXTURE_ONLY'
            and trained.get('production_qualification') is False
            and trained.get('ndu_eligible') is False
            and trained.get('native_Q24_adapter_head_executed') is False,
            'trained-source identity/authority drift')
    records = trained.get('cells')
    require(type(records) is list and len(records) == 8,
            'all eight real trained physical weights required')
    done, reports = set(), []
    for row in records:
        cap, arm = row['cap'], row['arm']
        require((cap, arm) not in done, 'duplicate physically trained model')
        done.add((cap, arm))
        weights = physically_load(root, row)
        command = [
            str(binary.resolve()), '--arm', arm,
            '--model', str((root / row['weight_file']).resolve()),
            '--model-sha256', row['weight_sha256'], '--trace', str(trace_path.resolve()),
            '--trace-sha256', trace_sha, '--cap', str(cap),
            '--hidden-width', str(row['hidden_width']),
        ]
        if row['rank'] is not None:
            command += ['--rank', str(row['rank'])]
        results = []
        for _ in range(2):
            process = subprocess.run(command, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, check=False, timeout=60)
            require(process.returncode == 0 and 0 < len(process.stdout) <= 5_000_000,
                    'Rust Q24 executable failed: ' + process.stderr[-1500:])
            results.append(unique_json(process.stdout.encode()))
        require(results[0] == results[1], 'independent Rust native OS processes diverged')
        sha_file(root / row['weight_file'], row['weight_sha256'])
        reports.append(verify(results[0], trace, row, weights, trace_sha))
    require(done == {(cap, arm) for cap in CAPS for arm in ARMS},
            'incomplete near-matched true physical training grid')
    return {'schema': 'hepta.neuron.near-matched-physical-native-oracle.v1',
            'authority': 'DENY_ALL', 'decision': 'NO_MODEL_PROMOTION',
            'actual_native_os_processes': 16, 'physically_loaded_models': 8,
            'independent_integer_adapter_head_parity': True,
            'independent_temporal_model_parity': False,
            'training_receipt_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'frozen_input_trace_sha256': trace_sha,
            'original_selected_v1_a0_verified': False,
            'native_target_host_attested': False,
            'future_utility_verified': False,
            'ndu_eligible': False, 'production_qualification': False,
            'rows': reports}

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('binary', 'binary-sha256', 'trained-root', 'trace', 'trace-sha256', 'output'):
        p.add_argument('--'+flag, required=True)
    a = p.parse_args()
    try:
        result = run(Path(a.binary), a.binary_sha256, Path(a.trained_root),
                     Path(a.trace), a.trace_sha256)
        with Path(a.output).open('x', encoding='utf-8') as w:
            json.dump(result, w, indent=2, sort_keys=True, allow_nan=False)
            w.write('\n')
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print('BLOCKED_NEAR_MATCHED_NATIVE_Q24: '+str(e), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
