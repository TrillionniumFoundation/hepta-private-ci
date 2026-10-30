"""Linux tiny-process lifecycle tests; never construct a production config."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from . import daemon_bootstrap as bootstrap
from . import wait4_launcher as launcher


def fixture(directory, mode='success', injection=''):
    """Create only tiny stdlib children and explicit synthetic completion records."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    ops, cwd = directory / 'ops', directory / 'empty'
    ops.mkdir()
    cwd.mkdir()
    script = directory / 'tiny_supervisor.py'
    script.write_text("""import json,os,pathlib,time
from operational.parameter_field_recovery06.owned_children import proc_identity
root=pathlib.Path(%r)
identity=proc_identity(os.getpid())
parent=proc_identity(os.getppid())
assert parent['parent_pid']==1
(root/'CHILD_STARTED.json').write_text(json.dumps({'identity':identity,'measuring_parent':parent,'synthetic_test_fixture':True}))
end=time.monotonic()+120
while not (root/'RELEASE').exists():
    if time.monotonic()>end:raise RuntimeError('Fixture release absent')
    assert proc_identity(parent['pid'])==parent
    time.sleep(.02)
if %r=='nonzero':raise SystemExit(7)
(root/'ops/COMPLETE.json').write_text(json.dumps({'schema':'hepta.fullstudy.pipeline-completion.4','complete':True,'synthetic_test_fixture':True}))
""" % (str(directory), mode))
    config = {'python': sys.executable, 'source_root': str(Path(__file__).resolve().parents[2]),
              'ops_root': str(ops), 'empty_cwd': str(cwd), 'synthetic_fixture': True,
              'descriptors': {'own_supervisor': bootstrap.descriptor(script),
                  'daemon_bootstrap': bootstrap.descriptor(Path(bootstrap.__file__).resolve()),
                  'wait4_launcher': bootstrap.descriptor(Path(launcher.__file__).resolve())}}
    (directory / 'CONFIG.json').write_text(json.dumps(config, sort_keys=True) + '\n')
    driver = directory / 'tiny_bootstrap_driver.py'
    driver.write_text("""import json,pathlib,signal,sys,time
signal.signal(signal.SIGHUP,signal.SIG_DFL)
sys.path.insert(0,%r)
from operational.parameter_field_recovery06 import daemon_bootstrap as d,wait4_launcher as w
root=pathlib.Path(%r)
config=json.loads((root/'CONFIG.json').read_text())
item=d.descriptor(root/'CONFIG.json')
binding={'execution_episode':w.EPISODE,'pipeline_config':item,'daemon_bootstrap':config['descriptors']['daemon_bootstrap'],'wait4_launcher':config['descriptors']['wait4_launcher']}
%s
def run(ready):return w.run_measured(config,item,root/'ops/wait4_launcher',detachment=ready)
result=d.detach_and_run(root/'detached',root/'launcher.lock',binding,run)
print(json.dumps(result),flush=True)
if '--stay' in sys.argv:
    while True:time.sleep(.05)
""" % (str(Path(__file__).resolve().parents[2]), str(directory), injection))
    (directory / 'SYNTHETIC_TEST_FIXTURE.json').write_text(json.dumps({
        'scientific_workers_started': 0, 'production_config': False, 'target': 'tiny stdlib supervisor only'}) + '\n')
    return driver


def await_file(path, timeout=8):
    deadline = time.monotonic() + timeout
    while not Path(path).is_file():
        if time.monotonic() >= deadline:
            raise AssertionError('Fixture file absent: ' + str(path))
        time.sleep(.02)
    return json.loads(Path(path).read_text())


class DetachedBootstrapTests(unittest.TestCase):
    def setUp(self):
        output = os.environ.get('HEPTA_DAEMON_TEST_OUTPUT')
        if output:
            self.base = Path(output) / self._testMethodName
        else:
            temp = tempfile.TemporaryDirectory(prefix='hepta-detached-fixture-')
            self.addCleanup(temp.cleanup)
            self.base = Path(temp.name) / 'case'
        self.addCleanup(self.release)

    def release(self):
        if self.base.exists():
            (self.base / 'RELEASE').touch(exist_ok=True)

    def launch(self, injection='', mode='success'):
        driver = fixture(self.base, mode, injection)
        result = subprocess.run([sys.executable, '-B', str(driver)], capture_output=True, text=True, timeout=6)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def finish(self, expected=0):
        self.release()
        value = await_file(self.base / 'ops/wait4_launcher/WAIT4_COMPLETE.json')
        returned = await_file(self.base / 'detached/DAEMON_RETURNED.json')
        self.assertEqual(value['exit_code'], expected)
        self.assertEqual(returned['target_exit_code'], expected)
        closure = await_file(self.base / 'ops/wait4_launcher/owned_supervisor/CLOSURE.json')
        self.assertTrue(closure['all_returned_direct_children_reaped'])
        self.assertEqual(value['total_cpu_seconds_inclusive'], closure['children'][0]['wait4']['cpu_seconds'])
        self.assertFalse(Path('/proc/%d' % value['waited_pid']).exists())
        return value

    def test_caller_returns_and_inherited_pipes_close_before_measured_child_finishes(self):
        driver = fixture(self.base)
        read_fd, write_fd = os.pipe()
        try:
            # communicate must receive EOF while the detached target remains live.
            result = subprocess.run([sys.executable, '-B', str(driver)], capture_output=True,
                                    text=True, pass_fds=(write_fd,), timeout=6)
            self.assertEqual(result.returncode, 0, result.stderr)
            accepted = json.loads(result.stdout)
            child = await_file(self.base / 'CHILD_STARTED.json')
            identity = accepted['measuring_parent_identity']
            self.assertEqual(bootstrap.proc_identity(identity['pid']), identity)
            self.assertEqual(child['measuring_parent'], identity)
            self.assertEqual(identity['parent_pid'], 1)
            target = os.readlink('/proc/self/fd/%d' % write_fd)
            links = []
            for path in Path('/proc/%d/fd' % identity['pid']).iterdir():
                try: links.append(os.readlink(path))
                except FileNotFoundError: pass
            self.assertNotIn(target, links)
            self.assertFalse((self.base / 'ops/wait4_launcher/WAIT4_COMPLETE.json').exists())
            value = self.finish()
            self.assertEqual(value['measuring_parent_identity'], identity)
            self.assertEqual(value['detached_start'], accepted['ready'])
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_originating_session_leader_exit_does_not_change_measuring_parent(self):
        driver = fixture(self.base)
        caller = subprocess.Popen([sys.executable, '-B', str(driver), '--stay'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            accepted = json.loads(caller.stdout.readline())
            await_file(self.base / 'CHILD_STARTED.json')
            identity = accepted['measuring_parent_identity']
            self.assertEqual(os.getsid(caller.pid), caller.pid)
            caller.send_signal(signal.SIGHUP)
            self.assertEqual(caller.wait(timeout=3), -signal.SIGHUP)
            self.assertEqual(bootstrap.proc_identity(identity['pid']), identity)
            self.assertEqual(self.finish()['measuring_parent_identity'], identity)
        finally:
            if caller.poll() is None:
                caller.terminate()
                caller.wait(timeout=3)
            caller.stdout.close()
            caller.stderr.close()

    def test_existing_attempt_cannot_launch_second_target(self):
        accepted = self.launch()
        await_file(self.base / 'CHILD_STARTED.json')
        original = bootstrap.descriptor(self.base / 'detached/READY.json')
        second = subprocess.run([sys.executable, '-B', str(self.base / 'tiny_bootstrap_driver.py')],
                                capture_output=True, text=True, timeout=3)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('FileExistsError', second.stderr)
        self.assertEqual(bootstrap.descriptor(self.base / 'detached/READY.json'), original)
        self.assertEqual(self.finish()['measuring_parent_identity'], accepted['measuring_parent_identity'])

    def test_acceptance_write_failure_never_starts_target_and_is_not_retryable(self):
        injection = """d.HANDOFF_SECONDS=.5
original=d.write_new
def failure(path,value):
    if pathlib.Path(path).name=='ACCEPTED.json':raise OSError('injected acceptance write failure')
    return original(path,value)
d.write_new=failure"""
        driver = fixture(self.base, injection=injection)
        result = subprocess.run([sys.executable, '-B', str(driver)], capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        failed = await_file(self.base / 'detached/DAEMON_FAILED.json', timeout=3)
        self.assertIn('acceptance absent', failed['message'])
        self.assertFalse(failed['target_start_record_exists'])
        self.assertFalse((self.base / 'CHILD_STARTED.json').exists())
        self.assertTrue((self.base / 'detached/BOOTSTRAP_FAILED.json').is_file())

    def test_ready_write_failure_preserves_startup_failure_without_target(self):
        injection = """original=d.write_new
def failure(path,value):
    if pathlib.Path(path).name=='READY.json':raise OSError('injected readiness write failure')
    return original(path,value)
d.write_new=failure"""
        driver = fixture(self.base, injection=injection)
        result = subprocess.run([sys.executable, '-B', str(driver)], capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        failed = await_file(self.base / 'detached/DAEMON_FAILED.json')
        self.assertIn('readiness write failure', failed['message'])
        self.assertFalse((self.base / 'detached/ACCEPTED.json').exists())
        self.assertFalse((self.base / 'CHILD_STARTED.json').exists())

    def test_nonzero_supervisor_has_actual_wait4_without_primary_claim(self):
        self.launch(mode='nonzero')
        await_file(self.base / 'CHILD_STARTED.json')
        result = self.finish(7)
        self.assertNotIn('primary_complete', result)
        self.assertFalse((self.base / 'ops/COMPLETE.json').exists())

    def test_ready_is_invisible_until_complete_fsynced_atomic_publication(self):
        self.base.mkdir(parents=True)
        path = self.base / 'READY.json'
        paused, proceed = threading.Event(), threading.Event()
        real_fsync = bootstrap.os.fsync
        errors = []
        def before_publication(fd):
            if os.path.isfile('/proc/self/fd/%d' % fd) and '.pending-' in os.readlink('/proc/self/fd/%d' % fd):
                paused.set()
                if not proceed.wait(3):
                    raise RuntimeError('Fixture release absent')
            return real_fsync(fd)
        def writer():
            try:
                bootstrap.write_new(path, {'complete_payload': 'x' * 32000})
            except BaseException as error:
                errors.append(error)
        with mock.patch.object(bootstrap.os, 'fsync', before_publication):
            thread = threading.Thread(target=writer)
            thread.start()
            try:
                self.assertTrue(paused.wait(3))
                self.assertFalse(path.exists())
                self.assertEqual(len(list(self.base.glob('.READY.json.pending-*'))), 1)
            finally:
                proceed.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(path.read_text()), {'complete_payload': 'x' * 32000})
        self.assertEqual(list(self.base.glob('.READY.json.pending-*')), [])

    def test_atomic_publication_never_overwrites_and_retains_failed_pending_bytes(self):
        self.base.mkdir(parents=True)
        path = self.base / 'ACCEPTED.json'
        first = bootstrap.write_new(path, {'first': True})
        with self.assertRaises(FileExistsError):
            bootstrap.write_new(path, {'replacement_forbidden': True})
        self.assertEqual(bootstrap.descriptor(path), first)
        pending = list(self.base.glob('.ACCEPTED.json.pending-*'))
        self.assertEqual(len(pending), 1)
        self.assertEqual(json.loads(pending[0].read_text()), {'replacement_forbidden': True})

    def test_direct_foreground_production_launcher_refuses_before_config_or_spawn(self):
        result = subprocess.run([sys.executable, '-B', launcher.__file__, '--config', '/nonexistent',
                                 '--expected-config-sha256', '0' * 64, '--execute'],
                                capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Direct measuring-parent execution is forbidden', result.stderr)


if __name__ == '__main__':
    unittest.main()
