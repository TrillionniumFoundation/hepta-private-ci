"""Linux-only exclusive two-phase handoff to the detached wait4 measuring parent.

READY is identity/FD evidence, never final wait4. A complete, exact ACCEPTED
receipt permits one callback; existing or ambiguous attempts are never retried.
"""

import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import threading
import time

SOURCE = Path(__file__).resolve().parents[2]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery06.owned_children import proc_identity

MAX_RECEIPT = 64 * 1024
HANDOFF_SECONDS = 15.0


def require(ok, message):
    if not ok:
        raise ValueError(message)


def descriptor(path):
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path and path.is_file() and not path.is_symlink(),
            'Noncanonical launch metadata')
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    # Removing the publication's temporary hardlink changes ctime, not content.
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            'Launch metadata changed while reading')
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write_new(path, value):
    """Publish complete bytes once; preserve a pending file on any I/O failure."""
    path = Path(path)
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(data) <= MAX_RECEIPT, 'Launch receipt exceeds 64 KiB')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.pending-', dir=path.parent)
    with os.fdopen(fd, 'wb') as stream:
        require(stream.write(data) == len(data), 'Short launch receipt write')
        stream.flush()
        os.fsync(stream.fileno())
    # link is an atomic, no-replace publication; readers cannot see partial JSON.
    os.link(temporary, path, follow_symlinks=False)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
        os.unlink(temporary)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return descriptor(path)


def bound_read(item):
    require(set(item) == {'path', 'bytes', 'sha256'} and item['bytes'] <= MAX_RECEIPT
            and descriptor(item['path']) == item, 'Launch descriptor differs')
    data = Path(item['path']).read_bytes()
    require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
            'Launch metadata changed before parsing')
    return json.loads(data)


def verify_ready(item, binding):
    value = bound_read(item)
    require(value['schema'] == 'hepta.execution06.detached-parent-ready.1'
            and value['binding'] == binding and value['final_wait4_complete'] is False,
            'Detached readiness binding differs')
    identity = value['measuring_parent_identity']
    require(identity['parent_pid'] == 1 and proc_identity(identity['pid']) == identity,
            'Detached measuring parent identity changed')
    require(value['inherited_fds_closed'] is True and value['stdin_is_devnull'] is True
            and value['stdout_stderr_are_regular_files'] is True,
            'Executor descriptors were not detached')
    return value


def close_executor_fds(directory, lock_fd):
    null_fd = os.open('/dev/null', os.O_RDONLY)
    out_fd = os.open(directory / 'daemon.stdout.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    err_fd = os.open(directory / 'daemon.stderr.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    for source, destination in ((null_fd, 0), (out_fd, 1), (err_fd, 2)):
        os.dup2(source, destination)
    # A real /proc inventory avoids arbitrary FD limits or inherited pipe tails.
    for name in list(Path('/proc/self/fd').iterdir()):
        fd = int(name.name)
        if fd in (0, 1, 2, lock_fd):
            continue
        try:
            os.close(fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
    require(stat.S_ISCHR(os.fstat(0).st_mode)
            and (os.fstat(0).st_rdev == os.stat('/dev/null').st_rdev)
            and all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1, 2)), 'Detached stdio differs')


def daemon_body(directory, binding, run, lock_fd):
    started, cpu = time.monotonic(), time.process_time()
    try:
        close_executor_fds(directory, lock_fd)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        os.umask(0o077)
        os.chdir('/')
        deadline = time.monotonic() + HANDOFF_SECONDS
        while os.getppid() != 1:
            require(time.monotonic() < deadline, 'Final daemon was not adopted by PID 1')
            time.sleep(0.01)
        identity = proc_identity(os.getpid())
        time.sleep(0.05)
        require(proc_identity(os.getpid()) == identity, 'Detached identity did not stabilize')
        ready = write_new(directory / 'READY.json', {
            'schema': 'hepta.execution06.detached-parent-ready.1', 'binding': binding,
            'measuring_parent_identity': identity, 'inherited_fds_closed': True,
            'stdin_is_devnull': True, 'stdout_stderr_are_regular_files': True,
            'stdout': str(directory / 'daemon.stdout.log'), 'stderr': str(directory / 'daemon.stderr.log'),
            'at_unix': time.time(), 'final_wait4_complete': False,
            'scientific_completion_claim': False, 'automatic_retry': False})
        accepted_path = directory / 'ACCEPTED.json'
        while not accepted_path.exists():
            require(time.monotonic() < deadline, 'Bootstrap acceptance absent; no target started')
            time.sleep(0.01)
        accepted = bound_read(descriptor(accepted_path))
        require(accepted['schema'] == 'hepta.execution06.detached-parent-accepted.1'
                and accepted['ready'] == ready and accepted['binding'] == binding,
                'Ambiguous or mismatched bootstrap acceptance')
        verify_ready(ready, binding)
        write_new(directory / 'TARGET_STARTED.json', {'binding': binding, 'ready': ready,
                  'measuring_parent_identity': identity, 'at_unix': time.time(), 'automatic_retry': False})
        result = run(ready)
        require(proc_identity(os.getpid()) == identity, 'Measuring parent changed before target completion')
        code = result['exit_code'] if isinstance(result, dict) else int(result or 0)
        write_new(directory / 'DAEMON_RETURNED.json', {
            'schema': 'hepta.execution06.detached-parent-returned.1', 'binding': binding,
            'ready': ready, 'measuring_parent_identity': identity, 'target_exit_code': code,
            'own_cpu_seconds_until_receipt': time.process_time() - cpu,
            'wall_seconds_until_receipt': time.monotonic() - started,
            'this_is_not_the_daemons_own_kernel_wait4': True,
            'final_supervisor_wait4_must_be_verified_separately': True})
        return code if code >= 0 else 128 - code
    except BaseException as error:
        try:
            write_new(directory / 'DAEMON_FAILED.json', {
                'schema': 'hepta.execution06.detached-parent-failure.1', 'binding': binding,
                'error_type': type(error).__name__, 'message': str(error)[:8192],
                'measuring_parent_identity_now': proc_identity(os.getpid()),
                'automatic_retry': False, 'target_start_record_exists': (directory / 'TARGET_STARTED.json').exists(),
                'own_cpu_seconds_until_receipt': time.process_time() - cpu,
                'wall_seconds_until_receipt': time.monotonic() - started,
                'final_supervisor_wait4_not_inferred': True})
        except BaseException as receipt_error:
            error.add_note('Detached failure receipt also failed: ' + type(receipt_error).__name__)
        return 1


def detach_and_run(directory, lock_path, binding, run):
    """Fork only local stdlib code; callers supply a fixed, already verified target."""
    require(sys.platform == 'linux' and threading.active_count() == 1 and callable(run),
            'Detachment requires a single-threaded Linux bootstrap')
    directory = Path(directory).absolute()
    require(directory.parent.resolve(strict=True) == directory.parent, 'Launch parent aliases another path')
    directory.mkdir(mode=0o700, exist_ok=False)  # Permanent single-attempt reservation.
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    bridge = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(stat.S_ISREG(os.fstat(lock_fd).st_mode), 'Launcher lock is not regular')
        intent = write_new(directory / 'INTENT.json', {
            'schema': 'hepta.execution06.detached-launch-intent.1', 'binding': binding,
            'bootstrap_identity': proc_identity(os.getpid()), 'automatic_retry': False,
            'mechanism': 'double fork, setsid, close inherited fds, stable PID1 parent, explicit READY/ACCEPTED',
            'final_wait4_complete': False})
        sys.stdout.flush()
        sys.stderr.flush()
        bridge = os.fork()
        if bridge == 0:
            try:
                os.setsid()
                daemon = os.fork()
                if daemon:
                    write_new(directory / 'FORKED.json', {'binding': binding, 'daemon_pid': daemon,
                              'bridge_identity': proc_identity(os.getpid()), 'intent': intent})
                    os._exit(0)
                code = daemon_body(directory, binding, run, lock_fd)
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
            except BaseException:
                os._exit(1)
        deadline = time.monotonic() + HANDOFF_SECONDS
        while True:
            pid, status, usage = os.wait4(bridge, os.WNOHANG)
            if pid:
                break
            require(time.monotonic() < deadline, 'Bridge exit unknown; reconcile, never retry')
            time.sleep(0.01)
        bridge_wait4 = write_new(directory / 'BRIDGE_WAIT4.json', {
            'schema': 'hepta.execution06.bootstrap-bridge-wait4.1', 'pid': pid,
            'wait_status': status, 'exit_code': os.waitstatus_to_exitcode(status),
            'user_cpu_seconds': usage.ru_utime, 'system_cpu_seconds': usage.ru_stime,
            'cpu_seconds': usage.ru_utime + usage.ru_stime, 'peak_rss_bytes': usage.ru_maxrss * 1024,
            'excludes_detached_measuring_parent_and_science': True})
        require(os.waitstatus_to_exitcode(status) == 0, 'Bridge failed; detached outcome must be reconciled')
        ready_path = directory / 'READY.json'
        while not ready_path.exists():
            require(not (directory / 'DAEMON_FAILED.json').exists(), 'Detached startup failed')
            require(time.monotonic() < deadline, 'Readiness unknown; reconcile, never retry')
            time.sleep(0.01)
        ready = descriptor(ready_path)
        value = verify_ready(ready, binding)
        forked = bound_read(descriptor(directory / 'FORKED.json'))
        require(forked['binding'] == binding and forked['daemon_pid'] == value['measuring_parent_identity']['pid']
                and forked['bridge_identity']['pid'] == bridge
                and value['measuring_parent_identity']['sid'] == bridge
                and value['measuring_parent_identity']['pgid'] == bridge,
                'Readiness is not the actual detached fork lineage')
        accepted = write_new(directory / 'ACCEPTED.json', {
            'schema': 'hepta.execution06.detached-parent-accepted.1', 'binding': binding,
            'ready': ready, 'bridge_wait4': bridge_wait4, 'bootstrap_identity': proc_identity(os.getpid()),
            'final_wait4_complete': False, 'automatic_retry': False})
        return {'status': 'DETACHED_PARENT_ACCEPTED_NOT_FINAL_WAIT4', 'ready': ready,
                'accepted': accepted, 'bridge_wait4': bridge_wait4,
                'measuring_parent_identity': value['measuring_parent_identity'], 'automatic_retry': False}
    except BaseException as error:
        try:
            write_new(directory / 'BOOTSTRAP_FAILED.json', {
                'binding': binding, 'error_type': type(error).__name__, 'message': str(error)[:8192],
                'bridge_pid': bridge, 'automatic_retry': False,
                'detached_outcome_must_be_reconciled': True})
        except BaseException as receipt_error:
            error.add_note('Bootstrap failure receipt also failed: ' + type(receipt_error).__name__)
        raise
    finally:
        os.close(lock_fd)  # The same open-file-description lock remains in the daemon.


def main():
    from operational.parameter_field_recovery06 import wait4_launcher as launcher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--expected-config-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    config, config_desc = launcher.load_config(args.config, args.expected_config_sha256)
    require(config['descriptors']['daemon_bootstrap'] == descriptor(Path(__file__).resolve()),
            'Wrong registered daemon bootstrap source')
    binding = {'execution_episode': launcher.EPISODE, 'pipeline_config': config_desc,
               'daemon_bootstrap': config['descriptors']['daemon_bootstrap'],
               'wait4_launcher': config['descriptors']['wait4_launcher']}
    if not args.execute:
        print(json.dumps({'status': 'DETACHED_LAUNCH_PREPARED_ONLY', 'binding': binding,
                          'supervisor_argv': launcher.supervisor_argv(config, config_desc), 'workers_started': 0}))
        return
    def run(ready):
        launcher.load_config(args.config, args.expected_config_sha256)
        return launcher.run_measured(config, config_desc, launcher.OPS / 'wait4_launcher', detachment=ready)
    result = detach_and_run(launcher.OPS / 'daemon_bootstrap',
                            launcher.OPS / '.execution06-launcher.lock', binding, run)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
