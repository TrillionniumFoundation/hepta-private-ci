import fcntl
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path('/Users/qianqi/work/hepta-joint-mac-fixtures-20261120-e9e051')
SOURCE = ROOT / 'source'
OUT = ROOT / 'fixture-native-6'
HEAD = '238fc48402f786db3d7f2a80b0abad6c0e5322bb'
PAYLOAD_SHA = '596d0483009434c83e58bf2fa9225a00de2c0ba59da997b9fe49b56eb2048ab8'
OLD_PAYLOAD_SHA = 'fe4fced4cf0b7ea6005ecdef212b19a9624c5be7d9179be282c9cd21a6120067'
os.environ['GIT_NO_LAZY_FETCH'] = '1'
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
env = dict(os.environ)
env['PATH'] = '/opt/homebrew/bin:/opt/homebrew/opt/rustup/bin:/Users/qianqi/.cargo/bin:' + env.get('PATH', '')
env['CARGO_TARGET_DIR'] = str(ROOT / 'native-target')
env['CARGO_BUILD_JOBS'] = '2'
env['CARGO_NET_OFFLINE'] = 'true'
env['GIT_TERMINAL_PROMPT'] = '0'
stages = []


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

def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')

OUT.mkdir(exist_ok=False)
controller = sys.argv[1].encode()
(OUT / 'CONTROLLER.py').write_bytes(controller)
started = time.monotonic()
intent = {'schema': 'hepta.joint.mac-fixture-native.v2', 'source_parent': HEAD,
          'source_scope': 'exact 238 source plus the two frozen fixture patches; not the full d1d tree',
          'new_model_calls': 0, 'new_training_updates': 0, 'original_E6_parent_runs': 0,
          'automatic_retry': False, 'payload_sha256': PAYLOAD_SHA,
          'previous_payload_sha256': OLD_PAYLOAD_SHA, 'controller_sha256': sha(controller),
          'requested_stages': ['fmt', 'fmt-check', 'project-just-fix', 'project-unwrap-clippy', 'native-project'],
          'build_jobs': 2, 'test_threads': 2, 'original_test_retries': 0,
          'cargo_net_offline': True, 'rust_process_timeout_or_kill': False}
write('INTENT.json', intent)
lock = None
error = None
frozen = None
protected_before = None
cas_rows = []
try:
    lock = (ROOT / 'fixture-native.lock').open('r+b')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    intent['fixture_lock_acquired'] = True
    old_raw = (ROOT / 'fixture-native-5/RESULT.json').read_bytes()
    assert sha(old_raw) == '4eb76583bf64b106a94432cbab91a756fae253eb91194b623d3bacc35ca5976f'
    old = json.loads(old_raw)
    assert old['exit_code'] == 1 and old['protected_unchanged'] and old['source_unchanged_during_native']
    assert old['stages'][0]['exit_code'] == 101
    assert sha((ROOT / 'candidate_payload.json').read_bytes()) == OLD_PAYLOAD_SHA
    payload_raw = (ROOT / 'candidate_payload_v2.json').read_bytes()
    assert sha(payload_raw) == PAYLOAD_SHA
    payload = json.loads(payload_raw)
    assert payload['source'] == HEAD and payload['previous_payload_sha256'] == OLD_PAYLOAD_SHA
    assert git('rev-parse', 'HEAD').decode().strip() == HEAD
    assert set(git('diff', '--name-only').decode().splitlines()) == {x['path'] for x in payload['files']}
    processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,stat=,comm='], text=True)
    blocked = []
    for line in processes.splitlines():
        fields = line.split(None, 4)
        if len(fields) != 5:
            continue
        pid, ppid, pgid = map(int, fields[:3])
        executable = Path(fields[4]).name
        if executable in {'cargo', 'cargo-nextest', 'rustc', 'clippy-driver'} or pid in {90338,90339,90349} or ppid in {90338,90339,90349} or pgid == 90339:
            blocked.append({'pid':pid,'ppid':ppid,'pgid':pgid,'stat':fields[3],'executable':executable})
    write('PROCESS_PREFLIGHT.json', {'blocking_processes':blocked, 'arguments_or_environment_read':False})
    assert not blocked, 'another Cargo/Rust or original native5 owner is present'
    receipts = {
        'dependency-crossterm-cache-seed-2/RESULT.json':'6fc8ef470a73caac73479c7e7eb8f7d40c2968f0aff50ad345ac468bd43ffc70',
        'dependency-nucleo-cache-seed-1/RESULT.json':'bf8c6142b1fc7cfcf1152196f8b5b95f1f35a7881fb1d2ede5265da7adcd54c0',
        'dependency-tokio-tungstenite-cache-seed-1/RESULT.json':'16d6db70778f8b99c1797a52d3d569f40ba409629188dbd0fc9c030332b3e8cd',
        'dependency-rules_rust-cache-seed-1/RESULT.json':'faef80545f0166e44a81cc4a018b84a75153d1aaf88b20fbbf8d6b36de5b0fca'}
    for name, expected in receipts.items():
        raw = (ROOT / name).read_bytes()
        assert sha(raw) == expected
        data = json.loads(raw)
        assert data['status'] == 'EXACT_LOCAL_CACHE_REF_READY' and data['source_unchanged'] and data['fsck_exit_code'] == 0
    refs = [('crossterm-ce0318b92aca4e8d','45fecb9508105988f42fe6ff0441783ed3717f92'),
            ('nucleo-425d994cd74b3654','4253de9faabb4e5c6d81d946a5e35a90f87347ee'),
            ('rules_rust-7226a686fb7656c8','b56cbaa8465e74127f1ea216f813cd377295ad81'),
            ('tokio-tungstenite-ea4445d9acecae62','0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186'),
            ('tungstenite-rs-006aed970da0a0a9','4fffad30fe373adbdcffab9545e9e9bf4f2fc19f')]
    for cache, rev in refs:
        actual = subprocess.check_output(['/usr/bin/git','--git-dir=/Users/qianqi/.cargo/git/db/'+cache,'rev-parse','--verify','refs/commit/'+rev], text=True).strip()
        assert actual == rev
    intent['dependency_receipts'] = receipts
    intent['verified_cached_git_refs'] = refs
    protected_before = {p:sha((SOURCE/p).read_bytes()) for p in old['protected_after']}
    assert protected_before == old['protected_after'] == old['protected_before']
    before = inventory()
    before_raw = (json.dumps(before, indent=2)+'\n').encode()
    assert sha(before_raw) == old['source_inventory_sha256'], 'source differs before authorized v2 CAS'
    write('PRIOR_INVENTORY_BINDING.json', {'bytes':len(before_raw),'sha256':sha(before_raw),'exact_native5_inventory_match':True})
    for row in payload['files']:
        path = SOURCE / row['path']
        current = path.read_bytes()
        assert sha(current) == row['previous_candidate_sha256']
        updated = row['content'].encode()
        assert sha(updated) == row['candidate_sha256']
        (OUT / ('before-'+path.name)).write_bytes(current)
        if current != updated:
            st = path.stat()
            temporary = OUT / ('cas-new-'+path.name)
            with temporary.open('xb') as f:
                f.write(updated); f.flush(); os.fsync(f.fileno())
            os.chmod(temporary, st.st_mode & 0o777)
            now = path.stat()
            assert (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns) == (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
            assert sha(path.read_bytes()) == row['previous_candidate_sha256']
            os.replace(temporary, path)
            assert sha(path.read_bytes()) == row['candidate_sha256']
            cas_rows.append({'path':row['path'],'before_sha256':sha(current),'after_sha256':sha(updated),'under_exclusive_fixture_lock':True})
        (OUT / path.name).write_bytes(path.read_bytes())
    assert len(cas_rows) == 1
    write('SOURCE_CAS.json',cas_rows)
    assert sha((ROOT/'candidate_payload.json').read_bytes()) == OLD_PAYLOAD_SHA
    frozen = inventory()
    raw = (json.dumps(frozen,indent=2)+'\n').encode()
    (OUT/'SOURCE_INVENTORY.json').write_bytes(raw)
    (OUT/'candidate.diff').write_bytes(git('diff','--binary'))
    intent.update(source_inventory_sha256=sha(raw),protected_before=protected_before,
                  prior_native5_result_sha256=sha(old_raw),
                  files=[{k:v for k,v in row.items() if k!='content'} for row in payload['files']],
                  unmaterialized_tracked_paths=sum(r['kind']=='unmaterialized_skip_worktree' for r in frozen),
                  materialized_paths=sum(r['kind']!='unmaterialized_skip_worktree' for r in frozen))
    write('INTENT.json',intent)
    commands = [
        ('fmt', ['/opt/homebrew/bin/just','fmt','--base',HEAD]),
        ('fmt-check', ['/opt/homebrew/bin/just','fmt','--base',HEAD,'--check']),
        ('project-just-fix', ['/opt/homebrew/bin/just','fix','--locked','--offline','-p','codex-hepta-agentd']),
        ('project-unwrap-clippy', ['/opt/homebrew/bin/just','clippy','--locked','--offline','-p','codex-hepta-agentd','--','-D','clippy::unwrap_used']),
        ('native-project', ['/opt/homebrew/bin/just','test','--locked','--offline','-p','codex-hepta-agentd','--lib','--retries','0','--test-threads','2','--no-tests','fail','--success-output','final','--failure-output','final'])]
    for name, argv in commands:
        run(name,argv)
        current = inventory()
        same = current == frozen
        write(name+'.SOURCE_CHECK.json', {'equals_frozen':same,'actual_inventory_sha256':sha((json.dumps(current,indent=2)+'\n').encode())})
        if not same:
            (OUT/(name+'.SOURCE_AFTER.json')).write_text(json.dumps(current,indent=2)+'\n')
            (OUT/(name+'.UNEXPECTED.diff')).write_bytes(git('diff','--binary'))
        assert same, 'formatter/fix/test changed the frozen source; stop before later stages'
except Exception as exc:
    error = repr(exc)
    (OUT/'error.txt').write_text(traceback.format_exc())
finally:
    after = inventory() if frozen is not None else None
    protected_after = {p:sha((SOURCE/p).read_bytes()) for p in protected_before} if protected_before is not None else None
    result = {**intent,'protected_after':protected_after,
              'protected_unchanged':protected_before is not None and protected_before==protected_after,
              'source_unchanged_during_validation':frozen is not None and frozen==after,
              'authorized_source_cas':cas_rows,'stages':stages,'error':error,
              'owner_wall_seconds':time.monotonic()-started,
              'exit_code':0 if error is None and frozen==after and protected_before==protected_after else 1}
    write('RESULT.json',result)
    print(json.dumps({'result':str(OUT/'RESULT.json'),'sha256':sha((OUT/'RESULT.json').read_bytes()),'exit_code':result['exit_code'],'error':error}),flush=True)
    if lock is not None:lock.close()
raise SystemExit(result['exit_code'])
