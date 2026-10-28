"""Actual child-tree, filesystem, failure and missing-observation checks."""

import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from resource_monitor import integrate
from resource_cleanup import signal_identity
from resource_samples import callable_pid, process_stat, storage_snapshot, validate_roots, visible_pid


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux resource profile')
class ResourceMonitorTests(unittest.TestCase):
    def monitor_command(self, root, code, *, timeout_seconds=10, monitor_code=None, executable=None):
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
        return command, paths

    def execute(self, root, code, **options):
        command, paths = self.monitor_command(root, code, **options)
        result = subprocess.run(command, capture_output=True, timeout=15, check=False)
        return result, json.loads(paths['output'].read_bytes()), paths

    def live_namespace_processes(self, sample):
        processes = {}
        for process in sample['processes']:
            if process['state'] == 'Z':
                continue
            try:
                pid = callable_pid(process['pid'], process['start_ticks'])
                processes[pid] = process
            except (OSError, ValueError, KeyError, IndexError):
                continue  # An observed process may exit before the readiness check.
        return processes

    def execute_sigterm(self, root, code, ready):
        command, paths = self.monitor_command(root, code)
        unrelated = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        monitor, observed = None, {}
        try:
            unrelated_visible = visible_pid(unrelated.pid)
            monitor = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            monitor_visible = visible_pid(monitor.pid)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.assertIsNone(monitor.poll(), 'monitor exited before the SIGTERM test boundary')
                samples = []
                if paths['samples'].exists():
                    samples = [json.loads(line) for line in paths['samples'].read_bytes().splitlines(keepends=True)
                               if line.endswith(b'\n')]
                    for sample in samples:
                        observed.update({p['pid']: p['start_ticks'] for p in sample['processes']
                                         if p['pid'] != monitor_visible})
                if samples and ready(samples[-1], root / 'stock'):
                    break
                time.sleep(.01)
            else:
                self.fail('did not reach the requested live-process SIGTERM boundary')
            monitor.send_signal(signal.SIGTERM)
            _, stderr = monitor.communicate(timeout=10)
            self.assertEqual(monitor.returncode, 1, stderr.decode())
            receipt = json.loads(paths['output'].read_bytes())
            self.assertFalse(receipt['passed'])
            self.assertEqual(receipt['termination_signal'], 'SIGTERM')
            self.assertIn('SIGTERM', receipt['monitor_error'])
            self.assertIsNone(receipt['launch_error'])
            self.assertTrue(receipt['cleanup']['requested'])
            self.assertTrue(receipt['cleanup']['observed_tree_stopped'])
            self.assertEqual(receipt['cleanup']['residual_live'], [])
            self.assertIsNone(unrelated.poll(), 'cleanup must leave unrelated processes running')
            self.assertNotIn(unrelated_visible, observed)
            self.assertNotIn(unrelated_visible,
                             [item['proc_visible_pid'] for item in receipt['cleanup']['signals']])
            for pid, started in observed.items():
                try:
                    current = process_stat(pid)
                    self.assertTrue(current['start_ticks'] != started or current['state'] == 'Z',
                                    'observed child still has live userspace after monitor exit')
                except FileNotFoundError:
                    pass
            for value in receipt['integrals'].values():
                self.assertEqual(value['observed_interval_ns'] + value['unobserved_interval_ns'],
                                 receipt['wall_ns_through_observation_close'])
            return receipt
        finally:
            if monitor is not None:
                if monitor.poll() is None:
                    monitor.send_signal(signal.SIGTERM)
                    try:
                        monitor.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        monitor.kill()
                        monitor.communicate(timeout=3)
                monitor.stdout.close()
                monitor.stderr.close()
            for pid, started in observed.items():
                signal_identity(pid, started)
            if unrelated.poll() is None:
                unrelated.kill()
            unrelated.wait(timeout=3)

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

    def test_sigterm_while_root_live_preserves_failed_receipt_and_cleans_session(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-term-root-') as temporary:
            code = ("import os,pathlib,sys,time; "
                    "(pathlib.Path(sys.argv[1])/'root.pid').write_text(str(os.getpid())); time.sleep(30)")

            def ready(sample, stock):
                pid_file = stock / 'root.pid'
                if not pid_file.exists() or not (text := pid_file.read_text()).isdecimal():
                    return False
                return int(text) in self.live_namespace_processes(sample)

            receipt = self.execute_sigterm(Path(temporary), code, ready)
            self.assertEqual(receipt['exit_code'], -9)
            self.assertEqual(receipt['cleanup']['group_signal']['result'], 'signalled_owned_unreaped_group')

    def test_sigterm_after_root_exit_cleans_observed_detached_descendant(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-term-detached-') as temporary:
            code = ("import os,pathlib,subprocess,sys,time\n"
                    "stock=pathlib.Path(sys.argv[1])\n"
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)\n"
                    "(stock/'root.pid').write_text(str(os.getpid()))\n"
                    "(stock/'descendant.pid').write_text(str(child.pid))\n"
                    "while not (stock/'allow-root-exit').exists(): time.sleep(.01)\n")
            identities = {}

            def ready(sample, stock):
                if not (stock / 'descendant.pid').exists():
                    return False
                if not identities:
                    texts = {name: (stock / f'{name}.pid').read_text() for name in ('root', 'descendant')}
                    if not all(text.isdecimal() for text in texts.values()):
                        return False
                    processes = self.live_namespace_processes(sample)
                    if any(int(text) not in processes for text in texts.values()):
                        return False
                    identities.update({name: processes[int(text)]['pid'] for name, text in texts.items()})
                live = {p['pid'] for p in sample['processes'] if p['state'] != 'Z'}
                if set(identities.values()) <= live:
                    (stock / 'allow-root-exit').touch()
                try:
                    process_stat(identities['root'])
                except FileNotFoundError:
                    return identities['descendant'] in live
                return False

            receipt = self.execute_sigterm(Path(temporary), code, ready)
            self.assertEqual(receipt['exit_code'], 0)
            self.assertIsNone(receipt['cleanup']['group_signal'])
            self.assertIn(identities['descendant'], [p['proc_visible_pid'] for p in receipt['cleanup']['signals']
                                                    if p['result'] == 'signalled_pidfd'])

    def test_sigterm_cleans_observed_detached_grandchild_without_signalling_sibling(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-term-grandchild-') as temporary:
            grandchild = 'import time; time.sleep(30)'
            child = ("import pathlib,subprocess,sys,time\n"
                     f"descendant=subprocess.Popen([sys.executable,'-I','-B','-c',{grandchild!r}],start_new_session=True)\n"
                     "(pathlib.Path(sys.argv[1])/'grandchild.pid').write_text(str(descendant.pid))\n"
                     "time.sleep(30)\n")
            code = ("import os,pathlib,subprocess,sys,time\n"
                    "stock=pathlib.Path(sys.argv[1])\n"
                    f"child=subprocess.Popen([sys.executable,'-I','-B','-c',{child!r},str(stock)],start_new_session=True)\n"
                    "(stock/'root.pid').write_text(str(os.getpid()))\n"
                    "(stock/'child.pid').write_text(str(child.pid))\n"
                    "time.sleep(30)\n")
            identities = {}

            def ready(sample, stock):
                paths = {name: stock / f'{name}.pid' for name in ('root', 'child', 'grandchild')}
                if not all(path.exists() for path in paths.values()):
                    return False
                texts = {name: path.read_text() for name, path in paths.items()}
                if not all(text.isdecimal() for text in texts.values()):
                    return False
                processes = self.live_namespace_processes(sample)
                if any(int(text) not in processes for text in texts.values()):
                    return False
                identities.update({name: processes[int(text)]['pid'] for name, text in texts.items()})
                return True

            receipt = self.execute_sigterm(Path(temporary), code, ready)
            signalled = {item['proc_visible_pid'] for item in receipt['cleanup']['signals']
                         if item['result'] == 'signalled_pidfd'}
            self.assertTrue({identities['child'], identities['grandchild']} <= signalled)

    def test_sigterm_during_popen_return_waits_for_owned_pid_initialization(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-term-launch-') as temporary:
            hook = ("original = m.subprocess.Popen\n"
                    "def launch_and_stop(*args, **kwargs):\n"
                    "    child = original(*args, **kwargs)\n"
                    "    m.os.kill(m.os.getpid(), m.signal.SIGTERM)\n"
                    "    return child\n"
                    "m.subprocess.Popen = launch_and_stop")
            result, receipt, _ = self.execute(Path(temporary), 'import time; time.sleep(30)', monitor_code=hook)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertFalse(receipt['passed'])
            self.assertEqual(receipt['termination_signal'], 'SIGTERM')
            self.assertIn('SIGTERM', receipt['monitor_error'])
            self.assertEqual(receipt['exit_code'], -9)
            self.assertEqual(receipt['sample_count'], 0)
            self.assertEqual(receipt['cleanup']['group_signal']['result'], 'signalled_owned_unreaped_group')
            self.assertTrue(receipt['cleanup']['observed_tree_stopped'])
            self.assertIsNotNone(receipt['child_exit_rusage'])

    def test_sigterm_during_final_status_report_cannot_leave_successful_receipt(self):
        with tempfile.TemporaryDirectory(prefix='hepta-v9-term-report-') as temporary:
            hook = ("import builtins\n"
                    "def stop_while_reporting(*args, **kwargs):\n"
                    "    m.os.kill(m.os.getpid(), m.signal.SIGTERM)\n"
                    "    builtins.print(*args, **kwargs)\n"
                    "m.print = stop_while_reporting")
            result, receipt, _ = self.execute(Path(temporary), 'import time; time.sleep(.02)', monitor_code=hook)
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertFalse(receipt['passed'])
            self.assertFalse(receipt['all_sample_points_complete'])
            self.assertEqual(receipt['termination_signal'], 'SIGTERM')
            self.assertIn('SIGTERM', receipt['monitor_error'])
            self.assertEqual(receipt['exit_code'], 0)

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
