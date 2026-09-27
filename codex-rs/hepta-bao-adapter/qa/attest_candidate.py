#!/usr/bin/env python3
"""Bind exact candidates to retained native logs; this does not grant activation."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from receipt_validation import validate_native_checks, validate_native_logs

HEX = frozenset('0123456789abcdef')

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def full_hex(value: object, length: int = 64) -> bool:
    return isinstance(value, str) and len(value) == length and all(c in HEX for c in value)

def tool(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()

def load_receipt(path: Path, role: str) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != 'hepta.secrets-native-feedback.v1':
        raise ValueError(f'unexpected {role} receipt schema')
    if value.get('candidateRole') != role or value.get('passed') is not True:
        raise ValueError(f'{role} native qualification did not pass')
    if not full_hex(value.get('head'), 40) or not full_hex(value.get('tree'), 40):
        raise ValueError(f'invalid {role} candidate identity')
    if value.get('identityClean') is not True:
        raise ValueError(f'{role} candidate identity was not clean')
    validate_native_checks(value, role)
    value['verifiedExecutedTests'] = validate_native_logs(value, role, path.parent)
    return value

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-receipt', type=Path, required=True)
    parser.add_argument('--merge-receipt', type=Path, required=True)
    parser.add_argument('--source-lock-sha256', required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    parser.add_argument('--merge-lock-sha256', required=True)
    parser.add_argument('--merge-manifest-sha256', required=True)
    parser.add_argument('--provider-evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for name in ('source_lock_sha256', 'source_manifest_sha256', 'merge_lock_sha256', 'merge_manifest_sha256'):
        if not full_hex(getattr(args, name)):
            raise ValueError(f'invalid {name}')
    source = load_receipt(args.source_receipt, 'source-head')
    merge = load_receipt(args.merge_receipt, 'synthetic-merge')
    provider = json.loads(args.provider_evidence.read_text(encoding='utf-8'))
    provider_digest = provider.get('serverSha256')
    if provider.get('dynamicLeaseExecutionProved') is not False or not full_hex(provider_digest):
        raise ValueError('provider evidence does not preserve the read-only blocker')
    attestation = {
        'schema': 'hepta.secrets-candidate-attestation.v1',
        'sourceCommitSha': source['head'], 'sourceTreeSha': source['tree'],
        'syntheticMergeSha': merge['head'], 'syntheticMergeTreeSha': merge['tree'],
        'toolchain': {'rustc': tool(['rustc','-vV']), 'cargo': tool(['cargo','-V'])},
        'os': platform.platform(), 'architecture': platform.machine(),
        'dependencyLockSha256': {'source': args.source_lock_sha256, 'syntheticMerge': args.merge_lock_sha256},
        'manifestSha256': {'source': args.source_manifest_sha256, 'syntheticMerge': args.merge_manifest_sha256},
        'providerBinarySha256': provider_digest,
        'providerEvidenceRole': 'historical_fixed_provider_probe_not_current_candidate_dynamic_e2e',
        'nativeReceipts': {'sourceSha256': sha256(args.source_receipt), 'syntheticMergeSha256': sha256(args.merge_receipt)},
        'executedNativeTests': {'source': source['verifiedExecutedTests'], 'syntheticMerge': merge['verifiedExecutedTests']},
        'providerEvidenceSha256': sha256(args.provider_evidence),
        'providerContract': 'kv_v2_exact_read_only', 'providerDynamicE2E': False,
        'productExecutionProved': False, 'independentAcceptance': False, 'releaseAuthority': False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(attestation, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(attestation, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
