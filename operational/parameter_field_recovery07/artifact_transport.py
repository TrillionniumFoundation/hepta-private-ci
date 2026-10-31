"""GitHub Actions archive barriers, with literal readback and owned-child wait4."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import signal
import stat
import time
import zipfile

LABELS = ('A-17', 'A-29', 'A-43', 'C', 'B-17', 'B-29', 'B-43', 'W',
          'R-17', 'R-29', 'R-43', 'A_endpoint', 'B_endpoint', 'C_endpoint',
          'controller', 'analysis', 'final_closure')
MAX_BYTES = 2 * 1024 ** 3
MAX_FILES = 20000
TRANSPORT_TIMEOUT_SECONDS = 900
FORBIDDEN = {'.git', '.ssh', '.aws', '.env', '.netrc', 'credentials', 'credentials.json',
             'id_rsa', 'id_ed25519', 'token', 'secrets', 'authorization'}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def write_json(path, value):
    with path.open('xb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def descriptor(path):
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
            size += len(block)
    return {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()}


def logical_path(value):
    path = PurePosixPath(value)
    if (not value or len(value) > 4096 or path.is_absolute() or str(path) != value or '\\' in value
            or any(p in ('.', '..') or p.startswith('.') or p.lower() in FORBIDDEN for p in path.parts)):
        raise ValueError('Unsafe logical archive path')
    return path


def validate_binding(label, binding, terminal=False, identity=None):
    sequence = 18 if terminal else LABELS.index(label) + 1
    expected = {'execution_episode', 'sequence', 'label', 'pipeline_config', 'completed_jobs', 'previous_ack'}
    if not expected.issubset(binding) or len(canonical(binding)) > 1024 * 1024:
        raise ValueError('Incomplete or oversized archive binding')
    if (binding['execution_episode'] != 'execution07_actions_20261031'
            or binding['sequence'] != sequence or binding['label'] != label
            or binding['completed_jobs'] != list(LABELS[:min(sequence, 14)])):
        raise ValueError('Wrong archive sequence or episode')
    for key in ('pipeline_config', 'previous_ack'):
        item = binding[key]
        if item is None and key == 'previous_ack' and sequence == 1:
            continue
        if not isinstance(item, dict) or descriptor(Path(item['path'])) != item:
            raise ValueError('Binding descriptor does not match literal file bytes')
    previous = binding['previous_ack']
    if sequence == 1 and previous is not None:
        raise ValueError('First archive cannot inherit an ACK')
    if sequence > 1:
        prior = json.loads(Path(previous['path']).read_text())
        if (prior['schema'] != 'hepta.github-actions-archive-ack.v1'
                or prior['binding']['sequence'] != sequence - 1
                or prior['binding']['label'] != LABELS[sequence - 2]
                or prior['binding']['completed_jobs'] != list(LABELS[:min(sequence - 1, 14)])
                or prior['binding']['pipeline_config'] != binding['pipeline_config']
                or prior['binding']['execution_episode'] != binding['execution_episode']
                or identity is None or prior['identity'] != identity):
            raise ValueError('Archive ACK ancestry mismatch')


def measured_client(operation, request, directory, health_check=None):
    request_path, result_path = directory / f'{operation}.request.json', directory / f'{operation}.result.json'
    write_json(request_path, request)
    node = os.environ.get('HEPTA_ARTIFACT_NODE') or shutil.which('node')
    if node is None:
        raise RuntimeError('Node runtime is not available')
    if health_check:
        health_check()
    start, started = time.monotonic(), time.time()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            null = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null, fd)
            os.execv(node, [node, str(Path(__file__).with_name('artifact_client.mjs')), str(request_path), str(result_path)])
        except BaseException:
            os._exit(127)
    timed_out, interrupted = False, None
    pidfd = None
    try:
        if hasattr(os, 'pidfd_open'):
            pidfd = os.pidfd_open(pid)
        while True:
            if health_check:
                health_check()
            waited, status, usage = os.wait4(pid, os.WNOHANG)
            if waited:
                break
            if time.monotonic() - start >= TRANSPORT_TIMEOUT_SECONDS:
                timed_out = True
                raise TimeoutError('Owned transport deadline')
            time.sleep(0.05)
    except BaseException as error:
        interrupted = error
        # This direct child remains unreaped, so its PID cannot be reused. Only
        # target a process group after confirming this child is its leader.
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            elif pidfd is not None and hasattr(signal, 'pidfd_send_signal'):
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        waited, status, usage = os.wait4(pid, 0)
    finally:
        if pidfd is not None:
            os.close(pidfd)
    cost = {'operation': operation, 'pid': pid, 'waited_pid': waited, 'started_at_unix': started,
            'wall_seconds': time.monotonic() - start, 'user_cpu_seconds': usage.ru_utime,
            'system_cpu_seconds': usage.ru_stime, 'peak_rss_bytes': usage.ru_maxrss * 1024,
            'exit_code': os.waitstatus_to_exitcode(status), 'timed_out': timed_out,
            'timeout_seconds': TRANSPORT_TIMEOUT_SECONDS, 'measurement': 'os.wait4 direct owned child',
            'interruption_type': type(interrupted).__name__ if interrupted else None}
    write_json(directory / f'{operation}.wait4.json', cost)
    if interrupted is not None:
        raise interrupted
    if timed_out or cost['exit_code'] != 0 or not result_path.is_file():
        raise RuntimeError(f'{operation} did not complete; no retry or ACK issued')
    result = json.loads(result_path.read_text())
    if result.get('ok') is not True or result.get('operation') != operation:
        raise RuntimeError(f'{operation} result invalid; no retry or ACK issued')
    return result['result'], cost


def snapshot(source, target, health_check=None):
    if health_check:
        health_check()
    if not source.is_absolute() or source != source.resolve(strict=True) or any(p.lower() in FORBIDDEN for p in source.parts):
        raise ValueError('Source must be an explicit canonical ordinary file')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    digest, size = hashlib.sha256(), 0
    with os.fdopen(fd, 'rb') as incoming, target.open('xb') as outgoing:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Archive input is not a regular file')
        for block in iter(lambda: incoming.read(1024 * 1024), b''):
            outgoing.write(block)
            digest.update(block)
            size += len(block)
            if health_check and size % (16 * 1024 * 1024) == 0:
                health_check()
            if size > MAX_BYTES:
                raise ValueError('Archive member exceeds the transport bound')
        outgoing.flush()
        os.fsync(outgoing.fileno())
        after = os.fstat(incoming.fileno())
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or size != before.st_size or source.stat() != after):
        raise ValueError('Archive input changed while copying')
    return {'bytes': size, 'sha256': digest.hexdigest()}


def readback(zip_path, upload_root, download_root, manifest, paths, health_check=None):
    expected = {'MANIFEST.json': descriptor(upload_root / 'MANIFEST.json')}
    expected.update({'payload/' + x['path']: x for x in manifest['files']})
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        names = [x.filename for x in members if not x.is_dir()]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('Downloaded archive has unexpected or duplicate files')
        if sum(x.file_size for x in members) > MAX_BYTES + 2 * 1024 * 1024:
            raise ValueError('Downloaded archive exceeds the transport bound')
        for member in members:
            if health_check:
                health_check()
            logical_path(member.filename.rstrip('/'))
            if stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                raise ValueError('Downloaded archive contains a link or encrypted member')
            if member.is_dir():
                if not any(x.startswith(member.filename) for x in expected):
                    raise ValueError('Unexpected directory in downloaded archive')
                continue
            target = download_root / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            actual = descriptor(target)
            if any(actual[k] != expected[member.filename][k] for k in ('bytes', 'sha256')):
                raise ValueError('Literal archive readback mismatch')
    comparisons = []
    for item in manifest['files']:
        if health_check:
            health_check()
        source = paths[item['path']]
        staged, returned = upload_root / 'payload' / item['path'], download_root / 'payload' / item['path']
        identities = [(x.stat().st_dev, x.stat().st_ino) for x in (source, staged, returned)]
        source_bytes = descriptor(source)
        if len(set(identities)) != 3 or any(source_bytes[k] != item[k] for k in ('bytes', 'sha256')):
            raise ValueError('Readback not independent or original bytes changed')
        comparisons.append({'path': item['path'], 'source_device_inode': identities[0],
                            'staged_device_inode': identities[1], 'readback_device_inode': identities[2]})
    return comparisons


def _archive(label, paths, binding, output_dir, terminal, health_check):
    started, parent_start = time.monotonic(), resource.getrusage(resource.RUSAGE_SELF)
    if not paths or len(paths) > MAX_FILES:
        raise ValueError('Archive requires a bounded explicit file map')
    identity = {key: os.environ.get(env) for key, env in
                [('repository', 'GITHUB_REPOSITORY'), ('run_id', 'GITHUB_RUN_ID'),
                 ('run_attempt', 'GITHUB_RUN_ATTEMPT'), ('head_sha', 'GITHUB_SHA'), ('job', 'GITHUB_JOB')]}
    if (not all(identity.values()) or not re.fullmatch('[0-9a-f]{40}', identity['head_sha'])
            or not identity['run_id'].isdigit() or not identity['run_attempt'].isdigit()
            or not os.environ.get('ACTIONS_RUNTIME_TOKEN') or not os.environ.get('ACTIONS_RESULTS_URL')):
        raise RuntimeError('Actual Actions identity and runtime credentials are required')
    validate_binding(label, binding, terminal, identity)
    output_dir = Path(output_dir).absolute()
    output_dir.mkdir(parents=True, exist_ok=False)
    upload_root, raw_root, download_root = [output_dir / x for x in ('upload', 'download_raw', 'readback')]
    for root in (upload_root, raw_root, download_root):
        root.mkdir()
    files, sources, total = [], {}, 0
    for relative, source in sorted(paths.items()):
        logical_path(relative)
        source = Path(source)
        item = {'path': relative, **snapshot(source, upload_root / 'payload' / relative, health_check)}
        total += item['bytes']
        if total > MAX_BYTES:
            raise ValueError('Archive exceeds the transport bound')
        files.append(item)
        sources[relative] = source
    manifest = {'schema': 'hepta.github-actions-archive-manifest.v1', 'binding': binding,
                'identity': identity, 'files': files, 'payload_bytes': total, 'file_count': len(files)}
    if len(canonical(manifest)) > 2 * 1024 * 1024:
        raise ValueError('Archive manifest exceeds the transport bound')
    manifest_path = upload_root / 'MANIFEST.json'
    write_json(manifest_path, manifest)
    name = f"hepta-r07-{identity['run_id']}-{identity['run_attempt']}-{label}"
    uploaded, upload_cost = measured_client('upload', {'operation': 'upload', 'name': name,
        'root': str(upload_root), 'files': [str(manifest_path)] + [str(upload_root / 'payload' / f['path']) for f in files]}, output_dir, health_check)
    downloaded, download_cost = measured_client('download', {'operation': 'download', 'id': uploaded['id'],
        'sha256': uploaded['sha256'], 'destination': str(raw_root)}, output_dir, health_check)
    archives = list(raw_root.iterdir())
    if len(archives) != 1 or archives[0].is_symlink() or not archives[0].is_file():
        raise ValueError('Expected one independently downloaded raw archive')
    archive = descriptor(archives[0])
    if archive['sha256'] != uploaded['sha256'] or archive['bytes'] != uploaded['bytes']:
        raise ValueError('Downloaded raw bytes do not match finalized artifact')
    comparisons = readback(archives[0], upload_root, download_root, manifest, sources, health_check)
    if health_check:
        health_check()
    parent_end = resource.getrusage(resource.RUSAGE_SELF)
    child_cpu = sum(x['user_cpu_seconds'] + x['system_cpu_seconds'] for x in (upload_cost, download_cost))
    parent_cpu = parent_end.ru_utime + parent_end.ru_stime - parent_start.ru_utime - parent_start.ru_stime
    cost = {'wall_seconds': time.monotonic() - started, 'cpu_seconds': child_cpu + parent_cpu,
            'transport_child_cpu_seconds': child_cpu, 'parent_self_cpu_delta_seconds': parent_cpu,
            'transport_child_peak_rss_bytes': max(upload_cost['peak_rss_bytes'], download_cost['peak_rss_bytes']),
            'parent_cumulative_peak_rss_bytes': parent_end.ru_maxrss * 1024,
            'scope': 'This synchronous barrier self CPU plus direct owned transport children; already included when the supervisor is measured inclusively; do not add twice.',
            'wait4': [upload_cost, download_cost]}
    ack = {'schema': 'hepta.github-actions-terminal-ack.v1' if terminal else 'hepta.github-actions-archive-ack.v1',
           'binding': binding, 'identity': identity, 'artifact': uploaded,
           'manifest': descriptor(manifest_path), 'logical_files': files, 'items_verified': len(files),
           'readback': {'raw_archive': archive, 'client': downloaded, 'all_sha256_and_bytes_match': True,
                        'independent_device_inodes': comparisons}, 'cost': cost,
           'storage_scope': 'GitHub Actions immutable artifact ID until provider expiry/deletion; not a Library receipt.',
           'acknowledged_at_unix': time.time()}
    ack_path = output_dir / 'ACK.json'
    write_json(ack_path, ack)
    return {'ack': descriptor(ack_path), 'binding': binding, 'items_verified': len(files),
            'manifest': descriptor(manifest_path), 'cost': cost, 'logical_files': files,
            'artifact': uploaded}


def archive_barrier(label, paths, binding, output_dir, *, health_check=None):
    """Produce one of 17 ACKs only after actual provider and literal readback proof."""
    if label not in LABELS:
        raise ValueError('Unknown registered archive barrier')
    return archive_attempt(label, paths, binding, output_dir, False, health_check)


def archive_terminal_metadata(paths, binding, output_dir, *, health_check=None):
    """Archive later terminal receipts separately; never pretend they were in stage 17."""
    return archive_attempt('terminal_metadata', paths, binding, output_dir, True, health_check)


def archive_attempt(label, paths, binding, output_dir, terminal, health_check):
    directory, existed = Path(output_dir).absolute(), Path(output_dir).exists()
    try:
        return _archive(label, paths, binding, directory, terminal, health_check)
    except BaseException as error:
        if not existed and directory.is_dir() and not (directory / 'FAILED.json').exists():
            receipts = [descriptor(directory / f'{name}.wait4.json') for name in ('upload', 'download')
                        if (directory / f'{name}.wait4.json').is_file()]
            write_json(directory / 'FAILED.json', {'schema': 'hepta.github-actions-archive-failure.v1',
                       'label': label, 'error_type': type(error).__name__, 'wait4_receipts': receipts,
                       'no_automatic_retry': True, 'ack_issued': False})
        raise
