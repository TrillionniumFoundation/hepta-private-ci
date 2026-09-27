#!/usr/bin/env python3
"""Qualification evidence parser regressions; no mocked product execution claims."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'kg_budget', Path(__file__).with_name('hepta-knowledge-graph-budget-check.py'))
BUDGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUDGET)
SHA = 'a' * 40


def fixtures():
    distribution = {'p50': 1, 'p95': 2, 'p99': 3}
    evidence = {
        'schema': 'hepta.knowledge-graph-target-host-evidence.v1',
        'sourceCommit': SHA, 'sourceTree': 'b' * 40,
        'hostProfileId': 'test-ci', 'buildProfile': 'release',
        'host': {'machine': 'x86_64', 'logicalCpuCount': 4},
        'parameters': {key: 10 for key in BUDGET.PARAMETERS},
        'benchmark': {
            'schema': 'hepta.knowledge-graph-perf-library.v2',
            'hostProfileId': 'test-ci',
            'writes': 10, 'querySamples': 10, 'reopenSamples': 10,
            'mutationNs': distribution.copy(), 'queryNs': distribution.copy(),
            'reopenNs': distribution.copy(),
            'contention': {'rounds': 10, 'readersPerRound': 10, 'writerNs': distribution.copy(), 'readerNs': distribution.copy()},
            'process': {'peakRssKiB': 8},
            'storage': {'databaseBytes': 4, 'walBytes': 4},
        },
    }
    profile = {
        'schema': 'hepta.knowledge-graph-budget.v1', 'profileId': 'test-ci',
        'purpose': 'hosted-ci-regression',
        'hostEquals': {'machine': 'x86_64', 'logicalCpuCount': 4},
        'minimumParameters': {key: 5 for key in BUDGET.PARAMETERS},
        'limits': {key: 10 for key in [*BUDGET.METRICS, 'databaseAndWalBytes']},
    }
    return evidence, profile


def set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


class BudgetEvidenceTests(unittest.TestCase):
    def test_complete_evidence_does_not_grant_authority(self):
        evidence, profile = fixtures()
        result = BUDGET.evaluate(evidence, profile, SHA)
        self.assertTrue(result['budgetPassed'])
        self.assertFalse(result['independentAcceptance'])
        self.assertFalse(result['activation'])
        self.assertFalse(result['release'])
        self.assertEqual(result['sourceCommit'], SHA)

    def test_over_budget_retains_observations_and_fails(self):
        evidence, profile = fixtures()
        profile['limits']['queryP99Ns'] = 2
        result = BUDGET.evaluate(evidence, profile, SHA)
        self.assertFalse(result['budgetPassed'])
        self.assertEqual(result['checks']['queryP99Ns'], {'observed': 3, 'maximum': 2, 'passed': False})

    def test_invalid_evidence_is_rejected(self):
        invalid = [
            (('sourceCommit',), 'c' * 40), (('sourceTree',), 'bad-tree'),
            (('buildProfile',), 'debug'), (('hostProfileId',), 'another-host'),
            (('host', 'machine'), 'aarch64'), (('host', 'logicalCpuCount'), True),
            (('parameters', 'writes'), 1), (('parameters', 'writes'), True),
            (('benchmark', 'hostProfileId'), 'wrong'),
            (('benchmark', 'writes'), 9),
            (('benchmark', 'querySamples'), 1),
            (('benchmark', 'reopenSamples'), True),
            (('benchmark', 'contention', 'rounds'), 9),
            (('benchmark', 'contention', 'readersPerRound'), 11),
            (('benchmark', 'mutationNs', 'p99'), 0),
            (('benchmark', 'queryNs', 'p99'), True),
            (('benchmark', 'queryNs', 'p99'), -1),
            (('benchmark', 'process', 'peakRssKiB'), None),
            (('benchmark', 'storage', 'walBytes'), float('nan')),
            (('benchmark', 'storage', 'databaseBytes'), 2.5),
        ]
        for path, value in invalid:
            with self.subTest(path=path, value=value):
                evidence, profile = fixtures()
                set_path(evidence, path, value)
                with self.assertRaises(ValueError):
                    BUDGET.evaluate(evidence, profile, SHA)

    def test_budget_keys_and_values_are_closed(self):
        for variant in ('missing', 'extra', 'bool', 'zero'):
            with self.subTest(variant=variant):
                evidence, profile = fixtures()
                if variant == 'missing':
                    del profile['limits']['queryP99Ns']
                elif variant == 'extra':
                    profile['limits']['unknown'] = 10
                elif variant == 'bool':
                    profile['limits']['queryP99Ns'] = True
                else:
                    profile['limits']['queryP99Ns'] = 0
                with self.assertRaises(ValueError):
                    BUDGET.evaluate(evidence, profile, SHA)

    def test_target_host_requires_cpu_and_storage_binding(self):
        evidence, profile = fixtures()
        profile['purpose'] = 'target-host-measurement'
        with self.assertRaises(ValueError):
            BUDGET.evaluate(evidence, profile, SHA)
        binding = {'cpuModel': 'fixture-cpu', 'storageIdentity': 'fixture-storage'}
        profile['hostEquals'].update(binding)
        with self.assertRaises(ValueError):
            BUDGET.evaluate(evidence, profile, SHA)
        evidence['host'].update(binding)
        result = BUDGET.evaluate(evidence, profile, SHA)
        self.assertTrue(result['budgetPassed'])
        self.assertFalse(result['independentAcceptance'])

    def test_json_duplicate_and_nonfinite_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'evidence.json'
            for payload in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}', '[]', 'null', 'true'):
                with self.subTest(payload=payload):
                    path.write_text(payload)
                    with self.assertRaises(ValueError):
                        BUDGET.read_json(path)
            path.write_text(json.dumps({'x': 1}))
            self.assertEqual(BUDGET.read_json(path), {'x': 1})

    def test_expected_source_requires_literal_lowercase_sha(self):
        evidence, profile = fixtures()
        for sha in ('main', 'A' * 40, 'a' * 39, 'g' * 40):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                BUDGET.evaluate(copy.deepcopy(evidence), profile, sha)


if __name__ == '__main__':
    unittest.main()
