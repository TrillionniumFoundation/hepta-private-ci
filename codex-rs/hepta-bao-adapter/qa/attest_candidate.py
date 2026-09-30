#!/usr/bin/env python3
"""Bind exact candidates to retained native logs; this does not grant activation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from receipt_validation import NATIVE_SCHEMA, validate_native_checks, validate_native_logs
from qualify import ROOT

HEX = frozenset('0123456789abcdef')

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def full_hex(value: object, length: int = 64) -> bool:
    return isinstance(value, str) and len(value) == length and all(c in HEX for c in value)

def tool(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()

def git(*args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def verify_source_bindings(source: dict, merge: dict, hashes: dict, expected: dict | None = None) -> str:
    """Bind retained evidence to available Git objects and one CI attempt."""
    for field in ('workflowRunId', 'workflowAttempt', 'workflowSha'):
        if not isinstance(source.get(field), str) or not source[field] or source[field] != merge.get(field):
            raise ValueError(f'candidate receipts differ in execution identity: {field}')
    if not full_hex(source['workflowSha'], 40):
        raise ValueError('invalid workflow SHA')
    if source.get('rustToolchain') != merge.get('rustToolchain'):
        raise ValueError('candidate receipts use different executed Rust toolchains')
    for field, environment_key in (
        ('workflowRunId', 'GITHUB_RUN_ID'), ('workflowAttempt', 'GITHUB_RUN_ATTEMPT'),
        ('workflowSha', 'GITHUB_WORKFLOW_SHA'),
    ):
        current = os.environ.get(environment_key)
        if current is not None and source[field] != current:
            raise ValueError(f'candidate receipt differs from current execution: {field}')
    if expected is not None and (
        source['head'] != expected['source'] or merge['head'] != expected['merge']
    ):
        raise ValueError('candidate receipts differ from expected source and merge SHA')
    for role, receipt in (('source', source), ('merge', merge)):
        actual_tree = git('rev-parse', receipt['head'] + '^{tree}').decode().strip()
        if actual_tree != receipt['tree']:
            raise ValueError(f'{role} receipt tree does not match its Git commit')
        for name, path in (
            ('lock', 'codex-rs/Cargo.lock'),
            ('manifest', 'docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json'),
        ):
            actual_hash = hashlib.sha256(git('show', receipt['head'] + ':' + path)).hexdigest()
            if actual_hash != hashes[role + '_' + name]:
                raise ValueError(f'{role} {name} hash does not match its Git object')
    parents = git('show', '-s', '--format=%P', merge['head']).decode().split()
    if len(parents) != 2 or parents[1] != source['head']:
        raise ValueError('synthetic merge must have exact base and source parents in order')
    if expected is not None and parents[0] != expected['base']:
        raise ValueError('synthetic merge base differs from expected base SHA')
    return parents[0]

def load_receipt(path: Path, role: str) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema') != NATIVE_SCHEMA:
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
    parser.add_argument('--expected-source-sha', required=True)
    parser.add_argument('--expected-base-sha', required=True)
    parser.add_argument('--expected-merge-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for name in ('source_lock_sha256', 'source_manifest_sha256', 'merge_lock_sha256', 'merge_manifest_sha256'):
        if not full_hex(getattr(args, name)):
            raise ValueError(f'invalid {name}')
    expected = {'source': args.expected_source_sha, 'base': args.expected_base_sha, 'merge': args.expected_merge_sha}
    if any(not full_hex(value, 40) for value in expected.values()):
        raise ValueError('invalid expected candidate SHA')
    source = load_receipt(args.source_receipt, 'source-head')
    merge = load_receipt(args.merge_receipt, 'synthetic-merge')
    base = verify_source_bindings(source, merge, {
        'source_lock': args.source_lock_sha256,
        'source_manifest': args.source_manifest_sha256,
        'merge_lock': args.merge_lock_sha256,
        'merge_manifest': args.merge_manifest_sha256,
    }, expected)
    provider = json.loads(args.provider_evidence.read_text(encoding='utf-8'))
    provider_digest = provider.get('serverSha256')
    if provider.get('dynamicLeaseExecutionProved') is not False or not full_hex(provider_digest):
        raise ValueError('provider evidence does not preserve the read-only blocker')
    attestation = {
        'schema': 'hepta.secrets-candidate-attestation.v1',
        'sourceCommitSha': source['head'], 'sourceTreeSha': source['tree'],
        'syntheticMergeSha': merge['head'], 'syntheticMergeTreeSha': merge['tree'],
        'baseSha': base, 'workflowRunId': source['workflowRunId'],
        'workflowAttempt': source['workflowAttempt'], 'workflowSha': source['workflowSha'],
        'toolchain': {'rustc': source['rustToolchain'], 'cargo': tool(['cargo','-V'])},
        'os': platform.platform(), 'architecture': platform.machine(),
        'dependencyLockSha256': {'source': args.source_lock_sha256, 'syntheticMerge': args.merge_lock_sha256},
        'manifestSha256': {'source': args.source_manifest_sha256, 'syntheticMerge': args.merge_manifest_sha256},
        'providerBinarySha256': provider_digest,
        'providerEvidenceRole': 'historical_fixed_provider_probe_not_current_candidate_dynamic_e2e',
        'nativeReceipts': {'sourceSha256': sha256(args.source_receipt), 'syntheticMergeSha256': sha256(args.merge_receipt)},
        'executedNativeTests': {'source': source['verifiedExecutedTests'], 'syntheticMerge': merge['verifiedExecutedTests']},
        'providerEvidenceSha256': sha256(args.provider_evidence),
        'providerContract': 'kv_v2_exact_read_only', 'providerDynamicE2E': False,
        'evidenceAuthentication': 'retained_native_logs_not_independently_signed',
        'independentAuthenticationVerified': False,
        'productExecutionProved': False, 'independentAcceptance': False, 'releaseAuthority': False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(attestation, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(attestation, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
