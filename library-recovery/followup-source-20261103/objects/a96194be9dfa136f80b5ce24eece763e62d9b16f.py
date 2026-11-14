#!/usr/bin/env python3
"""Read-only independent structural audit of a bounded Hepta Q24 shadow ZIP.

Authenticates SHA-256 of the *hosted ZIP bytes* against an independently frozen
expected digest; does not authenticate upstream weights, host, signer or training.
Never grants any model, NDU, effect, recovery, or deployment authority.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import stat
import zipfile
from pathlib import Path

ARMS = ('v2', 'v3', 'ssm', 'min_gru')
TIERS = (2048, 8192, 16384, 65536, 262144)
JSON_NAME = 'twenty-physical-q24-native-shadow.json'
SCHEMA = 'hepta.neuron.twenty-physical-q24-mechanism-matrix.v1'
AUDIT_SCHEMA = 'hepta.neuron.independent-hosted-physical-replay-audit.v1'
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024


class AuditBlocked(ValueError):
    pass


def require(condition: bool, error: str) -> None:
    if not condition:
        raise AuditBlocked(error)


def sha(value: object) -> str:
    require(type(value) is str and DIGEST.fullmatch(value) is not None and value != '0' * 64,
            'invalid SHA-256 identity')
    return value


def numeric(value: object, *, positive: bool = False) -> float:
    require(type(value) in (int, float), 'unbounded or nonnumeric observation')
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise AuditBlocked('unbounded or nonnumeric observation') from exc
    require(math.isfinite(result) and 0 <= result <= 10**15 and (not positive or result > 0),
            'unbounded or nonnumeric observation')
    return result


def pairs(rows: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in rows:
        require(key not in result, 'duplicate JSON object field')
        result[key] = value
    return result


def strict_json(raw: bytes) -> dict:
    data = json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(AuditBlocked('nonfinite JSON constant')))
    require(type(data) is dict, 'invalid root JSON document')
    return data


def audit(zip_path: Path, expected_zip_sha256: str) -> dict:
    expected_zip_sha256 = sha(expected_zip_sha256)
    require(zip_path.is_file() and not zip_path.is_symlink(), 'not an ordinary source ZIP')
    require(0 < zip_path.stat().st_size <= MAX_ZIP_BYTES, 'oversized ZIP')
    source_zip_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    require(source_zip_sha == expected_zip_sha256, 'original hosted ZIP bytes mismatch')
    with zipfile.ZipFile(zip_path, 'r') as archive:
        infos = archive.infolist()
        require(len(infos) == 1 and infos[0].filename == JSON_NAME, 'unexpected archive members')
        info = infos[0]
        require(0 < info.file_size <= MAX_JSON_BYTES, 'oversized JSON member')
        require(not (info.external_attr >> 16 & stat.S_IFMT(0o170000) == stat.S_IFLNK),
                'symlink archive member')
        raw = archive.read(info)  # also checks the ZIP CRC
        require(len(raw) == info.file_size, 'truncated JSON member')
    document = strict_json(raw)
    require(document.get('schema') == SCHEMA, 'wrong native artifact schema')
    require(document.get('evidence_class') == 'SYNTHETIC_NATIVE_RESEARCH_ONLY', 'untrusted evidence class')
    require(document.get('decision') == 'NO_MODEL_PROMOTION', 'promotion decision spoofed')
    for field in ('production_qualification', 'ndu_eligible', 'real_target_host_attested',
                  'crash_durable_recovery_verified', 'full_selected_model_head_executed',
                  'floating_torch_native_q24_prediction_parity_verified'):
        require(document.get(field) is False, f'unsupported qualification: {field}')
    for field in ('native_q24_temporal_replay_executed',
                  'cross_process_q24_frontier_and_head_receipts_equal'):
        require(document.get(field) is True, f'missing native research observation: {field}')
    require(document.get('twenty_native_physical_model_executions') == 20, 'wrong physical row census')
    require(document.get('forty_fresh_native_process_invocations') == 40, 'wrong process census')
    require(document.get('quantized_native_head_integer_oracle_matches') == 20, 'Q24 Head oracle incomplete')
    require(document.get('quantized_head_margin_oracle_matches') == 20, 'Q24 margin oracle incomplete')
    require(document.get('diagnostic_native_vs_float_gap_rows') == 20, 'floating/native gap panel incomplete')
    negative = document.get('native_negative_cases')
    require(type(negative) is list and len(negative) == document.get('native_negative_cases_rejected') == 6,
            'negative case census incomplete')
    ids = set()
    for item in negative:
        require(type(item) is dict and item.get('rejected_by_native_rust') is True,
                'negative case not rejected')
        test_id = item.get('test')
        require(type(test_id) is str and test_id and test_id not in ids, 'duplicate negative case')
        ids.add(test_id)
    a0 = document.get('frozen_a0_owner_revalidation')
    require(type(a0) is dict and a0.get('a0_rechecked') is False
            and a0.get('a0_evidence_class') == 'SYNTHETIC_FIXTURE_ONLY', 'false production A0 evidence')
    rows = document.get('results')
    require(type(rows) is list and len(rows) == len(ARMS) * len(TIERS), 'missing or extra model slots')
    slots = set()
    by_arm: dict[str, set[str]] = {name: set() for name in ARMS}
    all_weights = set()
    native_wall: dict[str, list[float]] = collections.defaultdict(list)
    max_gap_by_arm: dict[str, float] = collections.defaultdict(float)
    for row in rows:
        require(type(row) is dict, 'invalid model slot')
        arm, cap = row.get('arm'), row.get('private_parameter_cap')
        require(arm in ARMS and type(cap) is int and cap in TIERS, 'undeclared arm or budget')
        require((arm, cap) not in slots, 'duplicate arm-tier slot')
        slots.add((arm, cap))
        digest = sha(row.get('physical_artifact_sha256'))
        by_arm[arm].add(digest)
        all_weights.add(digest)
        require(row.get('fresh_process_count') == 2
                and row.get('independent_rust_processes_bit_identical') is True,
                'native physical double-execution not demonstrated')
        require(type(row.get('q24_head_integer_oracle')) is dict and
                row['q24_head_integer_oracle'].get('all_native_head_logits_match_independent_integer_oracle') is True and
                row['q24_head_integer_oracle'].get('all_native_head_sign_margins_match_independent_integer_oracle') is True,
                'native Head oracle not demonstrated')
        native = row.get('native_receipt')
        require(type(native) is dict and native.get('quantized_q24_head_executed_in_rust') is True
                and native.get('head_margin_authorized_for_final_use') is False
                and native.get('f32_head_executed') is False
                and native.get('durable_checkpoint_cas_verified') is False
                and native.get('decision') == 'NO_PROMOTION', 'unsafe native model receipt')
        gap = row.get('float_surrogate_vs_native_q24_state_gap')
        require(type(gap) is dict and gap.get('bitwise_float_to_q24_prediction_parity_proven') is False
                and gap.get('labelled_outcome_quality_verified') is False, 'false floating parity or task quality')
        max_gap = numeric(gap.get('max_probability_gap_ppm'))
        require(max_gap <= 1_000_000, 'probability gap exceeds valid ppm range')
        max_gap_by_arm[arm] = max(max_gap_by_arm[arm], max_gap)
        native_wall[arm].append(numeric(row.get('native_process_wall_micros_not_target_host_slo'), positive=True))
        for field in ('q24_checkpoint_chain_final', 'q24_replay_evidence_sha256', 'second_process_raw_stdout_sha256'):
            sha(row.get(field))
    require(slots == {(arm, tier) for arm in ARMS for tier in TIERS}, 'incomplete closed-world arm/budget matrix')
    realized = document.get('realized_budget_audit')
    require(type(realized) is dict
            and realized.get('physical_candidate_artifact_slots') == len(rows)
            and realized.get('effective_independent_physical_model_comparisons') == len(all_weights),
            'claimed unique-model counts differ from physical SHA census')
    require(realized.get('five_tier_exact_realized_parameter_design_valid') is False,
            'false matched-budget qualification')
    blockers = realized.get('five_tier_design_blockers')
    require(type(blockers) is list and 'CROSS_ARM_REALIZED_PRIVATE_PARAMETERS_NOT_EQUAL' in blockers,
            'missing documented cross-arm size mismatch')
    # This is deliberately descriptive: neither model ranking nor runtime SLO is claimed.
    return {
        'schema': AUDIT_SCHEMA,
        'source_zip_sha256': source_zip_sha,
        'source_json_sha256': hashlib.sha256(raw).hexdigest(),
        'observed_arm_budget_slots': len(rows),
        'observed_fresh_native_processes': sum(row['fresh_process_count'] for row in rows),
        'distinct_physical_model_weight_digests': len(all_weights),
        'distinct_model_weight_digests_per_arm': {arm: len(by_arm[arm]) for arm in ARMS},
        'all_twenty_slots_two_process_q24_replay_and_head_oracle': True,
        'observed_process_wall_micros_range_by_arm_not_runtime_slo': {
            arm: {'minimum': min(native_wall[arm]), 'maximum': max(native_wall[arm])} for arm in ARMS
        },
        'max_reported_float_to_native_probability_gap_ppm_by_arm': dict(max_gap_by_arm),
        'closed_world_budget_design_valid': False,
        'production_a0_attested': False,
        'selected_model_f32_to_native_q24_parity_verified': False,
        'real_task_outcome_quality_verified': False,
        'independent_publisher_weight_provenance_verified': False,
        'model_winner_selected': False,
        'ndu_eligible': False,
        'production_qualification': False,
        'authority': 'DENY_ALL',
        'decision': 'NO_MODEL_PROMOTION',
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    a = parser.parse_args()
    result = audit(a.zip, a.sha256)
    with a.output.open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')


if __name__ == '__main__':
    main()
