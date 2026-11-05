import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

ROOT = Path('/Users/qianqi/hepta-audit-bazel-wrapper-20261105')
SOURCE = ROOT / 'source'
EVIDENCE = ROOT / 'evidence'
COMMIT = '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
BASE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
FIXED = '890362b5a9c1ad57be55d7e5c8beb2033b2aa63a'
WRAPPER = '.github/scripts/run-bazel-ci.sh'
PYTHON = '/opt/homebrew/opt/python@3.14/bin/python3'
REPO = 'https://github.com/TrillionniumFoundation/hepta-private-ci.git'
PATH_VALUE = '/opt/homebrew/opt/python@3.14/bin:/usr/bin:/bin:/usr/sbin:/sbin'
env = dict(os.environ)
env.update({'PATH': PATH_VALUE, 'PYTHONDONTWRITEBYTECODE': '1', 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'})
records, commands, guards = [], [], []
current_tree = BASE
ordinary_index = None
tools = None
created = False


def now():
    return datetime.now(timezone.utc).isoformat()


def byte_id(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def file_id(path, tool=False):
    path = Path(path)
    info = path.lstat()
    if not tool:
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1, str(path)
    real = path.resolve() if tool else path
    assert real.is_file()
    before = real.stat()
    data = real.read_bytes()
    after = real.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {'path': str(path), 'resolved': str(real), **byte_id(data),
            'mode': oct(stat.S_IMODE(info.st_mode)), 'dev': info.st_dev, 'inode': info.st_ino,
            'symlink': stat.S_ISLNK(info.st_mode), 'nlink': info.st_nlink}


def equal(actual, expected):
    return all(actual[x] == expected[x] for x in ('bytes', 'sha256'))


def save(name, data):
    if isinstance(data, str):
        data = data.encode()
    path = EVIDENCE / name
    with path.open('xb') as stream:
        stream.write(data)
    result = file_id(path)
    records.append(result)
    return result


def save_json(name, value):
    return save(name, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def capacity():
    path = ROOT if ROOT.exists() else ROOT.parent
    info = os.statvfs(path)
    result = {'at': now(), 'path': str(path), 'available_bytes': info.f_bavail * info.f_frsize,
              'f_bavail': info.f_bavail, 'f_frsize': info.f_frsize, 'minimum_bytes': 5000000000}
    assert result['available_bytes'] >= result['minimum_bytes'], result
    return result


def git(args, index=None):
    e = dict(env)
    if index is not None:
        e['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(['/usr/bin/git', '-C', str(SOURCE), *args], env=e,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, (args, result.returncode, result.stderr.decode(errors='replace'))
    return result.stdout


def guard(label):
    assert SOURCE.resolve() == SOURCE
    actual_index = file_id(SOURCE / '.git/index')
    assert equal(actual_index, ordinary_index), 'ordinary index drift: preserve, no reset'
    head = git(['rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
    assert head == [COMMIT, BASE], head
    private = EVIDENCE / (label + '.index')
    git(['read-tree', BASE], private)
    git(['add', '-u', '--'], private)
    actual = git(['write-tree'], private).decode().strip()
    assert actual == current_tree, (actual, current_tree)
    assert not git(['ls-files', '--others', '--exclude-standard', '-z'], private)
    checked = []
    for expected in request['source_files']:
        expected = request['fixed_wrapper'] if expected['path'] == WRAPPER and current_tree == FIXED else expected
        row = file_id(SOURCE / expected['path'])
        assert equal(row, expected) and row['git_blob'] == expected['git_blob'], expected['path']
        if expected['path'] == WRAPPER:
            assert stat.S_IMODE((SOURCE / WRAPPER).stat().st_mode) == 0o755
        checked.append(row)
    locks = [file_id(SOURCE / path) for path in ('codex-rs/Cargo.lock', 'MODULE.bazel.lock')]
    for row, expected in zip(locks, request['locks']):
        assert equal(row, expected)
    current_tools = [file_id(path, tool=True) for path in (PYTHON, '/bin/bash', '/usr/bin/git')]
    assert current_tools == tools
    assert shutil.which('python3', path=PATH_VALUE) == PYTHON
    assert shutil.which('bash', path=PATH_VALUE) == '/bin/bash'
    assert equal(file_id(SOURCE / '.git/index'), ordinary_index)
    result = save_json(label + '.guard.json', {'at': now(), 'head': head[0], 'head_tree': head[1],
        'working_tree': actual, 'ordinary_index': actual_index, 'source_files': checked,
        'locks': locks, 'tools': current_tools, 'untracked': [], 'capacity': capacity()})
    guards.append(result)
    return result


def run(label, argv, cwd=None, guarded=False, require_success=True):
    item = {'label': label, 'argv': argv, 'cwd': str(cwd or SOURCE), 'started_at': now(),
            'attempt': 1, 'retries': 0, 'capacity_before': capacity(), 'source_tree': current_tree}
    if guarded:
        item['source_before'] = guard(label + '-before')
    save_json(label + '.command.json', item)
    stdout, stderr = EVIDENCE / (label + '.stdout.original'), EVIDENCE / (label + '.stderr.original')
    started = time.monotonic()
    print(json.dumps({'phase_start': label, 'argv': argv, 'source_tree': current_tree}), flush=True)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        result = subprocess.run(argv, cwd=item['cwd'], env=env, stdout=out, stderr=err, check=False)
    out_id, err_id = file_id(stdout), file_id(stderr)
    records.extend([out_id, err_id])
    item.update({'exit_code': result.returncode, 'duration_seconds': time.monotonic() - started,
                 'completed_at': now(), 'stdout': out_id, 'stderr': err_id})
    commands.append(item)
    save_json(label + '.execution.json', item)
    if guarded:
        item['source_after'] = guard(label + '-after')
    item['capacity_after'] = capacity()
    save_json(label + '.status.json', item)
    print(json.dumps({'phase_terminal': label, 'exit_code': result.returncode, 'seconds': item['duration_seconds']}), flush=True)
    if require_success:
        assert result.returncode == 0, label + ' failed; complete raw preserved'
    return item


def result_summary(item):
    text = '\n'.join(Path(item[key]['path']).read_text(errors='replace') for key in ('stdout', 'stderr'))
    totals = re.findall(r'^Ran ([0-9]+) tests? in ([0-9.]+)s$', text, re.M)
    failures = re.findall(r'^(FAIL|ERROR): ([^\n]+)$', text, re.M)
    skipped = re.findall(r'skipped=([0-9]+)', text)
    return {'command': item, 'original_summary': totals, 'failures': failures,
            'skipped': [int(x) for x in skipped], 'ran_exact_57': len(totals) == 1 and totals[0][0] == '57',
            'failed_targets_unbound_observed': 'failed_targets' in text and 'unbound variable' in text,
            'ok_line': bool(re.search(r'^OK$', text, re.M))}


raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-native-mac-bazel-wrapper-control-v1', 'host_alias': 'mac',
            'request': byte_id(raw), 'started_at': now(), 'source_commit': COMMIT,
            'before_tree': BASE, 'fixed_tree': FIXED, 'errors': [], 'real_bazel_product_builds': False}
success = False
try:
    assert request['execute'] is True and request['root_review_blob'] == '17dd529a880045c2a6c9bb661d6d86553adf97b6'
    assert os.getuid() == os.geteuid() == 501 and Path.home() == ROOT.parent
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64'
    assert not os.path.lexists(ROOT) and ROOT.parent.resolve() == ROOT.parent
    terminal['initial_capacity'] = capacity()
    tools = [file_id(path, tool=True) for path in (PYTHON, '/bin/bash', '/usr/bin/git')]
    assert tools[1]['sha256'] == '16303dedab719ddb63efd9dd68092a0da37b397bfd4fcb856d5f1c86c5ee414b'
    assert tools[2]['sha256'] == 'b8763cf250e607a778bb4603cecb5b90338814d0a3dfcba0d57b1de242f610e9'
    assert shutil.which('python3', path=PATH_VALUE) == PYTHON and shutil.which('bash', path=PATH_VALUE) == '/bin/bash'
    ROOT.mkdir(mode=0o700)
    EVIDENCE.mkdir(mode=0o700)
    SOURCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    save_json('host-and-environment.json', {'host_alias': 'mac', 'uname': list(platform.uname()),
        'uid': os.getuid(), 'euid': os.geteuid(), 'tools': tools, 'task_environment': {key: env[key] for key in
        ('PATH', 'PYTHONDONTWRITEBYTECODE', 'GIT_OPTIONAL_LOCKS', 'GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE')}})
    version = run('00-python-version', ['python3', '--version'], cwd=ROOT)
    assert Path(version['stdout']['path']).read_text().strip() == 'Python 3.14.3'
    run('01-bash-version', ['/bin/bash', '--version'], cwd=ROOT)
    run('02-git-version', ['/usr/bin/git', '--version'], cwd=ROOT)
    run('03-init', ['/usr/bin/git', 'init', str(SOURCE)], cwd=ROOT)
    run('04-fixed-fetch', ['/usr/bin/git', '-C', str(SOURCE), 'fetch', '--no-tags', '--depth=1', REPO, COMMIT], cwd=ROOT)
    run('05-fixed-checkout', ['/usr/bin/git', '-C', str(SOURCE), '-c', 'advice.detachedHead=false', 'checkout', '--detach', COMMIT], cwd=ROOT)
    ordinary_index = file_id(SOURCE / '.git/index')
    save('ordinary-index.original.bin', (SOURCE / '.git/index').read_bytes())
    save_json('source-baseline.json', {'head': COMMIT, 'head_tree': BASE, 'ordinary_index': ordinary_index})
    guard('initial-source')
    inventory_code = "import json,unittest; s=unittest.defaultTestLoader.discover('.github/scripts',pattern='test_run_bazel*.py'); walk=lambda t: sum((walk(x) for x in t),[]) if isinstance(t,unittest.TestSuite) else [t.id()]; print(json.dumps(walk(s)))"
    inventory = run('06-original-discovery-inventory', ['python3', '-c', inventory_code], guarded=True)
    names = json.loads(Path(inventory['stdout']['path']).read_text())
    assert len(names) == 57 and collections.Counter(names) == collections.Counter(request['expected_test_ids']), names
    save_json('selection.json', {'source_tree': BASE, 'test_ids': names, 'selected': len(names), 'retries': 0})
    argv = ['python3', '-m', 'unittest', 'discover', '-s', '.github/scripts', '-p', 'test_run_bazel*.py']
    before = run('07-original-controls-baseline', argv, guarded=True, require_success=False)
    before_review = result_summary(before)
    terminal['baseline_review'] = before_review
    save_json('baseline-review.json', before_review)
    assert before_review['ran_exact_57'], 'baseline did not execute original full57 scope; preserve actual result'
    wrapper = SOURCE / WRAPPER
    assert file_id(wrapper)['git_blob'] == '204c0ac2481f70cc977f777eb2299b740f7ddc17'
    post = request['fixed_wrapper']['content'].encode()
    assert equal(byte_id(post), request['fixed_wrapper']) and byte_id(post)['git_blob'] == '42b59b6354b5933c8155b992519682c06d024ca1'
    with wrapper.open('wb') as stream:
        stream.write(post)
    current_tree = FIXED
    guard('single-wrapper-fixed')
    save('single-wrapper-fixed.patch', git(['diff', '--binary', '--full-index', BASE, FIXED, '--']))
    after = run('08-original-controls-fixed', argv, guarded=True, require_success=False)
    after_review = result_summary(after)
    terminal['fixed_review'] = after_review
    save_json('fixed-review.json', after_review)
    assert after['exit_code'] == 0 and after_review['ran_exact_57'] and after_review['ok_line'] and not after_review['failures'] and not after_review['skipped'], 'fixed original57 did not pass; preserve raw and source'
    terminal['final_guard'] = guard('final')
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'completed_at': now(), 'success': success, 'source_tree': current_tree,
                     'commands': commands, 'source_guards': guards, 'records': list(records)})
    if created:
        receipt = save_json('terminal.json', terminal)
        print(json.dumps({'success': success, 'terminal': receipt, 'source_tree': current_tree, 'errors': terminal['errors']}), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)
