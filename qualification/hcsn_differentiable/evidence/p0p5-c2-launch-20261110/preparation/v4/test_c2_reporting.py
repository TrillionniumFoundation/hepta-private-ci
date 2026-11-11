"""Reporting-only regressions: real continuation work must not be described as zero fits."""
import ast
from pathlib import Path
import unittest

from c2_controller import cost_totals
from test_c2_terminal_result import TerminalResultTests


class ReportingTests(unittest.TestCase):
    def test_old_ambiguous_zero_field_is_absent_from_both_execution_reports(self):
        for filename in ('c2_runner.py', 'c2_controller.py'):
            tree = ast.parse(Path(__file__).with_name(filename).read_text())
            keys = [key.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                    for key in node.keys if isinstance(key, ast.Constant)]
            self.assertNotIn('formal_fits_started', keys)
            self.assertIn('fresh_independent_fits_started', keys)

    def test_missing_failed_result_cannot_report_zero_optimizer_work_as_known(self):
        rows = [{'name': 'complete', 'process_started': True, 'terminal_evidence_complete': True,
                 'new_main_updates_completed': 7, 'whole_process_wall_seconds': 2,
                 'attempt_wrapper_wall_seconds': 2.1, 'child_cpu_seconds': .5},
                {'name': 'missing', 'process_started': True, 'terminal_evidence_complete': False,
                 'whole_process_wall_seconds': 3, 'attempt_wrapper_wall_seconds': 3.1, 'child_cpu_seconds': .8}]
        result = cost_totals(rows, ['complete', 'missing'])
        self.assertEqual(result['actual_continuations_started'], 2)
        self.assertEqual(result['sum_verified_new_main_updates_completed'], 7)
        self.assertTrue(result['new_main_update_sum_is_lower_bound'])
        self.assertEqual(result['new_main_update_count_unknown_names'], ['missing'])
        self.assertEqual(result['sum_exact_per_child_cpu_seconds'], 1.3)

    def test_valid_failed_phase_keeps_its_actual_completed_update_count(self):
        fixture = TerminalResultTests(methodName='test_identified_nonzero_failure_remains_failed_and_fully_charged')
        fixture.setUp()
        try:
            fixture.result['status'] = 'budget_exhausted'
            fixture.write()
            row = fixture.gate(dict(fixture.process, returncode=2))
            self.assertEqual(row['status'], 'failed')
            self.assertEqual(row['new_main_updates_completed'], 3)
            result = cost_totals([row], [row['name']])
            self.assertEqual(result['sum_verified_new_main_updates_completed'], 3)
            self.assertFalse(result['new_main_update_sum_is_lower_bound'])
        finally:
            fixture.doCleanups()

    def test_failed_or_unknown_launch_counts_are_not_fresh_fit_claims(self):
        rows = [{'name': 'prelaunch_failure', 'process_started': False,
                 'whole_process_wall_seconds': .1, 'attempt_wrapper_wall_seconds': .1,
                 'terminal_evidence_complete': False},
                {'name': 'unknown', 'process_started': None, 'whole_process_wall_seconds': None,
                 'attempt_wrapper_wall_seconds': None}]
        result = cost_totals(rows, ['prelaunch_failure', 'unknown'])
        self.assertEqual(result['actual_continuations_started'], 0)
        self.assertTrue(result['actual_continuations_started_is_lower_bound'])
        self.assertEqual(result['new_main_update_count_unknown_names'], ['unknown'])
        self.assertTrue(result['new_main_update_sum_is_lower_bound'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
