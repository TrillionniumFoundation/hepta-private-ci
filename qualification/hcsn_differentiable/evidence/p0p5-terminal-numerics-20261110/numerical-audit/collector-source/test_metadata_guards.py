"""Metadata-only checks: preserve HOLD on incomplete, changed or invalid evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import collect_terminal as collector
from metadata_summary import classify_payload, expected_tasks, inspect_stage, sum_observed_cost


BASE = Path(__file__).parent / 'fixtures'
PAYLOAD = BASE / 'first-finite-best-1.json'
OUTER = BASE / 'first-finite-best-1-outer.json'


class MetadataGuards(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(PAYLOAD.read_bytes())
        self.outer = json.loads(OUTER.read_bytes())
        self.receipt_sha = self.payload['input_receipt_sha256']

    def classify(self, payload=None, outer=None, closure=True):
        return classify_payload(self.payload if payload is None else payload,
                                self.outer if outer is None else outer, self.receipt_sha, closure)

    def test_original_finite_pass_is_conditional_on_complete_evidence(self):
        self.assertTrue(self.classify()['qualified_named_finite_fixture'])
        self.assertFalse(self.classify(closure=False)['qualified_named_finite_fixture'])

    def test_partial_or_hard_killed_stage_is_not_admitted(self):
        for key, value in [('returncode', -9), ('stop_cause', 'declared_stage_or_remaining_whole_wall_cap'),
                           ('execution_status', 'failed_or_budget_exhausted')]:
            changed = deepcopy(self.outer)
            changed[key] = value
            self.assertFalse(self.classify(outer=changed)['qualified_named_finite_fixture'])

    def test_nan_or_altered_scaling_cannot_pass(self):
        for altered in [float('nan'), -0.1, 0.001]:
            changed = deepcopy(self.payload)
            changed['result']['scaled_errors'][0] = altered
            self.assertFalse(self.classify(payload=changed)['qualified_named_finite_fixture'])

    def test_memory_or_plan_or_receipt_change_withholds_pass(self):
        for key, value in [('peak_rss_bytes', 2147483649), ('plan_sha256', 'changed'),
                           ('input_receipt_sha256_after', 'changed'), ('auditor_source_unchanged', False)]:
            changed = deepcopy(self.payload)
            changed[key] = value
            self.assertFalse(self.classify(payload=changed)['qualified_named_finite_fixture'])

    def test_actual_outer_time_or_memory_excess_withholds_pass(self):
        for key, value in [('whole_process_wall_seconds', 901), ('sampled_peak_RSS_bytes', 2147483649),
                           ('reported_child_peak_RSS_sample_bytes', 2147483649), ('RSS_limit_bytes', 3221225472)]:
            changed = deepcopy(self.outer)
            changed[key] = value
            self.assertFalse(self.classify(outer=changed)['qualified_named_finite_fixture'])

    def test_missing_outer_and_unstarted_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'candidate'
            folder.mkdir()
            first = inspect_stage(root, 'candidate', 'finite-best-1', self.receipt_sha, True)
            self.assertEqual(first['observation_status'], 'not_observed_to_have_started')
            (folder / 'finite-best-1.json').write_bytes(PAYLOAD.read_bytes())
            second = inspect_stage(root, 'candidate', 'finite-best-1', self.receipt_sha, True)
            self.assertEqual(second['observation_status'], 'attempt_artifacts_without_outer_completion')
            self.assertFalse(second['qualified_named_finite_fixture'])

    def test_changed_result_hash_is_preserved_as_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'candidate'
            folder.mkdir()
            (folder / 'finite-best-1.json').write_text('{}')
            (folder / 'finite-best-1-outer.json').write_bytes(OUTER.read_bytes())
            row = inspect_stage(root, 'candidate', 'finite-best-1', self.receipt_sha, True)
            self.assertEqual(row['observation_status'], 'invalid_original_artifact_chain')
            self.assertFalse(row['qualified_named_finite_fixture'])
            self.assertEqual(row['outer']['returncode'], 0)

    def test_malformed_outer_does_not_abort_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'candidate'
            folder.mkdir()
            (folder / 'finite-best-1-outer.json').write_text('[]')
            row = inspect_stage(root, 'candidate', 'finite-best-1', self.receipt_sha, True)
            self.assertEqual(row['observation_status'], 'invalid_original_artifact_chain')

    def test_logrisk_exit_zero_does_not_upgrade_original_failure(self):
        payload = deepcopy(self.payload)
        payload.update(stage='logrisk', result={'primary_passed': False, 'direct_FD_inconclusive_count': 96,
                                               'direct_FD_resolved_disagreement_count': 1,
                                               'direct_FD_all_resolved_pass': False})
        value = self.classify(payload=payload)
        self.assertFalse(value['logrisk_primary_passed'])
        self.assertEqual(value['direct_FD_resolved_disagreement_count'], 1)
        self.assertFalse(value['qualified_named_finite_fixture'])

    def test_exact_predeclared_stage_roster_is_preserved(self):
        rows = expected_tasks()
        self.assertEqual(len(rows), 96)
        self.assertEqual(len(set(rows)), 96)
        self.assertEqual(sum(stage.startswith('finite-') for _, stage in rows), 60)
        self.assertEqual(rows[36], ('hcsn-s101-lr0.001', 'finite-best-0'))
        self.assertEqual(rows[-1], ('hcsn-s307-lr0.003', 'finite-last-0'))

    def test_missing_stage_cost_stays_unknown_and_nested(self):
        rows = [{'name': 'x', 'stage': 'a', 'observation_status': 'completed_artifact_chain', 'outer': self.outer},
                {'name': 'x', 'stage': 'b', 'observation_status': 'attempt_artifacts_without_outer_completion'},
                {'name': 'x', 'stage': 'c', 'observation_status': 'not_observed_to_have_started'}]
        value = sum_observed_cost(rows)
        self.assertEqual(value['waited_stage_CPU_seconds'], self.outer['waited_child_CPU_seconds'])
        self.assertEqual(value['missing_or_invalid_cost_rows'], [{'name': 'x', 'stage': 'b'}])

    def test_terminal_guard_rejects_live_unknown_or_extended_attempt(self):
        launch = {'schema': 'terminal-HCSN-hard-deadline-launch-v1', 'process_started': True,
                  'pid': 1969758, 'hard_whole_wall_seconds': 10800, 'status': 'whole_budget_exhausted',
                  'returncode': -9, 'argv': [str(collector.PROGRAM / 'run_audit.py')],
                  'started_utc': '2026-11-10T19:21:58+00:00', 'finished_utc': '2026-11-10T22:21:58+00:00',
                  'stop_cause': 'predeclared_hard10800_whole_process_group_limit'}
        collector.terminal_guard(launch, {'returncode': 1})
        for key, value in [('status', 'running'), ('returncode', None), ('hard_whole_wall_seconds', 10801),
                           ('stop_cause', 'unknown'), ('pid', 5)]:
            bad = deepcopy(launch)
            bad[key] = value
            with self.assertRaises(ValueError):
                collector.terminal_guard(bad, {'returncode': 1})

    def test_metadata_cannot_be_written_inside_original_evidence(self):
        for protected in (collector.AUDIT, collector.PROGRAM, collector.LAUNCH, collector.BOOTSTRAP):
            with self.assertRaises(ValueError):
                collector.require_isolated_output(protected / 'new-metadata')

    def test_unreadable_known_process_does_not_establish_absence(self):
        cmdline = Mock()
        cmdline.parent.name = '1969758'
        cmdline.read_bytes.side_effect = PermissionError('synthetic denied read')
        cmdline.parent.stat.return_value.st_uid = collector.os.geteuid()
        with patch.object(collector, 'Path') as paths:
            paths.return_value.glob.return_value = [cmdline]
            result = collector.live_original_processes()
        self.assertFalse(result['absence_established'])
        self.assertEqual(len(result['scan_errors']), 1)
        self.assertTrue(result['scan_errors'][0]['possibly_relevant'])


if __name__ == '__main__':
    unittest.main()
