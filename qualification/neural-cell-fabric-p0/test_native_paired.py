"""Adversarial and physical true CPU calls in two matched-work pilots."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import unittest
from fabric import Denied
from native_paired import _envelope, run_paired
from native import CellProgram
from fabric import sha, Q24


class NativePairTests(unittest.TestCase):
    def test_actual_compiled_vs_typed_equal_work(self):
        r = run_paired(repetitions=64, repeats=2)
        self.assertEqual(r['calls_per_arm'], 128)
        self.assertTrue(r['typed_vs_native_same_numeric_outputs'])
        self.assertEqual(len(r['paired_runs']), 2)
        self.assertTrue(r['native_excludes_double_python_reference_but_postcall_uses_separate_oracle'])
        self.assertFalse(r['speedup_claim_authorized'])
        self.assertEqual((r['authority'], r['disposition']), ('DENY_ALL', 'HOLD_NO_GO'))
        self.assertIn('real OS UI', r['scope_missing'])

    def test_bounded_cost_plan(self):
        for options in ({'repetitions': 63}, {'repetitions': 4097},
                        {'repetitions': 64, 'repeats': 1}):
            with self.subTest(options=options):
                with self.assertRaises(Denied):
                    run_paired(**options)

    def test_invalid_program_no_effect(self):
        p = CellProgram(sha(b'a'), sha(b'b'), 1, 'CLICK_UI', requested_effect=True)
        with self.assertRaises(Denied):
            _envelope(p, (Q24,), (Q24,))

    def test_input_shape_and_boolean_rejected(self):
        p = CellProgram(sha(b'a'), sha(b'b'), 1, 'PURE_Q24_DOT16')
        for a,b in [((True,), (Q24,)), ((Q24,), ()), ((9*Q24,), (Q24,))]:
            with self.subTest(a=a,b=b):
                with self.assertRaises(Denied):
                    _envelope(p,a,b)


if __name__ == '__main__':
    unittest.main()
