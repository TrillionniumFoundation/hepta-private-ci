#!/usr/bin/env python3
"""Research-only geometry gate for the exact pre-existing Hepta Q24 shadow trainer.

This only counts the *physical tensor shapes* of the existing trainer. It never
trains, invokes a pretrained Encoder, authenticates a Cell or grants authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = 'hepta.neuron.fixed-width-realized-budget-feasibility.v1'
TRAINER_GIT_BLOB = '0f0c4f595639c077459120785d2daeeec2ce6eda'
CAPS = (2_048, 8_192, 16_384, 65_536, 262_144)
ARMS = ('v2', 'v3', 'ssm', 'min_gru')


class Invalid(ValueError):
    pass


def strictly_int(value: int, *, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise Invalid('non-integer/out-of-range training dimension or cap')
    return value


def git_blob_sha(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise Invalid('trainer source must be original raw bytes')
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


def verify_trainer(path: Path, *, pinned_sha: str = TRAINER_GIT_BLOB) -> dict:
    path = Path(path)
    if (not path.is_file() or path.is_symlink() or
            path.stat().st_size > 128 * 1024 or path.stat().st_size == 0):
        raise Invalid('trainer physical source missing/symlink/unbounded')
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    attrs = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(before, a) != getattr(after, a) for a in attrs):
        raise Invalid('trainer source changed during inspection')
    if not (isinstance(pinned_sha, str) and len(pinned_sha) == 40 and
            all(c in '0123456789abcdef' for c in pinned_sha)):
        raise Invalid('invalid pinned Git blob identifier')
    if git_blob_sha(raw) != pinned_sha:
        raise Invalid('original trainer Git blob is not the pinned source')
    return {'source_git_blob_sha1': pinned_sha,
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'source_bytes_locally_bound': True,
            'model_or_live_weight_execution_verified': False}


def rank_for_budget(width: int, cap: int) -> int:
    """Exact rank-selection expression in pinned matched_train.py.

    This is a fixed *width*, not an automatic five-tier model design.
    """
    strictly_int(width, lo=5, hi=256)
    strictly_int(cap, lo=1, hi=262_144)
    space = cap - (width + 1) - width - 2 * width
    rank = min(width, space // (4 * width))
    if rank < 1:
        raise Invalid('minGRU rank cannot fit complete private tier')
    return rank


def component_count(arm: str, width: int, *, rank: int | None = None) -> dict:
    strictly_int(width, lo=5, hi=256)
    if arm not in ARMS:
        raise Invalid('unknown Q24 research model arm')
    projection = width  # saved identity structure.projection counts physically
    head = width + 1   # head.weight plus head.bias
    if arm == 'v2':
        temporal = 0
    elif arm == 'v3':
        temporal = 3 * width  # gate_bias/input_gain/change_gain
    elif arm == 'ssm':
        temporal = 2 * width  # decay_per_step/input_gain
    else:
        strictly_int(rank, lo=1, hi=width)
        temporal = 4 * rank * width + 2 * width
    return {'structure_projection': projection,
            'private_head': head,
            'temporal': temporal,
            'total': projection + head + temporal}


def audit(*, width: int, caps: tuple[int, ...] = CAPS,
          pinned_source: dict | None = None) -> dict:
    strictly_int(width, lo=5, hi=256)
    if type(caps) is not tuple or not caps or len(caps) > 8 or any(
        type(cap) is not int or cap <= 0 or cap > 262_144 for cap in caps
    ) or tuple(sorted(set(caps))) != caps:
        raise Invalid('duplicate/unordered/invalid parameter caps')
    slots = []
    for cap in caps:
        rank = rank_for_budget(width, cap)
        for arm in ARMS:
            count = component_count(arm, width,
                                    rank=rank if arm == 'min_gru' else None)
            if count['total'] > cap:
                raise Invalid('trainer geometry does not fit nominal parameter cap')
            slots.append({'arm': arm, 'nominal_ceiling': cap,
                          'width': width, 'rank': rank if arm == 'min_gru' else None,
                          **count})
    distinct_geometry = len({(x['arm'], x['width'], x['rank'], x['total']) for x in slots})
    distinct_capacities_by_arm = {
        arm: len({row['total'] for row in slots if row['arm'] == arm})
        for arm in ARMS
    }
    per_cap_equal = all(
        len({row['total'] for row in slots if row['nominal_ceiling'] == cap}) == 1
        for cap in caps
    )
    five_tier = all(len({row['total'] for row in slots if row['arm'] == arm}) == len(caps)
                    for arm in ARMS)
    # The v2, v3 and SSM tensor counts differ for *every* positive shared width;
    # 2*w+1, 5*w+1 and 4*w+1 can never all be identical. This statement is
    # about the pinned architecture, not a fundamental limit on other models.
    intrinsic_mismatch = len({component_count(arm, width)['total']
                              for arm in ('v2', 'v3', 'ssm')}) != 1
    feasible = per_cap_equal and five_tier and not intrinsic_mismatch
    return {'schema': SCHEMA, 'authority': 'DENY_ALL', 'decision': 'NO_FAIR_FIVE_TIER_COMPARISON',
            'reusable_existing_trainer_geometry_only': True,
            'source_blob_expected': TRAINER_GIT_BLOB,
            'source_git_blob_verified_locally': pinned_source is not None,
            'declared_width_not_authenticated_against_deployment': True,
            'nominal_caps_are_not_realized_parameters': True,
            'five_tier_equal_realized_parameter_design_valid': feasible,
            'fixed_width_cross_arm_exact_match_mathematically_impossible': intrinsic_mismatch,
            'distinct_geometry_count_not_weight_sha_count': distinct_geometry,
            'distinct_capacities_by_arm': distinct_capacities_by_arm,
            'per_cap_cross_arm_equal_realized_parameters': per_cap_equal,
            'each_arm_five_distinct_parameter_tiers': five_tier,
            'rows': slots,
            'actual_weight_loading_verified': False,
            'train_optimizer_work_or_cost_verified': False,
            'signed_a0_selected_cell_verified': False,
            'production_promotion_permitted': False,
            'ndu_eligible': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--trainer-source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        source = verify_trainer(args.trainer_source) if args.trainer_source else None
        result = audit(width=args.width, pinned_source=source)
        # New file only, never overwrite an earlier study result.
        with args.output.open('x', encoding='utf-8') as dst:
            json.dump(result, dst, sort_keys=True, indent=2, allow_nan=False)
            dst.write('\n')
        return 0
    except (Invalid, ValueError, OSError) as exc:
        parser.exit(2, 'BLOCKED_FIXED_WIDTH_CAPACITY_PLAN: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
