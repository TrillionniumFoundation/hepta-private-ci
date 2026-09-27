#!/usr/bin/env python3
"""Parser/harness fault tests; synthetic fixtures are not performance receipts."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_kg_evidence import check_observed_parameters, strict_object

SPEC = importlib.util.spec_from_file_location(
    'kg_measure', Path(__file__).with_name('hepta-knowledge-graph-target-measure.py'))
MEASURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEASURE)


def fixture():
    latency = {'p50': 1, 'p95': 2, 'p99': 3}
    return {
        'schema': MEASURE.BENCHMARK_SCHEMA, 'hostProfileId': 'test',
        'writes': 4, 'querySamples': 3, 'reopenSamples': 2,
        'mutationNs': latency.copy(), 'queryNs': latency.copy(), 'reopenNs': latency.copy(),
        'contention': {'readersPerRound': 2, 'rounds': 3,
                       'writerNs': latency.copy(), 'readerNs': latency.copy(), 'roundNs': latency.copy()},
        'boundedQueryWork': {'returnedEdges': 1, 'omittedEdges': 2, 'matchingEdges': 3,
                             'selectedEdgesCloned': 1, 'relationEdgesScanned': 3},
        'storage': {'databaseBytes': 8, 'walBytes': 8}, 'process': {'peakRssKiB': 8},
    }


def arguments():
    return argparse.Namespace(writes=4, query_samples=3, reopen_samples=2,
                              contention_readers=2, contention_rounds=3,
                              host_profile_id='test', target_dir=None)


class MeasurementTests(unittest.TestCase):
    def test_strict_nested_json_and_root(self):
        for text in ['[]', 'null', 'true', '1', '{"nested":{"a":1,"a":2}}',
                     '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":-1e999}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_object(text)
        self.assertEqual(strict_object('{"x":2.5}'), {'x': 2.5})

    def test_raw_receipt_rejects_ambiguity(self):
        raw = MEASURE.PREFIX + json.dumps(fixture())
        self.assertEqual(MEASURE.parse_receipt(raw, 'test')['writes'], 4)
        for output in ['', raw + '\n' + raw, MEASURE.PREFIX + '[]',
                       raw.replace('"writes": 4', '"writes": 1, "writes": 4'),
                       raw.replace('"writes": 4', '"writes": NaN')]:
            with self.subTest(output=output), self.assertRaises(SystemExit):
                MEASURE.parse_receipt(output, 'test')

    def test_all_actual_fixture_dimensions_are_bound(self):
        params = {'writes': 4, 'querySamples': 3, 'reopenSamples': 2,
                  'contentionReaders': 2, 'contentionRounds': 3}
        check_observed_parameters(fixture(), params)
        for name in params:
            for value in [0, True, params[name] + 1]:
                changed = copy.deepcopy(params)
                changed[name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    check_observed_parameters(fixture(), changed)
        missing = fixture()
        del missing['contention']['rounds']
        with self.assertRaises(ValueError):
            check_observed_parameters(missing, params)

    def exercise_native(self, variant='valid'):
        with tempfile.TemporaryDirectory() as directory:
            # The harness resolves cargo's executable path before executing it.
            # macOS aliases /var to /private/var; compare canonical identity,
            # while retaining the independent content-drift assertion below.
            executable = Path(directory).resolve() / 'memory-test'
            executable.write_bytes(b'synthetic-native-executable-not-a-measurement')
            artifact = {'reason': 'compiler-artifact', 'target': {'name': 'codex_hepta_memory'},
                        'profile': {'test': True}, 'executable': str(executable)}
            observed = fixture()
            if variant == 'counts':
                observed['writes'] = 1
            status = 'test result: ok. 1 passed; 0 failed; 0 ignored; 20 filtered out;'
            if variant == 'skipped':
                status = 'test result: ok. 0 passed; 0 failed; 1 ignored; 20 filtered out;'
            raw = MEASURE.PREFIX + json.dumps(observed) + '\n' + status
            def command(*args, **kwargs):
                if args[0] == 'cargo':
                    self.assertIn('--release', args)
                    self.assertIn('--no-run', args)
                    return '' if variant == 'missing-executable' else json.dumps(artifact)
                self.assertEqual(args[0], str(executable))
                self.assertIn('--exact', args)
                self.assertIn(MEASURE.TEST_NAME, args)
                self.assertEqual(kwargs['env']['HEPTA_KG_BENCH_WRITES'], '4')
                if variant == 'binary-drift':
                    executable.write_bytes(b'changed')
                return raw
            with patch.object(MEASURE, 'command', side_effect=command):
                return MEASURE.run_benchmark(arguments())

    def test_native_artifact_digest_and_one_test_are_bound(self):
        receipt, duration, raw, native = self.exercise_native()
        self.assertEqual(receipt['writes'], 4)
        self.assertGreaterEqual(duration, 0)
        self.assertIn('1 passed', raw)
        self.assertEqual(native['sha256'], hashlib.sha256(
            b'synthetic-native-executable-not-a-measurement').hexdigest())
        self.assertEqual(native['kind'], 'native-rust-test-harness')

    def test_skipped_drift_and_undersized_execution_are_rejected(self):
        for variant in ['counts', 'skipped', 'missing-executable', 'binary-drift']:
            with self.subTest(variant=variant), self.assertRaises(SystemExit):
                self.exercise_native(variant)


if __name__ == '__main__':
    unittest.main()
