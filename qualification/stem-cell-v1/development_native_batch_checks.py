"""Actual CPU batch tests; require LLVM, never skip missing native execution."""

import math
import random
import unittest
from dataclasses import replace
from unittest.mock import patch

from development_native import DecisionIR, NativeDecisionCache, PreparedDecision, Rule, interpret


class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.program = DecisionIR(2, (Rule((1.0, -2.0), 0.5, 2), Rule((0.0, 1.0), 0.0, 1)), 0)
        self.cache = NativeDecisionCache(capacity=1)
        self.native, _ = self.cache.compile(self.program)
        self.reference = PreparedDecision(self.program)

    def test_actual_single_ffi_batch_matches_all_scalar_paths(self):
        rows = tuple((float(i - 8), float(i % 3 - 1)) for i in range(32))
        expected = tuple(interpret(self.program, row) for row in rows)
        with patch.object(self.native, '_batch_function', wraps=self.native._batch_function) as invoke:
            self.assertEqual(self.native.run_batch(rows), expected)
            self.assertEqual(invoke.call_count, 1)
        self.assertEqual(self.reference.run_batch(rows), expected)
        self.assertEqual(tuple(self.native(row) for row in rows), expected)

    def test_whole_batch_preflight_rejects_late_bad_member_without_execution(self):
        for row in ((math.nan, 0), (0, True), (1001, 0), (0,), [0, 0]):
            with self.subTest(row=row):
                with patch.object(self.native, '_batch_function') as invoke:
                    with self.assertRaises(ValueError):
                        self.native.run_batch(((0.0, 0.0), row))
                    invoke.assert_not_called()
                with self.assertRaises(ValueError):
                    self.reference.run_batch(((0.0, 0.0), row))

    def test_cardinality_and_container_bounds(self):
        for rows in ((), ((0.0, 0.0),) * 33, [(0.0, 0.0)]):
            with self.subTest(rows=len(rows)):
                for runner in (self.native, self.reference):
                    with self.assertRaises(ValueError):
                        runner.run_batch(rows)

    def test_public_ir_cannot_change_compiled_input_allocation(self):
        with self.assertRaises(AttributeError):
            self.native.program = DecisionIR(1, (Rule((1.0,), 0.0, 1),), 0)
        # Even deliberate mutation of the returned copy cannot alter native width.
        public_copy = self.native.program
        object.__setattr__(public_copy, 'width', 1)
        self.assertEqual(self.native.program.width, 2)
        with self.assertRaises(ValueError):
            self.native((1.0,))
        self.assertEqual(self.native((1.0, 0.0)), 2)

    def test_source_ir_is_detached_at_admission(self):
        object.__setattr__(self.program, 'width', 1)
        self.assertEqual(self.native((1.0, 0.0)), 2)
        self.assertEqual(self.reference((1.0, 0.0)), 2)

    def test_static_validation_is_shared_optimization_not_native_only_waiver(self):
        with patch.object(DecisionIR, 'validate', side_effect=AssertionError('static recheck')):
            self.assertEqual(self.native((1.0, 0.0)), self.reference((1.0, 0.0)))
            for runner in (self.native, self.reference):
                with self.assertRaises(ValueError):
                    runner((math.inf, 0.0))

    def test_cache_eviction_preserves_outstanding_batch_function(self):
        self.cache.compile(replace(self.program, default_action=9))
        self.assertEqual(self.native.run_batch(((0.0, -1.0),)), (2,))
        self.assertEqual(self.cache.compilations, 2)

    def test_batch_numerical_boundaries(self):
        rng = random.Random(812)
        rows = []
        for _ in range(100):
            y = rng.uniform(-100, 100)
            x = 0.5 + 2*y
            rows.extend(((x, y), (math.nextafter(x, math.inf), y), (math.nextafter(x, -math.inf), y)))
        for start in range(0, len(rows), 32):
            batch = tuple(rows[start:start+32])
            self.assertEqual(self.native.run_batch(batch), self.reference.run_batch(batch))

    def test_native_error_does_not_fall_back_or_retry(self):
        with patch.object(self.native, '_batch_function', return_value=-1) as invoke:
            with self.assertRaises(RuntimeError):
                self.native.run_batch(((0.0, 0.0),))
            self.assertEqual(invoke.call_count, 1)

    def test_benchmark_reports_full_batch_latency_and_prepared_control(self):
        from development_native_benchmark import compare_batches
        report = compare_batches(self.program, ((0.0, 0.0), (1.0, 0.0)), repetitions=10, warmup=0)
        self.assertEqual(set(report['summaries']),
                         {'prepared_typed', 'native_scalar_calls', 'native_one_batch_call'})
        self.assertEqual(report['summaries']['prepared_typed']['requests'], 20)
        self.assertEqual(len(report['raw_batch_ns']['native_one_batch_call']), 10)
        self.assertFalse(report['per_item_latency_reported'])
        self.assertFalse(report['production_authorized'])
        self.assertEqual(report['computer_use_e2e_status'], 'not_run')

    def test_benchmark_rejects_invalid_batch_before_compilation(self):
        from development_native_benchmark import compare_batches
        with patch.object(NativeDecisionCache, 'compile') as compile_native:
            with self.assertRaises(ValueError):
                compare_batches(self.program, ((0.0, 0.0), (math.nan, 0.0)), repetitions=10)
            compile_native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
