"""CONTEXT_RECONSTRUCTION: Linux-only owned direct-child wait4 and cleanup.

This transparent core-local adapter preserves scientific argv, cwd, environment
and process-group semantics. All returned direct children have one wait4 owner.
The former workspace's code/test hashes do not validate this reconstruction.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time

RECONSTRUCTION = "CONTEXT_RECONSTRUCTION"
MAX_RECEIPT_BYTES = 64 * 1024


def proc_identity(pid):
    raw = Path('/proc/%d/stat' % pid).read_text()
    close = raw.rfind(')')
    fields = raw[close + 2:].split()
    if close < 0 or int(raw.split(' ', 1)[0]) != pid or len(fields) < 20:
        raise RuntimeError('Invalid Linux process identity')
    return {'pid': pid, 'parent_pid': int(fields[1]), 'pgid': int(fields[2]),
            'sid': int(fields[3]), 'start_ticks': int(fields[19])}


def _error_record(error):
    value = {'type': type(error).__name__, 'message': str(error)[:8192]}
    if isinstance(error, SystemExit):
        value['system_exit_code'] = error.code if isinstance(error.code, (int, str, type(None))) else repr(error.code)[:1024]
    return value


def _note(original, message):
    try:
        original.add_note(message[:8192])
    except BaseException:
        pass


class OwnedProcess:
    """Only poll/wait below may reap the wrapped Popen's direct child."""

    def __init__(self, owner, raw, attempt):
        self.owner, self._raw, self.attempt = owner, raw, attempt
        self.pid, self.args = raw.pid, raw.args
        self.stdin, self.stdout, self.stderr = raw.stdin, raw.stdout, raw.stderr
        self.identity = None
        self.pidfd = None
        self.wait4 = None
        self.wait4_receipt = None
        self.wait4_unavailable = None
        self.signals = []
        self.started_monotonic = attempt['started_monotonic']

    @property
    def returncode(self):
        return None if self.wait4 is None else self.wait4['exit_code']

    def _capture_identity(self):
        before = proc_identity(self.pid)
        if before['parent_pid'] != self.owner.identity['pid']:
            raise RuntimeError('Returned process is not this controller direct child')
        fd = os.pidfd_open(self.pid, 0)
        try:
            if proc_identity(self.pid) != before:
                raise RuntimeError('Child identity changed while opening pidfd')
        except BaseException:
            os.close(fd)
            raise
        self.identity, self.pidfd = before, fd

    def _close_pidfd(self):
        if self.pidfd is not None:
            fd, self.pidfd = self.pidfd, None
            os.close(fd)

    def poll(self):
        if self.wait4 is not None:
            return self.wait4['exit_code']
        if self.wait4_unavailable is not None:
            raise ChildProcessError(self.wait4_unavailable['message'])
        try:
            while True:
                try:
                    pid, status, usage = os.wait4(self.pid, os.WNOHANG)
                    break
                except InterruptedError:
                    continue
        except ChildProcessError as error:
            self.wait4_unavailable = _error_record(error)
            self.owner.emit('%03d.WAIT4_UNAVAILABLE.json' % self.attempt['number'], {
                'pid': self.pid, 'identity': self.identity, 'error': self.wait4_unavailable,
                'exact_direct_child_cpu_known': False, 'external_reap_or_nonchild': True})
            self._close_pidfd()
            raise
        if pid == 0:
            return None
        if pid != self.pid:
            raise RuntimeError('wait4 returned another child')
        code = os.waitstatus_to_exitcode(status)
        # Set these before receipt I/O; a write failure must never cause re-reap.
        self._raw.returncode = code
        self.wait4 = {'pid': pid, 'wait_status': status, 'exit_code': code,
                      'user_cpu_seconds': usage.ru_utime, 'system_cpu_seconds': usage.ru_stime,
                      'cpu_seconds': usage.ru_utime + usage.ru_stime,
                      'peak_rss_bytes': usage.ru_maxrss * 1024,
                      'wall_seconds': time.monotonic() - self.started_monotonic,
                      'identity': self.identity, 'waited_unix': time.time(),
                      'scope': 'Direct worker and descendants it waited for; nested inside outer controller wait4.',
                      'scientific_completion_claim': False}
        try:
            self.wait4_receipt = self.owner.emit('%03d.WAIT4.json' % self.attempt['number'], self.wait4)
        finally:
            self._close_pidfd()
        return code

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.01 if deadline is None else max(0, min(0.01, deadline-time.monotonic())))

    def send_signal(self, signum):
        if self.poll() is not None:
            return
        if self.identity is None or self.pidfd is None:
            self._capture_identity()
        current = proc_identity(self.pid)
        if current != self.identity or current['parent_pid'] != os.getpid():
            raise RuntimeError('Refusing signal: owned child identity changed')
        record = {'signal': int(signum), 'identity': copy.deepcopy(current),
                  'sent_unix': time.time(), 'mechanism': 'pidfd_send_signal', 'sent': False}
        try:
            signal.pidfd_send_signal(self.pidfd, signum, None, 0)
            record['sent'] = True
        except ProcessLookupError:
            record['already_exited'] = True
            self.poll()
        self.signals.append(record)
        self.owner.emit('%03d.SIGNAL.%03d.json' % (self.attempt['number'], len(self.signals)), record)

    def terminate(self):
        self.send_signal(signal.SIGTERM)

    def kill(self):
        self.send_signal(signal.SIGKILL)

    def record(self):
        return {'attempt': self.attempt['number'], 'pid': self.pid, 'identity': self.identity,
                'signals': self.signals, 'wait4': self.wait4, 'wait4_receipt': self.wait4_receipt,
                'wait4_unavailable': self.wait4_unavailable}


class OwnedChildren:
    """Fresh receipt scope and bounded cleanup for the controller's own children."""

    def __init__(self, receipt_directory, binding=None, term_grace_seconds=1.0, kill_wait_seconds=2.0):
        if sys.platform != 'linux' or not all(hasattr(os, name) for name in ('wait4', 'pidfd_open')) or not hasattr(signal, 'pidfd_send_signal'):
            raise RuntimeError('Owned child accounting requires Linux wait4 and pidfds')
        if not 0 <= term_grace_seconds <= 30 or not 0 < kill_wait_seconds <= 30:
            raise ValueError('Invalid bounded child cleanup interval')
        self.started_monotonic, self.started_cpu = time.monotonic(), time.process_time()
        self.identity = proc_identity(os.getpid())
        if (self.identity['parent_pid'] != os.getppid() or self.identity['pgid'] != os.getpgid(0)
                or self.identity['sid'] != os.getsid(0)):
            raise RuntimeError('/proc does not match the controller PID namespace')
        self.directory = Path(receipt_directory).absolute()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.binding = copy.deepcopy(binding or {})
        self.term_grace_seconds, self.kill_wait_seconds = term_grace_seconds, kill_wait_seconds
        self.attempts, self.children, self.receipt_errors = [], [], []
        self.cleaning, self.pending_signal, self.closed = False, None, False
        self.closure = None
        self.emit('INTENT.json', {'schema': 'hepta.execution06.owned-children.intent.1',
                  'reconstruction': RECONSTRUCTION, 'controller_identity': self.identity,
                  'binding': self.binding, 'term_grace_seconds': term_grace_seconds,
                  'kill_wait_seconds': kill_wait_seconds, 'started_unix': time.time(),
                  'global_subprocess_patched': False, 'process_groups_changed': False,
                  'cost_scope': 'Direct children attributed inside an inclusive outer controller wait4; do not add twice.'})

    def emit(self, name, value):
        if Path(name).name != name:
            raise ValueError('Receipt name must be a single filename')
        try:
            payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
            if len(payload) > MAX_RECEIPT_BYTES:
                raise ValueError('Owned child receipt exceeds 64 KiB bound')
            path = self.directory/name
            with path.open('xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            return {'path': str(path), 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        except BaseException as error:
            self.receipt_errors.append({'name': name, 'error': _error_record(error)})
            raise

    def spawn(self, factory, *args, **kwargs):
        if self.cleaning or self.closed:
            raise RuntimeError('Cannot spawn during owned-child closure')
        argv = args[0] if args else kwargs.get('args')
        if (not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= 128
                or any(not isinstance(item, str) or '\x00' in item for item in argv)
                or sum(len(item) for item in argv) > 32768 or kwargs.get('shell', False)):
            raise ValueError('Owned worker requires a bounded explicit argv without shell')
        executable = Path(kwargs.get('executable') or argv[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError('Owned worker executable must be an existing absolute executable')
        cwd = Path(kwargs.get('cwd') or os.getcwd()).resolve()
        if not cwd.is_dir():
            raise ValueError('Owned worker cwd is not a directory')
        attempt = {'number': len(self.attempts)+1, 'argv': list(argv), 'cwd': str(cwd),
                   'executable': str(executable), 'started_monotonic': time.monotonic(),
                   'construction_entered': False, 'returned_child': False,
                   'construction_wait4_unavailable': False}
        self.attempts.append(attempt)
        self.emit('%03d.INTENT.json' % attempt['number'], {**attempt, 'started_unix': time.time(),
                  'source_validation_scope': 'Caller frozen verify_job before Popen; source binding in controller INTENT.',
                  'constructor_environment_values_recorded': False})
        attempt['construction_entered'] = True
        try:
            raw = factory(*args, **kwargs)
        except BaseException as error:
            attempt['construction_wait4_unavailable'] = True
            attempt['construction_error'] = _error_record(error)
            try:
                self.emit('%03d.CONSTRUCTION_FAILED.json' % attempt['number'], {
                    **attempt, 'exact_direct_child_cpu_known': False,
                    'scope': 'Popen did not return; internal setup child may already be reaped. No retry or invented PID.'})
            except BaseException as receipt_error:
                _note(error, 'Owned construction failure receipt also failed: ' + repr(receipt_error))
            raise
        child = OwnedProcess(self, raw, attempt)
        self.children.append(child)  # Track before fallible /proc, pidfd, receipt work.
        attempt['returned_child'] = True
        attempt['pid'] = child.pid
        child._capture_identity()
        self.emit('%03d.START.json' % attempt['number'], {
            'attempt': attempt['number'], 'argv': list(argv), 'cwd': str(cwd),
            'identity': child.identity, 'returned_unix': time.time(),
            'process_groups_changed': False, 'wait4_owner_pid': self.identity['pid']})
        return child

    def health_check(self):
        if proc_identity(os.getpid()) != self.identity:
            raise RuntimeError('Controller process identity changed')
        if any(child.wait4_unavailable is not None for child in self.children):
            raise RuntimeError('An owned worker was reaped outside its wait4 owner')

    def close(self, original_error=None, return_value=None):
        if self.closed:
            return self.closure
        self.cleaning = True
        cleanup_errors = []

        def observe_all():
            for child in self.children:
                if child.wait4 is None and child.wait4_unavailable is None:
                    try:
                        child.poll()
                    except BaseException as error:
                        cleanup_errors.append({'pid': child.pid, 'operation': 'wait4', 'error': _error_record(error)})

        def pending():
            return [child for child in self.children if child.wait4 is None and child.wait4_unavailable is None]

        observe_all()
        for signum, duration in ((signal.SIGTERM, self.term_grace_seconds), (signal.SIGKILL, self.kill_wait_seconds)):
            for child in pending():
                try:
                    child.send_signal(signum)
                except BaseException as error:
                    cleanup_errors.append({'pid': child.pid, 'operation': 'signal', 'signal': int(signum), 'error': _error_record(error)})
            deadline = time.monotonic() + duration
            while pending() and time.monotonic() < deadline:
                observe_all()
                if pending():
                    time.sleep(min(0.01, max(0, deadline-time.monotonic())))
            observe_all()
        for child in self.children:
            if child.wait4 is not None:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as error:
                            cleanup_errors.append({'pid': child.pid, 'operation': 'stream_close', 'error': _error_record(error)})
                try:
                    child._close_pidfd()
                except BaseException as error:
                    cleanup_errors.append({'pid': child.pid, 'operation': 'pidfd_close', 'error': _error_record(error)})
        all_reaped = all(child.wait4 is not None for child in self.children)
        construction_unknown = any(row['construction_wait4_unavailable'] for row in self.attempts)
        self.closure = {
            'schema': 'hepta.execution06.owned-children.closure.1', 'reconstruction': RECONSTRUCTION,
            'controller_identity': self.identity, 'binding': self.binding,
            'attempt_count': len(self.attempts), 'returned_children': len(self.children),
            'attempts': self.attempts, 'children': [child.record() for child in self.children],
            'all_returned_direct_children_reaped': all_reaped,
            'accounting_complete_for_attempted_direct_workers': all_reaped and not construction_unknown and not self.receipt_errors,
            'construction_wait4_unavailable': construction_unknown,
            'direct_workers_cpu_seconds': sum(child.wait4['cpu_seconds'] for child in self.children if child.wait4 is not None),
            'own_cpu_seconds_until_summary': time.process_time()-self.started_cpu,
            'wall_seconds_until_summary': time.monotonic()-self.started_monotonic,
            'original_exception': None if original_error is None else _error_record(original_error),
            'return_value': return_value if isinstance(return_value, (int, str, bool, type(None))) else None,
            'pending_signal': self.pending_signal, 'cleanup_errors': cleanup_errors,
            'receipt_errors': self.receipt_errors,
            'scientific_completion_claim': False,
            'cost_scope': 'Each direct-worker wait4 once; already nested in outer controller wait4. Own CPU excludes final summary serialization/write.'}
        self.closed = True
        try:
            self.emit('CLOSURE.json', self.closure)
        except BaseException as error:
            try:
                sys.stderr.write(json.dumps({'owned_child_closure_write_failed': _error_record(error),
                    'all_returned_direct_children_reaped': all_reaped, 'attempt_count': len(self.attempts)})[:4096]+'\n')
            except BaseException:
                pass
            raise
        if not all_reaped or cleanup_errors or self.receipt_errors:
            raise RuntimeError('Owned child cleanup or receipt integrity incomplete; inspect CLOSURE.json')
        return self.closure


class _SubprocessProxy:
    def __init__(self, original, owner):
        self.original, self.owner = original, owner

    def __getattr__(self, name):
        return getattr(self.original, name)

    def Popen(self, *args, **kwargs):
        return self.owner.spawn(self.original.Popen, *args, **kwargs)


class _TerminationSignal(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__('Controller received signal %d' % signum)


def run_controller(core, controller_call, receipt_directory, *args, binding=None,
                   term_grace_seconds=1.0, kill_wait_seconds=2.0, **kwargs):
    """Run a callback with a core-local Popen proxy; preserve its result/error."""
    owner = OwnedChildren(receipt_directory, binding, term_grace_seconds, kill_wait_seconds)
    original = core.subprocess
    old_handler = None
    signal_installed = False
    error, value = None, None

    def terminated(signum, frame):
        owner.pending_signal = signum
        if not owner.cleaning:
            raise _TerminationSignal(signum)

    core.subprocess = _SubprocessProxy(original, owner)
    try:
        if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
            old_handler = signal.signal(signal.SIGTERM, terminated)
            signal_installed = True
        try:
            value = controller_call(*args, **kwargs)
        except BaseException as caught:
            error = caught
        finally:
            owner.cleaning = True
            try:
                owner.close(error, value)
            except BaseException as cleanup_error:
                if error is None:
                    error = cleanup_error
                else:
                    _note(error, 'Owned child finalization also failed: ' + repr(cleanup_error))
    finally:
        core.subprocess = original
        if signal_installed:
            signal.signal(signal.SIGTERM, old_handler)
    if signal_installed and owner.pending_signal is not None:
        os.kill(os.getpid(), owner.pending_signal)
        raise RuntimeError('Restored default signal delivery unexpectedly returned')
    if error is not None:
        raise error.with_traceback(error.__traceback__)
    return value
