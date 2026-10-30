"""Linux-only, external execution06 root barrier orchestration.

Production CLI paths and source pins are fixed. This is engineering glue, not a
scientific runner or a Library API client. Root supplies full actual folder and
materialization responses. Each phase and helper runs at most once. Publication
requires a separate explicit command; only the supervisor can accept an ACK.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
BASE = Path('/workspace/scratch/178ced6a501f')
SOURCE = BASE / 'fullstudy_recovery06_git'
OPS = BASE / 'fullstudy_execution06_ops'
ROOT = OPS / 'root_archive_io'
ENGINEERING = ROOT / '_engineering'
EMPTY_CWD = OPS / 'empty_cwd'
EPISODE = 'execution06_detached_20261030'
VENV = str(BASE / 'runtime_recovery_20261030/venv/bin/python')
PYTHON = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3'
OWN = SOURCE / 'operational/parameter_field_recovery06'
OLD = SOURCE / 'operational/parameter_field_recovery04'
ARCHIVE_IO = OWN / 'archive_io.py'
EXTERNAL_STEP = OLD / 'external_step.py'
HELPERS = BASE / 'executor_recovery_20261030T1152/helpers'
CODE_PINS = {
    ARCHIVE_IO: '84eb4813a0bf487c5a1edfe77185ae4863c7d6f3431898eac9bc91e7f1946449',
    OWN / 'supervisor.py': '9fe5a97112693d6eb2f718c50d09c3b53a85c4f949d1b571b0494b48902f547b',
    EXTERNAL_STEP: 'fb238cd0f28e331a2e9d4ada5950f436a2d31e579fa9fbd8c36cce70404c2b21',
    OLD / 'supervisor.py': 'cc1526c88184e26ce9eb363f053e2e2babce924020d80589b0891f4385307682',
    OLD / 'durable_archive.py': 'dfeee33870f3ca429284542cb8ca9ff8c9471a8fc8ff0339c3de251cabf260da',
    HELPERS / 'library_download.py': '7a092c11922d14a5c61ce1a9beb7d1d3af89bd22b3eff4549abf79ac28878989',
    HELPERS / 'library_file_transfer.py': 'd0385de4b634c4a6d4c26a83b40ee4ff33461e42473ce8c0387460be2465e314',
    HELPERS / 'library_hosted_apps.py': '7958642b88cde925aaca036989de1028c0864eb6d82a9cb175ebf9380cb9677b',
    HELPERS / 'library_upload.py': '5bc473dadefe1f68ee8797baaed19d6662642d0ea4bcba128fa12938faa0d767',
}
LABELS = ['A-17', 'A-29', 'A-43', 'C', 'B-17', 'B-29', 'B-43', 'W',
          'R-17', 'R-29', 'R-43', 'A_endpoint', 'B_endpoint', 'C_endpoint',
          'controller', 'analysis', 'final_closure']
STAGES = [f'{i:02d}_{label}' for i, label in enumerate(LABELS, 1)]
MAX_METADATA = 8 * 1024 * 1024
DESC_KEYS = {'path', 'bytes', 'sha256'}
IDENTITY_KEYS = {'pid', 'parent_pid', 'pgid', 'sid', 'start_ticks'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(path, parent=BASE):
    path = Path(path).absolute()
    need(path == path.resolve() and path.is_relative_to(parent), 'Path aliases or leaves its bound directory: ' + str(path))
    return path


def absent(path):
    need(not os.path.lexists(path), 'Existing path is not retryable; reconcile: ' + str(path))


def file_bytes(path):
    """Read bounded metadata only, with no symlink or concurrent replacement."""
    path = canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_METADATA, 'Expected bounded regular metadata: ' + str(path))
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(MAX_METADATA + 1)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        need(len(data) == before.st_size and all(getattr(before, k) == getattr(after, k) for k in fields), 'Metadata changed during read: ' + str(path))
        now = path.stat(follow_symlinks=False)
        need(all(getattr(after, k) == getattr(now, k) for k in fields), 'Metadata path changed during read: ' + str(path))
        return data
    finally:
        os.close(fd)


def descriptor(path):
    path = canonical(path)
    data = file_bytes(path)
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def desc_shape(value):
    need(isinstance(value, dict) and set(value) == DESC_KEYS
         and isinstance(value['path'], str) and type(value['bytes']) is int and value['bytes'] >= 0
         and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']), 'Invalid exact file descriptor')
    canonical(value['path'])
    return value


def verify(value):
    desc_shape(value)
    need(descriptor(value['path']) == value, 'Metadata descriptor differs: ' + value['path'])
    return value


def read(path):
    value = json.loads(file_bytes(path))
    need(isinstance(value, dict), 'Expected a JSON object: ' + str(path))
    return value


def write_bytes(path, data):
    """Atomic exclusive publication; an uncertain temporary file is retained."""
    path = canonical(path)
    need(path.parent.is_dir(), 'Parent must already exist: ' + str(path.parent))
    absent(path)
    temporary = path.with_name(path.name + '.writing')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path, follow_symlinks=False)
    temporary.unlink()
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return descriptor(path)


def write(path, value):
    return write_bytes(path, (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode())


def copy_input(path, target):
    data = file_bytes(path)
    original = {'path': str(canonical(path)), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    saved = write_bytes(target, data)
    need(saved['sha256'] == original['sha256'] and saved['bytes'] == original['bytes'], 'Input copy differs')
    return {'original': original, 'saved': saved}


def code_identity():
    values = []
    for path, expected in CODE_PINS.items():
        actual = descriptor(path)
        need(actual['sha256'] == expected, 'Frozen source/helper pin differs: ' + str(path))
        values.append(actual)
    return {'glue': descriptor(__file__), 'frozen_dependencies': values}


def archive_code(code):
    by_path = {row['path']: row for row in code['frozen_dependencies']}
    return {'metadata_helper': by_path[str(ARCHIVE_IO)],
            'frozen_archive': by_path[str(OLD / 'durable_archive.py')],
            'frozen_supervisor': by_path[str(OWN / 'supervisor.py')],
            'frozen_external_step': by_path[str(EXTERNAL_STEP)],
            'official_library_helpers': [by_path[str(HELPERS / name)] for name in
                ('library_download.py', 'library_file_transfer.py', 'library_hosted_apps.py', 'library_upload.py')]}


def proc_identity(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    fields = text[text.rfind(')') + 2:].split()
    need(int(text.split(' ', 1)[0]) == pid and fields[0] not in ('Z', 'X', 'x'), 'Supervisor is absent, reused, or exited')
    return {'pid': pid, 'parent_pid': int(fields[1]), 'pgid': int(fields[2]),
            'sid': int(fields[3]), 'start_ticks': int(fields[19])}


def live_guard(status):
    start_path = OPS / 'supervisor_run/START_POLICY.json'
    start_desc, start = descriptor(start_path), read(start_path)
    need(start.get('schema') == 'hepta.execution06.supervisor-start-policy.1'
         and start.get('execution_episode') == EPISODE and start.get('source_root') == str(SOURCE)
         and start.get('ops_root') == str(OPS), 'Supervisor startup binding differs')
    expected = start.get('supervisor_identity', {})
    need(set(expected) == IDENTITY_KEYS and all(type(v) is int and v >= 0 for v in expected.values()), 'Invalid supervisor startup identity')
    need(proc_identity(expected['pid']) == expected, 'Supervisor identity, including original parent, changed')
    legacy = {'pid': expected['pid'], 'start_ticks': str(expected['start_ticks']),
              'process_group': expected['pgid'], 'session': expected['sid']}
    need(status.get('pid') == expected['pid']
         and {k: status.get('identity', {}).get(k) for k in legacy} == legacy, 'STATUS identity differs from startup')
    need(os.readlink('/proc/self/ns/pid') == os.readlink(f"/proc/{expected['pid']}/ns/pid")
         and proc_identity(os.getpid())['pgid'] == os.getpgid(0), 'Run in the original host PID namespace')
    started, deadline = start.get('started_monotonic'), start.get('deadline_monotonic')
    need(all(type(v) in (int, float) and math.isfinite(v) for v in (started, deadline))
         and math.isclose(deadline - started, 43200.0, rel_tol=0, abs_tol=1e-6)
         and started <= time.monotonic() <= deadline, 'Original supervisor deadline is invalid or exhausted')
    return {'start_policy': start_desc, 'identity': expected, 'legacy_identity': legacy}


def current(stage, requested=None):
    need(stage in STAGES, 'Unknown stage name')
    need(not (OPS / 'FAILED.json').exists() and not (OPS / 'COMPLETE.json').exists(), 'Pipeline is terminal; stop this handoff')
    status_path = OPS / 'STATUS.json'
    status = read(status_path)
    pending = status.get('awaiting_durable')
    need(isinstance(pending, dict) and set(pending) == {'request', 'ack_path'}, 'No exact current awaiting handoff')
    request = verify(pending['request'])
    need(request['path'] == str(OPS / 'durable' / stage / 'REQUEST.json'), 'Current awaiting stage differs')
    if requested is not None:
        need(requested == request, 'Supplied REQUEST descriptor differs from current awaiting')
    value = read(request['path'])
    binding = value.get('binding', {})
    index = STAGES.index(stage)
    need(value.get('schema') == 'hepta.fullstudy.library-archive-request.1'
         and value.get('state') == 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK'
         and value.get('required_ack_schema') == 'hepta.fullstudy.library-archive-ack.1'
         and binding.get('execution_episode') == EPISODE and binding.get('sequence') == index + 1
         and binding.get('label') == LABELS[index], 'Current request episode or stage binding differs')
    ack = OPS / 'durable' / stage / 'ACK.json'
    need(status.get('schema') == 'hepta.fullstudy.execution06-status.1'
         and status.get('execution_episode') == EPISODE
         and status.get('phase') == 'await_durable_ack_' + LABELS[index]
         and pending['ack_path'] == str(ack), 'Current STATUS phase/schema differs')
    absent(ack)
    items = value.get('items')
    need(isinstance(items, list) and 1 <= len(items) <= 20, 'A single whole ordered handoff requires 1..20 items')
    names = set()
    for item in items:
        desc_shape(item)
        path = canonical(item['path'], ack.parent)
        need(path.parent == ack.parent and path.name not in names, 'Ambiguous ordered source item')
        names.add(path.name)
    return {'request': request, 'value': value, 'live': live_guard(status)}


def tool_payload(path):
    response = read(path)
    need(response.get('isError') is not True and isinstance(response.get('content'), list), 'Expected a complete successful ToolResponse envelope')
    payload = response.get('structuredContent')
    if payload is None:
        blocks = [x.get('text') for x in response['content'] if isinstance(x, dict) and x.get('type') == 'text']
        need(len(blocks) == 1 and isinstance(blocks[0], str), 'No unambiguous complete ToolResponse payload')
        payload = json.loads(blocks[0])
    need(isinstance(payload, dict), 'ToolResponse payload must be an object')
    payload = payload.get('result', payload)
    need(isinstance(payload, dict) and not payload.get('warnings') and not payload.get('unavailable_items')
         and not payload.get('partial_bindings'), 'Partial, unavailable, or warned ToolResponse requires root reconciliation')
    return payload


def folder_identity(path, stage, directory_id):
    need(isinstance(directory_id, str) and directory_id.strip() == directory_id and directory_id, 'Actual directory_id is required')
    payload = tool_payload(path)
    rows = payload.get('results')
    need(isinstance(rows, list) and len(rows) == 1, 'Expected exactly one actual create_folder result')
    row = rows[0]
    need(isinstance(row, dict) and row.get('operation') == 'create_folder' and row.get('status') == 'succeeded'
         and not row.get('error_code') and row.get('directory_id') == directory_id
         and isinstance(row.get('path'), str) and Path(row['path']).name == stage, 'Actual create_folder identity or stage differs')
    return {'directory_id': directory_id, 'folder_path': row['path']}


def remote(row):
    need(isinstance(row, dict), 'Missing actual remote identity')
    for key in ('file_id', 'file_name', 'library_file_id'):
        need(isinstance(row.get(key), str) and row[key], 'Missing actual Library identity: ' + key)
    name = row['file_name']
    need(Path(name).name == name and name not in ('.', '..'), 'Unsafe actual Library basename')
    version = row.get('current_version_number')
    need(type(version) is int and version >= 0, 'Missing actual current version; zero is valid')
    return {key: row[key] for key in ('file_id', 'file_name', 'library_file_id')} | {'version': version}


def whole_upload_result(path, items):
    value = read(path)
    rows = value.get('results')
    need(isinstance(rows, list) and len(rows) == len(items), 'Ordered upload count differs')
    result, seen = [], set()
    for item, row in zip(items, rows):
        need(isinstance(row, dict) and row.get('local_path') == item['path']
             and row.get('purpose') == 'create_library_file' and row.get('status') == 'succeeded'
             and row.get('local_metadata_applied') is True and not row.get('warnings'), 'Upload has a failed, partial, unknown, or reordered item; do not retry')
        identity = remote(row)
        need(identity['library_file_id'] not in seen, 'Duplicate upload Library identity')
        seen.add(identity['library_file_id'])
        result.append({'local': item, 'remote_identity': identity})
    return result


def step_argv(directory, argv, stdin=None):
    result = [VENV, '-B', str(EXTERNAL_STEP), '--directory', str(directory), '--cwd', str(EMPTY_CWD)]
    if stdin is not None:
        result += ['--stdin-file', stdin['path']]
    return result + ['--', *argv]


def validate_wait4(path, argv, stdin, directory):
    path, directory = canonical(path), canonical(directory)
    need(path == directory / 'WAIT4.json' and not (directory / 'FAILED.json').exists(), 'Measured helper failure or wrong WAIT4 path')
    value = read(path)
    need(value.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
         and value.get('complete') is True and value.get('command_success') is True
         and value.get('child', {}).get('exit_code') == 0, 'Measured helper was not successful; do not retry')
    need(verify(value['intent'])['path'] == str(directory / 'INTENT.json'), 'WAIT4 INTENT path differs')
    intent = read(value['intent']['path'])
    need(intent.get('schema') == 'hepta.execution04.root-engineering-intent.1'
         and intent.get('argv') == argv and intent.get('cwd') == str(EMPTY_CWD)
         and intent.get('stdin') == stdin and intent.get('automatic_retry') is False, 'Measured helper command/stdin binding differs')
    if stdin is not None:
        verify(stdin)
    for key, filename in (('stdout', 'helper.stdout.log'), ('stderr', 'helper.stderr.log')):
        need(verify(value[key])['path'] == str(directory / filename), 'Measured helper output path differs')
    return {'wait4': descriptor(path), 'stdout': value['stdout'], 'stderr': value['stderr']}


class Phase:
    """Exclusive local phase journal; this is not a remote or supervisor status."""

    def __init__(self, stage, name, context, code):
        self.stage, self.name, self.context, self.code = stage, name, context, code
        self.directory = ENGINEERING / f'{stage}_{name}_phase'
        self.directory.mkdir(mode=0o700, exist_ok=False)
        self.steps = []
        self.remote_helper_attempted = False
        self.intent = write(self.directory / 'INTENT.json', {
            'schema': 'hepta.execution06.root-barrier-phase-intent.1', 'at_utc': utc(),
            'execution_episode': EPISODE, 'stage': stage, 'phase': name,
            'request': context['request'], 'supervisor': context['live'], 'execution_code': code,
            'automatic_retry': False, 'supervisor_acceptance_claimed': False})

    def check(self):
        need(code_identity() == self.code, 'Glue or frozen source changed during phase')
        context = current(self.stage, self.context['request'])
        need(context['live'] == self.context['live'], 'Supervisor startup changed during phase')

    def run(self, label, argv, stdin=None, exact_external=None, remote_helper=False):
        self.check()
        directory = ENGINEERING / f'{self.stage}_{label}'
        command = step_argv(directory, argv, stdin)
        if exact_external is not None:
            need(isinstance(exact_external, list) and all(isinstance(x, str) for x in exact_external), 'Expected exact original external_step argv')
            directory = canonical(exact_external[4], ROOT / self.stage / 'readback_steps')
            command = step_argv(directory, argv, stdin)
            need(exact_external == command, 'Original READBACK_PLAN external_step argv differs')
            command = exact_external
        absent(directory)
        if stdin is not None:
            verify(stdin)
        stdout = self.directory / (label + '.wrapper.stdout.log')
        stderr = self.directory / (label + '.wrapper.stderr.log')
        attempt = write(self.directory / (label + '.ATTEMPT.json'), {
            'schema': 'hepta.execution06.root-barrier-helper-attempt.1', 'at_utc': utc(),
            'external_step_argv': command, 'expected_wait4': str(directory / 'WAIT4.json'),
            'remote_helper': remote_helper, 'automatic_retry': False})
        self.steps.append({'attempt': attempt, 'expected_wait4': str(directory / 'WAIT4.json')})
        if remote_helper:
            self.remote_helper_attempted = True
        with stdout.open('xb') as out, stderr.open('xb') as err:
            completed = subprocess.run(command, cwd=EMPTY_CWD, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err, check=False)
            out.flush()
            err.flush()
            os.fsync(out.fileno())
            os.fsync(err.fileno())
        self.steps[-1].update({'external_step_returncode': completed.returncode,
                              'wrapper_stdout': descriptor(stdout), 'wrapper_stderr': descriptor(stderr)})
        need(completed.returncode == 0, 'External step failed or has an uncertain outcome; inspect saved evidence, do not retry')
        result = validate_wait4(directory / 'WAIT4.json', argv, stdin, directory)
        self.steps[-1].update(result)
        return result

    def complete(self, results):
        return write(self.directory / 'DONE.json', {
            'schema': 'hepta.execution06.root-barrier-phase-done.1', 'at_utc': utc(),
            'execution_episode': EPISODE, 'stage': self.stage, 'phase': self.name,
            'intent': self.intent, 'request': self.context['request'], 'execution_code': self.code,
            'steps': self.steps, 'results': results, 'automatic_retry': False,
            'supervisor_acceptance_claimed': False})

    def failed(self, error):
        write(self.directory / 'FAILED.json', {
            'schema': 'hepta.execution06.root-barrier-phase-failure.1', 'at_utc': utc(),
            'intent': self.intent, 'error_type': type(error).__name__, 'message': str(error),
            'steps': self.steps, 'remote_helper_attempted': self.remote_helper_attempted,
            'remote_outcome_requires_root_reconciliation': self.remote_helper_attempted,
            'automatic_retry': False, 'no_new_phase_attempt_authorized': True})


@contextmanager
def phase(stage, name, context, code):
    canonical(ENGINEERING)
    ENGINEERING.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = ENGINEERING / (stage + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    created = None
    try:
        need(stat.S_ISREG(os.fstat(fd).st_mode), 'Stage lock is not regular')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current(stage, context['request'])
        created = Phase(stage, name, context, code)
        yield created
    except BaseException as error:
        if created is not None:
            try:
                created.failed(error)
            except BaseException:
                pass  # Original error and existing intent/attempt evidence remain authoritative.
        raise
    finally:
        os.close(fd)


def prior(stage, name, context, code):
    directory = ENGINEERING / f'{stage}_{name}_phase'
    absent(directory / 'FAILED.json')
    value = read(directory / 'DONE.json')
    need(value.get('schema') == 'hepta.execution06.root-barrier-phase-done.1'
         and value.get('stage') == stage and value.get('phase') == name
         and value.get('execution_episode') == EPISODE and value.get('request') == context['request']
         and value.get('execution_code') == code and value.get('supervisor_acceptance_claimed') is False,
         'Prior phase binding differs')
    verify(value['intent'])
    intent = read(value['intent']['path'])
    need(intent.get('supervisor') == context['live'] and intent.get('execution_code') == code, 'Prior phase supervisor or code changed')
    return value


def bound_work(stage, context, code):
    work = canonical(ROOT / stage, ROOT)
    bound = read(work / 'BOUND_REQUEST.json')
    need(bound.get('schema') == 'hepta.execution06.root-archive-binding.1'
         and bound.get('request') == context['request'] and bound.get('work_directory') == str(work)
         and bound.get('execution_code') == archive_code(code)
         and bound.get('supervisor_identity') == context['live']['legacy_identity'], 'Frozen stage work binding differs')
    verify(bound['request_descriptor_input'])
    return work, bound


def archive_argv(command, work, *extra):
    return [VENV, '-B', str(ARCHIVE_IO), command, '--work-directory', str(work), *extra]


def output_json(measured):
    return read(measured['stdout']['path'])


def upload(args):
    code = code_identity()
    supplied = read(args.request_descriptor)
    context = current(args.stage, supplied)
    folder = folder_identity(args.folder_response, args.stage, args.directory_id)
    work = ROOT / args.stage
    absent(work)
    expected_stdout = ENGINEERING / (args.stage + '_upload') / 'helper.stdout.log'
    need(canonical(args.upload_stdout) == expected_stdout, '--upload-stdout must be the exact forthcoming upload WAIT4 stdout path')
    for name in ('prepare_upload', 'upload', 'prepare_readback', 'upload_phase'):
        absent(ENGINEERING / f'{args.stage}_{name}')
    with phase(args.stage, 'upload', context, code) as p:
        request_input = copy_input(args.request_descriptor, p.directory / 'REQUEST_DESCRIPTOR_INPUT.json')
        folder_input = copy_input(args.folder_response, p.directory / 'CREATE_FOLDER_TOOLRESPONSE.json')
        need(read(request_input['saved']['path']) == context['request']
             and folder_identity(folder_input['saved']['path'], args.stage, args.directory_id) == folder,
             'Supplied metadata changed before its exclusive saved copy')
        write(p.directory / 'INPUTS.json', {'request': request_input, 'folder': folder_input, 'actual_folder': folder})
        prepared = p.run('prepare_upload', archive_argv('prepare-upload', work,
            '--request-descriptor', request_input['saved']['path'], '--directory-id', args.directory_id))
        work, bound = bound_work(args.stage, context, code)
        need(bound['directory_id'] == folder['directory_id'], 'Bound folder identity differs')
        upload_desc = descriptor(work / 'UPLOAD_REQUEST.json')
        expected = {'uploads': [{'local_path': item['path'], 'purpose': 'create_library_file',
                    'library_artifact_type': 'other', 'directory_id': args.directory_id} for item in context['value']['items']]}
        need(read(upload_desc['path']) == expected and output_json(prepared).get('upload_request') == upload_desc, 'Frozen ordered whole upload preparation differs')
        measured = p.run('upload', [PYTHON, '-B', str(HELPERS / 'library_upload.py')], upload_desc, remote_helper=True)
        need(measured['stdout']['path'] == str(expected_stdout), 'Actual upload stdout differs from mandatory argument')
        items = whole_upload_result(measured['stdout']['path'], context['value']['items'])
        readback = p.run('prepare_readback', archive_argv('prepare-readback', work,
            '--upload-wait4', measured['wait4']['path'], '--upload-stdout', measured['stdout']['path']))
        arguments_desc = descriptor(work / 'MATERIALIZE_ARGS.json')
        arguments = read(arguments_desc['path'])
        expected_args = {'items': [{key: item['remote_identity'][key] for key in
                         ('file_id', 'file_name', 'library_file_id')} for item in items],
                         'destination': {'directory': str(work / 'readback')}}
        need(arguments == expected_args and output_json(readback).get('materialize_arguments') == arguments_desc, 'Materialization arguments differ')
        verified_desc = descriptor(work / 'UPLOAD_VERIFIED.json')
        verified = read(verified_desc['path'])
        need(verified.get('request') == context['request'] and verified.get('items') == items
             and verified.get('upload_wait4') == measured['wait4'] and verified.get('upload_stdout') == measured['stdout'], 'Frozen upload verification binding differs')
        p.check()
        result = {'materialize_arguments': arguments_desc, 'upload_verified': verified_desc,
                  'upload_wait4': measured['wait4'], 'upload_stdout': measured['stdout'],
                  'actual_folder': folder, 'next_action': 'root_explicit_prepare_materialize',
                  'actual_ack_published': False}
        done = p.complete(result)
    return {'phase_receipt': done, **result, 'materialize_arguments_value': arguments}


def check_plan(plan, work, context, uploaded, materialize):
    need(plan.get('schema') == 'hepta.execution06.root-readback-helper-plan.1'
         and plan.get('request') == context['request'] and plan.get('automatic_retry') is False
         and plan.get('root_executes_official_helpers_explicitly') is True, 'Frozen readback plan binding differs')
    for key, path in (('upload_verified', work / 'UPLOAD_VERIFIED.json'),
                      ('materialize_arguments', work / 'MATERIALIZE_ARGS.json'),
                      ('materialize_receipt', Path(materialize['path']))):
        need(verify(plan[key])['path'] == str(path), 'Readback plan input path differs')
    need(plan['materialize_receipt'] == materialize, 'Full actual materialize response differs')
    payload = tool_payload(materialize['path'])
    transfers = payload.get('transfers')
    need(isinstance(transfers, list) and len(transfers) == len(uploaded['items']), 'Complete materialization transfer count differs')
    by_id = {x.get('library_file_id'): x for x in transfers if isinstance(x, dict)}
    need(len(by_id) == len(transfers), 'Duplicate or malformed materialization identities')
    jobs = plan.get('items')
    need(isinstance(jobs, list) and len(jobs) == len(context['value']['items']), 'Readback plan item count differs')
    paths = set()
    for index, (job, item, saved) in enumerate(zip(jobs, context['value']['items'], uploaded['items'])):
        need(job.get('index') == index and job.get('local') == item and job.get('remote_identity') == saved['remote_identity'], 'Ordered readback item binding differs')
        transfer_desc = verify(job['transfer'])
        need(transfer_desc['path'] == str(work / 'transfers' / f'{index:03d}.json'), 'Exact transfer metadata path differs')
        transfer = read(transfer_desc['path'])
        need(transfer == by_id.get(saved['remote_identity']['library_file_id'])
             and remote(transfer) == saved['remote_identity'], 'Actual materialization identity/version differs')
        need('size_bytes' not in transfer or transfer['size_bytes'] == item['bytes'], 'Readback transfer size differs')
        action = 'apply-xattrs' if transfer.get('workspace_path') else 'materialize'
        output = canonical(transfer.get('workspace_path') or work / 'readback' / transfer['file_name'], work / 'readback')
        need(output.name == transfer['file_name'] and str(output) not in paths, 'Ambiguous readback destination')
        paths.add(str(output))
        if action == 'apply-xattrs':
            need(output.is_file() and not output.is_symlink(), 'Materialization workspace file is unavailable')
        else:
            need(isinstance(transfer.get('download_url'), str) and transfer['download_url'], 'Missing actual signed transfer')
            absent(output)
        argv = [PYTHON, '-B', str(HELPERS / 'library_file_transfer.py'), action, str(output)]
        directory = work / 'readback_steps' / f'{index:03d}'
        need(job.get('helper_argv') == argv and job.get('expected_output_path') == str(output)
             and job.get('wait4_path') == str(directory / 'WAIT4.json')
             and job.get('external_step_argv') == step_argv(directory, argv, transfer_desc), 'Original exact READBACK_PLAN argv differs')
        absent(directory)
    return jobs


def readback(args):
    code = code_identity()
    context = current(args.stage)
    previous = prior(args.stage, 'upload', context, code)
    work, _ = bound_work(args.stage, context, code)
    verify(previous['results']['upload_verified'])
    verify(previous['results']['materialize_arguments'])
    tool_payload(args.materialize_response)
    for name in ('prepare_transfers', 'ack_candidate', 'readback_phase'):
        absent(ENGINEERING / f'{args.stage}_{name}')
    for filename in ('READBACK_PLAN.json', 'ACK_CANDIDATE.json', 'ACK_CANDIDATE_VERIFIED.json'):
        absent(work / filename)
    with phase(args.stage, 'readback', context, code) as p:
        full_response = copy_input(args.materialize_response, p.directory / 'MATERIALIZE_TOOLRESPONSE.json')
        write(p.directory / 'INPUTS.json', {'materialize_response': full_response,
                                         'prior_upload_done': descriptor(ENGINEERING / f'{args.stage}_upload_phase/DONE.json')})
        prepared = p.run('prepare_transfers', archive_argv('prepare-transfers', work,
                          '--materialize-receipt', full_response['saved']['path']))
        plan_desc = descriptor(work / 'READBACK_PLAN.json')
        need(output_json(prepared).get('readback_plan') == plan_desc, 'Frozen prepared plan descriptor differs')
        uploaded = read(work / 'UPLOAD_VERIFIED.json')
        jobs = check_plan(read(plan_desc['path']), work, context, uploaded, full_response['saved'])
        for job in jobs:
            verify(plan_desc)
            verify(job['transfer'])
            result = p.run(f"transfer_{job['index']:03d}", job['helper_argv'], job['transfer'],
                           exact_external=job['external_step_argv'], remote_helper=True)
            need(file_bytes(result['stdout']['path']).decode().strip() == job['expected_output_path'],
                 'Official transfer helper stdout must be its exact plain-text output path')
        candidate_step = p.run('ack_candidate', archive_argv('ack', work))
        result = output_json(candidate_step)
        candidate = verify(result['candidate'])
        frozen = verify(result['frozen_verification'])
        need(candidate['path'] == str(work / 'ACK_CANDIDATE.json')
             and frozen['path'] == str(work / 'ACK_CANDIDATE_VERIFIED.json')
             and result.get('actual_ack_published') is False, 'Candidate helper unexpectedly published or returned another path')
        p.check()
        result = {'candidate': candidate, 'frozen_verification': frozen, 'readback_plan': plan_desc,
                  'actual_ack_published': False, 'next_action': 'root_review_then_separate_publish_command'}
        done = p.complete(result)
    return {'phase_receipt': done, **result}


def publish(args):
    need(args.publish_ack is True, 'Publication requires explicit --publish-ack')
    need(re.fullmatch('[0-9a-f]{64}', args.expected_candidate_sha256 or ''), 'Root must supply the reviewed candidate SHA256')
    code = code_identity()
    context = current(args.stage)
    previous = prior(args.stage, 'readback', context, code)
    work, _ = bound_work(args.stage, context, code)
    approved = verify(previous['results']['candidate'])
    verify(previous['results']['frozen_verification'])
    need(approved['path'] == str(work / 'ACK_CANDIDATE.json')
         and approved['sha256'] == args.expected_candidate_sha256, 'Root-reviewed candidate SHA256 differs')
    absent(work / 'ACK_PUBLISH_LIVENESS.json')
    for name in ('publish_ack', 'publish_phase'):
        absent(ENGINEERING / f'{args.stage}_{name}')
    with phase(args.stage, 'publish', context, code) as p:
        write(p.directory / 'ROOT_EXPLICIT_APPROVAL.json', {'candidate': approved, 'publish_ack': True,
              'meaning': 'Root invoked this separate command after candidate review; acceptance remains the supervisor action'})
        measured = p.run('publish_ack', archive_argv('ack', work, '--publish-ack'))
        actual = output_json(measured)
        need(actual.get('actual_ack_published') is True and actual.get('candidate') == approved, 'Publication result or reviewed candidate differs')
        ack = verify(actual['actual_ack'])
        need(ack['path'] == str(OPS / 'durable' / args.stage / 'ACK.json')
             and (ack['bytes'], ack['sha256']) == (approved['bytes'], approved['sha256']), 'Actual ACK bytes differ from reviewed candidate')
        liveness = verify(actual['publish_liveness'])
        need(liveness['path'] == str(work / 'ACK_PUBLISH_LIVENESS.json'), 'Publication liveness receipt path differs')
        # The supervisor may already have advanced. Do not require the old await,
        # manufacture acceptance, or call the publication command a second time.
        result = {'candidate': approved, 'actual_ack': ack, 'publish_liveness': liveness,
                  'actual_ack_published': True, 'supervisor_acceptance_claimed': False,
                  'root_must_separately_verify': str(OPS / 'durable' / args.stage / 'ACK_VERIFIED.json')}
        done = p.complete(result)
    return {'phase_receipt': done, **result}


def status():
    """Read-only metadata observation; never creates a work or receipt directory."""
    result = {'read_only': True, 'execution_episode': EPISODE, 'ops_path': str(OPS), 'ops_exists': OPS.exists()}
    if not OPS.exists():
        return result
    canonical(OPS)
    for name in ('FAILED.json', 'COMPLETE.json'):
        if (OPS / name).is_file():
            result[name] = descriptor(OPS / name)
    if not (OPS / 'STATUS.json').is_file():
        result['status_exists'] = False
        return result
    status_path = OPS / 'STATUS.json'
    data = file_bytes(status_path)
    actual = json.loads(data)
    need(isinstance(actual, dict), 'Actual STATUS must be an object')
    result['status_descriptor'] = {'path': str(status_path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    result['observed_status'] = {key: actual.get(key) for key in
        ('schema', 'execution_episode', 'phase', 'pid', 'identity', 'awaiting_durable', 'completed_jobs', 'acks') if key in actual}
    pending = actual.get('awaiting_durable')
    if isinstance(pending, dict) and isinstance(pending.get('request'), dict):
        request = pending['request']
        desc_shape(request)
        path = canonical(request['path'], OPS / 'durable')
        stage = path.parent.name
        need(path.name == 'REQUEST.json' and stage in STAGES, 'Unrecognized actual status REQUEST path')
        result['awaiting_stage'] = stage
        result['actual_request'] = verify(request)
        result['phase_records'] = {}
        for phase_name in ('upload', 'readback', 'publish'):
            directory = ENGINEERING / f'{stage}_{phase_name}_phase'
            result['phase_records'][phase_name] = {name: descriptor(directory / name) for name in
                ('INTENT.json', 'DONE.json', 'FAILED.json') if (directory / name).is_file()}
        result['ack_records'] = {name: descriptor(path.parent / name) for name in
            ('ACK.json', 'ACK_VERIFIED.json') if (path.parent / name).is_file()}
        result['expected_upload_stdout'] = str(ENGINEERING / f'{stage}_upload/helper.stdout.log')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true', help='Read actual current metadata only; creates nothing')
    sub = parser.add_subparsers(dest='command')
    up = sub.add_parser('upload')
    up.add_argument('--stage', required=True, choices=STAGES)
    up.add_argument('--request-descriptor', required=True)
    up.add_argument('--folder-response', required=True)
    up.add_argument('--directory-id', required=True)
    up.add_argument('--upload-stdout', required=True)
    up.set_defaults(run=upload)
    rb = sub.add_parser('readback')
    rb.add_argument('--stage', required=True, choices=STAGES)
    rb.add_argument('--materialize-response', required=True)
    rb.set_defaults(run=readback)
    pub = sub.add_parser('publish')
    pub.add_argument('--stage', required=True, choices=STAGES)
    pub.add_argument('--expected-candidate-sha256', required=True)
    pub.add_argument('--publish-ack', action='store_true', required=True)
    pub.set_defaults(run=publish)
    args = parser.parse_args(argv)
    need(bool(args.status) != bool(args.command), 'Choose --status alone or one explicit phase')
    result = status() if args.status else args.run(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
