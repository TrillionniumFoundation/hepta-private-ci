#!/usr/bin/env python3
"""Fail-closed physical Cell Split evidence qualification; never grants cutover authority."""
import argparse
import base64
import hashlib
import itertools
import json
import math
import subprocess
import tempfile
from pathlib import Path

METRICS = ('p50_ms', 'p95_ms', 'p99_ms', 'throughput_s', 'cpu_pct',
           'rss_bytes', 'communication_bytes', 'fsync_p99_ms', 'lock_wait_p99_ms',
           'recovery_p99_ms', 'long_term_negative_transfer', 'utility',
           'future_window_retention')
LOWER = ('p50_ms', 'p95_ms', 'p99_ms', 'cpu_pct', 'rss_bytes', 'communication_bytes',
         'fsync_p99_ms', 'lock_wait_p99_ms', 'recovery_p99_ms',
         'long_term_negative_transfer')
HIGHER = ('throughput_s', 'utility', 'future_window_retention')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(value):
    return isinstance(value, str) and len(value) == 64 and all(
        char in '0123456789abcdef' for char in value)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def verify_observer(evidence, signature, key):
    raw = base64.b64decode(signature, validate=True)
    require(len(raw) == 64, 'invalid Ed25519 signature')
    with tempfile.TemporaryDirectory() as directory:
        message_path = Path(directory) / 'message'
        signature_path = Path(directory) / 'signature'
        message_path.write_bytes(canonical(evidence))
        signature_path.write_bytes(raw)
        completed = subprocess.run(
            ['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(key),
             '-rawin', '-in', str(message_path), '-sigfile', str(signature_path)],
            check=False, capture_output=True)
        require(completed.returncode == 0, 'observer signature verification failed')


def qualify(manifest, observer_key, pinned_policy_digest):
    policy = {name: value for name, value in manifest.items() if name != 'cases'}
    require(hashlib.sha256(canonical(policy)).hexdigest() == pinned_policy_digest,
            'externally pinned qualification policy mismatch')
    require(manifest.get('schema') == 'hepta.physical-split-qualification.v1',
            'invalid schema')
    factors = manifest.get('dimensions')
    require(isinstance(factors, dict) and len(factors) == 4,
            'exactly four binary factors required')
    for name, values in factors.items():
        require(isinstance(name, str) and bool(name)
                and isinstance(values, list) and len(values) == 2
                and len(set(values)) == 2
                and all(isinstance(v, str) and bool(v) for v in values),
                'invalid factor')
    expected = set(itertools.product(*factors.values()))
    workload = manifest.get('frozen_workload_sha256')
    observer = manifest.get('observer_id')
    require(digest(workload), 'frozen workload digest required')
    require(isinstance(observer, str) and bool(observer), 'observer identity required')
    upper = manifest.get('max_candidate_over_baseline')
    lower = manifest.get('min_candidate_over_baseline')
    require(isinstance(upper, dict) and set(upper) == set(LOWER), 'upper limits incomplete')
    require(isinstance(lower, dict) and set(lower) == set(HIGHER), 'lower limits incomplete')
    require(all(number(value) and value >= 1 for value in upper.values()),
            'invalid upper ratio')
    require(all(number(value) and value > 0 for value in lower.values()),
            'invalid lower ratio')
    cases = manifest.get('cases')
    require(isinstance(cases, list) and len(cases) == 16,
            'exactly sixteen cases required')
    seen = set()
    for case in cases:
        require(isinstance(case, dict) and set(case) == {'evidence', 'signature_b64'},
                'case must contain only evidence and signature')
        evidence = case['evidence']
        require(isinstance(evidence, dict), 'invalid evidence')
        require(evidence.get('observer_id') == observer, 'observer mismatch')
        executor_id, evaluator_id = evidence.get('executor_id'), evidence.get('evaluator_id')
        require(all(isinstance(value, str) and bool(value)
                    for value in (executor_id, evaluator_id))
                and len({executor_id, evaluator_id, observer}) == 3,
                'observer/evaluator/executor role collision')
        require(evidence.get('frozen_workload_sha256') == workload,
                'unfrozen workload')
        combination = evidence.get('factors')
        require(isinstance(combination, dict) and set(combination) == set(factors),
                'factor names mismatch')
        key = tuple(combination[name] for name in factors)
        require(key in expected and key not in seen, 'unknown or duplicate case')
        seen.add(key)
        for name in ('baseline_evidence_sha256', 'candidate_evidence_sha256'):
            require(digest(evidence.get(name)), f'{name} missing')
        require(evidence['baseline_evidence_sha256']
                != evidence['candidate_evidence_sha256'], 'identical evidence digests')
        for name in ('baseline', 'candidate'):
            values = evidence.get(name)
            require(isinstance(values, dict) and set(values) == set(METRICS),
                    f'{name} metrics incomplete')
            require(all(number(value) for value in values.values()),
                    f'{name} has invalid metrics')
            require(all(values[metric] > 0 for metric in HIGHER),
                    f'{name} positive metrics invalid')
        baseline, candidate = evidence['baseline'], evidence['candidate']
        for metric, limit in upper.items():
            require(candidate[metric] <= baseline[metric] * limit
                    if baseline[metric] else candidate[metric] == 0,
                    f'{metric} regression')
        for metric, limit in lower.items():
            require(candidate[metric] >= baseline[metric] * limit,
                    f'{metric} improvement below threshold')
        verify_observer(evidence, case['signature_b64'], observer_key)
    require(seen == expected, 'matrix incomplete')
    return {'qualified': True, 'cases_verified': 16,
            'frozen_workload_sha256': workload, 'observer_id': observer,
            'execution_authority': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest')
    parser.add_argument('--pinned-observer-public-key', required=True)
    parser.add_argument('--pinned-policy-sha256', required=True)
    args = parser.parse_args()
    try:
        result = qualify(read_json(args.manifest),
                         Path(args.pinned_observer_public_key),
                         args.pinned_policy_sha256)
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({'qualified': False, 'reason': str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
