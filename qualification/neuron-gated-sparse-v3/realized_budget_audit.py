#!/usr/bin/env python3
"""No-authority A3 audit of five budget CEILINGS vs physically realized Cell capacity.

Not an efficacy study, A0 trusted owner census, Rust execution, or a promotion gate.
Reads exactly 20 physical candidate safetensors; deliberately denies conclusions
from duplicated tiers, unequal realized parameters, or untrusted provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from candidate_inventory import verify_artifact

CAPS = (2048, 8192, 16384, 65536, 262144)
ARMS = ('v2', 'v3', 'ssm', 'min_gru')
SOURCE_SCHEMA = 'hepta.neuron.five-arm-differentiable-shadow-train.v1'
REPORT_SCHEMA = 'hepta.neuron.realized-budget-physical-audit.v2'


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def unique_json(data: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(root: Path, expected_receipt_sha: str, *, synthetic_fixture_only: bool = False,
          allow_legacy_fixture: bool = False) -> dict:
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'missing/symlink study root')
    raw = (root / 'training-receipt.json').read_bytes()
    require(0 < len(raw) <= 2*1024*1024 and sha_bytes(raw) == expected_receipt_sha,
            'frozen physical training receipt SHA mismatch')
    receipt = unique_json(raw)
    require(type(receipt) is dict and receipt.get('schema') == SOURCE_SCHEMA,
            'unsupported original training schema')
    evidence_class = receipt.get('evidence_class')
    if synthetic_fixture_only:
        allowed = ('SYNTHETIC_FIXTURE_ONLY',)
        if allow_legacy_fixture:
            allowed += (None,)
        require(evidence_class in allowed,
                'only explicit synthetic fixtures accepted in this research audit')
    else:
        require(evidence_class == 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
                'real-format review requires signed A0 format; this tool does not authenticate host')
    require(receipt.get('production_qualification') is False
            and receipt.get('ndu_eligible') is False
            and receipt.get('no_change_optimizer_steps') == 0,
            'model receipt claimed authority or trained frozen no-change V1')
    steps = receipt.get('candidate_optimizer_steps')
    require(type(steps) is int and steps > 0, 'missing common training step count')
    models = receipt.get('models')
    require(type(models) is list and len(models) == 20,
            'all 5x4 physical candidate records are required')
    observed: dict[tuple[int,str], dict] = {}
    widths: set[int] = set()
    for record in models:
        require(type(record) is dict and
                type(record.get('cap')) is int and record['cap'] in CAPS and
                record.get('arm') in ARMS, 'unknown arm or budget ceiling')
        cap, arm = record['cap'], record['arm']
        require((cap, arm) not in observed, 'duplicate arm/budget slot')
        require(type(record.get('width')) is int and 5 <= record['width'] <= 256,
                'invalid Cell private width')
        require(record.get('optimizer_steps') == steps,
                'different learned model training schedule/step count')
        require(record.get('weight_file') == f'{cap}/{arm}.safetensors',
                'path traversal or wrong file slot')
        path = root / record['weight_file']
        require(not path.is_symlink() and not path.parent.is_symlink(),
                'untrusted model/parent symlink')
        required_fields = ('weight_sha256','parameter_count','rank')
        require(all(k in record for k in required_fields),
                'unbound physical model identity, count or rank')
        physically = verify_artifact(path, record['weight_sha256'],
                                     arm=arm, width=record['width'], rank=record['rank'],
                                     expected_count=record['parameter_count'])
        count = physically['private_parameter_count']
        require(count <= cap, 'candidate exceeded its advertised ceiling')
        if 'quantization_saturations' in record:
            require(type(record['quantization_saturations']) is int and
                    record['quantization_saturations'] == 0,
                    'post-training temporal quantization silently changed parameters')
        declared_costs = ('cpu_seconds', 'wall_seconds',
                          'optimizer_state_bytes_estimate')
        if any(k in record for k in declared_costs):
            require(all(k in record for k in declared_costs),
                    'partial resource/cost telemetry cannot support cost matching')
            require(all(type(record[k]) in (int, float) and
                        math.isfinite(record[k]) and record[k] >= 0
                        for k in declared_costs),
                    'nonfinite or negative training/optimizer cost')
        widths.add(record['width'])
        observed[(cap,arm)] = {
            'parameter_ceiling': cap, 'arm':arm, 'width':record['width'],
            'realized_private_parameters':count, 'rank':record['rank'],
            'sha256':record['weight_sha256'],
            'physical_weight_bytes':physically['physical_model_bytes'],
            'ceiling_fill_ratio':round(count/cap, 6),
            'cpu_seconds_self_reported':record.get('cpu_seconds'),
            'wall_seconds_self_reported':record.get('wall_seconds'),
            'optimizer_state_bytes_estimate_claimed':record.get('optimizer_state_bytes_estimate'),
        }
    require(len(widths) == 1, 'common input width was not frozen across arms/tiers')
    require(set(observed) == {(cap,arm) for cap in CAPS for arm in ARMS},
            'incomplete exact 5x4 study matrix')

    per_arm = {}
    for arm in ARMS:
        rows = [observed[cap,arm] for cap in CAPS]
        shapes = {(r['realized_private_parameters'], r['width'], r['rank']) for r in rows}
        sha = {r['sha256'] for r in rows}
        sha_to_caps: dict[str, list[int]] = {}
        for row in rows:
            sha_to_caps.setdefault(row['sha256'], []).append(row['parameter_ceiling'])
        per_arm[arm] = {
            'by_parameter_ceiling': rows,
            'duplicate_artifact_ceiling_groups': [caps for caps in sha_to_caps.values()
                                                 if len(caps) > 1],
            'independent_physical_artifact_count': len(sha),
            'independent_capacity_profile_count':len(shapes),
            'effective_redundant_nominal_ceiling_count':len(CAPS)-len(shapes),
            'distinct_realized_capacity_shapes': len(shapes),
            'distinct_physical_weight_sha256':len(sha),
            'all_five_tiers_same_effective_model_capacity':len(shapes)==1,
            'all_five_tiers_same_physical_artifact':len(sha)==1,
        }
    by_cap = {}
    for cap in CAPS:
        counts = [observed[cap,arm]['realized_private_parameters'] for arm in ARMS]
        by_cap[str(cap)] = {
            'actual_private_parameter_counts':dict(zip(ARMS,counts)),
            'same_realized_private_parameter_count_across_four_arms':len(set(counts))==1,
            'realized_max_min_parameter_ratio':round(max(counts)/min(counts), 6),
            'shared_training_steps_not_equal_training_flops':True,
        }
    unique_shas = {r['sha256'] for r in observed.values()}
    meaningful_ranks = per_arm['min_gru']['distinct_realized_capacity_shapes']
    all_actual_equal = all(x['same_realized_private_parameter_count_across_four_arms']
                           for x in by_cap.values())
    distinct_each_arm = all(x['distinct_realized_capacity_shapes'] == len(CAPS)
                            for x in per_arm.values())
    physically_unique_each_arm = all(x['distinct_physical_weight_sha256'] == len(CAPS)
                                   for x in per_arm.values())
    design_valid = distinct_each_arm and physically_unique_each_arm and all_actual_equal
    reasons = []
    if not distinct_each_arm:
        reasons.append('DUPLICATED_CAPACITY_ACROSS_NOMINAL_TIERS')
    if not physically_unique_each_arm:
        reasons.append('IDENTICAL_PHYSICAL_WEIGHTS_IN_MULTIPLE_CEILINGS')
    if not all_actual_equal:
        reasons.append('CROSS_ARM_REALIZED_PRIVATE_PARAMETERS_NOT_EQUAL')
    if not reasons:
        reasons.append('STRUCTURE_ONLY_INDEPENDENT_UTILITY_NOT_MEASURED')
    return {
        'schema':REPORT_SCHEMA, 'source_receipt_sha256':expected_receipt_sha,
        'evidence_class':'SYNTHETIC_FIXTURE_ONLY' if synthetic_fixture_only else
                         'SIGNED_A0_FORMAT_NOT_EXECUTION',
        'cell_width':next(iter(widths)),
        'nominal_budget_ceiling_slots':len(CAPS),
        'physical_candidate_artifact_slots':len(observed),
        'distinct_physical_candidate_contents':len(unique_shas),
        'per_arm':per_arm,
        'per_budget_ceiling':by_cap,
        'all_arms_realized_at_equal_private_parameter_count_per_tier':all_actual_equal,
        'five_distinct_effective_min_gru_capacity_tiers':meaningful_ranks == len(CAPS),
        'five_distinct_effective_capacity_tiers_across_every_arm':distinct_each_arm,
        'five_distinct_physical_models_across_every_arm':physically_unique_each_arm,
        'effective_independent_physical_model_comparisons':sum(
            x['independent_physical_artifact_count'] for x in per_arm.values()),
        'effective_independent_capacity_profile_comparisons':sum(
            x['independent_capacity_profile_count'] for x in per_arm.values()),
        'five_tier_exact_realized_parameter_design_valid':design_valid,
        'five_tier_design_blockers':reasons,
        'five_tier_design_admission':'BLOCKED' if not design_valid else
                                     'STRUCTURAL_ONLY_NOT_MODEL_QUALITY',
        'effective_min_gru_capacity_tier_count':meaningful_ranks,
        'same_size_head_to_head_quality_claim_admissible':False,
        'matched_training_compute_independently_verified':False,
        'frozen_selected_v1_host_qualified':False,
        'future_ndu_utility_qualified':False,
        'target_host_a4_qualified':False,
        'ndu_eligible':False, 'production_qualification':False,
        'decision':'NO_MODEL_PROMOTION',
        'limitations':[
            'Nominal parameter ceilings are not realized parameter matching.',
            'Repeated physical weights do not establish independent model-budget comparisons.',
            'Shared Encoder and genuine selected V1 are outside these 20 candidate files.',
            'This physical-file audit is not training provenance, Q24 Rust invocation or efficacy.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trained-root',type=Path,required=True)
    parser.add_argument('--receipt-sha256',required=True)
    parser.add_argument('--synthetic-canary',action='store_true')
    parser.add_argument('--require-five-tier-matched-design',action='store_true',
                        help='exit 2 unless all 5 physical model tiers are unique per arm and '
                             'the realized private parameter counts match across arms')
    parser.add_argument('--allow-legacy-fixture',action='store_true',
                        help='local historical research fixture with no A0 class only')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    try:
        require(not args.allow_legacy_fixture or args.synthetic_canary,
                'legacy canary requires explicit synthetic flag')
        result=audit(args.trained_root,args.receipt_sha256,
                     synthetic_fixture_only=args.synthetic_canary,
                     allow_legacy_fixture=args.allow_legacy_fixture)
        with args.report.open('x',encoding='utf-8') as output:
            json.dump(result,output,sort_keys=True,indent=2)
            output.write('\n')
        if args.require_five_tier_matched_design and not result[
                'five_tier_exact_realized_parameter_design_valid']:
            print(json.dumps({'status':'BLOCKED_FIVE_TIER_REALIZED_DESIGN',
                              'reasons':result['five_tier_design_blockers'],
                              'report':str(args.report),'ndu_eligible':False}),file=sys.stderr)
            return 2
        print(json.dumps({'status':'PHYSICAL_BUDGET_AUDIT_RESEARCH_ONLY',
                          'distinct_model_weights':result['distinct_physical_candidate_contents'],
                          'production_qualification':False}))
        return 0
    except (ValueError,TypeError,KeyError,OSError) as e:
        print(json.dumps({'status':'BLOCKED_REALIZED_BUDGET_AUDIT','error':str(e),
                          'production_qualification':False}),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
