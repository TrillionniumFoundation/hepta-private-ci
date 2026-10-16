#!/usr/bin/env python3
"""Research-only BYTE-budget preflight using actual safetensors serializer.

Counts encoded F32/I64 tensor bytes plus physical safetensors header, NOT just
scalar counts. Every candidate tensor has an actual operator role; there is
no unused padding. This creates only zero-filled shape templates and never
trains, selects, or executes a live Cell.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

from near_matched_capacity_design import geometry, Invalid

SCHEMA = 'hepta.neuron.byte-budget-physical-shape-preflight.v1'
BYTE_CAPS = (8_192, 32_768)
ARMS = ('v2', 'v3', 'ssm', 'min_gru')
ALLOWED_GAP_PPM = 20_000
SOURCE_WIDTH = 32

TENSOR_RENAMES = {
    'private_input_adapter.weight': 'adapter.weight',
    'private_input_adapter.bias': 'adapter.bias',
    'private_binary_head.weight': 'head.weight',
    'private_binary_head.bias': 'head.bias',
    'native_identity_projection.weight_q24': 'structure.projection',
}


@lru_cache(maxsize=4096)
def physical_shape(arm: str, hidden_width: int, rank: int | None) -> dict:
    """Reconstruct the physical ABI with pinned Torch+safetensors; no fake size."""
    import torch
    from safetensors.torch import save
    g = geometry(SOURCE_WIDTH, arm, hidden_width, rank)
    tensors = {}
    shape_info = {}
    for logical_name, shape in g['unmaterialized_tensor_shapes'].items():
        name = TENSOR_RENAMES.get(logical_name, logical_name)
        if name in tensors:
            raise Invalid('duplicate physical tensor name')
        dtype = torch.int64 if (
            name.startswith('temporal.') or name == 'structure.projection'
        ) else torch.float32
        tensors[name] = torch.zeros(shape, dtype=dtype)
        shape_info[name] = {'shape': shape, 'dtype': 'I64' if dtype == torch.int64 else 'F32'}
    serialized = save(tensors)
    expected_payload_bytes = sum(
        tensor.numel() * tensor.element_size() for tensor in tensors.values()
    )
    header = len(serialized) - expected_payload_bytes
    if header <= 8 or expected_payload_bytes <= 0:
        raise Invalid('impossible encoded safetensors structure')
    return {
        'arm': arm,
        'shared_feature_width': SOURCE_WIDTH,
        'hidden_width': hidden_width,
        'rank': rank,
        'physical_safetensors_bytes': len(serialized),
        'actual_tensor_payload_bytes': expected_payload_bytes,
        'safetensors_header_and_metadata_bytes': header,
        'private_parameter_count': g['complete_proposed_private_parameters'],
        'trainable_parameter_count': g['trainable_private_parameters'],
        'tensor_shapes_and_dtypes': shape_info,
        'template_weights_are_untrained_zero_fixtures': True,
    }


def choose(arm: str, budget: int, *, max_rank: int = 4) -> dict:
    if arm not in ARMS or type(budget) is not int or budget not in BYTE_CAPS:
        raise Invalid('unknown arm or unregistered physical byte ceiling')
    if type(max_rank) is not int or not 1 <= max_rank <= 4:
        raise Invalid('invalid bounded low-rank limit')
    best = None
    key = None
    for hidden in range(5, 257):
        ranks = range(1, min(hidden, max_rank) + 1) if arm == 'min_gru' else (None,)
        for rank in ranks:
            candidate = physical_shape(arm, hidden, rank)
            used = candidate['physical_safetensors_bytes']
            if used > budget:
                continue
            # Most physical bytes used, then widest actual hidden state, then
            # smaller low rank. No tensor padding to force artificial equality.
            candidate_key = (used, hidden, -(rank or 0))
            if key is None or candidate_key > key:
                key, best = candidate_key, candidate
    if best is None or (budget - best['physical_safetensors_bytes']) * 1_000_000 > (
        ALLOWED_GAP_PPM * budget
    ):
        raise Invalid('no genuinely materialized near-matched byte geometry')
    return dict(best, byte_budget=budget,
                budget_unfilled_ppm=(budget - best['physical_safetensors_bytes']) * 1_000_000 // budget)


def audit() -> dict:
    tiers = []
    for budget in BYTE_CAPS:
        rows = {arm: choose(arm, budget) for arm in ARMS}
        if any(r['physical_safetensors_bytes'] > budget for r in rows.values()):
            raise Invalid('physical weight exceeds budget')
        tiers.append({'physical_byte_ceiling': budget, 'candidate_shapes': rows,
                      'within_2pct_serialized_byte_ceiling': True,
                      'real_training_performed': False,
                      'actual_model_weights_created': False})
    result = {
        'schema': SCHEMA, 'authority': 'DENY_ALL',
        'decision': 'NO_MODEL_PROMOTION',
        'study_kind': 'SERIALIZED_SAFETENSORS_BYTES_NOT_PARAMETERS',
        'fixed_shared_feature_width': SOURCE_WIDTH,
        'predeclared_byte_caps': list(BYTE_CAPS),
        'max_gap_ppm': ALLOWED_GAP_PPM,
        'tiers': tiers,
        'equal_model_parameter_counts_verified': False,
        'equal_inference_resident_memory_verified': False,
        'equal_optimizer_or_training_flops_verified': False,
        'original_live_selected_v1_a0_verified': False,
        'genuine_learned_weights_measured': False,
        'future_utility_verified': False,
        'native_full_forward_verified': False,
        'production_qualification': False, 'ndu_eligible': False,
    }
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    result['planning_payload_sha256'] = hashlib.sha256(raw).hexdigest()
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        result = audit()
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
        return 0
    except (Invalid, OSError, ValueError) as error:
        print('BLOCKED_HEPTA_SERIALIZED_BYTE_BUDGET: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
