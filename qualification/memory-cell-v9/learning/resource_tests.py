"""Actual child-tree, filesystem, failure and missing-observation checks."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from resource_monitor import integrate
from resource_cleanup import signal_identity
from resource_samples import callable_pid, process_stat, storage_snapshot, validate_roots, visible_pid


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux resource profile')
class ResourceMonitorTests(unittest.TestCase):
    def execute(self, root, code, *, timeout_seconds=10, monitor_code=None, executable=None):
        stock = root / 'stock'
        stock.mkdir()
        paths = {key: root / (key + ('.json' if key == 'output' else '.log'))
                 for key in ('output', 'samples', 'stdout', 'stderr')}
        command = [sys.executable, '-I', '-B']
        if monitor_code is None:
            command.append(str(HERE / 'resource_monitor.py'))
        else:
            command.extend(['-c', f'import sys; sys.path.insert(0, {str(HERE)!r}); import resource_monitor as m;\n'
                            + monitor_code + '\nraise SystemExit(m.main())'])
        for key, path in paths.items():
            command.extend(['--' + key, str(path)])
        command.extend(['--root', str(stock), '--interval-ms', '10', '--timeout-seconds', str(timeout_seconds),
                        '--', executable or sys.executable, '-I', '-B', '-c', code, str(stock)])
        result = subprocess.run(command, capture_output=True, timeout=15, check=False)
        return result, json.loads(paths['output'].read_bytes()), paths

    def test_observes_descendant_memory_and_growing_then_removed_stock(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-') as temporary:
            code = ("import pathlib,subprocess,sys,time; p=pathlib.Path(sys.argv[1])/'value'; "
                    "p.write_bytes(b'a'*8192); data=bytearray(8*1024*1024); "
                    "child=subprocess.Popen([sys.executable,'-c','import time; a=bytearray(6*1024*1024); time.sleep(.3)']); "
                    "time.sleep(.15); p.write_bytes(b'b'*16384); child.wait(); p.unlink(); print('hepta-observed')")
            result, receipt, paths = self.execute(Path(temporary), code)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(receipt['passed'])
            self.assertFalse(receipt['full_cost_exact'])
            self.assertGreaterEqual(len(receipt['observed_process_identities']), 3)
            self.assertGreaterEqual(receipt['peaks_of_sequential_sample_sums']['storage_logical_bytes'], 16384)
            self.assertGreater(receipt['integrals']['tree_rss_bytes']['sampled_byte_ns_estimate'], 0)
            self.assertGreater(receipt['integrals']['storage_logical_bytes']['sampled_byte_ns_estimate'], 0)
            self.assertEqual(paths['stdout'].read_text(), 'hepta-observed\n')
            self.assertEqual(receipt['samples']['sha256'], hashlib.sha256(paths['samples'].read_bytes()).hexdigest())
            self.assertIsNotNone(receipt['child_exit_rusage'])
            for value in receipt['integrals'].values():
                self.assertEqual(value['observed_interval_ns'] + value['unobserved_interval_ns'],
                                 receipt['wall_ns_through_observation_close'])
            self.assertGreater(receipt['sampling_gaps']['before_first_sample_ns'], 0)
            self.assertGreater(receipt['sampling_gaps']['after_last_sample_ns'], 0)

    def test_failed_child_preserves_exit_stderr_and_evidence(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-fail-') as temporary:
            result, receipt, paths = self.execute(Path(temporary), "import sys; print('deliberate failure',file=sys.stderr); sys.exit(7)")
            self.assertEqual((result.returncode, receipt['passed'], receipt['exit_code']), (1, False, 7))
            self.assertEqual(paths['stderr'].read_text(), 'deliberate failure\n')

    def test_failed_launch_preserves_unknown_cost_receipt(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-launch-fail-') as temporary:
            root = Path(temporary)
            result, receipt, _ = self.execute(root, '', executable=str(root / 'absent-command'))
            self.assertEqual(result.returncode, 1)
            self.assertFalse(receipt['passed'])
            self.assertFalse(receipt['all_sample_points_complete'])
            self.assertIn('FileNotFoundError', receipt['launch_error'])
            self.assertIsNone(receipt['child_exit_rusage'])
            self.assertEqual(receipt['sample_count'], 0)
            for value in receipt['integrals'].values():
                self.assertIsNone(value['sampled_byte_ns_estimate'])
                self.assertEqual(value['unobserved_interval_ns'], receipt['wall_ns_through_observation_close'])

    def test_entirely_unavailable_sample_intervals_have_null_estimates(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-unobserved-') as temporary:
            hook = ("original = m.observe\n"
                    "def missing(*args):\n"
                    "    value = original(*args)\n"
                    "    value['metrics'] = dict.fromkeys(value['metrics'])\n"
                    "    value['process_errors'].append({'error':'injected unavailable measurement'})\n"
                    "    return value\n"
                    "m.observe = missing")
            _, receipt, _ = self.execute(Path(temporary), 'import time; time.sleep(.1)', monitor_code=hook)
            self.assertGreater(receipt['sample_count'], 1)
            self.assertFalse(receipt['all_sample_points_complete'])
            for value in receipt['integrals'].values():
                self.assertEqual(value['observed_interval_ns'], 0)
                self.assertIsNone(value['sampled_byte_ns_estimate'])
                self.assertEqual(value['unobserved_interval_ns'], receipt['wall_ns_through_observation_close'])

    def test_exception_after_root_exit_cleans_observed_detached_descendant(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-detached-error-') as temporary:
            hook = ("original = m.observe\n"
                    "def fail_after_reaping(*args):\n"
                    "    value = original(*args)\n"
                    "    if args[0] not in [p['pid'] for p in value['processes']]:\n"
                    "        raise RuntimeError('injected sample failure after direct child exit')\n"
                    "    return value\n"
                    "m.observe = fail_after_reaping")
            code = ("import pathlib,subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],start_new_session=True); "
                    "(pathlib.Path(sys.argv[1])/'descendant.pid').write_text(str(child.pid)); time.sleep(.25)")
            result, receipt, _ = self.execute(Path(temporary), code, monitor_code=hook)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertEqual(receipt['exit_code'], 0)
            self.assertIn('after direct child exit', receipt['monitor_error'])
            self.assertIsNone(receipt['cleanup']['group_signal'])
            self.assertTrue(receipt['cleanup']['observed_tree_stopped'])
            self.assertEqual(receipt['cleanup']['residual_live'], [])
            descendant = int((Path(temporary) / 'stock/descendant.pid').read_text())
            self.assertIn(descendant, [item.get('namespace_pid') for item in receipt['cleanup']['signals']
                                       if item['result'] == 'signalled_pidfd'])

    def test_timeout_after_root_exit_cleans_observed_detached_descendant(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-detached-timeout-') as temporary:
            code = ("import subprocess,sys,time; "
                    "subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],start_new_session=True); time.sleep(.25)")
            result, receipt, _ = self.execute(Path(temporary), code, timeout_seconds=1)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertTrue(receipt['timed_out_or_sample_cap'])
            self.assertIsNone(receipt['cleanup']['group_signal'])
            self.assertTrue(receipt['cleanup']['observed_tree_stopped'])
            self.assertTrue(any(item['result'] == 'signalled_pidfd' for item in receipt['cleanup']['signals']))

    def test_unreaped_root_cleanup_stops_its_own_session(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-root-timeout-') as temporary:
            result, receipt, _ = self.execute(Path(temporary), 'import time; time.sleep(10)', timeout_seconds=1)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertEqual(receipt['exit_code'], -9)
            self.assertEqual(receipt['cleanup']['group_signal']['result'], 'signalled_owned_unreaped_group')
            self.assertTrue(receipt['cleanup']['observed_tree_stopped'])

    def test_pidfd_mapping_and_changed_identity_never_signal_another_process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'], start_new_session=True)
        try:
            visible = visible_pid(child.pid)
            started = process_stat(visible)['start_ticks']
            self.assertEqual(callable_pid(visible, started), child.pid)
            self.assertEqual(signal_identity(visible, started + 1)['result'], 'identity_changed_not_signalled')
            self.assertIsNone(child.poll())
            self.assertEqual(signal_identity(visible, started)['result'], 'signalled_pidfd')
            self.assertEqual(child.wait(timeout=3), -9)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)

    def test_nested_pid_namespace_mapping_uses_callers_depth(self):
        with mock.patch('resource_samples.namespace_index', return_value=1), \
             mock.patch('resource_samples.namespace_pids', return_value=[101, 202, 303]), \
             mock.patch('resource_samples.process_stat', return_value={'start_ticks': 7}):
            self.assertEqual(callable_pid(101, 7), 202)

    def test_reuse_after_pidfd_open_is_rejected_before_signal(self):
        with mock.patch('resource_cleanup.process_stat', side_effect=[{'start_ticks': 7, 'state': 'R'}, {'start_ticks': 8}]), \
             mock.patch('resource_cleanup.callable_pid', return_value=202), \
             mock.patch('resource_cleanup.os.pidfd_open', return_value=987654), \
             mock.patch('resource_cleanup.os.close') as close, \
             mock.patch('resource_cleanup.signal.pidfd_send_signal') as send:
            self.assertEqual(signal_identity(101, 7)['result'], 'identity_changed_not_signalled')
            send.assert_not_called()
            close.assert_called_once_with(987654)

    def test_missing_measurement_never_becomes_zero_cost(self):
        totals = {'rss': {'trapezoid_numerator_byte_ns': 0, 'observed_interval_ns': 0, 'unobserved_interval_ns': 0}}
        integrate({'monotonic_ns': 10, 'metrics': {'rss': 20}},
                  {'monotonic_ns': 40, 'metrics': {'rss': None}}, totals)
        self.assertEqual(totals, {'rss': {'trapezoid_numerator_byte_ns': 0,
                                        'observed_interval_ns': 0, 'unobserved_interval_ns': 30}})

    def test_overlapping_roots_and_symlink_stock_are_not_silently_counted(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-resource-path-') as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                validate_roots([str(root), str(root / 'nested')])
            (root / 'linked').symlink_to('/dev/null')
            observed = storage_snapshot([root])
            self.assertIsNone(observed['logical_bytes'])
            self.assertGreater(observed['error_count'], 0)


if __name__ == '__main__':
    unittest.main()
