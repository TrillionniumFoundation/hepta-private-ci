import fcntl
import hashlib
import json
import os
import resource
import subprocess
import time
import traceback
from pathlib import Path

ROOT = Path('/Users/qianqi/work/hepta-joint-mac-fixtures-20261120-e9e051')
SOURCE = ROOT / 'source'
OUT = ROOT / 'fixture-native-5'
HEAD = '238fc48402f786db3d7f2a80b0abad6c0e5322bb'
PAYLOAD_SHA = 'fe4fced4cf0b7ea6005ecdef212b19a9624c5be7d9179be282c9cd21a6120067'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE)


def inventory():
    rows = []
    tagged = {r[2:]: r[0] for r in git('ls-files', '-v', '-z').decode().split('\0') if r}
    for record in git('ls-files', '--stage', '-z').decode().split('\0'):
        if not record:
            continue
        fields, name = record.split('\t', 1)
        mode, blob, stage = fields.split()
        assert stage == '0'
        path = SOURCE / name
        if not path.exists() and not path.is_symlink():
            assert tagged[name] == 'S', ('missing non-sparse tracked input', name)
            rows.append({'path': name, 'kind': 'unmaterialized_skip_worktree', 'git_mode': mode, 'git_blob': blob})
            continue
        if path.is_symlink():
            raw = os.readlink(path).encode()
            kind = 'symlink'
        else:
            raw = path.read_bytes()
            kind = 'regular'
        rows.append({'path': name, 'kind': kind, 'git_mode': mode, 'git_blob': blob, 'bytes': len(raw), 'sha256': sha(raw)})
    return rows


OUT.mkdir(exist_ok=False)
lock = (ROOT / 'fixture-native.lock').open('a+b')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
payload_raw = (ROOT / 'candidate_payload.json').read_bytes()
assert sha(payload_raw) == PAYLOAD_SHA
payload = json.loads(payload_raw)
assert payload['source'] == HEAD
assert git('rev-parse', 'HEAD').decode().strip() == HEAD
assert set(git('diff', '--name-only').decode().splitlines()) == {r['path'] for r in payload['files']}
prior_result = json.loads((ROOT / 'fixture-native-2/RESULT.json').read_text())
assert sha((ROOT / 'fixture-native-2/RESULT.json').read_bytes()) == '14ed67d3cd60d9b985d051f415902b2955ba69c46be70c32c4881d9960677a0c'
assert prior_result['exit_code'] == 1 and prior_result['source_unchanged_during_native']
assert prior_result['stages'][0]['name'] == 'native-project' and prior_result['stages'][0]['exit_code'] == 101
assert json.loads((ROOT / 'prepare-1/RESULT.json').read_text())['exit_code'] == 0
observed_raw = (ROOT / 'fixture-native-3/INTERRUPTION_OBSERVATION.json').read_bytes()
assert sha(observed_raw) == 'fd53ea215f8f0a41c70e41d50a4528aec55b614917b09fff9e3311fe7edfa944'
observed = json.loads(observed_raw)
assert observed['terminal_exit_code'] == -2 and not observed['known_owned_processes_remaining']
assert not observed['source_changed'] and not observed['original_wrapper_result_written']
prior_native4_raw = (ROOT / 'fixture-native-4/RESULT.json').read_bytes()
assert sha(prior_native4_raw) == 'dd55367752fc4bef8fbd6734f5a98dc586cc71044397b2c7c500dd6f041308c3'
prior_native4 = json.loads(prior_native4_raw)
assert prior_native4['exit_code'] == 1 and prior_native4['protected_unchanged'] and prior_native4['source_unchanged_during_native']
assert prior_native4['stages'][0]['name'] == 'native-project' and prior_native4['stages'][0]['exit_code'] == 101
seed_raw = (ROOT / 'dependency-crossterm-cache-seed-2/RESULT.json').read_bytes()
assert sha(seed_raw) == '6fc8ef470a73caac73479c7e7eb8f7d40c2968f0aff50ad345ac468bd43ffc70'
seed = json.loads(seed_raw)
assert seed['status'] == 'EXACT_LOCAL_CACHE_REF_READY' and seed['fsck_exit_code'] == 0 and seed['source_unchanged']
assert seed['prior_native4_result_sha256'] == sha(prior_native4_raw)
assert seed['after_ref'] == '45fecb9508105988f42fe6ff0441783ed3717f92' and seed['tree'] == 'f43069917d73c60e5286f56fef318cb13febf204'
actual_cached_ref = subprocess.check_output(['/usr/bin/git', '--git-dir=/Users/qianqi/.cargo/git/db/crossterm-ce0318b92aca4e8d', 'rev-parse', '--verify', 'refs/commit/45fecb9508105988f42fe6ff0441783ed3717f92'], text=True).strip()
assert actual_cached_ref == seed['after_ref']
known_ids = {80065, 80073, 80074, 80078, 80081, 91954, 91955, 91964, 91965, 91968, 91971}
processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,stat=,comm='], text=True)
assert not [line for line in processes.splitlines() if any(int(value) in known_ids for value in line.split(None, 3)[:2]) or int(line.split(None, 3)[2]) in {80065, 91955}]
protected = ['codex-rs/hepta-agentd/src/learning_iteration_research_external_material.rs',
             'codex-rs/hepta-agentd/src/circuit_cell_tests.rs',
             'codex-rs/Cargo.lock', '.github/blob-size-allowlist.txt']
protected_before = {p: sha((SOURCE / p).read_bytes()) for p in protected}
intent = {'schema': 'hepta.joint.mac-fixture-native.v1', 'source_parent': HEAD,
          'scope': 'two fixture path repairs; original project unit tests; no E6 business parent or model execution',
          'new_model_calls': 0, 'new_training_updates': 0, 'original_E6_parent_runs': 0,
          'automatic_retry': False, 'payload_sha256': PAYLOAD_SHA,
          'prior_preflight_failure_sha256': sha((ROOT / 'fixture-native-1/RESULT.json').read_bytes()),
          'prior_locked_offline_dependency_failure_sha256': sha((ROOT / 'fixture-native-2/RESULT.json').read_bytes()),
          'prior_git_library_interruption_observation_sha256': sha(observed_raw),
          'prior_git_cli_dependency_failure_sha256': sha(prior_native4_raw),
          'exact_local_cache_seed_result_sha256': sha(seed_raw),
          'dependency_acquisition': 'Original native4 terminal; exact locked crossterm commit seeded once through local Git --update-shallow, with old partial files preserved; this native5 uses --locked --offline and no Cargo.lock/source change',
          'inventory_scope': 'all tracked Git identities plus exact materialized bytes; inherited skip-worktree absent files explicitly listed, not claimed as read',
          'protected_before': protected_before,
          'files': [{k: v for k, v in row.items() if k != 'content'} for row in payload['files']]}
(OUT / 'INTENT.json').write_text(json.dumps(intent, indent=2) + '\n')
env = dict(os.environ)
env['PATH'] = '/opt/homebrew/bin:/opt/homebrew/opt/rustup/bin:/Users/qianqi/.cargo/bin:' + env.get('PATH', '')
env['CARGO_TARGET_DIR'] = str(ROOT / 'native-target')
env['CARGO_BUILD_JOBS'] = '2'
env['CARGO_NET_GIT_FETCH_WITH_CLI'] = 'true'
env['CARGO_NET_OFFLINE'] = 'true'
env['GIT_TERMINAL_PROMPT'] = '0'
stages = []


def run(name, argv):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with (OUT / (name + '.stdout')).open('xb') as stdout, (OUT / (name + '.stderr')).open('xb') as stderr:
        process = subprocess.Popen(argv, cwd=SOURCE / 'codex-rs', env=env, stdout=stdout, stderr=stderr)
        (OUT / (name + '.CHILD.json')).write_text(json.dumps({'pid': process.pid, 'argv': argv}) + '\n')
        print(json.dumps({'stage': name, 'state': 'running', 'pid': process.pid}), flush=True)
        exit_code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    row = {'name': name, 'argv': argv, 'exit_code': exit_code, 'wall_seconds': time.monotonic() - started,
           'child_user_cpu_seconds': after.ru_utime - before.ru_utime,
           'child_system_cpu_seconds': after.ru_stime - before.ru_stime}
    for label in ['stdout', 'stderr']:
        raw = (OUT / (name + '.' + label)).read_bytes()
        row[label + '_bytes'] = len(raw)
        row[label + '_sha256'] = sha(raw)
    (OUT / (name + '.EXIT.json')).write_text(json.dumps(row, indent=2) + '\n')
    stages.append(row)
    print(json.dumps(row), flush=True)
    if exit_code:
        raise RuntimeError(f'{name} exited {exit_code}')


started = time.monotonic()
error = None
frozen = None
try:
    for row in payload['files']:
        path = SOURCE / row['path']
        assert sha(path.read_bytes()) == row['candidate_sha256']
        assert path.read_bytes() == (ROOT / 'fixture-native-1' / Path(row['path']).name).read_bytes()
        (OUT / Path(row['path']).name).write_bytes(path.read_bytes())
    (OUT / 'candidate.diff').write_bytes(git('diff', '--binary'))
    frozen = inventory()
    raw = (json.dumps(frozen, indent=2) + '\n').encode()
    (OUT / 'SOURCE_INVENTORY.json').write_bytes(raw)
    intent['source_inventory_sha256'] = sha(raw)
    assert sha(raw) == prior_native4['source_inventory_sha256'], 'source differs from original terminal native4'
    intent['unmaterialized_tracked_paths'] = sum(r['kind'] == 'unmaterialized_skip_worktree' for r in frozen)
    intent['materialized_paths'] = len(frozen) - intent['unmaterialized_tracked_paths']
    (OUT / 'INTENT.json').write_text(json.dumps(intent, indent=2) + '\n')
    run('native-project', ['/opt/homebrew/bin/just', 'test', '--locked', '--offline', '-p', 'codex-hepta-agentd', '--lib', '--retries', '0', '--test-threads', '2', '--no-tests', 'fail', '--success-output', 'final', '--failure-output', 'final'])
except Exception as exc:
    error = repr(exc)
    (OUT / 'error.txt').write_text(traceback.format_exc())
protected_after = {p: sha((SOURCE / p).read_bytes()) for p in protected}
after = inventory() if frozen is not None else None
result = {**intent, 'protected_after': protected_after, 'protected_unchanged': protected_before == protected_after,
          'source_unchanged_during_native': frozen is not None and frozen == after,
          'stages': stages, 'owner_wall_seconds': time.monotonic() - started, 'error': error,
          'exit_code': 0 if error is None and protected_before == protected_after and frozen == after else 1}
(OUT / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'result': str(OUT / 'RESULT.json'), 'result_sha256': sha((OUT / 'RESULT.json').read_bytes()),
                  'exit_code': result['exit_code'], 'error': error}), flush=True)
raise SystemExit(result['exit_code'])
