#!/usr/bin/env python3
"""Evaluate KG measurement budgets; never grants production acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

from hepta_kg_evidence import check_observed_parameters, strict_object

METRICS = {
    'mutationP99Ns': ('mutationNs', 'p99'),
    'queryP99Ns': ('queryNs', 'p99'),
    'reopenP99Ns': ('reopenNs', 'p99'),
    'contentionWriterP99Ns': ('contention', 'writerNs', 'p99'),
    'contentionReaderP99Ns': ('contention', 'readerNs', 'p99'),
    'peakRssKiB': ('process', 'peakRssKiB'),
}
PARAMETERS = ('writes', 'querySamples', 'reopenSamples', 'contentionReaders', 'contentionRounds')


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label}: expected integer >= {minimum}')
    return value


def at(obj, path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            raise ValueError(f'missing metric {".".join(path)}')
        obj = obj[key]
    return obj


def evaluate(evidence, profile, expected_sha):
    if not re.fullmatch('[0-9a-f]{40}', expected_sha):
        raise ValueError('expected SHA must be a lowercase literal commit SHA')
    if evidence.get('schema') != 'hepta.knowledge-graph-target-host-evidence.v1':
        raise ValueError('unsupported evidence schema')
    if evidence.get('sourceCommit') != expected_sha or not re.fullmatch('[0-9a-f]{40}', str(evidence.get('sourceTree', ''))):
        raise ValueError('source identity mismatch')
    if profile.get('schema') != 'hepta.knowledge-graph-budget.v1':
        raise ValueError('unsupported budget schema')
    if profile.get('purpose') not in ('hosted-ci-regression', 'target-host-measurement'):
        raise ValueError('unsupported budget purpose')
    if not isinstance(profile.get('profileId'), str) or not profile['profileId']:
        raise ValueError('missing profile ID')
    if evidence.get('hostProfileId') != profile['profileId']:
        raise ValueError('profile identity mismatch')
    if evidence.get('buildProfile') != 'release':
        raise ValueError('budgets require the release build profile')
    host = evidence.get('host', {})
    expected_host = profile.get('hostEquals', {})
    required = {'machine', 'logicalCpuCount'}
    if profile['purpose'] == 'target-host-measurement':
        required |= {'cpuModel', 'storageIdentity'}
    if not required.issubset(expected_host):
        raise ValueError('budget omits required CPU/storage host binding')
    for key, value in expected_host.items():
        if not value or host.get(key) != value or type(host.get(key)) is not type(value):
            raise ValueError(f'host identity mismatch: {key}')
    minimums = profile.get('minimumParameters', {})
    parameters = evidence.get('parameters', {})
    if set(minimums) != set(PARAMETERS):
        raise ValueError('all fixture minima are required')
    for key in PARAMETERS:
        if integer(parameters.get(key), key, 1) < integer(minimums[key], key, 1):
            raise ValueError(f'undersized measurement fixture: {key}')
    benchmark = evidence.get('benchmark', {})
    if benchmark.get('schema') != 'hepta.knowledge-graph-perf-library.v2' or benchmark.get('hostProfileId') != profile['profileId']:
        raise ValueError('benchmark identity mismatch')
    check_observed_parameters(benchmark, parameters)
    for path in [('mutationNs',), ('queryNs',), ('reopenNs',), ('contention', 'writerNs'), ('contention', 'readerNs')]:
        distribution = at(benchmark, path)
        values = [integer(at(distribution, (key,)), key) for key in ('p50', 'p95', 'p99')]
        if values != sorted(values):
            raise ValueError('nonmonotone percentiles')
    limits = profile.get('limits', {})
    if set(limits) != set(METRICS) | {'databaseAndWalBytes'}:
        raise ValueError('all budgets required; unknown budget keys rejected')
    measured = {name: integer(at(benchmark, path), name) for name, path in METRICS.items()}
    measured['databaseAndWalBytes'] = sum(integer(at(benchmark, ('storage', key)), key) for key in ('databaseBytes', 'walBytes'))
    results = {name: {'observed': value, 'maximum': integer(limits[name], name, 1), 'passed': value <= limits[name]} for name, value in measured.items()}
    return {'schema': 'hepta.knowledge-graph-budget-evaluation.v1', 'sourceCommit': expected_sha,
            'sourceTree': evidence['sourceTree'], 'profileId': profile['profileId'], 'purpose': profile['purpose'],
            'checks': results, 'budgetPassed': all(row['passed'] for row in results.values()),
            'independentAcceptance': False, 'activation': False, 'release': False}


def read_json(path):
    return strict_object(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = evaluate(read_json(args.evidence), read_json(args.profile), args.expected_sha)
    except (ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'KG budget evidence rejected: {error}\n')
    for name in ('evidence', 'profile'):
        result[name + 'Sha256'] = hashlib.sha256(Path(getattr(args, name)).read_bytes()).hexdigest()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['budgetPassed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
