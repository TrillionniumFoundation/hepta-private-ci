#!/usr/bin/env python3
"""Research-only, source-ZIP-pinned descriptive Cell mechanism cost frontier.

This script cannot establish utility, hardware equivalence or model authority.
It deliberately makes no model choice without genuine independent future utility.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import stat
import zipfile

SCHEMA = 'hepta.neuron.archived-resource-only-frontier.v1'
ARTIFACTS = {
    'trained': ('9c871918e306f6f0fa0c6f3864bd75ff9271df3829ce8b58108618fc99e93995',
                ('twenty-physical-q24-native-shadow.json',)),
    'mechanism': ('f65886ca41941de185dd2af8bb9f05221933e9208e078889179dc5671650834b',
                  ('neuron-q24-fixture-matrix.json', 'neuron-q24-cost-analysis.json')),
}
SCALES = (64, 256, 1024, 4096)
TEMPORAL = ('v2', 'v3', 'ssm', 'min_gru')
ARMS = ('v1',) + TEMPORAL
CAPS = (2048, 8192, 16384, 65536, 262144)

class Invalid(ValueError):
    """Do not proceed if original evidence bytes or experimental scope drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def pairs(items):
    seen = {}
    for k, v in items:
        require(k not in seen, 'duplicated JSON evidence key')
        seen[k] = v
    return seen


def strict_json(raw: bytes) -> dict:
    require(1 <= len(raw) <= 1_000_000, 'oversize/empty JSON member')
    def finite_number(token: str) -> float:
        value = float(token)
        require(math.isfinite(value), 'nonfinite JSON evidence')
        return value

    x = json.loads(raw, object_pairs_hook=pairs, parse_float=finite_number,
                   parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite JSON evidence')))
    require(type(x) is dict, 'bad archived JSON payload')
    return x


def pinned_zip(path: Path, name: str) -> tuple[dict, dict]:
    require(name in ARTIFACTS, 'unregistered hosted ZIP')
    expected_hash, expected_members = ARTIFACTS[name]
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'missing/symlink original hosted ZIP')
    a = path.stat()
    require(100 <= a.st_size <= 1_000_000, 'bounded ZIP size required')
    raw = path.read_bytes()
    b = path.stat()
    attrs = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(all(getattr(a, k) == getattr(b, k) for k in attrs), 'ZIP changed during hashing')
    require(hashlib.sha256(raw).hexdigest() == expected_hash, 'original hosted ZIP SHA256 mismatch')
    # Read exactly the immutable bytes already SHA-256 checked; a second
    # filesystem path open would permit replacement between hash and parse.
    with zipfile.ZipFile(io.BytesIO(raw), 'r') as z:
        infos = z.infolist()
        require(sorted(i.filename for i in infos) == sorted(expected_members),
                'missing/foreign/duplicate evidence member')
        members = {}
        for i in infos:
            require(i.file_size <= 1_000_000 and i.compress_size <= 1_000_000,
                    'unbounded evidence extraction')
            require(not stat.S_ISLNK((i.external_attr >> 16) & 0xffff),
                    'symlinked ZIP member refused')
            members[i.filename] = strict_json(z.read(i))
    return members, {'zip_sha256': expected_hash, 'zip_size_bytes': len(raw)}


def nonnegative_exact_int(value, field: str, *, positive=False) -> int:
    require(type(value) is int and 0 <= value <= 10**15 and (not positive or value > 0),
            f'non-integer/out-of-range {field}')
    return value


def archived_weights(doc: dict) -> dict:
    require(doc.get('schema') == 'hepta.neuron.twenty-physical-q24-mechanism-matrix.v1',
            'unexpected native shadow schema')
    require(doc.get('evidence_class') == 'SYNTHETIC_NATIVE_RESEARCH_ONLY',
            'physical native receipt cannot represent target deployment')
    for key in ('production_qualification', 'ndu_eligible', 'real_target_host_attested',
                'floating_torch_native_q24_prediction_parity_verified',
                'full_selected_model_head_executed', 'crash_durable_recovery_verified'):
        require(doc.get(key) is False, f'forged physical qualification: {key}')
    require(doc.get('decision') == 'NO_MODEL_PROMOTION', 'wrong native source decision')
    a0 = doc.get('frozen_a0_owner_revalidation')
    require(type(a0) is dict and a0.get('a0_rechecked') is False,
            'forged selected production A0')
    require(doc.get('twenty_native_physical_model_executions') == 20,
            'missing native physical execution census')
    require(doc.get('forty_fresh_native_process_invocations') == 40,
            'missing two independent OS processes per model')
    rows = doc.get('results')
    require(type(rows) is list and len(rows) == 20, 'twenty physical slots required')
    slots, by_arm = set(), defaultdict(set)
    for row in rows:
        require(type(row) is dict, 'invalid physical slot row')
        arm, cap = row.get('arm'), row.get('private_parameter_cap')
        require(arm in TEMPORAL and type(cap) is int and cap in CAPS,
                'invalid arm/ceiling slot')
        require((arm, cap) not in slots, 'duplicated physical arm/ceiling slot')
        slots.add((arm, cap))
        h = row.get('physical_artifact_sha256')
        require(type(h) is str and len(h) == 64 and all(c in '0123456789abcdef' for c in h),
                'malformed original weight digest')
        by_arm[arm].add(h)
        require(row.get('fresh_process_count') == 2 and
                row.get('independent_rust_processes_bit_identical') is True,
                'native process replays not both observed and identical')
        oracle = row.get('q24_head_integer_oracle')
        require(type(oracle) is dict and
                oracle.get('all_native_head_logits_match_independent_integer_oracle') is True and
                oracle.get('all_native_head_sign_margins_match_independent_integer_oracle') is True and
                oracle.get('full_original_f32_policy_execution_verified') is False,
                'native integer oracle/f32 status not original')
    require(slots == {(a, c) for a in TEMPORAL for c in CAPS},
            'incomplete physical four-arm five-ceiling grid')
    count = len(set.union(*by_arm.values()))
    realized = doc.get('realized_budget_audit')
    require(type(realized) is dict and
            realized.get('five_tier_exact_realized_parameter_design_valid') is False and
            realized.get('production_qualification') is False and
            realized.get('effective_independent_physical_model_comparisons') == count,
            'claimed capacity/design conflicts with measured weight census')
    require(count == 5 and {a:len(v) for a,v in by_arm.items()} ==
            {'v2':1,'v3':1,'ssm':1,'min_gru':2},
            'source artifact no longer matches registered five unique geometries')
    return {'nominal_file_slots': len(rows), 'fresh_native_process_calls': 40,
            'distinct_weight_digests': count,
            'distinct_weight_digests_by_arm': {a:len(by_arm[a]) for a in TEMPORAL},
            'f32_vs_native_head_policy_parity_verified': False,
            'selected_production_a0_verified': False}


def mechanism_costs(matrix: dict, analysis: dict) -> list[dict]:
    require(matrix.get('schema') == 'hepta.neuron.mechanism-only-matrix.v1' and
            analysis.get('schema') == 'hepta.neuron.five-arm-mechanism-cost-summary.v1',
            'unrecognized mechanism resource schema')
    require(matrix.get('source_evidence_kind') ==
            'UNVERIFIED_KERNEL_ONLY_NOT_TARGET_HOST_ACCEPTANCE',
            'mechanism source represented as true target host')
    for key in ('target_host_qualified','trained_artifacts_qualified','parameter_budgets_matched','ndu_eligible'):
        require(matrix.get(key) is False, 'overclaimed matrix qualification: '+key)
    for key in ('qualified_target_host','qualified_p99_sla',
                'verified_same_budget_full_model_execution','verified_real_training',
                'verified_independent_evaluator','production_qualification','ndu_eligible'):
        require(analysis.get(key) is False, 'overclaimed cost qualification: '+key)
    require(analysis.get('decision') == 'NO_MODEL_PROMOTION', 'wrong archived decision')
    require(matrix.get('arms') == list(ARMS) and matrix.get('scales') == list(SCALES),
            'wrong matrix scales/arms')
    require(matrix.get('trace_sha256') == analysis.get('original_trace_sha256'),
            'wrong common trace digest')
    rows = matrix.get('results')
    require(type(rows) is list and len(rows) == 20, 'missing 20 mechanism-only slots')
    original, seen = {}, set()
    for row in rows:
        require(type(row) is dict, 'invalid mechanism result')
        arm, cells = row.get('arm'), row.get('cells')
        require(arm in ARMS and type(cells) is int and cells in SCALES,
                'invalid arm/cell count')
        require((arm,cells) not in seen,'duplicate mechanism slot')
        seen.add((arm,cells))
        require(row.get('trained_model') is False and
                row.get('artifact_provenance_verified') is False and
                row.get('production_qualification') is False and
                row.get('ndu_eligible') is False,
                'trained/provenanced mechanism model falsely claimed')
        require(row.get('trace_sha256') == matrix['trace_sha256'],
                'drifting Q24 input trace')
        for k in ('p99_tick_nanos','process_peak_rss_bytes',
                  'mechanism_tick_throughput_per_second_milli'):
            nonnegative_exact_int(row.get(k), k, positive=True)
        original[(arm,cells)] = row
    require(seen == {(a,c) for a in ARMS for c in SCALES},
            'incomplete five-arm/four-scale mechanism matrix')
    comparisons = analysis.get('comparisons')
    require(type(comparisons) is list and len(comparisons) == 4,
            'incomplete archive cost-comparison scales')
    scales_observed = set()
    for group in comparisons:
        require(type(group) is dict and type(group.get('cells')) is int and
                group['cells'] in SCALES, 'bad cost comparison scale')
        require(group['cells'] not in scales_observed,
                'duplicated archived cost-comparison scale')
        scales_observed.add(group['cells'])
        reports = group.get('arms')
        require(type(reports) is list and len(reports) == 5,
                'incomplete archived scale arms')
        require({r.get('arm') for r in reports} == set(ARMS),
                'invalid archived arm names')
        for r in reports:
            original_row = original[(r['arm'],group['cells'])]
            for key_src, key_report in (
                    ('p99_tick_nanos','p99_tick_nanos'),
                    ('process_peak_rss_bytes','process_peak_rss_bytes'),
                    ('mechanism_tick_throughput_per_second_milli',
                     'mechanism_tick_throughput_per_second_milli')):
                require(original_row[key_src] == r.get(key_report),
                        'archived matrix-vs-analysis cost mismatch')
    require(scales_observed == set(SCALES), 'missing archived cost-comparison scale')
    return [{'arm':arm,'cells':cells,
             'p99_tick_nanos':original[(arm,cells)]['p99_tick_nanos'],
             'process_peak_rss_bytes':original[(arm,cells)]['process_peak_rss_bytes'],
             'mechanism_tick_throughput_per_second_milli':
                 original[(arm,cells)]['mechanism_tick_throughput_per_second_milli']}
            for cells in SCALES for arm in ARMS]


def resource_dominators(rows: list[dict], *, cells: int) -> dict[str,list[str]]:
    """Only descriptive synthetic resource dominance; *not* quality Pareto."""
    sample = {r['arm']:r for r in rows if r['cells']==cells}
    require(set(sample)==set(ARMS),'scale missing before resource calculation')
    dominators = {}
    for a, ar in sample.items():
        dominators[a] = []
        for b, br in sample.items():
            if a==b:continue
            weak=(br['p99_tick_nanos']<=ar['p99_tick_nanos'] and
                  br['process_peak_rss_bytes']<=ar['process_peak_rss_bytes'] and
                  br['mechanism_tick_throughput_per_second_milli']>=
                  ar['mechanism_tick_throughput_per_second_milli'])
            strict=(br['p99_tick_nanos']<ar['p99_tick_nanos'] or
                    br['process_peak_rss_bytes']<ar['process_peak_rss_bytes'] or
                    br['mechanism_tick_throughput_per_second_milli']>
                    ar['mechanism_tick_throughput_per_second_milli'])
            if weak and strict:dominators[a].append(b)
    return dominators


def audit(trained_zip: Path, mechanism_zip: Path) -> dict:
    a, ak = pinned_zip(trained_zip, 'trained')
    b, bk = pinned_zip(mechanism_zip, 'mechanism')
    weights = archived_weights(a['twenty-physical-q24-native-shadow.json'])
    resources = mechanism_costs(b['neuron-q24-fixture-matrix.json'],
                                b['neuron-q24-cost-analysis.json'])
    dominates = {str(c):resource_dominators(resources,cells=c) for c in SCALES}
    return {'schema':SCHEMA,'authority':'DENY_ALL',
            'decision':'NO_QUALIFIED_LEARNING_COST_PARETO',
            'original_zip_receipts':{'trained':ak,'mechanism':bk},
            'physical_native_shadow_census':weights,
            'mechanism_only_cost_observations':resources,
            'descriptive_resource_only_dominators_by_scale':dominates,
            'resource_only_4096_undominated':
                [a for a,b in dominates['4096'].items() if not b],
            'candidate_task_quality_and_future_utility_verified':False,
            'old_task_retention_and_negative_transfer_verified':False,
            'frozen_no_change_task_utility_verified':False,
            'same_budget_trained_model_cost_verified':False,
            'real_encoder_worker_wal_cas_included':False,
            'target_host_full_stack_and_4096_cells_verified':False,
            'independent_signed_a0_owner_verified':False,
            'complete_lifecycle_quality_cost_pareto_admissible':False,
            'statistical_model_winner_selected':False,
            'production_model_promotion_permitted':False,
            'ndu_eligible':False,
            'source_is_only_hosted_archived_synthetic_research':True}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trained-zip',type=Path,required=True)
    p.add_argument('--mechanism-zip',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    try:
        result=audit(args.trained_zip,args.mechanism_zip)
        with args.output.open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2,sort_keys=True,allow_nan=False)
            f.write('\n')
    except (Invalid, OSError, ValueError, zipfile.BadZipFile) as e:
        p.exit(2, 'BLOCKED_ARCHIVED_RESEARCH_FRONTIER: '+str(e)+'\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
