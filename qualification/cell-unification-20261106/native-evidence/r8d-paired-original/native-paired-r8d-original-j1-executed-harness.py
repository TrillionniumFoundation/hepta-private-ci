from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time


ROOT = Path('/home/alex/work/hepta-cell-unified-20261106-a')
SOURCE = ROOT / 'source'
EVIDENCE = ROOT / 'evidence'
STEM = 'native-paired-r8d-original-j1'
TREE = '6d88ca9c8964669a408d8549efaeff7b94d68674'
EXPECTED_LOCK = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
TEST_NAMES = {
    'five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash',
    'two_real_pairs_restart_one_without_peer_pid_churn',
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def descendants(pid):
    found = set()
    pending = [pid]
    while pending:
        item = pending.pop()
        if item in found:
            continue
        found.add(item)
        try:
            children = Path(f'/proc/{item}/task/{item}/children').read_text().split()
            pending.extend(int(child) for child in children)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return found


def process_sample(pid):
    base = Path(f'/proc/{pid}')
    try:
        raw = (base / 'stat').read_text()
        fields = raw[raw.rindex(')') + 2:].split()
        io = {}
        for line in (base / 'io').read_text().splitlines():
            key, value = line.split(':', 1)
            if key in {'rchar', 'wchar', 'syscr', 'syscw', 'read_bytes', 'write_bytes', 'cancelled_write_bytes'}:
                io[key] = int(value.strip())
        fd_paths = []
        for fd in (base / 'fd').iterdir():
            try:
                target = os.readlink(fd)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if target.startswith('/tmp/hsup-pairs-') or target.startswith(str(ROOT / 'target')):
                fd_paths.append({'fd': int(fd.name), 'path': target})
        return {
            'pid': pid,
            'observed_unix': time.time(),
            'state': fields[0],
            'user_ticks': int(fields[11]),
            'system_ticks': int(fields[12]),
            'child_user_ticks': int(fields[13]),
            'child_system_ticks': int(fields[14]),
            'start_ticks': int(fields[19]),
            'wchan': (base / 'wchan').read_text().strip(),
            'io': io,
            'fd_paths': sorted(fd_paths, key=lambda x: x['fd']),
        }
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def fixture_stages(roots):
    result = []
    for root in sorted(roots):
        directory = Path(root)
        entries = []
        if not directory.exists():
            result.append({'root': root, 'exists': False})
            continue
        for walk_root, dirs, files in os.walk(directory, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                path = Path(walk_root) / name
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                entries.append({
                    'path': str(path.relative_to(directory)),
                    'bytes': info.st_size,
                    'kind': 'regular' if stat.S_ISREG(info.st_mode) else 'socket' if stat.S_ISSOCK(info.st_mode) else 'other',
                    'mtime_unix': info.st_mtime,
                })
                if len(entries) >= 1000:
                    break
            if len(entries) >= 1000:
                break
        result.append({'root': root, 'exists': True, 'entries': entries, 'bounded_at_1000_entries': len(entries) >= 1000})
    return result


assert subprocess.check_output(['git', 'write-tree'], cwd=SOURCE, text=True).strip() == TREE
subprocess.run(['git', 'diff', '--quiet'], cwd=SOURCE, check=True)
assert sha(SOURCE / 'codex-rs/Cargo.lock') == EXPECTED_LOCK
env = os.environ.copy()
assert env.get('CARGO_PROFILE_TEST_DEBUG') is None
assert env.get('CARGO_PROFILE_DEV_DEBUG') is None
env.update({
    'RUSTUP_TOOLCHAIN': '1.96.0',
    'CARGO_BUILD_JOBS': '2',
    'CARGO_TARGET_DIR': str(ROOT / 'target'),
    'CARGO_NET_GIT_FETCH_WITH_CLI': 'true',
    'NEXTEST_TEST_THREADS': '2',
    'PYTHONDONTWRITEBYTECODE': '1',
})
env['PATH'] = str(ROOT / 'bin') + ':' + str(Path.home() / '.cargo/bin') + ':' + env['PATH']
env.update(json.loads((EVIDENCE / 'agentd-prerequisite-env.json').read_text()))
command = ['just', 'test', '--locked', '-p', 'codex-hepta-supervisor', '--test', 'paired_process_product', '--retries', '0', '-j', '1']
manifest = {
    'source_tree': TREE,
    'source_manifest': 'native-candidate-r8-source.json',
    'command': command,
    'kind': 'diagnostic_original_source_profile_single_thread',
    'purpose': 'Distinguish original paired fixture CPU/file verification and concurrency cost without changing source, original 60-second nextest deadline, permissions, assertions or filters.',
    'profile': {key: env.get(key) for key in ['RUSTUP_TOOLCHAIN', 'CARGO_BUILD_JOBS', 'CARGO_TARGET_DIR', 'NEXTEST_TEST_THREADS', 'NEXTEST_PROFILE', 'CARGO_PROFILE_TEST_DEBUG', 'CARGO_PROFILE_DEV_DEBUG', 'CARGO_INCREMENTAL']},
    'profile_source_files': {path: sha(SOURCE / path) for path in ['codex-rs/Cargo.toml', 'codex-rs/.config/nextest.toml', 'justfile', 'scripts/run-nextest.py', 'scripts/just-shell.py']},
    'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
    'no_network_probe_or_environment_dump': True,
    'only_own_subprocess_descendants_observed': True,
}
(EVIDENCE / (STEM + '-source.json')).write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'phase': 'paired-original-j1-start', **manifest}), flush=True)
observations = []
tracked = {}
binaries = {}
start = time.time()
with (EVIDENCE / (STEM + '.log')).open('wb') as output:
    proc = subprocess.Popen(['/usr/bin/time', '-v', '-o', str(EVIDENCE / (STEM + '-resources.txt')), *command], cwd=SOURCE / 'codex-rs', env=env, stdout=output, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        now = time.monotonic()
        for pid in descendants(proc.pid):
            if pid in tracked:
                continue
            try:
                exe = os.readlink(f'/proc/{pid}/exe')
                if not exe.startswith(str(ROOT / 'target/debug/deps/paired_process_product-')):
                    continue
                argv = Path(f'/proc/{pid}/cmdline').read_bytes().decode('utf-8', 'replace').split('\0')
                matched = [arg for arg in argv if arg in TEST_NAMES]
                if not matched or '--ignored' in argv:
                    continue
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            tracked[pid] = {'name': matched[0], 'first_seen_monotonic': now, 'sampled': set(), 'roots': set(), 'exe': exe, 'last': None, 'done': False}
            binary = Path(exe)
            info = binary.stat()
            binaries[exe] = {'path': exe, 'bytes': info.st_size, 'mtime_unix': info.st_mtime}
            print(json.dumps({'phase': 'paired-test-seen', 'pid': pid, 'name': matched[0], 'binary': binaries[exe]}), flush=True)
        for pid, tracked_test in tracked.items():
            if tracked_test['done']:
                continue
            sample = process_sample(pid)
            if sample is None:
                tracked_test['done'] = True
                observations.append({'name': tracked_test['name'], 'phase': 'last_observed_before_exit', 'sample': tracked_test['last'], 'fixture_stages': fixture_stages(tracked_test['roots'])})
                continue
            age = now - tracked_test['first_seen_monotonic']
            sample['age_since_first_seen_seconds'] = age
            for item in sample['fd_paths']:
                matched = re.match(r'^(/tmp/hsup-pairs-[^/]+)(?:/|$)', item['path'])
                if matched:
                    tracked_test['roots'].add(matched.group(1))
            tracked_test['last'] = sample
            for boundary in [0, 10, 30, 55]:
                if age >= boundary and boundary not in tracked_test['sampled']:
                    tracked_test['sampled'].add(boundary)
                    observation = {'name': tracked_test['name'], 'phase': f'at_{boundary}_seconds', 'sample': sample, 'fixture_stages': fixture_stages(tracked_test['roots'])}
                    observations.append(observation)
                    print(json.dumps({'phase': 'paired-test-sample', 'name': tracked_test['name'], 'boundary_seconds': boundary, 'pid': pid, 'user_ticks': sample['user_ticks'], 'system_ticks': sample['system_ticks'], 'io': sample['io'], 'wchan': sample['wchan'], 'fixture_roots': sorted(tracked_test['roots'])}), flush=True)
        time.sleep(0.5)
    code = proc.wait()
end = time.time()
for tracked_test in tracked.values():
    if not tracked_test['done']:
        observations.append({'name': tracked_test['name'], 'phase': 'last_observed_before_gate_exit', 'sample': tracked_test['last'], 'fixture_stages': fixture_stages(tracked_test['roots'])})
for binary in binaries.values():
    binary['sha256_after_gate'] = sha(Path(binary['path']))
(EVIDENCE / (STEM + '-observations.json')).write_text(json.dumps({'source_tree': TREE, 'binary_inventory': list(binaries.values()), 'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'), 'observations': observations}, indent=2) + '\n')
content = (EVIDENCE / (STEM + '.log')).read_text()
receipt = {
    'command': command,
    'kind': manifest['kind'],
    'staged_tree': TREE,
    'source_manifest': STEM + '-source.json',
    'observations': STEM + '-observations.json',
    'start_unix': start,
    'end_unix': end,
    'elapsed_seconds': end - start,
    'exit_code': code,
    'log_sha256': sha(EVIDENCE / (STEM + '.log')),
    'summaries': [line for line in content.splitlines() if 'Summary [' in line],
    'disk_after': shutil.disk_usage(ROOT)._asdict(),
    'no_source_changes': subprocess.check_output(['git', 'write-tree'], cwd=SOURCE, text=True).strip() == TREE,
}
subprocess.run(['git', 'diff', '--quiet'], cwd=SOURCE, check=True)
(EVIDENCE / (STEM + '-receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt), flush=True)
print(content[-16000:], flush=True)
raise SystemExit(code)
