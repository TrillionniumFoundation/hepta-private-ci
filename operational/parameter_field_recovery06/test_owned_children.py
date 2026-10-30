"""CONTEXT_RECONSTRUCTION: real small-child ownership tests, never science."""

import contextlib
import errno
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from . import owned_children as owned


READY_SLEEP = "import time; print('ready',flush=True); time.sleep(30)"
IGNORE_TERM = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(30)"


def raw_wait4(process, timeout=5):
    deadline = time.monotonic()+timeout
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return {'pid': pid, 'wait_status': status, 'exit_code': process.returncode,
                    'cpu_seconds': usage.ru_utime+usage.ru_stime,
                    'user_cpu_seconds': usage.ru_utime, 'system_cpu_seconds': usage.ru_stime,
                    'peak_rss_bytes': usage.ru_maxrss*1024}
        if time.monotonic() >= deadline:
            os.kill(process.pid, signal.SIGKILL)
            pid, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            raise TimeoutError('Synthetic child exceeded bounded test wait')
        time.sleep(.01)


class OwnedChildrenTests(unittest.TestCase):
    def setUp(self):
        target = os.environ.get('HEPTA_OWNED_TEST_OUTPUT')
        if target:
            self.base = Path(target)/self._testMethodName; self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='owned-reconstruction-'); self.addCleanup(temporary.cleanup); self.base = Path(temporary.name)
        self.core = SimpleNamespace(subprocess=subprocess)
        self.receipts = self.base/'owned'
        self.original_popen = subprocess.Popen

    def run_owned(self, callback, **kwargs):
        return owned.run_controller(self.core, callback, self.receipts,
                                    term_grace_seconds=.05, kill_wait_seconds=.5, **kwargs)

    def spawn(self, code, **kwargs):
        return self.core.subprocess.Popen([sys.executable, '-B', '-c', code], cwd=self.base,
                                         stdout=self.core.subprocess.PIPE, stderr=self.core.subprocess.STDOUT, **kwargs)

    def ready(self, code=READY_SLEEP):
        process = self.spawn(code)
        self.assertEqual(process.stdout.readline(), b'ready\n')
        return process

    def closure(self):
        value = json.loads((self.receipts/'CLOSURE.json').read_text())
        self.assertIs(self.core.subprocess, subprocess)
        self.assertIs(subprocess.Popen, self.original_popen)
        return value

    def assert_reaped(self, closure, count):
        self.assertEqual(closure['returned_children'], count)
        self.assertTrue(closure['all_returned_direct_children_reaped'])
        self.assertTrue(all(not Path('/proc/%d' % row['pid']).exists() for row in closure['children']))

    def test_exact_passthrough_normal_return_and_single_wait4(self):
        expected = {'cwd': str(self.base), 'marker': 'unchanged explicit fixture value', 'pgid': os.getpgid(0), 'sid': os.getsid(0)}
        environment = dict(os.environ); environment['OWNED_TEST_MARKER'] = expected['marker']
        captured = {}; sentinel = object()
        def callback():
            process = self.spawn("import json,os; print(json.dumps({'cwd':os.getcwd(),'marker':os.environ['OWNED_TEST_MARKER'],'pgid':os.getpgid(0),'sid':os.getsid(0)}))", env=environment)
            with mock.patch.object(process._raw, 'poll', side_effect=AssertionError('raw poll must never reap')):
                captured['output'] = json.loads(process.stdout.read())
                self.assertEqual(process.wait(), 0)
                first = process.wait4
                self.assertEqual(process.poll(), 0); self.assertEqual(process.wait(timeout=0), 0)
                self.assertIs(process.wait4, first)
            return sentinel
        self.assertIs(self.run_owned(callback), sentinel)
        self.assertEqual(captured['output'], expected)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(len(list(self.receipts.glob('*.WAIT4.json'))), 1)
        self.assertEqual(closure['direct_workers_cpu_seconds'], closure['children'][0]['wait4']['cpu_seconds'])
        self.assertTrue(closure['accounting_complete_for_attempted_direct_workers'])
        self.assertEqual(closure['children'][0]['signals'], [])

    def test_nonzero_exit_code_is_original(self):
        self.assertEqual(self.run_owned(lambda: self.spawn('raise SystemExit(7)').wait()), 7)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(closure['children'][0]['wait4']['exit_code'], 7)

    def test_memory_error_object_preserved_and_child_reaped(self):
        original = MemoryError('synthetic registered margin failure')
        def callback():
            self.ready()
            raise original
        with self.assertRaises(MemoryError) as caught:
            self.run_owned(callback)
        self.assertIs(caught.exception, original)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(closure['original_exception'], {'type': 'MemoryError', 'message': str(original)})
        self.assertEqual(closure['children'][0]['wait4']['exit_code'], -signal.SIGTERM)

    def test_system_exit_object_and_code_preserved(self):
        original = SystemExit(37)
        def callback():
            self.ready()
            raise original
        with self.assertRaises(SystemExit) as caught:
            self.run_owned(callback)
        self.assertIs(caught.exception, original); self.assertEqual(caught.exception.code, 37)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(closure['original_exception']['system_exit_code'], 37)

    def test_already_exited_unreaped_child_never_signaled(self):
        def callback():
            process = self.spawn("print('done',flush=True)")
            self.assertEqual(process.stdout.read(), b'done\n')
        self.run_owned(callback)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(closure['children'][0]['signals'], [])
        self.assertEqual(closure['children'][0]['wait4']['exit_code'], 0)

    def test_ignored_term_escalates_to_kill_and_waits(self):
        self.run_owned(lambda: self.ready(IGNORE_TERM))
        closure = self.closure(); self.assert_reaped(closure, 1)
        row = closure['children'][0]
        self.assertEqual([item['signal'] for item in row['signals']], [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(row['wait4']['exit_code'], -signal.SIGKILL)

    def test_identity_mismatch_refuses_signal_and_unrelated_group_peer_survives(self):
        peer = subprocess.Popen([sys.executable, '-B', '-c', READY_SLEEP], cwd=self.base, stdout=subprocess.PIPE)
        self.assertEqual(peer.stdout.readline(), b'ready\n')
        try:
            def callback():
                process = self.ready(); actual = process.identity
                process.identity = {**actual, 'start_ticks': actual['start_ticks']+1}
                try:
                    with mock.patch.object(signal, 'pidfd_send_signal', wraps=signal.pidfd_send_signal) as send:
                        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                            process.terminate()
                        send.assert_not_called()
                    self.assertEqual(os.getpgid(peer.pid), os.getpgid(process.pid))
                    self.assertIsNone(process.poll())
                finally:
                    process.identity = actual
            self.run_owned(callback)
            self.assert_reaped(self.closure(), 1)
            self.assertTrue(Path('/proc/%d' % peer.pid).exists())
            os.kill(peer.pid, signal.SIGTERM)
            result = raw_wait4(peer)
            self.assertEqual(result['exit_code'], -signal.SIGTERM)
        finally:
            if peer.returncode is None:
                os.kill(peer.pid, signal.SIGKILL); raw_wait4(peer)
            peer.stdout.close()

    def test_two_live_children_are_both_reaped_on_exception(self):
        original = RuntimeError('synthetic controller failure')
        def callback():
            self.ready(); self.ready()
            raise original
        with self.assertRaises(RuntimeError) as caught:
            self.run_owned(callback)
        self.assertIs(caught.exception, original)
        closure = self.closure(); self.assert_reaped(closure, 2)
        self.assertTrue(closure['accounting_complete_for_attempted_direct_workers'])

    def test_real_exec_format_error_preserves_unknown_construction_cost(self):
        executable = self.base/'bad_exec'; executable.write_text('not an executable header\n'); executable.chmod(0o700)
        captured = {}
        def callback():
            try:
                self.core.subprocess.Popen([str(executable)], cwd=self.base)
            except OSError as error:
                captured['error'] = error
                raise
        with self.assertRaises(OSError) as caught:
            self.run_owned(callback)
        self.assertIs(caught.exception, captured['error']); self.assertEqual(caught.exception.errno, errno.ENOEXEC)
        closure = self.closure()
        self.assertEqual((closure['attempt_count'], closure['returned_children']), (1, 0))
        self.assertTrue(closure['construction_wait4_unavailable'])
        self.assertFalse(closure['accounting_complete_for_attempted_direct_workers'])
        self.assertNotIn('pid', closure['attempts'][0])

    def test_start_receipt_failure_tracks_and_reaps_returned_child(self):
        original = OSError('synthetic START receipt write failure')
        emit = owned.OwnedChildren.emit
        def fail(owner, name, value):
            if name.endswith('.START.json'):
                owner.receipt_errors.append({'name': name, 'error': {'type': 'OSError', 'message': str(original)}})
                raise original
            return emit(owner, name, value)
        with mock.patch.object(owned.OwnedChildren, 'emit', fail):
            with self.assertRaises(OSError) as caught:
                self.run_owned(lambda: self.spawn(READY_SLEEP))
        self.assertIs(caught.exception, original)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertFalse(closure['accounting_complete_for_attempted_direct_workers'])

    def test_final_receipt_failure_never_masks_original_exception(self):
        original = MemoryError('original failure before final receipt')
        emit = owned.OwnedChildren.emit
        def fail(owner, name, value):
            if name == 'CLOSURE.json':
                raise OSError('synthetic final receipt failure')
            return emit(owner, name, value)
        def callback():
            self.ready()
            raise original
        with mock.patch.object(owned.OwnedChildren, 'emit', fail), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(MemoryError) as caught:
                self.run_owned(callback)
        self.assertIs(caught.exception, original)
        self.assertTrue(any('finalization also failed' in value for value in original.__notes__))
        self.assertIn('owned_child_closure_write_failed', stderr.getvalue())
        waited = [json.loads(p.read_text()) for p in self.receipts.glob('*.WAIT4.json')]
        self.assertEqual(len(waited), 1)
        self.assertFalse(Path('/proc/%d' % waited[0]['pid']).exists())
        self.assertIs(self.core.subprocess, subprocess)

    def test_envelope_proxy_nests_without_global_popen_mutation(self):
        observed = []
        class EnvelopeProxy:
            def __init__(inner, original):
                inner.original = original
            def __getattr__(inner, name):
                return getattr(inner.original, name)
            def Popen(inner, *args, **kwargs):
                value = inner.original.Popen(*args, **kwargs); observed.append(value.pid); return value
        def callback():
            original = self.core.subprocess
            self.core.subprocess = EnvelopeProxy(original)
            try:
                self.assertIs(subprocess.Popen, self.original_popen)
                return self.spawn('raise SystemExit(3)').wait()
            finally:
                self.core.subprocess = original
        self.assertEqual(self.run_owned(callback), 3)
        closure = self.closure(); self.assert_reaped(closure, 1)
        self.assertEqual(observed, [closure['children'][0]['pid']])

    def driver(self, mode):
        path = self.base/'driver.py'
        repo = Path(__file__).resolve().parents[2]
        code = """import json,os,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from operational.parameter_field_recovery06.owned_children import run_controller
core=SimpleNamespace(subprocess=subprocess)
mode=sys.argv[3]
def callback():
    source=\"import time; print('ready',flush=True); time.sleep(30)\" if mode=='signal' else \"import time; end=time.process_time()+.06\\nwhile time.process_time()<end: pass\"
    child=core.subprocess.Popen([sys.executable,'-B','-c',source],cwd=sys.argv[2],stdout=core.subprocess.PIPE)
    if mode=='signal':
        assert child.stdout.readline()==b'ready\\n'
        print(json.dumps({'worker_pid':child.pid,'driver_pid':os.getpid()}),flush=True)
        while True:time.sleep(.05)
    return child.wait()
raise SystemExit(run_controller(core,callback,Path(sys.argv[2])/'driver_owned',term_grace_seconds=.05,kill_wait_seconds=.5))
"""
        path.write_text(code)
        return subprocess.Popen([sys.executable, '-B', str(path), str(repo), str(self.base), mode],
                                cwd=self.base, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_external_sigterm_preserves_real_signal_exit_and_reaps_worker(self):
        process = self.driver('signal')
        try:
            line = process.stdout.readline()
            self.assertTrue(line, 'Synthetic driver did not become ready')
            ready = json.loads(line)
            os.kill(process.pid, signal.SIGTERM)
            measured = raw_wait4(process)
            (self.base/'DRIVER_WAIT4.json').write_text(json.dumps(measured, indent=2)+'\n')
            self.assertEqual(measured['exit_code'], -signal.SIGTERM)
            closure = json.loads((self.base/'driver_owned/CLOSURE.json').read_text())
            self.assert_reaped(closure, 1)
            self.assertEqual(closure['pending_signal'], signal.SIGTERM)
            self.assertFalse(Path('/proc/%d' % ready['worker_pid']).exists())
        finally:
            if process.returncode is None:
                os.kill(process.pid, signal.SIGKILL); raw_wait4(process)
            process.stdout.close(); process.stderr.close()

    def test_actual_outer_wait4_contains_inner_worker_cpu_without_addition(self):
        process = self.driver('cpu')
        try:
            measured = raw_wait4(process)
            self.assertEqual(measured['exit_code'], 0, process.stderr.read().decode())
            closure = json.loads((self.base/'driver_owned/CLOSURE.json').read_text())
            self.assert_reaped(closure, 1)
            inner = closure['direct_workers_cpu_seconds']
            self.assertGreater(inner, .05)
            self.assertGreaterEqual(measured['cpu_seconds']+1e-6, inner)
            (self.base/'OUTER_WAIT4.json').write_text(json.dumps({**measured, 'inner_cpu_is_nested': inner,
                'exclusive_remainder': measured['cpu_seconds']-inner,
                'reported_total': measured['cpu_seconds'], 'do_not_add_inner_again': True}, indent=2)+'\n')
        finally:
            if process.returncode is None:
                os.kill(process.pid, signal.SIGKILL); raw_wait4(process)
            process.stdout.close(); process.stderr.close()


if __name__ == '__main__':
    unittest.main()
