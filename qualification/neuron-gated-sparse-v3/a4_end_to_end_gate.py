#!/usr/bin/env python3
"""A4: signed target-host 100-slot end-to-end receipt *structure*, never promotion.

Only an independent, authenticated runtime owner can attest real execution.
Even a cryptographically valid schema cannot prove the host actually ran it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

from a0_deployment_evidence import load_public_key, verify_signed
from matched_train import CAPS, ARMS, sha_file, unique_json, require, utc

SCHEMA = 'hepta.neuron.a4-end-to-end-host-100-slot.v1'
SCALES = (64, 256, 1024, 4096)
ALL_ARMS = ('no-change-v1',) + ARMS
HEX = set('0123456789abcdef')
PERF_FIELDS = {
    'measurement_kind', 'device_kind', 'request_count',
    'cpu_micros', 'process_tree_peak_rss_bytes', 'gpu_peak_alloc_bytes',
    'gpu_peak_total_bytes', 'encoder_forward_invocations', 'encoder_forward_rows',
    'throughput_milli_requests_per_second',
    'request_p50_micros', 'request_p95_micros', 'request_p99_micros',
    'batch_p95_micros', 'batch_p99_micros', 'cold_model_load_micros',
    'cas_p99_micros', 'signature_p99_micros', 'cns_p99_micros',
    'wal_bytes_written', 'recovery_p99_micros', 'lost_replay_count',
}
RECEIPT_FIELDS = {
    'model_load', 'inference_dispatch', 'checkpoint_cas', 'checkpoint_reopen',
    'authority_final_use', 'signature_verify', 'cns_route',
    'wal_commit', 'generation_fence', 'revocation_denial',
}
PROOFS = {
    'checkpoint_reopen_verified', 'generation_fence_verified',
    'revocation_denial_verified', 'no_duplicate_model_per_cell_verified',
}


def exact(x: Any, fields: set[str], what: str) -> dict:
    require(type(x) is dict and set(x) == fields, what + ': incorrect required fields')
    return x


def digest(x: Any, what: str) -> str:
    require(type(x) is str and len(x) == 64 and x != '0'*64
            and all(ch in HEX for ch in x), what + ': invalid SHA256')
    return x


def positive_int(x: Any, what: str, *, zero: bool = False) -> int:
    require(type(x) is int and (x >= 0 if zero else x > 0), what + ': invalid integer')
    return x


def percentile(p: dict) -> None:
    require(p['request_p50_micros'] <= p['request_p95_micros'] <= p['request_p99_micros'],
            'request latency percentile order')
    require(p['batch_p95_micros'] <= p['batch_p99_micros'],
            'batch percentile order')
    require(p['gpu_peak_alloc_bytes'] <= p['gpu_peak_total_bytes'], 'GPU allocation exceeds device use')
    if p['device_kind'] == 'gpu':
        require(p['gpu_peak_alloc_bytes'] > 0, 'GPU profiler absent for GPU profile')
    require(p['encoder_forward_invocations'] <= p['encoder_forward_rows'] <= p['request_count'],
            'Encoder calls/rows exceed requests')
    require(p['lost_replay_count'] == 0, 'acknowledged replay history lost')


def validate(host: Any, training: Any, *, host_id: str, train_sha: str,
             physical_weights_root: Path, selected_v1: Path, selected_v1_sha: str,
             host_key_fingerprint: str) -> dict:
    exact(training, {
        'schema','source_train_sha256','encoder_digest_claimed','cell_id',
        'training_cutoff_utc','train_source_group_hashes',
        'no_change_v1_selected_sha256','no_change_optimizer_steps',
        'candidate_optimizer_steps','cpu_only','preregistered_window','seed',
        'schedule_sha256','target_host_attested','native_q24_parity_verified',
        'training_provenance_independently_verified','future_utility_verified',
        'ndu_eligible','production_qualification','decision','models',
        'peak_process_rss_kib_not_arm_comparable','evidence_class',
        'a0_registry_sha256','a0_host_id','a0_checkpoint_digest_claimed','a0_generation_claimed',
    }, 'frozen training receipt')
    require(training['schema'] == 'hepta.neuron.five-arm-differentiable-shadow-train.v1'
            and training['evidence_class'] == 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION'
            and training['no_change_optimizer_steps'] == 0
            and training['ndu_eligible'] is False
            and training['production_qualification'] is False,
            'missing actual A0 signed-format claim / frozen V1 baseline')
    require(training['a0_host_id'] == host_id and
            training['no_change_v1_selected_sha256'] == selected_v1_sha,
            'A0 host or frozen baseline drift')
    sha_file(selected_v1, selected_v1_sha)
    expected = {}
    for row in training['models']:
        key = (row['cap'], row['arm'])
        require(key not in expected and key[0] in CAPS and key[1] in ARMS,
                'duplicate or unknown trained model')
        require(row['optimizer_steps'] == training['candidate_optimizer_steps'] and
                0 < row['parameter_count'] <= key[0], 'training budget/steps mismatch')
        path = physical_weights_root / row['weight_file']
        require(path.is_relative_to(physical_weights_root) and
                row['weight_file'] == f'{key[0]}/{key[1]}.safetensors', 'model traversal/path mismatch')
        sha_file(path, row['weight_sha256'])
        expected[key] = row['weight_sha256']
    require(set(expected) == {(cap,arm) for cap in CAPS for arm in ARMS},
            'incomplete 20 physical trained candidates')
    exact(host, {'schema','host_id','host_profile_sha256','source_commit_sha',
                 'encoder_bundle_sha256','a0_registry_sha256','training_receipt_sha256',
                 'measurement_started_at_utc','measurement_ended_at_utc',
                 'measurements'}, 'A4 signed host payload')
    require(host['schema'] == SCHEMA and host['host_id'] == host_id,
            'wrong A4 schema/target host')
    for name in ('host_profile_sha256','encoder_bundle_sha256','a0_registry_sha256',
                 'training_receipt_sha256'):
        digest(host[name], name)
    require(host['training_receipt_sha256'] == train_sha and
            host['a0_registry_sha256'] == training['a0_registry_sha256'],
            'A4 trace/census no longer pinned')
    require(type(host['source_commit_sha']) is str
            and len(host['source_commit_sha']) == 40
            and all(x in HEX for x in host['source_commit_sha']),
            'unknown source commit')
    require(utc(host['measurement_started_at_utc']) <
            utc(host['measurement_ended_at_utc']), 'invalid target-host measurement window')
    rows = host['measurements']
    require(type(rows) is list and len(rows) == len(CAPS)*len(ALL_ARMS)*len(SCALES),
            '100 end-to-end arm/tier/scale receipts required')
    seen = set()
    results = defaultdict(dict)
    for row in rows:
        exact(row, {'parameter_cap','arm','cell_count','model_sha256',
                    'execution_receipts_sha256','performance','proofs'}, 'host sample')
        cap,arm,scale = row['parameter_cap'], row['arm'], row['cell_count']
        require(type(cap) is int and cap in CAPS and arm in ALL_ARMS
                and type(scale) is int and scale in SCALES
                and (cap,arm,scale) not in seen, 'bad/duplicate A4 arm-tier-scale')
        seen.add((cap,arm,scale))
        correct = selected_v1_sha if arm == 'no-change-v1' else expected[(cap,arm)]
        require(row['model_sha256'] == correct, 'A4 loaded artifact does not match frozen model')
        rec = exact(row['execution_receipts_sha256'], RECEIPT_FIELDS, 'physical owner receipts')
        for k,v in rec.items():
            digest(v, 'physical receipt '+k)
        proof = exact(row['proofs'], PROOFS, 'host safety invariants')
        require(all(value is True for value in proof.values()), 'owner fence/revoke/reopen evidence missing')
        p = exact(row['performance'], PERF_FIELDS, 'complete end-to-end telemetry')
        require(p['measurement_kind'] == 'target-host-real-end-to-end'
                and p['device_kind'] in ('cpu','gpu'), 'mechanism/synthetic sample is not A4')
        for field in PERF_FIELDS - {'measurement_kind','device_kind'}:
            positive_int(p[field], field, zero=field in {
                'gpu_peak_alloc_bytes','gpu_peak_total_bytes','lost_replay_count',
                'encoder_forward_invocations','encoder_forward_rows',
            })
        require(p['request_count'] >= scale, 'real request count below stated Cell scale')
        percentile(p)
        results[str(cap)][f'{arm}@{scale}'] = {
            'p99_request_micros_claimed':p['request_p99_micros'],
            'peak_process_tree_rss_bytes_claimed':p['process_tree_peak_rss_bytes'],
            'measured_throughput_milli_claimed':p['throughput_milli_requests_per_second'],
        }
    require(seen == {(cap,arm,s) for cap in CAPS for arm in ALL_ARMS for s in SCALES},
            'missing required Cell counts for at least one arm/budget')
    return {
        'schema':'hepta.neuron.a4-end-to-end-structural-review.v1',
        'signed_host_key_fingerprint':host_key_fingerprint,
        'host_id':host_id,'training_sha256':train_sha,
        '100_complete_end_to_end_signed_host_claim_slots':len(seen),
        'signature_and_physical_candidate_bytes_consistent':True,
        'trusted_host_execution_independently_attested':False,
        'native_q24_prediction_parity_verified':False,
        'causal_future_ndu_benefit_verified':False,
        'ndu_eligible':False,'production_qualification':False,
        'decision':'NO_MODEL_PROMOTION',
        'host_claimed_measures':dict(sorted(results.items())),
        'limitations':['Signed telemetry claims do not establish a trusted target host.',
                       'Source/clock/device signer independence needs external owner attestation.',
                       'Q24 parity, real future NDU effect and authorized cutover remain blocked.']
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('signed-host-receipts','trusted-host-public-key','host-id',
                 'training-receipt','training-sha256','trained-root',
                 'selected-v1','selected-v1-sha256','report'):
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    try:
        pub, fingerprint = load_public_key(Path(args.trusted_host_public_key))
        data=verify_signed(Path(args.signed_host_receipts),pub,fingerprint,SCHEMA)
        receipt_path=Path(args.training_receipt)
        sha_file(receipt_path,args.training_sha256)
        training=unique_json(receipt_path.read_bytes())
        result=validate(data,training,host_id=args.host_id,train_sha=args.training_sha256,
                        physical_weights_root=Path(args.trained_root).resolve(strict=True),
                        selected_v1=Path(args.selected_v1),
                        selected_v1_sha=args.selected_v1_sha256,
                        host_key_fingerprint=fingerprint)
        with Path(args.report).open('x',encoding='utf-8') as f:
            json.dump(result,f,sort_keys=True,indent=2)
            f.write('\n')
        print(json.dumps({'status':'A4_SIGNED_SCHEMA_COMPLETE_UNVERIFIED',
                          'slots':100,'production_qualification':False,'ndu_eligible':False}))
        return 0
    except (ValueError,KeyError,TypeError,FileNotFoundError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED_A4_HOST_EVIDENCE','reason':str(exc)}),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
