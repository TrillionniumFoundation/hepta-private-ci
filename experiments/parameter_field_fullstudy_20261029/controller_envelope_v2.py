"""Registered failure observation around the unchanged attempt02 controller.

Only this module's launch_v2 subprocess reference is temporarily proxied. No
resource threshold, worker command, scientific kernel, or original receipt is
rewritten. Recovery of one separately registered historical incident is explicit.
"""

import argparse
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import traceback
from types import SimpleNamespace

from . import launch_v2 as core
from .resource_v2 import RAW_OPEN, StorageBudget, load_registration, memory_admission, pending_growth

SCHEMA = "hepta.fullstudy.controller-envelope.1"
MODULE = "experiments.parameter_field_fullstudy_20261029.controller_envelope_v2"
ROOT = core.ROOT


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    with RAW_OPEN(path) as stream:
        return json.load(stream)


def descriptor(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": core.digest(path)}


def check_descriptor(item):
    require(descriptor(item["path"]) == item, "Registered descriptor bytes differ")
    return Path(item["path"])


def validate(args):
    registration = load_registration(args.amendment, args.amendment_sha256)
    require(core.digest(args.freeze) == args.freeze_sha256, "Envelope source-freeze bytes differ")
    freeze = core.verify_controller(args, registration)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    require(freeze.get("controller_envelope_schema") == SCHEMA
            and freeze["source_files"].get(own) == core.digest(__file__), "Envelope source is not explicitly frozen")
    parent = freeze.get("controller_parent", {})
    check_descriptor(parent)
    old = core.verify_controller(SimpleNamespace(freeze=parent["path"]), registration)
    require(old.get("controller_envelope_schema") is None,
            "The unchanged controller parent must precede this envelope")
    require(all(freeze["source_files"].get(name) == digest for name, digest in old["source_files"].items()),
            "Original controller source closure changed or was omitted")
    require(freeze.get("protocol_sha256") == old.get("protocol_sha256") == registration["original_protocol"]["sha256"],
            "Controller scientific protocol ancestry differs")
    root = Path(args.root).resolve()
    require(root == Path(registration["raw_root"]).resolve(), "Envelope raw root differs")
    require(not (getattr(args, "recover_zero_work", False) and args.resume_admission),
            "Historical recovery and observed admission resume are separate operations")
    require(freeze.get("artifacts", {}).get(parent["path"]) == parent["sha256"], "Controller parent is not artifact-bound")
    return registration, freeze


def worker_rows(root):
    path = Path(root) / "ACTIVE_WORKERS.json"
    return read(path).get("workers", []) if path.exists() else []


def scientific_paths_present(root):
    root = Path(root)
    return ((root / "operations").exists() or any(root.glob("stage_*"))
            or bool(list((root / "controller").glob("*.START.json"))))


def live_task_pids(root):
    watched = core.MODULES | {core.__name__, MODULE}
    result = []
    for process in Path('/proc').glob('[0-9]*'):
        if int(process.name) == os.getpid():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().decode('utf-8', 'replace').split('\0')
            if '-m' not in argv or '--root' not in argv:
                continue
            module, directory = argv[argv.index('-m') + 1], argv[argv.index('--root') + 1]
            if module in watched and Path(directory).resolve() == Path(root).resolve():
                result.append(int(process.name))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(result)


def raw_inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        require(not path.is_symlink(), "Historical recovery refuses symbolic links")
        if path.is_dir():
            continue
        require(stat.S_ISREG(path.lstat().st_mode), "Historical recovery refuses nonregular files")
        item = descriptor(path)
        result[path.relative_to(root).as_posix()] = {key: item[key] for key in ('bytes', 'sha256')}
    return result


def recover_zero_work(args, registration, freeze, storage):
    recovery = freeze.get('zero_work_recovery')
    require(isinstance(recovery, dict), "No historical zero-work incident was registered")
    incident_path = check_descriptor(recovery['incident'])
    require(freeze.get('artifacts', {}).get(str(incident_path)) == recovery['incident']['sha256'],
            "Historical incident is not artifact-bound")
    require(descriptor(args.queue) == recovery['queue'], "Historical queue changed")
    incident, root = read(incident_path), storage.root
    require(incident.get('schema') == 'hepta.fullstudy.controller-infrastructure-failure.1'
            and incident.get('attempt_id') == registration['attempt_id']
            and Path(incident['raw_root']).resolve() == root
            and incident.get('scientific_workers_started') == 0
            and incident.get('scheduled_gradient_microsteps') == 0
            and incident.get('error_type') == 'MemoryError'
            and incident.get('standard_admission_failure_receipt_written') is False
            and bool(incident.get('basis_for_zero_worker_count')),
            "Historical incident is not the explicitly documented zero-work postmortem")
    require(not scientific_paths_present(root) and not worker_rows(root) and not live_task_pids(root),
            "Historical recovery requires no scientific paths, registered workers, or live task processes")
    inventory = raw_inventory(root)
    require(inventory == recovery['prior_raw_files'], "Historical raw metadata inventory changed")
    required = {'controller/START.json', 'ACTIVE_WORKERS.json', 'PROGRESS.json'}
    allowed_locks = {'.ops-controller.lock', '.ops-write.lock', '.ops-phase.lock', '.ops-slot-0.lock', '.ops-slot-1.lock'}
    require(required <= set(inventory) and set(inventory) <= required | allowed_locks
            and all(inventory[name]['bytes'] == 0 for name in set(inventory) - required),
            "Historical raw inventory contains unregistered execution evidence")
    require(set(incident['raw_evidence']) == required, "Historical incident evidence population differs")
    for relative, item in incident['raw_evidence'].items():
        require(Path(item['path']).resolve() == root / relative
                and {key: item[key] for key in ('bytes', 'sha256')} == inventory[relative]
                and read(root / relative) == item['content'], "Historical incident bytes or recorded contents differ")
    started, progress = read(root / 'controller/START.json'), read(root / 'PROGRESS.json')
    require(started['source_freeze_sha256'] == freeze['controller_parent']['sha256']
            and started['amendment_sha256'] == registration['_sha256']
            and not progress.get('running') and not progress.get('results')
            and set(progress['pending']) == {job['id'] for job in core.validate_queue(read(args.queue), root)},
            "Historical source, resource, or zero-work progress binding differs")
    relative = Path(recovery['archive_relative'])
    require(not relative.is_absolute() and '..' not in relative.parts and len(relative.parts) == 2
            and relative.parts[0] == 'controller_recoveries' and relative.parts[1].isalnum(), "Unsafe historical archive identity")
    destination = root / relative
    require(not destination.exists(), "Historical recovery destination already exists")
    admission = memory_admission(registration['concurrency']['worker_reservation_bytes'],
                                 registration['concurrency']['memory_margin_bytes'], pending_growth(root))
    if not admission['allowed']:
        print(json.dumps({'status': 'ADMISSION_BLOCKED', 'scope': 'historical_zero_work_recovery',
                          'recovery_archived': False, 'workers_started_in_this_invocation': 0,
                          'historical_Popen_observation_available': False, 'admission': admission}), flush=True)
        return False
    moved = []
    try:
        with storage.writer_lock():
            storage.check()
            require(raw_inventory(root) == inventory, "Historical evidence changed immediately before archival")
            destination.mkdir(parents=True, exist_ok=False)
            storage.write_json(destination / 'RECOVERY_START.json', {
                'schema': SCHEMA, 'incident': recovery['incident'], 'prior_raw_files': inventory,
                'new_source_freeze_sha256': args.freeze_sha256, 'admission': admission,
                'historical_classification': 'source-and-artifact postmortem; not a retrospective Popen observer',
                'scientific_parameters_changed': False, 'started_unix': time.time()})
            storage.write_bytes(destination / 'INCIDENT.json', incident_path.read_bytes())
            for relative_name in ('controller', 'ACTIVE_WORKERS.json', 'PROGRESS.json'):
                (root / relative_name).rename(destination / relative_name)
                moved.append(relative_name)
            for name in required:
                require(descriptor(destination / name)['sha256'] == inventory[name]['sha256']
                        and (destination / name).stat().st_size == inventory[name]['bytes'], "Historical archive bytes differ")
            storage.write_json(destination / 'RECOVERY_COMPLETE.json', {
                'schema': SCHEMA, 'recovery_complete': True, 'incident': recovery['incident'],
                'new_source_freeze_sha256': args.freeze_sha256, 'old_controller_parent': freeze['controller_parent'],
                'moved': moved, 'original_metadata_bytes_preserved': True,
                'historical_Popen_observation_available': False, 'scientific_work_added_by_recovery': 0})
    except BaseException as error:
        write_failure(storage, destination / 'RECOVERY_FAILED.json', {
            'schema': SCHEMA, 'recovery_complete': False, 'moved': moved,
            'error_type': type(error).__name__, 'message': str(error)[:4096],
            'original_metadata_preserved_at_old_or_archive_paths': True,
            'historical_Popen_observation_available': False})
        raise
    return True


class ObservedSubprocess:
    def __init__(self, original):
        self.original, self.attempts, self.returned = original, [], []

    def __getattr__(self, name):
        return getattr(self.original, name)

    def Popen(self, *args, **kwargs):
        argv = args[0] if args else kwargs.get('args')
        row = {'attempt': len(self.attempts) + 1, 'started_unix': time.time(),
               'argv_sha256': hashlib.sha256(json.dumps(argv, sort_keys=True).encode()).hexdigest()}
        self.attempts.append(row)
        process = self.original.Popen(*args, **kwargs)
        self.returned.append({'attempt': row['attempt'], 'pid': int(process.pid)})
        return process


@contextmanager
def observe_spawns():
    original = core.subprocess
    observer = ObservedSubprocess(original)
    core.subprocess = observer
    try:
        yield observer
    finally:
        core.subprocess = original


def write_failure(storage, path, value):
    payload = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=False) + '\n').encode()
    if len(payload) > 64 * 1024:
        value = {**value, 'failure_receipt_truncated': True,
                 'full_serialized_failure_sha256': hashlib.sha256(payload).hexdigest()}
        for key in ('traceback', 'message'):
            if isinstance(value.get(key), str):
                value[key] = value[key][-4096:]
        payload = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=False) + '\n').encode()
    require(len(payload) <= 64 * 1024, "Envelope failure receipt exceeded its fixed bound")
    try:
        return storage.write_bytes(path, payload, failure_record=True)
    except (OSError, RuntimeError, MemoryError):
        print(payload.decode(), flush=True)
        return None


def failure_receipts(args, registration, storage, observer, error, entry_queue_sha, started_wall, started_cpu):
    root = storage.root
    try:
        unchanged = (core.digest(args.queue) == entry_queue_sha and core.digest(args.freeze) == args.freeze_sha256
                     and core.digest(args.amendment) == args.amendment_sha256)
        no_work = (not observer.attempts and not observer.returned and not worker_rows(root)
                   and not scientific_paths_present(root) and not live_task_pids(root) and unchanged)
    except (OSError, ValueError, KeyError):
        no_work = False
    pending = [str(path.relative_to(root)) for path in root.rglob('*')
               if path.is_file() and path.name.endswith(('.ops-pending', '.cas-link'))]
    resource_error = (isinstance(error, MemoryError)
                      or isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT, errno.ENOMEM, errno.EMFILE, errno.ENFILE, errno.EAGAIN)
                      or isinstance(error, RuntimeError) and str(error).startswith((
                          'Registered attempt02 physical reserve/inodes exhausted',
                          'Registered cumulative logical raw cap exhausted',
                          'Registered outer 12 hour execution window exhausted')))
    safe_resume = no_work and not pending and resource_error
    record = {'schema': SCHEMA, 'complete': False, 'status': 'OBSERVED_ZERO_SPAWN_FAILURE' if no_work else 'PARTIAL_OR_UNCERTAIN_EXECUTION_FAILURE',
              'attempt_id': registration['attempt_id'], 'source_freeze_sha256': args.freeze_sha256,
              'amendment_sha256': registration['_sha256'], 'entry_queue_sha256': entry_queue_sha,
              'Popen_attempt_count': len(observer.attempts), 'Popen_returned_count': len(observer.returned),
              'Popen_attempts': observer.attempts, 'returned_processes': observer.returned,
              'scheduled_gradient_microsteps': 0 if no_work else None,
              'unknown_additional_work': not no_work, 'automatic_admission_resume_safe': safe_resume,
              'pending_write_artifacts': pending, 'error_type': type(error).__name__, 'message': str(error)[:4096],
              'traceback': ''.join(traceback.format_exception(error))[-24576:],
              'originals_preserved': True, 'thresholds_unchanged': True,
              'wall_seconds': time.monotonic() - started_wall,
              'cpu_seconds': time.process_time() - started_cpu,
              'process_cpu_seconds_total': time.process_time(),
              'timing_scope': 'This envelope invocation, including validation/recovery before the observed controller failure.',
              'partial_workers_not_terminated_by_envelope': bool(observer.returned)}
    directory = root / 'controller'
    receipt = write_failure(storage, directory / 'ENVELOPE_FAILED.json', record)
    if safe_resume and not (directory / 'ADMISSION_FAILED.json').exists():
        write_failure(storage, directory / 'ADMISSION_FAILED.json', {
            'status': 'ADMISSION_BLOCKED', 'complete': False, 'attempt_id': registration['attempt_id'],
            'scientific_workers_started': 0, 'gradient_work_during_admission_wait': 0,
            'source_freeze_sha256': args.freeze_sha256, 'amendment_sha256': registration['_sha256'],
            'initial_queue_sha256': entry_queue_sha, 'scientific_outcome_claim': False,
            'existing_evidence_preserved': True, 'envelope_failure_receipt': receipt,
            'Popen_observer_confirmed_zero_attempts': True,
            'cause': {'error_type': type(error).__name__, 'message': str(error)[:4096]}})
    return record


def terminal_exit(args, code):
    """Correct only outer exit status; the original controller records stay intact."""
    if code is not None:
        return code
    root, directory = Path(args.root).resolve(), Path(args.root).resolve() / 'controller'
    if (directory / 'EXECUTION_FAILED.json').exists() or not (directory / 'EXECUTION.json').is_file():
        return 1
    try:
        value, queue = read(directory / 'EXECUTION.json'), read(args.queue)
        jobs = core.validate_queue(queue, root)
        if (not queue.get('finalize') or value.get('complete') is not True
                or value.get('source_freeze_sha256') != args.freeze_sha256
                or core.digest(args.freeze) != args.freeze_sha256
                or set(value['jobs']) != core.EXPECTED_IDS
                or {job['id'] for job in jobs} != core.EXPECTED_IDS):
            return 1
        for job in jobs:
            result = value['jobs'][job['id']]
            relative = Path(job['completion'])
            if (relative.is_absolute() or '..' in relative.parts
                    or result.get('complete') is not True or result.get('exit_code') != 0):
                return 1
            item = descriptor(root / relative)
            if result.get('completion') != {**item, 'path': relative.as_posix()}:
                return 1
    except (OSError, ValueError, KeyError, TypeError):
        return 1
    return 0


def execute(args):
    started_wall, started_cpu = time.monotonic(), time.process_time()
    registration, freeze = validate(args)
    root = Path(args.root).resolve()
    storage = StorageBudget(root, registration)
    with RAW_OPEN(root / '.ops-controller.lock', 'a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if getattr(args, 'recover_zero_work', False):
            if not recover_zero_work(args, registration, freeze, storage):
                return 75
        elif (root / 'controller').exists() and not args.resume_admission:
            raise ValueError('Existing controller requires registered recovery or unchanged admission resume')
        entry_queue_sha = core.digest(args.queue)
        with observe_spawns() as observer:
            try:
                code = core.run(args)
            except BaseException as error:
                failure_receipts(args, registration, storage, observer, error, entry_queue_sha, started_wall, started_cpu)
                raise
        return terminal_exit(args, code)


def main():
    parser = argparse.ArgumentParser()
    for name in ('root', 'queue', 'freeze', 'freeze-sha256', 'amendment', 'amendment-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--resume-admission', action='store_true')
    parser.add_argument('--recover-zero-work', action='store_true')
    raise SystemExit(execute(parser.parse_args()))


if __name__ == '__main__':
    main()
