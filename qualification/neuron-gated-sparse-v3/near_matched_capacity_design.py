#!/usr/bin/env python3
"""Research-only geometry of a *proposed* trainable Cell adapter, NOT an executed model.

A common frozen d-vector feeds a private dense affine d->h adapter, the same
h-channel native fixed Q24 identity projection, temporal kernel and h->1 Head.
Every stored scalar is charged; changing the old trainer is REQUIRED.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

SCHEMA = 'hepta.neuron.proposed-near-matched-capacity.v1'
ARMS = ('v2', 'v3', 'ssm', 'min_gru')
CAPS = (2048, 8192, 16384, 65536, 262144)
MAX_WIDTH, MAX_ALLOWED_GAP_PPM = 256, 20000

class Invalid(ValueError):
    pass

def bounded_int(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise Invalid(f'{label}: expected bounded exact integer')
    return value

def geometry(input_width: int, arm: str, hidden_width: int, rank: int | None = None) -> dict:
    bounded_int(input_width, minimum=5, maximum=256, label='input width')
    bounded_int(hidden_width, minimum=5, maximum=256, label='hidden width')
    if arm not in ARMS:
        raise Invalid('unregistered Cell mechanism')
    if arm == 'min_gru':
        bounded_int(rank, minimum=1, maximum=hidden_width, label='rank')
    elif rank is not None:
        raise Invalid('non-minGRU rank forbidden')
    shapes = {'private_input_adapter.weight': [hidden_width, input_width],
              'private_input_adapter.bias': [hidden_width],
              'private_binary_head.weight': [1, hidden_width],
              'private_binary_head.bias': [1],
              'native_identity_projection.weight_q24': [hidden_width]}
    if arm in ('v3', 'ssm'):
        names = ('gate_bias', 'input_gain', 'change_gain') if arm == 'v3' else (
            'decay_per_step', 'input_gain')
        shapes.update({'temporal.' + name: [hidden_width] for name in names})
    elif arm == 'min_gru':
        for name in ('gate_input', 'candidate_input'):
            shapes['temporal.' + name] = [rank, hidden_width]
        for name in ('gate_output', 'candidate_output'):
            shapes['temporal.' + name] = [hidden_width, rank]
        for name in ('gate_bias', 'candidate_bias'):
            shapes['temporal.' + name] = [hidden_width]
    counts = {name: __import__('math').prod(dims) for name, dims in shapes.items()}
    adapter = sum(v for k, v in counts.items() if k.startswith('private_input_adapter.'))
    head = sum(v for k, v in counts.items() if k.startswith('private_binary_head.'))
    temporal = sum(v for k, v in counts.items() if k.startswith('temporal.'))
    fixed = counts['native_identity_projection.weight_q24']
    expected_temporal = {'v2': 0, 'v3': 3*hidden_width, 'ssm': 2*hidden_width,
                         'min_gru': 4*(rank or 0)*hidden_width+2*hidden_width}[arm]
    if (adapter, head, temporal, fixed) != (
            hidden_width*(input_width+1), hidden_width+1, expected_temporal, hidden_width):
        raise Invalid('tensor shape / weight-count mismatch')
    return {'arm': arm, 'shared_frozen_feature_width': input_width,
            'private_temporal_width': hidden_width, 'min_gru_rank': rank,
            'adapter_trainable_parameters': adapter,
            'head_trainable_parameters': head,
            'temporal_trainable_parameters': temporal,
            'fixed_native_q24_identity_projection_parameters': fixed,
            'trainable_private_parameters': adapter+head+temporal,
            'complete_proposed_private_parameters': sum(counts.values()),
            'unmaterialized_tensor_shapes': shapes}

def choose(input_width: int, arm: str, cap: int, *, max_rank: int) -> dict | None:
    bounded_int(cap, minimum=1, maximum=262144, label='cap')
    bounded_int(max_rank, minimum=1, maximum=16, label='max rank')
    best, key = None, None
    for h in range(5, 257):
        ranks = range(1, min(h, max_rank)+1) if arm == 'min_gru' else (None,)
        for rank in ranks:
            row = geometry(input_width, arm, h, rank)
            count = row['complete_proposed_private_parameters']
            if count <= cap and (key is None or (count, h, -(rank or 0)) > key):
                best, key = row, (count, h, -(rank or 0))
    return best

def audit(*, feature_width: int, caps: tuple[int, ...] = CAPS,
          max_rank: int = 4, max_gap_ppm: int = MAX_ALLOWED_GAP_PPM) -> dict:
    bounded_int(feature_width, minimum=5, maximum=256, label='feature width')
    bounded_int(max_rank, minimum=1, maximum=16, label='rank')
    bounded_int(max_gap_ppm, minimum=0, maximum=MAX_ALLOWED_GAP_PPM, label='gap')
    if type(caps) is not tuple or not 1 <= len(caps) <= 5 or any(
            type(x) is not int or x not in CAPS for x in caps
    ) or tuple(sorted(set(caps))) != caps:
        raise Invalid('unregistered, duplicated or unordered parameter ceilings')
    tiers, feasible, blocked = [], [], []
    for cap in caps:
        rows = {arm: choose(feature_width, arm, cap, max_rank=max_rank)
                for arm in ARMS}
        missing = [arm for arm, row in rows.items() if row is None]
        rows = {arm: row for arm, row in rows.items() if row is not None}
        for row in rows.values():
            count = row['complete_proposed_private_parameters']
            row['budget_ceiling'] = cap
            row['unfilled_ceiling_ppm'] = (cap-count)*1000000//cap
        matched = not missing and all(
            (cap-row['complete_proposed_private_parameters'])*1000000
            <= max_gap_ppm*cap for row in rows.values())
        (feasible if matched else blocked).append(cap)
        tiers.append({'nominal_ceiling': cap,
                      'result': 'PROPOSED_NEAR_MATCH_ONLY' if matched else 'BLOCKED_REALIZED_GEOMETRY',
                      'every_arm_within_declared_gap': matched,
                      'candidate_geometries': rows, 'missing_arms': missing,
                      'actual_physical_weights_created': False,
                      'native_q24_adapter_supported': False,
                      'actual_realized_parameters_verified': False,
                      'training_compute_equal_verified': False})
    report = {'schema': SCHEMA, 'authority': 'DENY_ALL', 'decision': 'NO_MODEL_PROMOTION',
              'unchanged_common_encoder_feature_width': feature_width,
              'max_min_gru_rank': max_rank,
              'maximum_allowed_unfilled_budget_ppm': max_gap_ppm,
              'geometry_semantics': 'PROPOSED_DENSE_AFFINE_ADAPTER_TEMPORAL_HEAD_NOT_IMPLEMENTED',
              'original_fixed_width_training_profile_reusable_without_change': False,
              'proposed_tensor_geometry_only_not_safetensors': True,
              'fake_capacity_padding_permitted': False,
              'native_identity_projection_immutable_and_resident': True,
              'equal_resident_memory_or_training_flops_verified': False,
              'compatible_proposed_ceiling_count': len(feasible),
              'proposed_near_match_ceiling_values': feasible,
              'blocked_ceiling_values': blocked, 'tiers': tiers}
    for flag in ('signed_deployed_no_change_a0_verified',
                 'same_dataset_training_fidelity_verified',
                 'same_training_flops_or_cpu_verified',
                 'physical_weight_shas_observed', 'real_shared_encoder_or_worker_invoked',
                 'native_q24_full_forward_verified',
                 'target_host_resource_and_recovery_verified',
                 'future_window_utility_verified', 'ndu_eligible',
                 'production_qualification'):
        report[flag] = False
    raw = json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    report['planning_payload_sha256'] = hashlib.sha256(raw).hexdigest()
    return report

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-width', type=int, required=True)
    parser.add_argument('--max-rank', type=int, default=4)
    parser.add_argument('--max-gap-ppm', type=int, default=20000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(feature_width=args.feature_width,
                       max_rank=args.max_rank, max_gap_ppm=args.max_gap_ppm)
        with args.output.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write('\n')
        return 0
    except (ValueError, OSError) as exc:
        print('BLOCKED_NEAR_MATCHED_CAPACITY: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
