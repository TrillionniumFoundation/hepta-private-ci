import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
SOURCE = ROOT / 'source'
OUT = ROOT / 'evidence/bootstrap-P4-git-tool-augmentation-v1'
TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
COMMIT = '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
PARENT = ROOT / 'evidence/bootstrap-P4-readonly-completion-v4/new-host-build-only-baseline.json'
PARENT_SHA = '16022204ade97bd6cdc78176e5dff2b8c19c536180aa9c5e7a5a219ddda7140f'
records = []

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def physical(path):
    path = Path(path)
    assert path.resolve() == path
    s = path.lstat()
    assert stat.S_ISREG(s.st_mode)
    data = path.read_bytes()
    a = path.lstat()
    assert (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) == (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns)
    return {'path': str(path), **identity(data), 'mode': oct(stat.S_IMODE(s.st_mode)), 'dev': s.st_dev, 'inode': s.st_ino, 'nlink': s.st_nlink}

def equal(a, b):
    return all(a[k] == b[k] for k in ('bytes', 'sha256'))

def save(name, value):
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    path = OUT / name
    with path.open('xb') as stream:
        stream.write(data)
    pin = physical(path)
    records.append(pin)
    return pin

def git(args, private=None):
    env = dict(environment, GIT_OPTIONAL_LOCKS='0')
    if private is not None:
        env['GIT_INDEX_FILE'] = str(private)
    result = subprocess.run(['/usr/bin/git', '-C', str(SOURCE), *args], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, {'argv': args, 'stderr': result.stderr.decode(errors='replace')}
    return result.stdout

def guard(label):
    index = physical(SOURCE / '.git/index')
    assert equal(index, parent['ordinary_index'])
    assert git(['rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines() == [COMMIT, TREE]
    private = OUT / (label + '.index')
    assert not private.exists()
    git(['read-tree', TREE], private)
    git(['add', '-u', '--'], private)
    actual = git(['write-tree'], private).decode().strip()
    assert actual == TREE
    assert git(['ls-files', '--others', '--exclude-standard', '-z'], private) == b''
    locked = {p: physical(SOURCE / p) for p in parent['locks']}
    assert all(equal(row, parent['locks'][p]) for p, row in locked.items())
    assert equal(physical(SOURCE / '.git/index'), index)
    assert equal(physical('/usr/bin/git'), git_initial)
    return save(label + '.guard.json', {'source_tree': TREE, 'head': COMMIT,
        'ordinary_index': index, 'locks': locked, 'untracked': [], 'git': physical('/usr/bin/git')})

assert ROOT.resolve() == ROOT and SOURCE.resolve() == SOURCE and not os.path.lexists(OUT)
assert os.getuid() == 1000
for name in ('GIT_INDEX_FILE', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS'):
    assert not os.environ.get(name)
parent_pin = physical(PARENT)
assert parent_pin['bytes'] == 265463 and parent_pin['sha256'] == PARENT_SHA
parent = json.loads(PARENT.read_bytes())
assert parent['source_tree'] == TREE and parent['source_commit'] == COMMIT
assert parent['role'] == 'BUILD_ONLY_CURRENT_HOST' and parent['tests_executed'] is False
assert {row['name'] for row in parent['tools']} == {'rustc', 'cargo', 'cargo-clippy', 'rustfmt', 'just', 'cargo-nextest', 'bazel'}
environment = dict(os.environ)
environment.update(parent['environment'])
assert Path(shutil.which('git', path=environment['PATH'])).resolve() == Path('/usr/bin/git')
git_initial = physical('/usr/bin/git')
assert os.access('/usr/bin/git', os.X_OK)
space = os.statvfs(ROOT)
assert space.f_bavail * space.f_frsize >= 64000000000
OUT.mkdir(mode=0o700)
started = datetime.now(timezone.utc).isoformat()
before = guard('before')
command = subprocess.run(['/usr/bin/git', '--version'], cwd=ROOT, env=environment,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
for name, data in [('git-version.stdout.original', command.stdout), ('git-version.stderr.original', command.stderr)]:
    with (OUT / name).open('xb') as stream:
        stream.write(data)
    records.append(physical(OUT / name))
assert command.returncode == 0 and command.stdout.startswith(b'git version ')
after = guard('after')
row = {'name': 'git', **git_initial, 'version_output': command.stdout.decode(),
       'observed_at': started, 'observation_scope': 'Current read-only completion; not claimed as original P4 pre-build capture.'}
doc = dict(parent)
doc['tools'] = [*parent['tools'], row]
doc['tool_identity_augmentation'] = {'parent': parent_pin, 'current_git_observation': row,
    'source_guards': [before, after], 'commands_repeated': False, 'tests_executed': False,
    'only_parent_field_modified': 'tools appended git; augmentation provenance added',
    'original_three_commands_six_source_guards_environment_artifacts_unchanged': True}
baseline_pin = save('new-host-build-only-baseline-with-git.json', doc)
assert {k: v for k, v in doc.items() if k not in ('tools', 'tool_identity_augmentation')} == {k: v for k, v in parent.items() if k != 'tools'}
assert doc['tools'][:-1] == parent['tools']
assert equal(physical(PARENT), parent_pin)
terminal = {'success': True, 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
    'parent': parent_pin, 'baseline': baseline_pin, 'git': row, 'source_guards': [before, after],
    'version_command': {'argv': ['/usr/bin/git', '--version'], 'exit_code': command.returncode},
    'records': list(records), 'tests_executed': False, 'build_or_list_repeated': False}
terminal_pin = save('terminal.json', terminal)
assets = []
for pin in [*terminal['records'], terminal_pin]:
    data = Path(pin['path']).read_bytes()
    assert equal(identity(data), pin)
    z = gzip.compress(data, compresslevel=9, mtime=0)
    assert gzip.decompress(z) == data
    assets.append({'original': pin, 'encoding': 'gzip-mtime0-base64', 'compressed': identity(z), 'data_base64': base64.b64encode(z).decode()})
transport = save('complete-originals.transport.json', {'assets': assets, 'native_originals_preserved': True})
print(json.dumps({'success': True, 'terminal': terminal_pin, 'baseline': baseline_pin, 'transport': transport,
    'tests_executed': False, 'build_or_list_repeated': False}), flush=True)
