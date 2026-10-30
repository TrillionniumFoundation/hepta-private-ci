"""Explicit, one-stage retirement of supervisor-accepted execution06 readbacks.

External engineering tool, Linux only. It preserves compressed source parts,
RAW/CAS, frozen science, small provenance, and remote objects. It never uploads,
publishes ACKs, retries a mutation, or executes a scientific process. Run both
explicit phases through the unchanged recovery04 external_step.py meter.
"""
import argparse
import ast
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

sys.dont_write_bytecode = True
BASE = Path('/workspace/scratch/178ced6a501f')
SOURCE = BASE / 'fullstudy_recovery06_git'
OPS = BASE / 'fullstudy_execution06_ops'
RAW = BASE / 'fullstudy_execution06_durable_raw'
RETIREMENT_ROOT = BASE / 'execution06_recovery_20261030/readback_retirement06'
EPISODE = 'execution06_detached_20261030'
HELPERS = BASE / 'executor_recovery_20261030T1152/helpers'
HELPER_PYTHON = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3'
HELPER_PINS = {
    'library_download.py': '7a092c11922d14a5c61ce1a9beb7d1d3af89bd22b3eff4549abf79ac28878989',
    'library_file_transfer.py': 'd0385de4b634c4a6d4c26a83b40ee4ff33461e42473ce8c0387460be2465e314',
    'library_hosted_apps.py': '7958642b88cde925aaca036989de1028c0864eb6d82a9cb175ebf9380cb9677b',
    'library_upload.py': '5bc473dadefe1f68ee8797baaed19d6662642d0ea4bcba128fa12938faa0d767',
}
COMMIT = 'bc4e757f5c90f6365f383c1127be710d2ded874a'
CONFIG_SHA = 'd16bac3194b36d286f180976ddbc7dff16e544763e195d408a135b30af4fb86e'
LABELS = ['A-17', 'A-29', 'A-43', 'C', 'B-17', 'B-29', 'B-43', 'W',
          'R-17', 'R-29', 'R-43', 'A_endpoint', 'B_endpoint', 'C_endpoint',
          'controller', 'analysis', 'final_closure']
STAGES = ['%02d_%s' % (i, v) for i, v in enumerate(LABELS, 1)]
MAX_METADATA = 16 * 1024 ** 2
RESERVE = 256 * 1024 ** 2
IDENTITY_KEYS = {'pid', 'parent_pid', 'pgid', 'sid', 'start_ticks'}
STAT_KEYS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
             'st_size', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns', 'st_blocks')
CODE = {'operational/parameter_field_recovery06/supervisor.py': '9fe5a97112693d6eb2f718c50d09c3b53a85c4f949d1b571b0494b48902f547b', 'operational/parameter_field_recovery06/archive_io.py': '84eb4813a0bf487c5a1edfe77185ae4863c7d6f3431898eac9bc91e7f1946449', 'operational/parameter_field_recovery04/durable_archive.py': 'dfeee33870f3ca429284542cb8ca9ff8c9471a8fc8ff0339c3de251cabf260da', 'operational/parameter_field_recovery06/producer_adapter.py': '14ef2027993d39549099161833b91246a8c85469d4118274fed46b809463eed7', 'operational/parameter_field_recovery06/registration.py': '1e30fc9e0a234046346f4c46d01b217f009660dbd1b120da0d53f5298daa79ca', 'operational/parameter_field_recovery06/postseal/prepare_pins.py': '4b7c54ae135286e6b9d080dd30d148b303bd1daa5a0c0612fc2850354c4acd4d', 'operational/parameter_field_recovery06/postseal/review.py': '9682c1e07398a8ad0efb2babdc03fc61079ade33f76aa1fa77838d41fe167c5a', 'operational/parameter_field_recovery06/postseal/run_supplement.py': '0fc55b5e031c3cbeb1f796d3fd493f7f6689e747693c41fdf263675b0fba38a1', 'experiments/parameter_field_fullstudy_20261029/finalize_v2.py': '6fbf4a7a994120b6c0ae577a10d9ba992ad483d253ff0afb9aea42af8bb705ac', 'supplements/parameter_field_fullstudy_20261030/postseal_supplement.py': '1b705285b99fc7185c20155fa85f3a5d370b473196eaf59c8ae1d6bb2941a633', 'operational/parameter_field_recovery06/cwd_runner.py': '95403029436c72dfb7a545de4794781947a45de62a9412a8be20ed1623f9f86b', 'operational/parameter_field_recovery06/daemon_bootstrap.py': '8caa56a4af9e8c66a8cb5ce6f26469779dca6174ce0e234a5e9ea5626a1234a3', 'operational/parameter_field_recovery06/wait4_launcher.py': '2ed6930e78aa9ba3328fc9525e0bb995b8bbbb6cd2b5bc6fa586b4e3fb2476dd', 'operational/parameter_field_recovery04/external_step.py': 'fb238cd0f28e331a2e9d4ada5950f436a2d31e579fa9fbd8c36cce70404c2b21'}


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(path):
    value = Path(path)
    need(value.is_absolute() and value == value.resolve() and value.is_relative_to(BASE),
         'Path leaves the fixed workspace or contains a symlink: ' + str(path))
    return value


def signature(info):
    return {key: getattr(info, key) for key in STAT_KEYS}


def file_stat(path):
    path = canonical(path)
    value = path.lstat()
    need(stat.S_ISREG(value.st_mode), 'Not a regular nonsymlink file: ' + str(path))
    return signature(value)


def attrs(fd):
    return {name: base64.b64encode(os.getxattr(fd, name)).decode()
            for name in sorted(os.listxattr(fd))}


def metadata_bytes(path):
    path = canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
    try:
        before = signature(os.fstat(fd))
        need(stat.S_ISREG(before['st_mode']) and before['st_size'] <= MAX_METADATA,
             'Expected bounded regular metadata: ' + str(path))
        chunks, total = [], 0
        while chunk := os.read(fd, min(1024 * 1024, MAX_METADATA + 1 - total)):
            total += len(chunk)
            need(total <= MAX_METADATA, 'Metadata exceeded its bound')
            chunks.append(chunk)
        data = b''.join(chunks)
        need(len(data) == before['st_size'] and signature(os.fstat(fd)) == before
             and file_stat(path) == before, 'Metadata changed during read: ' + str(path))
        return data
    finally:
        os.close(fd)


def descriptor(path):
    path = canonical(path)
    data = metadata_bytes(path)
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def desc_shape(value):
    need(isinstance(value, dict) and set(value) == {'path', 'bytes', 'sha256'}
         and isinstance(value['path'], str) and type(value['bytes']) is int and value['bytes'] >= 0
         and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']),
         'Invalid exact descriptor')
    canonical(value['path'])
    return value


def bound(item):
    desc_shape(item)
    data = metadata_bytes(item['path'])
    need(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
         'Exact metadata descriptor changed: ' + item['path'])
    value = json.loads(data)
    need(isinstance(value, dict), 'Expected JSON object')
    return value


def read(path):
    return bound(descriptor(path))


def fsync_dir(path):
    fd = os.open(canonical(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def reserve(path, allocation=2 * 1024 ** 2):
    value = os.statvfs(path)
    need(value.f_bavail * value.f_frsize >= RESERVE + allocation and value.f_favail >= 2000,
         'Cannot preserve original physical reserve for retirement evidence')
    return {'available_bytes': value.f_bavail * value.f_frsize, 'available_inodes': value.f_favail}


def write_new(path, value):
    path = canonical(path)
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    need(len(data) <= 2 * 1024 ** 2, 'Retirement metadata exceeds its bound')
    reserve(path.parent, ((len(data) + 4095) // 4096) * 4096)
    need(not os.path.lexists(path), 'Existing evidence is not retryable: ' + str(path))
    temporary = path.with_name(path.name + '.writing')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        need(os.write(fd, data) == len(data), 'Short metadata write')
        os.fsync(fd)
    finally:
        os.close(fd)
    os.link(temporary, path, follow_symlinks=False)
    temporary.unlink()
    fsync_dir(path.parent)
    return descriptor(path)


class Journal:
    def __init__(self, path):
        self.path = canonical(path)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.events = 0
        fsync_dir(self.path.parent)

    def log(self, event, **value):
        data = (json.dumps({'event': event, 'at_utc': utc(), **value}, sort_keys=True, allow_nan=False) + '\n').encode()
        need(len(data) <= 2 * 1024 ** 2, 'Journal event exceeds bound')
        reserve(self.path.parent, len(data) + 4096)
        need(os.write(self.fd, data) == len(data), 'Short journal write; stop without retry')
        os.fsync(self.fd)
        self.events += 1

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def verify_code():
    values = []
    for relative, expected in CODE.items():
        item = descriptor(SOURCE / relative)
        need(item['sha256'] == expected, 'Audited frozen consumer changed: ' + relative)
        values.append(item)
    helpers = []
    for name, expected in sorted(HELPER_PINS.items()):
        item = descriptor(HELPERS / name)
        need(item['sha256'] == expected, 'Official restored helper changed: ' + name)
        helpers.append(item)
    return {'script': descriptor(Path(__file__).resolve()), 'frozen_sources': values,
            'official_helpers': helpers}


def bound_archive_code():
    return {'metadata_helper': descriptor(SOURCE / 'operational/parameter_field_recovery06/archive_io.py'),
            'frozen_archive': descriptor(SOURCE / 'operational/parameter_field_recovery04/durable_archive.py'),
            'frozen_supervisor': descriptor(SOURCE / 'operational/parameter_field_recovery06/supervisor.py'),
            'frozen_external_step': descriptor(SOURCE / 'operational/parameter_field_recovery04/external_step.py'),
            'official_library_helpers': [descriptor(HELPERS / name) for name in sorted(HELPER_PINS)]}


def pipeline():
    item = descriptor(OPS / 'registrations/initial/PIPELINE_CONFIG.json')
    need(item['sha256'] == CONFIG_SHA, 'Not the one actual execution06 pipeline configuration')
    cfg = bound(item)
    need(cfg.get('schema') == 'hepta.fullstudy.execution06.configuration.1'
         and cfg.get('execution_episode') == EPISODE and cfg.get('source_commit') == COMMIT
         and all(cfg.get(k) == str(v) for k, v in
                 [('source_root', SOURCE), ('ops_root', OPS), ('raw_root', RAW)]), 'Pipeline identity differs')
    policy_desc = cfg['descriptors']['cwd_policy']
    policy = bound(policy_desc)
    need(policy['schema'] == 'hepta.fullstudy.cwd-policy.5'
         and policy['execution_episode'] == EPISODE and policy['capacity_wait_seconds'] == 300
         and all(policy.get(k) == str(v) for k, v in
                 [('source_root', SOURCE), ('ops_root', OPS), ('raw_root', RAW)])
         and all(policy['source_files'].get(k) == v for k, v in CODE.items()), 'Frozen cwd policy differs')
    for name, expected in policy['source_files'].items():
        relative = Path(name)
        need(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe frozen source path')
        need(descriptor(SOURCE / relative)['sha256'] == expected, 'Full frozen source closure differs: ' + name)
    return item, cfg, policy_desc


def proc_identity(pid):
    value = Path('/proc/%d/stat' % pid).read_text()
    fields = value[value.rfind(')') + 2:].split()
    need(int(value.split(' ', 1)[0]) == pid and fields[0] not in ('Z', 'X', 'x'), 'Original process is no longer live')
    return {'pid': pid, 'parent_pid': int(fields[1]), 'pgid': int(fields[2]),
            'sid': int(fields[3]), 'start_ticks': int(fields[19])}


def oom_counts():
    values = {k: int(v) for k, v in (x.split() for x in Path('/sys/fs/cgroup/memory.events').read_text().splitlines())}
    return {key: values[key] for key in ('oom', 'oom_kill')}


def load_terminal(config_desc, cfg, start):
    """Use the exact frozen metadata-only terminal ancestry function."""
    complete_desc = descriptor(OPS / 'COMPLETE.json')
    complete = bound(complete_desc)
    outer_desc = descriptor(OPS / 'wait4_launcher/WAIT4_COMPLETE.json')
    outer = bound(outer_desc)
    need(complete.get('schema') == 'hepta.fullstudy.pipeline-completion.4'
         and complete.get('complete') is True and complete.get('execution_episode') == EPISODE
         and complete.get('pipeline_config') == config_desc and complete.get('jobs_verified') == 14
         and complete.get('required_finalizer_seals_verified') == 30
         and len(complete.get('durable_stages', [])) == 17
         and outer.get('schema') == 'hepta.fullstudy.execution06-outer-wait4.1'
         and outer.get('exit_code') == outer.get('wait_status') == 0
         and outer.get('config') == config_desc and outer.get('primary_complete') == complete_desc
         and outer.get('child_identity') == start['supervisor_identity']
         and outer.get('waited_pid') == start['supervisor_identity']['pid'], 'Successful actual primary/outer exit is not closed')
    source = SOURCE / 'operational/parameter_field_recovery06/postseal/prepare_pins.py'
    tree = ast.parse(metadata_bytes(source), filename=str(source))
    function = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'detached_provenance']
    need(len(function) == 1, 'Frozen detached provenance function population differs')
    namespace = {'OPS': OPS, 'SOURCE': SOURCE, 'EPISODE': EPISODE,
                 'need': need, 'descriptor': descriptor, 'bound': bound}
    exec(compile(ast.Module(body=function, type_ignores=[]), str(source), 'exec'), namespace)
    detached = namespace['detached_provenance'](config_desc, cfg, outer)
    return {'complete': complete_desc, 'outer_wait4': outer_desc, 'detached': detached}, complete


class Health:
    def __init__(self, config_desc, cfg, policy_desc):
        self.start_desc = descriptor(OPS / 'supervisor_run/START_POLICY.json')
        self.start_stat = file_stat(self.start_desc['path'])
        self.start = bound(self.start_desc)
        value = self.start
        need(value.get('schema') == 'hepta.execution06.supervisor-start-policy.1'
             and value.get('execution_episode') == EPISODE and value.get('cwd_policy') == policy_desc
             and all(value.get(k) == str(v) for k, v in
                     [('source_root', SOURCE), ('ops_root', OPS), ('raw_root', RAW)]), 'Startup binding differs')
        owner = value['supervisor_identity']
        need(set(owner) == IDENTITY_KEYS and all(type(v) is int and v > 0 for v in owner.values()), 'Invalid integer supervisor identity')
        started, deadline = value['started_monotonic'], value['deadline_monotonic']
        need(all(type(v) in (int, float) and math.isfinite(v) for v in (started, deadline))
             and math.isclose(deadline - started, 43200.0, rel_tol=0, abs_tol=1e-6)
             and started <= time.monotonic() <= deadline, 'Original absolute 12-hour deadline is invalid/exhausted')
        need(set(value['oom_baseline']) == {'oom', 'oom_kill'}
             and all(type(v) is int and v >= 0 for v in value['oom_baseline'].values()), 'Invalid original OOM baseline')
        self.terminal = self.complete = None
        if (OPS / 'COMPLETE.json').exists():
            self.terminal, self.complete = load_terminal(config_desc, cfg, value)
        self.last_check = 0.0
        self(force=True)

    def __call__(self, force=False):
        if not force and time.monotonic() - self.last_check < 0.2:
            return
        need(not (OPS / 'FAILED.json').exists(), 'Failed episode must remain intact')
        need(descriptor(self.start_desc['path']) == self.start_desc
             and file_stat(self.start_desc['path']) == self.start_stat, 'Original startup record changed')
        need(time.monotonic() <= self.start['deadline_monotonic'], 'Original absolute deadline exhausted')
        actual_oom = oom_counts()
        need(all(actual_oom[k] <= self.start['oom_baseline'][k] for k in actual_oom), 'Original OOM baseline exceeded')
        if self.terminal is None:
            owner = self.start['supervisor_identity']
            need(proc_identity(owner['pid']) == owner, 'Original supervisor identity including parent changed')
            need(os.readlink('/proc/self/ns/pid') == os.readlink('/proc/%d/ns/pid' % owner['pid']), 'PID namespace differs')
        else:
            for item in [self.terminal['complete'], self.terminal['outer_wait4'], *self.terminal['detached']['receipts'].values()]:
                need(descriptor(item['path']) == item, 'Actual terminal ancestry changed')
        self.last_check = time.monotonic()

    def evidence(self):
        return {'start_policy': self.start_desc, 'supervisor_identity': self.start['supervisor_identity'],
                'deadline_monotonic': self.start['deadline_monotonic'], 'oom_baseline': self.start['oom_baseline'],
                'basis': 'PRIMARY_OUTER_AND_DETACHED_COMPLETE' if self.terminal else 'LIVE_ORIGINAL_SUPERVISOR',
                'terminal': self.terminal}


def accepted(stage, config_desc, health):
    need(stage in STAGES, 'Unknown fixed stage')
    health(force=True)
    target = STAGES.index(stage) + 1
    chain, previous_ack = [], None
    chosen = None
    for index in range(1, target + 1):
        directory = OPS / 'durable' / STAGES[index - 1]
        anchors = {key: descriptor(directory / name) for key, name in
                   [('request', 'REQUEST.json'), ('ack', 'ACK.json'), ('ack_verified', 'ACK_VERIFIED.json')]}
        request, ack, verified = [bound(anchors[key]) for key in ('request', 'ack', 'ack_verified')]
        binding = request['binding']
        need(request.get('schema') == 'hepta.fullstudy.library-archive-request.1'
             and request.get('state') == 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK'
             and request.get('required_ack_schema') == 'hepta.fullstudy.library-archive-ack.1'
             and binding.get('execution_episode') == EPISODE and binding.get('sequence') == index
             and binding.get('label') == LABELS[index - 1] and binding.get('pipeline_config') == config_desc
             and binding.get('completed_jobs') == LABELS[:min(index, 14)] and binding.get('previous_ack') == previous_ack,
             'Actual accepted archive chain differs')
        need(ack.get('schema') == request['required_ack_schema'] and ack.get('status') == 'VERIFIED_REMOTE_READBACK'
             and ack.get('unknown_upload_outcome') is False and ack.get('request') == verified.get('request') == anchors['request']
             and verified.get('ack') == anchors['ack'] and verified.get('binding') == ack.get('binding') == binding
             and verified.get('readback_bytes_verified_here') is True
             and len(ack.get('items', [])) == len(request['items']) == verified.get('items_verified'),
             'Stage lacks the exact supervisor-accepted ACK')
        ids = []
        for expected, item in zip(request['items'], ack['items'], strict=True):
            desc_shape(expected); desc_shape(item['readback'])
            remote = item['remote_identity']
            need(item['local'] == expected and item.get('upload_item_success') is True
                 and item.get('remote_readback_performed') is True and item.get('readback_remote_identity') == remote
                 and all(item['readback'][k] == expected[k] for k in ('bytes', 'sha256'))
                 and isinstance(remote.get('library_file_id'), str) and bool(remote['library_file_id'])
                 and type(remote.get('version')) is int and remote['version'] >= 0,
                 'Actual remote identity/ordered readback differs')
            ids.append(remote['library_file_id'])
        need(len(set(ids)) == len(ids) and sorted(ids) == verified.get('remote_library_file_ids'), 'Remote file IDs differ')
        manifest, verification = bound(request['manifest']), bound(request['archive_verification'])
        need(manifest['binding'] == verification['binding'] == binding
             and verification.get('verification_complete') is True and verification.get('manifest') == request['manifest'],
             'Original archive manifest/verification chain differs')
        chain.append(anchors)
        previous_ack = anchors['ack']
        if index == target:
            chosen = directory, request, ack, verified
    directory, request, ack, verified = chosen
    work = OPS / 'root_archive_io' / stage
    root_binding = descriptor(work / 'BOUND_REQUEST.json')
    root = bound(root_binding)
    owner = health.start['supervisor_identity']
    legacy = {'pid': owner['pid'], 'process_group': owner['pgid'], 'session': owner['sid'], 'start_ticks': str(owner['start_ticks'])}
    need(root.get('schema') == 'hepta.execution06.root-archive-binding.1'
         and root.get('request') == chain[-1]['request'] and root.get('work_directory') == str(work)
         and root.get('supervisor_identity') == legacy and root.get('execution_code') == bound_archive_code()
         and ack.get('root_operational_binding') == root_binding,
         'Root work binding differs from original accepted request/owner')
    status = read(OPS / 'STATUS.json')
    need(status.get('schema') == 'hepta.fullstudy.execution06-status.1' and status.get('execution_episode') == EPISODE
         and status.get('pid') == owner['pid'] and {k: status.get('identity', {}).get(k) for k in legacy} == legacy
         and type(status.get('durable_acks')) is int and target <= status['durable_acks'] <= 17
         and status.get('completed_jobs', [])[:min(target, 14)] == LABELS[:min(target, 14)]
         and (status.get('awaiting_durable') or {}).get('request') != chain[-1]['request']
         and status.get('phase') != 'await_durable_ack_' + LABELS[target - 1],
         'Actual supervisor STATUS has not advanced past this accepted stage')
    if health.complete is not None:
        need(health.complete['durable_stages'][target - 1] == verified, 'Primary completion differs from accepted stage')
    anchors = {'stage_chain': chain, 'root_binding': root_binding, 'pipeline_config': config_desc,
               'start_policy': health.start_desc}
    return {'directory': directory, 'work': work, 'anchors': anchors, 'request': request, 'ack': ack,
            'verified': verified, 'health': health.evidence(), 'status_observed': status}


class IncompleteProcObservation(RuntimeError):
    def __init__(self, record):
        self.record = record
        super().__init__('Incomplete read-only /proc coverage: ' + json.dumps(record, sort_keys=True))


def no_open_references(rows, allowed_self_fd=None):
    """Fresh complete visible /proc snapshot; unknown coverage fails closed."""
    paths, keys = set(), set()
    for row in rows:
        paths.add(row['path'])
        keys.add((row['stat']['st_dev'], row['stat']['st_ino']))
    me = proc_identity(os.getpid())
    need(me['parent_pid'] == os.getppid() and me['pgid'] == os.getpgid(0) and me['sid'] == os.getsid(0), 'Host PID namespace mismatch')
    seen, errors, hits, gone = {}, [], [], set()
    fd_count = map_count = 0
    for _ in range(3):
        current = {int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()}
        todo = current - set(seen)
        if not todo:
            break
        for pid in sorted(todo):
            process = Path('/proc') / str(pid)
            try:
                text = (process / 'stat').read_text()
                fields = text[text.rfind(')') + 2:].split()
                seen[pid] = int(fields[19])
                for fd_path in (process / 'fd').iterdir():
                    try:
                        target, info = os.readlink(fd_path), fd_path.stat()
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    fd_count += 1
                    if pid == os.getpid() and allowed_self_fd is not None and fd_path.name == str(allowed_self_fd):
                        need((info.st_dev, info.st_ino) in keys, 'Excluded own FD is not a selected archive')
                        continue
                    if target.removesuffix(' (deleted)') in paths or (info.st_dev, info.st_ino) in keys:
                        hits.append({'pid': pid, 'kind': 'fd', 'fd': fd_path.name})
                for line in (process / 'maps').read_text().splitlines():
                    parts = line.split(None, 5)
                    need(len(parts) >= 5, 'Unparseable /proc/maps entry')
                    major, minor = (int(x, 16) for x in parts[3].split(':'))
                    map_count += 1
                    if (os.makedev(major, minor), int(parts[4])) in keys or (len(parts) == 6 and parts[5].removesuffix(' (deleted)') in paths):
                        hits.append({'pid': pid, 'kind': 'mmap', 'inode': int(parts[4])})
                after = (process / 'stat').read_text()
                need(int(after[after.rfind(')') + 2:].split()[19]) == seen[pid], 'PID was reused during no-use scan')
            except (FileNotFoundError, ProcessLookupError):
                gone.add(pid)
                if pid not in seen:
                    seen[pid] = None
            except OSError as error:
                errors.append({'pid': pid, 'error_type': type(error).__name__, 'errno': error.errno})
    remaining = {int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()} - set(seen)
    result = {'at_utc': utc(), 'pid_start_ticks_scanned': {str(k): v for k, v in seen.items()},
              'fds_checked': fd_count, 'maps_checked': map_count, 'gone_during_scan': sorted(gone),
              'new_unscanned_pids': sorted(remaining), 'access_errors': errors, 'target_references': hits,
              'allowed_own_fd': allowed_self_fd, 'snapshot_not_continuous_kernel_lease': True}
    need(not hits, 'Selected archive is referenced: ' + json.dumps(result, sort_keys=True))
    if remaining or errors:
        result['full_visible_proc_namespace_checked'] = False
        raise IncompleteProcObservation(result)
    result['full_visible_proc_namespace_checked'] = True
    return result


def settled_no_use(rows, health, journal, allowed_self_fd=None, clock=time.monotonic, sleeper=time.sleep):
    """Only unknown read-only coverage may settle; mutations are never retried.

    Same 10-second / 0.2-second rule as the independently tested stage03 cache
    tool. The original full no-reference PASS remains mandatory. Known users,
    other exceptions, elapsed deadline, and OOM changes fail immediately.
    """
    started, attempts, last_error = clock(), 0, None
    deadline = started + 10.0
    while True:
        health(force=True)
        if clock() >= deadline:
            raise TimeoutError('Complete /proc coverage did not settle in 10 seconds') from last_error
        attempts += 1
        try:
            result = no_open_references(rows, allowed_self_fd=allowed_self_fd)
        except IncompleteProcObservation as error:
            record = error.record
            need(isinstance(record, dict) and record.get('target_references') == []
                 and record.get('full_visible_proc_namespace_checked') is False
                 and isinstance(record.get('new_unscanned_pids'), list)
                 and all(type(pid) is int and pid > 0 for pid in record['new_unscanned_pids'])
                 and isinstance(record.get('access_errors'), list)
                 and all(isinstance(e, dict) and type(e.get('pid')) is int and e['pid'] > 0
                         and type(e.get('errno')) is int and isinstance(e.get('error_type'), str)
                         for e in record['access_errors'])
                 and (record['new_unscanned_pids'] or record['access_errors']),
                 'Only complete unknown-coverage records may enter bounded read-only observation')
            remaining = max(0.0, deadline - clock())
            journal.log('INCOMPLETE_READ_ONLY_PROC_OBSERVATION', attempt=attempts,
                        original_observation=record, remaining_monotonic_seconds=remaining,
                        mutation_performed_in_response=False, wait_seconds=min(0.2, remaining))
            last_error = error
            if remaining:
                sleeper(min(0.2, remaining))
            continue
        need(clock() <= deadline, 'Complete /proc observation arrived after its fixed deadline')
        need(result.get('target_references') == [] and result.get('new_unscanned_pids') == []
             and result.get('access_errors') == [] and result.get('full_visible_proc_namespace_checked') is True,
             'Original full no-reference PASS is required after observation settling')
        health(force=True)
        return {**result, 'read_only_observation_attempts': attempts,
                'read_only_observation_elapsed_seconds': clock() - started,
                'read_only_observation_limit_seconds': 10.0, 'automatic_mutation_retry': False}


def row_scope(state):
    rows = []
    for expected, item in zip(state['request']['items'], state['ack']['items'], strict=True):
        original = Path(expected['path'])
        if not re.fullmatch(r'part-[0-9]{4}\.tar\.gz', original.name):
            continue
        duplicate = Path(item['readback']['path'])
        need(original.parent == state['directory'] and duplicate.parent == state['work'] / 'readback'
             and original.name == duplicate.name and item['local'] == expected, 'Part escaped exact accepted copy scope')
        original_stat, duplicate_stat = file_stat(original), file_stat(duplicate)
        need(original_stat['st_nlink'] == duplicate_stat['st_nlink'] == 1
             and (original_stat['st_dev'], original_stat['st_ino']) != (duplicate_stat['st_dev'], duplicate_stat['st_ino']),
             'Both parts must be independent single-link regular files')
        rows.append({'duplicate': item['readback'], 'retained_original': expected,
                     'duplicate_stat': duplicate_stat, 'retained_original_stat': original_stat,
                     'remote_identity': item['remote_identity']})
    need(rows and len({r['duplicate']['path'] for r in rows}) == len(rows), 'No unique eligible part copies')
    return rows


def scan_rows(rows):
    return [{'path': row[key]['path'], 'stat': row[key + '_stat']} for row in rows for key in ('duplicate', 'retained_original')]


def verified_part(item, expected_stat, remote, health, journal):
    """No data writes: full hash, then last-read DONTNEED on that verified FD."""
    desc_shape(item)
    path = canonical(item['path'])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
    try:
        before = signature(os.fstat(fd))
        need(before == expected_stat and stat.S_ISREG(before['st_mode']) and before['st_nlink'] == 1,
             'Part identity changed at verified open')
        attributes = attrs(fd)
        need(os.getxattr(fd, 'user.library-file-id').decode() == remote['library_file_id']
             and os.getxattr(fd, 'user.library-file-version').decode() == str(remote['version']),
             'Actual remote identity/version xattrs differ')
        no_use = settled_no_use([{'path': str(path), 'stat': before}], health, journal, allowed_self_fd=fd)
        health(force=True)
        digest = hashlib.sha256()
        while data := os.read(fd, 1024 * 1024):
            digest.update(data)
            health()
        need(digest.hexdigest() == item['sha256'] and before['st_size'] == item['bytes']
             and signature(os.fstat(fd)) == before and file_stat(path) == before and attrs(fd) == attributes,
             'Part bytes/identity/xattrs changed during full read')
        journal.log('FINAL_CACHE_ADVICE_AFTER_VERIFIED_READ_INTENT', item=item, stat=before,
                    sha256=digest.hexdigest(), xattrs=attributes, no_use=no_use)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        need(signature(os.fstat(fd)) == before and file_stat(path) == before and attrs(fd) == attributes,
             'Part identity/xattrs changed after final advice')
        journal.log('VERIFIED_PART_AND_FINAL_ADVICE_COMPLETE', item=item, stat=before,
                    xattrs=attributes, final_payload_operation='POSIX_FADV_DONTNEED',
                    bytes_or_xattrs_written=False, resource_admission_claim=False)
        return attributes
    finally:
        os.close(fd)


def frozen_verify(state, health):
    path = SOURCE / 'operational/parameter_field_recovery04/durable_archive.py'
    spec = importlib.util.spec_from_file_location('_retirement06_frozen_archive', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    need(Path(module.__file__) == path, 'Wrong original ACK verifier')
    need(module.verify_ack(state['anchors']['stage_chain'][-1]['ack']['path'],
                           state['anchors']['stage_chain'][-1]['request'], heartbeat=health) == state['verified'],
         'Actual payload re-verification differs from supervisor acceptance')


def helper_chain(state):
    """Recheck actual accepted helper metadata without any helper invocation."""
    plan = read(state['work'] / 'READBACK_PLAN.json')
    saved = read(state['work'] / 'UPLOAD_VERIFIED.json')
    request_desc = state['anchors']['stage_chain'][-1]['request']
    need(plan.get('schema') == 'hepta.execution06.root-readback-helper-plan.1'
         and saved.get('schema') == 'hepta.execution06.root-upload-verified.1'
         and plan.get('request') == saved.get('request') == request_desc
         and len(plan.get('items', [])) == len(saved.get('items', [])) == len(state['ack']['items']),
         'Actual root upload/readback plan population differs')
    for name in ('upload_verified', 'materialize_arguments', 'materialize_receipt'):
        need(descriptor(plan[name]['path']) == plan[name], 'Readback plan metadata binding changed')
    need(plan['upload_verified'] == descriptor(state['work'] / 'UPLOAD_VERIFIED.json')
         and saved['upload_wait4'] == state['ack']['items'][0]['upload_wait4']
         and saved['upload_stdout'] == state['ack']['items'][0]['upload_receipt']
         and saved['upload_request'] == descriptor(state['work'] / 'UPLOAD_REQUEST.json')
         and saved['materialize_destination'] == str(state['work'] / 'readback'), 'Actual upload receipt binding differs')
    root_binding = bound(state['anchors']['root_binding'])
    upload_request = bound(saved['upload_request'])
    need(upload_request == {'uploads': [{'local_path': x['path'], 'purpose': 'create_library_file',
         'library_artifact_type': 'other', 'directory_id': root_binding['directory_id']} for x in state['request']['items']]},
         'Whole ordered upload input changed')
    uploaded_rows = bound(saved['upload_stdout']).get('results')
    need(isinstance(uploaded_rows, list) and len(uploaded_rows) == len(saved['items']), 'Whole ordered upload outcome differs')
    for item, uploaded in zip(saved['items'], uploaded_rows, strict=True):
        need(uploaded.get('local_path') == item['local']['path'] and uploaded.get('purpose') == 'create_library_file'
             and uploaded.get('status') == 'succeeded' and uploaded.get('local_metadata_applied') is True,
             'Upload outcome is not the complete actual success record')
        remote = {k: uploaded[k] for k in ('file_id', 'file_name', 'library_file_id')}
        remote['version'] = uploaded['current_version_number']
        need(remote == item['remote_identity'], 'Ordered actual upload identity differs')
    materialization = bound(plan['materialize_receipt'])
    need(materialization.get('isError') is not True, 'Materialization ToolResponse failed')
    payload = materialization.get('structuredContent')
    if payload is None:
        blocks = [x['text'] for x in materialization.get('content', []) if x.get('type') == 'text']
        need(len(blocks) == 1, 'Missing complete actual materialization ToolResponse')
        payload = json.loads(blocks[0])
    need(isinstance(payload, dict), 'Malformed materialization payload')
    payload = payload.get('result', payload)
    need(isinstance(payload, dict) and not payload.get('unavailable_items') and not payload.get('warnings')
         and not payload.get('partial_bindings') and isinstance(payload.get('transfers'), list),
         'Actual materialization is partial or uncertain')
    transfers = {x['library_file_id']: x for x in payload['transfers']}
    need(len(transfers) == len(payload['transfers']) == len(plan['items']), 'Actual materialization count differs')
    for item, job, uploaded in zip(state['ack']['items'], plan['items'], saved['items'], strict=True):
        need(job['local'] == uploaded['local'] == item['local']
             and job['remote_identity'] == uploaded['remote_identity'] == item['remote_identity']
             and job['transfer'] == item['complete_transfer_receipt']
             and job['wait4_path'] == item['readback_helper_wait4']['path']
             and job['expected_output_path'] == item['readback']['path']
             and item['readback_receipt'] == plan['materialize_receipt'], 'Readback helper identity/path chain differs')
        transfer = bound(job['transfer'])
        need(transfer == transfers[item['remote_identity']['library_file_id']], 'Actual transfer object changed')
        expected_action = 'apply-xattrs' if transfer.get('workspace_path') else 'materialize'
        expected_output = transfer.get('workspace_path') or str(state['work'] / 'readback' / transfer['file_name'])
        transferred = {k: transfer[k] for k in ('file_id', 'file_name', 'library_file_id')}
        transferred['version'] = transfer['current_version_number']
        need(expected_output == item['readback']['path'] and transferred == item['remote_identity'],
             'Actual materialization transfer differs')
        expected_readback = [HELPER_PYTHON, '-B', str(HELPERS / 'library_file_transfer.py'), expected_action, expected_output]
        need(job['helper_argv'] == expected_readback, 'Official readback helper argv differs')
        for key, expected_argv, expected_stdin, expected_stdout in (
                ('upload_wait4', [HELPER_PYTHON, '-B', str(HELPERS / 'library_upload.py')],
                 descriptor(state['work'] / 'UPLOAD_REQUEST.json'), item['upload_receipt']),
                ('readback_helper_wait4', expected_readback, job['transfer'], item['readback_helper_stdout'])):
            receipt = bound(item[key])
            need(receipt.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
                 and receipt.get('complete') is True and receipt.get('command_success') is True
                 and receipt.get('child', {}).get('exit_code') == receipt.get('child', {}).get('wait_status') == 0,
                 'Original measured helper did not close successfully')
            intent = bound(receipt['intent'])
            need(intent.get('schema') == 'hepta.execution04.root-engineering-intent.1'
                 and intent.get('argv') == expected_argv and intent.get('stdin') == expected_stdin
                 and intent.get('cwd') == str(OPS / 'empty_cwd') and intent.get('automatic_retry') is False
                 and receipt['stdout'] == expected_stdout, 'Measured helper intent/stdout differs')
            for value in (expected_stdin, receipt['stdout'], receipt['stderr']):
                need(descriptor(value['path']) == value, 'Actual measured helper support changed')
            need(not Path(item[key]['path']).with_name('FAILED.json').exists(), 'Helper failure marker exists')
        need(metadata_bytes(item['readback_helper_stdout']['path']).decode().strip() == item['readback']['path'],
             'Readback helper plain-text output path differs')


def protected_files(state, rows):
    helper_chain(state)
    excluded = {row[key]['path'] for row in rows for key in ('duplicate', 'retained_original')}
    roots = [state['directory'], state['work']]
    engineering = OPS / 'root_archive_io/_engineering'
    need(engineering.is_dir() and not engineering.is_symlink(), 'Expected completed root engineering receipt directory')
    prefix = state['directory'].name + '_'
    roots.extend(p for p in engineering.iterdir() if p.name.startswith(prefix))
    result = set()
    for root in roots:
        canonical(root)
        need(root.is_dir() and not root.is_symlink(), 'Unexpected root engineering scope')
        for path in root.rglob('*'):
            need(not path.is_symlink(), 'Symlink in preserved metadata closure')
            if path.is_file() and str(path) not in excluded:
                result.add(path)
            else:
                need(path.is_dir() or str(path) in excluded, 'Unsupported preserved evidence inode type')
    for item in state['ack']['items']:
        for key in ('upload_receipt', 'readback_receipt', 'upload_wait4', 'readback_helper_wait4',
                    'readback_helper_stdout', 'complete_transfer_receipt'):
            value = item[key]
            need(descriptor(value['path']) == value, 'Helper provenance changed')
            result.add(Path(value['path']))
        for key in ('upload_wait4', 'readback_helper_wait4'):
            record = bound(item[key])
            need(record.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
                 and record.get('complete') is True and record.get('command_success') is True
                 and record['child']['exit_code'] == 0, 'Original helper WAIT4 is not successful')
            for path in Path(item[key]['path']).parent.iterdir():
                need(not path.is_symlink(), 'Symlink in preserved helper evidence')
                if path.is_file():
                    result.add(path)
    return sorted(result)


def preservation_rows(state, rows):
    return [{'descriptor': descriptor(path), 'stat': file_stat(path)} for path in protected_files(state, rows)]


def check_preservation(state, rows, protected):
    need([str(p) for p in protected_files(state, rows)] == [p['descriptor']['path'] for p in protected],
         'Preserved file population changed')
    for row in protected:
        need(descriptor(row['descriptor']['path']) == row['descriptor']
             and file_stat(row['descriptor']['path']) == row['stat'], 'Preserved metadata bytes/identity changed')


@contextmanager
def stage_lock(directory, new=False):
    path = directory / 'OPERATION.lock'
    flags = os.O_RDWR | os.O_NOFOLLOW
    if new:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def fail_record(directory, error, removed):
    try:
        write_new(directory / 'FAILED.json', {'schema': 'hepta.execution06.readback-retirement-failure.1',
            'at_utc': utc(), 'error_type': type(error).__name__, 'message': str(error),
            'known_unlinks_returned': removed, 'automatic_retry': False,
            'manual_reconciliation_required': True,
            'journal_last_intent_may_have_committed_before_completion_record': True})
    except BaseException as receipt_error:
        error.add_note('Failure receipt also failed: ' + repr(receipt_error))


def prepare(args):
    need(args.stage in STAGES and isinstance(args.reason, str) and 1 <= len(args.reason) <= 4096,
         'Explicit fixed stage and concrete reason required')
    code = verify_code()
    config_desc, cfg, policy_desc = pipeline()
    health = Health(config_desc, cfg, policy_desc)
    state = accepted(args.stage, config_desc, health)
    need(state['anchors']['stage_chain'][-1]['request']['sha256'] == args.expected_request_sha256,
         'Externally selected REQUEST SHA differs')
    root = canonical(RETIREMENT_ROOT)
    root.mkdir(exist_ok=True)
    destination = root / args.stage
    reserve(root)
    destination.mkdir(exist_ok=False)
    fsync_dir(root)
    with stage_lock(destination, new=True):
        journal = Journal(destination / 'PREPARE_JOURNAL.jsonl')
        try:
            write_new(destination / 'PREPARE_INTENT.json', {'schema': 'hepta.execution06.readback-retirement-prepare-intent.1',
                'at_utc': utc(), 'stage': args.stage, 'code': code, 'anchors': state['anchors'],
                'health': state['health'], 'reason': args.reason, 'deletions_authorized_here': 0, 'automatic_retry': False})
            rows = row_scope(state)
            initial_scan = settled_no_use(scan_rows(rows), health, journal)
            frozen_verify(state, health)
            # The original verifier may read with relatime. Capture current stat
            # now; all subsequent archive reads use O_NOATIME and end in advice.
            rows = row_scope(state)
            for row in rows:
                for key in ('retained_original', 'duplicate'):
                    row[key + '_xattrs'] = verified_part(row[key], row[key + '_stat'], row['remote_identity'], health, journal)
            protected = preservation_rows(state, rows)
            final_scan = settled_no_use(scan_rows(rows), health, journal)
            fresh = accepted(args.stage, config_desc, health)
            need(fresh['anchors'] == state['anchors'], 'Accepted immutable anchors changed')
            value = {'schema': 'hepta.execution06.accepted-readback-part-retirement-plan.1',
                     'at_utc': utc(), 'execution_episode': EPISODE, 'stage': args.stage, 'reason': args.reason,
                     'code': code, 'anchors': state['anchors'], 'health': state['health'],
                     'rows': rows, 'preserved_files': protected, 'initial_no_use': initial_scan, 'final_no_use': final_scan,
                     'status_at_prepare': fresh['status_observed'],
                     'allocated_bytes_upper_bound': sum(row['duplicate_stat']['st_blocks'] * 512 for row in rows),
                     'deletion_executed': False, 'automatic_retry': False,
                     'only_scope': 'accepted independent readback/part-NNNN.tar.gz duplicate bytes',
                     'later_manual_verify_ack_requires_real_remote_rematerialization': True,
                     'scientific_or_resource_admission_claim': False}
            plan = write_new(destination / 'PLAN.json', value)
            journal.log('PREPARATION_COMPLETE', plan=plan, eligible_parts=len(rows), deletions=0)
            print(json.dumps({'plan': plan, 'eligible_parts': len(rows), 'deletions': 0}, sort_keys=True))
            return plan
        except BaseException as error:
            fail_record(destination, error, [])
            raise
        finally:
            journal.close()


def unlink_once(row, parent_fd, parent_path, health, journal):
    """A single fixed-dirfd unlink, never retried after ambiguous completion."""
    duplicate = Path(row['duplicate']['path'])
    health(force=True)
    need(canonical(parent_path) == duplicate.parent, 'Readback parent changed')
    parent_now, parent_open = parent_path.stat(), os.fstat(parent_fd)
    need((parent_now.st_dev, parent_now.st_ino) == (parent_open.st_dev, parent_open.st_ino), 'Readback parent inode changed')
    observed = signature(os.stat(duplicate.name, dir_fd=parent_fd, follow_symlinks=False))
    need(observed == row['duplicate_stat'] and observed['st_nlink'] == 1, 'Duplicate changed immediately before unlink')
    # The prior full read proved bytes and all xattrs. Recheck source identity and
    # current xattrs immediately before committing this one unlink.
    for key in ('retained_original', 'duplicate'):
        path = Path(row[key]['path'])
        need(file_stat(path) == row[key + '_stat'], 'Retained source or duplicate identity changed')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME)
        try:
            need(signature(os.fstat(fd)) == row[key + '_stat'] and attrs(fd) == row[key + '_xattrs'], 'Part xattrs changed before unlink')
        finally:
            os.close(fd)
    scan = settled_no_use(scan_rows([row]), health, journal)
    health(force=True)
    need(signature(os.stat(duplicate.name, dir_fd=parent_fd, follow_symlinks=False)) == row['duplicate_stat']
         and file_stat(row['retained_original']['path']) == row['retained_original_stat'],
         'Source or duplicate changed after no-use observation')
    journal.log('UNLINK_INTENT', duplicate=row['duplicate'], stat=row['duplicate_stat'],
                retained_original=row['retained_original'], no_use=scan,
                fixed_parent={'path': str(parent_path), 'dev': parent_open.st_dev, 'ino': parent_open.st_ino})
    os.unlink(duplicate.name, dir_fd=parent_fd)
    # Record returned unlink before another fallible observation. A crash in
    # either interval still requires reconciliation of the last fsynced intent.
    journal.log('UNLINK_RETURNED', duplicate=row['duplicate'])
    os.fsync(parent_fd)
    need(not os.path.lexists(duplicate), 'Retired path reappeared; do not unlink it again')
    journal.log('UNLINK_DURABLE_AND_ABSENT', duplicate=row['duplicate'], immediately_absent=True)


def execute(args):
    need(args.execute is True, 'Explicit --execute is required for deletion')
    path = canonical(args.plan)
    need(path.name == 'PLAN.json' and path.parent.parent == RETIREMENT_ROOT and path.parent.name in STAGES,
         'Plan is outside the one-stage retirement root')
    item = descriptor(path)
    need(item['sha256'] == args.expected_plan_sha256, 'Externally selected plan SHA differs')
    plan = bound(item)
    code = verify_code()
    need(plan.get('schema') == 'hepta.execution06.accepted-readback-part-retirement-plan.1'
         and plan.get('execution_episode') == EPISODE and plan.get('stage') == path.parent.name
         and plan.get('code') == code and plan.get('deletion_executed') is False
         and plan.get('automatic_retry') is False, 'Plan/code identity differs')
    need(not (path.parent / 'FAILED.json').exists(), 'Preparation failed; no automatic reuse')
    with stage_lock(path.parent):
        directory = path.parent / 'execution'
        directory.mkdir(exist_ok=False)
        fsync_dir(path.parent)
        journal = Journal(directory / 'JOURNAL.jsonl')
        removed, started, cpu = [], time.monotonic(), time.process_time()
        try:
            before = reserve(directory)
            write_new(directory / 'INTENT.json', {'schema': 'hepta.execution06.readback-retirement-execute-intent.1',
                'at_utc': utc(), 'plan': item, 'code': code, 'automatic_retry': False, 'before': before})
            config_desc, cfg, policy_desc = pipeline()
            health = Health(config_desc, cfg, policy_desc)
            state = accepted(plan['stage'], config_desc, health)
            need(state['anchors'] == plan['anchors'] and state['health']['start_policy'] == plan['health']['start_policy']
                 and state['health']['supervisor_identity'] == plan['health']['supervisor_identity'], 'Original accepted anchors/owner changed')
            rows = row_scope(state)
            need(len(rows) == len(plan['rows']), 'Selected copy population changed')
            for row, saved in zip(rows, plan['rows'], strict=True):
                need(all(saved.get(k) == v for k, v in row.items()), 'Selected exact part identity changed since plan')
                for key in ('retained_original', 'duplicate'):
                    attributes = verified_part(row[key], row[key + '_stat'], row['remote_identity'], health, journal)
                    need(attributes == saved[key + '_xattrs'], 'Part xattrs differ from selected plan')
                    row[key + '_xattrs'] = attributes
            check_preservation(state, rows, plan['preserved_files'])
            journal.log('ALL_PRECOMMIT_CHECKS_COMPLETE', no_use=settled_no_use(scan_rows(rows), health, journal))
            parent_path = state['work'] / 'readback'
            parent_fd = os.open(canonical(parent_path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for row in rows:
                    fresh = accepted(plan['stage'], config_desc, health)
                    need(fresh['anchors'] == plan['anchors'], 'Accepted anchors changed before mutation')
                    unlink_once(row, parent_fd, parent_path, health, journal)
                    removed.append(row['duplicate'])
            finally:
                os.close(parent_fd)
            check_preservation(state, rows, plan['preserved_files'])
            for row in rows:
                need(verified_part(row['retained_original'], row['retained_original_stat'], row['remote_identity'], health, journal)
                     == row['retained_original_xattrs'], 'Retained source changed after retirement')
            health(force=True)
            need(verify_code() == code, 'Frozen or external code changed during operation')
            after = reserve(directory)
            need(all(not os.path.lexists(row['path']) for row in removed), 'A retired path reappeared; reconcile without another unlink')
            result = {'schema': 'hepta.execution06.accepted-readback-part-retirement-result.1',
                'at_utc': utc(), 'complete': True, 'plan': item, 'code': code, 'count': len(removed), 'removed': removed,
                'retained_source_parts_full_sha_and_xattrs_verified_after': True,
                'all_small_metadata_bytes_and_identity_preserved': True,
                'all_last_archive_hash_reads_followed_by_same_fd_DONTNEED': True,
                'source_raw_cas_ack_and_remote_mutations': 0, 'all_selected_duplicate_paths_absent': True,
                'before': before, 'after': after, 'shared_space_delta_not_exclusively_attributed': True,
                'own_cpu_seconds': time.process_time() - cpu, 'wall_seconds': time.monotonic() - started,
                'cost_scope': 'This process only; retain enclosing actual recovery04 external_step WAIT4.',
                'automatic_retry': False, 'snapshot_not_continuous_kernel_lease': True,
                'later_manual_verify_ack_requires_real_remote_rematerialization': True,
                'scientific_completion_or_resource_admission_claim': False}
            result_desc = write_new(directory / 'RESULT.json', result)
            journal.log('RETIREMENT_COMPLETE', result=result_desc)
            print(json.dumps({'result': result_desc, 'removed_count': len(removed)}, sort_keys=True))
            return result_desc
        except BaseException as error:
            fail_record(directory, error, removed)
            raise
        finally:
            journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    pre = sub.add_parser('prepare')
    pre.add_argument('--stage', choices=STAGES, required=True)
    pre.add_argument('--expected-request-sha256', required=True)
    pre.add_argument('--reason', required=True)
    pre.set_defaults(run=prepare)
    exe = sub.add_parser('execute')
    exe.add_argument('--plan', required=True)
    exe.add_argument('--expected-plan-sha256', required=True)
    exe.add_argument('--execute', action='store_true', required=True)
    exe.set_defaults(run=execute)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
