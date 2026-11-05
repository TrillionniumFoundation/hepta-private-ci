import collections
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = Path('/home/qq/work/hepta-audit-pty-diagnostic-20261105')
SOURCE = ROOT / 'source'
TARGET = ROOT / 'target-dev-small'
EVIDENCE = ROOT / 'evidence/native-project-v1'
SHARED_ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
SHARED_TOOLS = SHARED_ROOT / 'tools'
COMMIT = '1ddadae2c1bcb3c48047d2692565606833e87909'
TREE = '73f4b30499524d6137bb8f4b40c3977de286d1a5'
BASE_COMMIT = '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
BASE_TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
REPOSITORY = 'https://github.com/TrillionniumFoundation/hepta-private-ci.git'
PACKAGE = 'codex-utils-pty'
records = []
commands = []
baseline = None
request = None
created = False
current_tree = TREE
env = dict(os.environ)


def now():
    return datetime.now(timezone.utc).isoformat()


def bytes_id(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def file_id(path):
    path = Path(path)
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1, f'not independent regular file: {path}'
    digest = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
    size = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            blob.update(chunk)
            size += len(chunk)
    assert size == info.st_size
    return {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest(),
            'git_blob': blob.hexdigest(), 'mode': oct(stat.S_IMODE(info.st_mode)),
            'dev': info.st_dev, 'inode': info.st_ino}


def content_equal(actual, expected):
    return all(actual[key] == expected[key] for key in ('bytes', 'sha256'))


def save(name, data):
    if isinstance(data, str):
        data = data.encode()
    path = EVIDENCE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    result = file_id(path)
    records.append(result)
    return result


def save_json(name, value):
    return save(name, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def capacity(initial=False):
    path = ROOT if ROOT.exists() else ROOT.parent
    info = os.statvfs(path)
    result = {'at': now(), 'path': str(path), 'f_bavail': info.f_bavail,
              'f_frsize': info.f_frsize, 'available_bytes': info.f_bavail * info.f_frsize,
              'minimum_bytes': 200000000000 if initial else 64000000000}
    assert result['available_bytes'] >= result['minimum_bytes'], f'capacity guard: {result}'
    return result


def git(args, index=None):
    actual_env = dict(env)
    actual_env['GIT_OPTIONAL_LOCKS'] = '0'
    if index is not None:
        actual_env['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(['/usr/bin/git', '-C', str(SOURCE), *args], env=actual_env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, f'guard git {args}: {result.returncode}: {result.stderr.decode(errors="replace")}'
    return result.stdout


def check_shared_inputs(label):
    rows = []
    for expected in request['shared_readonly_files']:
        path = Path(expected['path'])
        assert path.is_relative_to(SHARED_ROOT)
        actual = file_id(path)
        assert content_equal(actual, expected), f'shared readonly input changed: {path}'
        rows.append(actual)
    return save_json(label + '.shared-readonly.json', rows)


def source_guard(label, allow_hygiene_change=False):
    global current_tree
    assert SOURCE.resolve() == SOURCE and TARGET.resolve() == TARGET
    ordinary = file_id(SOURCE / '.git/index')
    assert content_equal(ordinary, baseline['ordinary_index']), 'ordinary index drift; preserve, do not reset'
    head = git(['rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
    assert head == [COMMIT, TREE], f'HEAD or committed tree changed: {head}'
    private = EVIDENCE / (label + '.index')
    git(['read-tree', TREE], private)
    git(['add', '-u', '--'], private)
    actual = git(['write-tree'], private).decode().strip()
    others = git(['ls-files', '--others', '--exclude-standard', '-z'], private)
    assert not others, 'unexpected untracked source input; preserve and stop'
    checked = []
    for expected in baseline['guarded_files']:
        row = file_id(SOURCE / expected['relative_path'])
        assert content_equal(row, expected), f'lock or recipe changed: {expected["relative_path"]}'
        checked.append(row)
    assert content_equal(file_id(SOURCE / '.git/index'), ordinary)
    if not allow_hygiene_change:
        assert actual == current_tree, f'whole source tree drift: {actual} != {current_tree}'
    current_tree = actual
    receipt = {'at': now(), 'head': head[0], 'head_tree': head[1], 'working_tree': actual,
               'ordinary_index': ordinary, 'guarded_files': checked, 'untracked': [],
               'capacity': capacity(), 'shared_inputs': check_shared_inputs(label)}
    return save_json(label + '.guard.json', receipt)


def command(label, argv, cwd=None, guarded=True, hygiene=False, require_success=True):
    item = {'label': label, 'argv': argv, 'cwd': str(cwd or SOURCE / 'codex-rs'),
            'started_at': now(), 'capacity_before': capacity(), 'attempt': 1,
            'cargo_profile': 'dev-small', 'nextest_profile': 'local'}
    if guarded:
        item['source_before'] = source_guard(label + '-before')
        item['source_tree_before'] = current_tree
    save_json(label + '.command.json', item)
    stdout = EVIDENCE / (label + '.stdout.original')
    stderr = EVIDENCE / (label + '.stderr.original')
    start = time.monotonic()
    print(json.dumps({'phase_start': label, 'argv': argv, 'source_tree': current_tree}), flush=True)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        result = subprocess.run(argv, cwd=item['cwd'], env=env, stdout=out, stderr=err, check=False)
    out_id, err_id = file_id(stdout), file_id(stderr)
    records.extend([out_id, err_id])
    item.update({'completed_at': now(), 'duration_seconds': time.monotonic() - start,
                 'exit_code': result.returncode, 'stdout': out_id, 'stderr': err_id})
    commands.append(item)
    # Persist the actual command outcome before a post-command guard can reject it.
    save_json(label + '.execution.json', item)
    item['capacity_after'] = capacity()
    if guarded:
        item['source_after'] = source_guard(label + '-after', allow_hygiene_change=hygiene)
        item['source_tree_after'] = current_tree
    save_json(label + '.status.json', item)
    print(json.dumps({'phase_terminal': label, 'exit_code': result.returncode,
                      'seconds': item['duration_seconds'], 'source_tree': current_tree}), flush=True)
    if require_success:
        assert result.returncode == 0, f'{label}: exit {result.returncode}; original output preserved'
    return item


def catalog_artifacts(catalog):
    binaries = []
    for sid, suite in sorted(catalog['rust-suites'].items()):
        path = Path(suite['binary-path'])
        assert path.is_relative_to(TARGET) and path.resolve() == path and os.access(path, os.X_OK)
        binaries.append({'binary_id': sid, **file_id(path)})
    helpers = []
    for package_id, values in sorted(catalog['rust-build-meta']['non-test-binaries'].items()):
        for value in values:
            if value['kind'] != 'bin-exe':
                continue
            path = Path(value['path'])
            if not path.is_absolute():
                path = TARGET / path
            assert path.is_relative_to(TARGET) and path.resolve() == path and os.access(path, os.X_OK)
            helpers.append({'package_id': package_id, 'catalog_entry': value, **file_id(path)})
    return binaries, helpers


def verify_test_result(catalog, expected, test, junit_before, started_ns, binaries, helpers):
    junit = SOURCE / 'codex-rs/target/nextest/local/junit.xml'
    assert junit.is_file() and junit.stat().st_mtime_ns >= started_ns - 2000000000, 'fresh JUnit missing'
    actual_junit = file_id(junit)
    assert junit_before is None or not content_equal(actual_junit, junit_before), 'stale JUnit identity'
    copied = save('pty-project.junit.xml', junit.read_bytes())
    cases = []
    for case in ET.fromstring(junit.read_bytes()).iter('testcase'):
        result = 'FAIL' if case.find('failure') is not None else 'ERROR' if case.find('error') is not None else 'SKIP' if case.find('skipped') is not None else 'PASS'
        cases.append({'classname': case.attrib.get('classname'), 'name': case.attrib.get('name'),
                      'seconds': case.attrib.get('time'), 'result': result,
                      'failure': '\n'.join(x.text or '' for x in case if x.tag in ('failure', 'error'))})
    key = lambda rows: collections.Counter((x['classname'], x['name']) for x in rows)
    binaries_after, helpers_after = catalog_artifacts(catalog)
    raw = '\n'.join(Path(test[k]['path']).read_text(errors='replace') for k in ('stdout', 'stderr'))
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw)
    early = [{'line': number, 'text': line} for number, line in enumerate(clean.splitlines(), 1)
             if any(needle in line.lower() for needle in ('skipping', 'requires a remote test environment'))]
    review = {'tested_source_tree': TREE, 'host_alias': 'ai395', 'platform': 'Linux x86_64',
              'package': PACKAGE, 'cargo_profile': 'dev-small', 'nextest_profile': 'local',
              'retries': 0, 'command_exit_code': test['exit_code'], 'junit': copied,
              'cases': cases, 'counts': dict(collections.Counter(x['result'] for x in cases)),
              'exact_roster': key(cases) == key(expected),
              'programs_before': binaries, 'programs_after': binaries_after,
              'helpers_before': helpers, 'helpers_after': helpers_after,
              'programs_stable': binaries == binaries_after, 'helpers_stable': helpers == helpers_after,
              'observed_early_return_lines': early,
              'summaries': [line for line in clean.splitlines() if 'Starting ' in line or 'Summary' in line],
              'does_not_qualify_macos_intel_or_windows': True}
    review['qualified_local_project_pass'] = (
        test['exit_code'] == 0 and review['exact_roster'] and review['programs_stable']
        and review['helpers_stable'] and not early and all(x['result'] == 'PASS' for x in cases))
    save_json('pty-project-review.json', review)
    assert review['qualified_local_project_pass'], 'project test or execution qualification failed; stop before hygiene'
    return review


def export_hygiene_diff(label, before):
    delta = git(['diff', '--binary', '--full-index', before, current_tree, '--'])
    patch = save(label + '.patch', delta)
    paths = [x.decode() for x in git(['diff', '--name-only', '-z', before, current_tree, '--']).split(b'\0') if x]
    posts = []
    for position, relative in enumerate(paths):
        path = SOURCE / relative
        assert path.is_file(), f'hygiene removed an existing source path: {relative}'
        posts.append({'relative_path': relative, 'source': file_id(path),
                      'archived_postimage': save(f'{label}-postimages/{position:03}.source', path.read_bytes())})
    result = {'before_tree': before, 'after_tree': current_tree, 'patch': patch,
              'changed_paths': paths, 'postimages': posts,
              'tested_tree_remains': TREE, 'tests_reexecuted_after_hygiene': False}
    save_json(label + '.diff.json', result)
    return result


raw_request = sys.stdin.buffer.read()
request = json.loads(raw_request)
terminal = {'schema': 'hepta-ai395-independent-pty-project-terminal-v1', 'started_at': now(),
            'request': bytes_id(raw_request), 'host_alias': 'ai395', 'source_commit': COMMIT,
            'tested_tree': TREE, 'base_commit': BASE_COMMIT, 'errors': [],
            'tests_executed': False, 'fix_executed': False, 'fmt_executed': False,
            'B_source_target_or_tools_mutated': False, 'macos_intel_qualification': False,
            'windows_qualification': False}
success = False
try:
    assert request['execute'] is True and request['root_execution_guard_blob'], 'disabled candidate; root guard required'
    guard_text = request['root_execution_guard_text']
    assert bytes_id(guard_text.encode())['git_blob'] == request['root_execution_guard_blob']
    guard = json.loads(guard_text)
    assert guard['execute'] is True and guard['runner']['sha256'] == request['runner_sha256']
    assert request['source_commit'] == COMMIT and request['source_tree'] == TREE
    assert request['base_commit'] == BASE_COMMIT and request['owned_root'] == str(ROOT)
    user = pwd.getpwuid(os.getuid())
    assert user.pw_name == 'qq' and user.pw_dir == '/home/qq'
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'x86_64'
    assert ROOT.parent.resolve() == ROOT.parent and ROOT.parent.is_dir()
    assert not os.path.lexists(ROOT), 'new PTY root already exists; do not reuse or remove it'
    terminal['capacity_before_creation'] = capacity(initial=True)
    for name in ['RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GIT_INDEX_FILE']:
        assert not os.environ.get(name), f'unexpected nonempty injection environment name: {name}'
    for expected in request['tool_pins']:
        path = Path(expected['path'])
        assert path.is_relative_to(SHARED_TOOLS) or path == Path('/usr/bin/git')
        actual = file_id(path)
        assert content_equal(actual, expected) and os.access(path, os.X_OK), f'tool identity drift: {path}'
    assert file_id('/usr/bin/git')['sha256'] == 'ed8b2df973b28c0fb773b9c0dc0816d3ee2b3835bb932d9153c21417bb51b362'
    ROOT.mkdir(mode=0o700)
    created = True
    for name in ['source', 'target-dev-small', 'evidence', 'cargo-home']:
        (ROOT / name).mkdir(mode=0o700)
    EVIDENCE.mkdir(mode=0o700)
    save('request.original.json', raw_request)
    save('root-guard.original.json', guard_text)
    save_json('host-and-capacity.json', {'uname': dict(zip(os.uname()._fields, os.uname())) if hasattr(os.uname(), '_fields') else list(os.uname()),
                                       'uid': os.getuid(), 'euid': os.geteuid(), 'user': user.pw_name,
                                       'capacity': terminal['capacity_before_creation']})
    rust_bin = SHARED_TOOLS / 'rustup-home/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin'
    env.update({'PATH': str(SHARED_TOOLS / 'bin') + ':' + str(rust_bin) + ':' + request['system_path'],
                'RUSTUP_HOME': str(SHARED_TOOLS / 'rustup-home'), 'RUSTUP_TOOLCHAIN': '1.95.0',
                'CARGO_HOME': str(ROOT / 'cargo-home'), 'CARGO_TARGET_DIR': str(TARGET),
                'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '4', 'CARGO_NET_GIT_FETCH_WITH_CLI': 'true',
                'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never',
                'PYTHONDONTWRITEBYTECODE': '1', 'NEXTEST_PROFILE': 'local'})
    save_json('task-environment.json', {key: env[key] for key in ('PATH', 'RUSTUP_HOME', 'RUSTUP_TOOLCHAIN',
              'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS',
              'CARGO_NET_GIT_FETCH_WITH_CLI', 'GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE',
              'PYTHONDONTWRITEBYTECODE', 'NEXTEST_PROFILE')})
    check_shared_inputs('initial')
    command('01-git-init', ['/usr/bin/git', 'init', '--initial-branch=pty-diagnostic', str(SOURCE)], cwd='/', guarded=False)
    command('02-exact-fetch', ['/usr/bin/git', '-C', str(SOURCE), 'fetch', '--no-tags', '--depth=2', REPOSITORY, COMMIT], cwd='/', guarded=False)
    assert git(['rev-parse', 'FETCH_HEAD']).decode().strip() == COMMIT
    command('03-exact-checkout', ['/usr/bin/git', '-C', str(SOURCE), 'checkout', '--detach', COMMIT], cwd='/', guarded=False)
    assert git(['rev-parse', 'HEAD', 'HEAD^{tree}', BASE_COMMIT + '^{tree}']).decode().splitlines() == [COMMIT, TREE, BASE_TREE]
    parent_lines = [line[7:] for line in git(['cat-file', '-p', COMMIT]).decode().split('\n\n', 1)[0].splitlines() if line.startswith('parent ')]
    assert parent_lines == [BASE_COMMIT]
    fulltree = git(['ls-tree', '-rz', '--full-tree', COMMIT])
    stage = git(['ls-files', '--stage', '-z'])
    save('initial-full-tree.original.nul', fulltree)
    save('initial-stage.original.nul', stage)
    tree_rows = {}
    for line in fulltree.split(b'\0'):
        if line:
            header, path = line.split(b'\t', 1)
            mode, kind, blob = header.split()
            tree_rows[path] = (mode, blob)
    stage_rows = {}
    for line in stage.split(b'\0'):
        if line:
            header, path = line.split(b'\t', 1)
            mode, blob, number = header.split()
            assert number == b'0' and path not in stage_rows
            stage_rows[path] = (mode, blob)
    assert tree_rows == stage_rows
    changed = [x.decode() for x in git(['diff', '--name-only', '-z', BASE_COMMIT, COMMIT, '--']).split(b'\0') if x]
    assert sorted(changed) == sorted(row['path'] for row in request['nine_source_postimages'])
    for row in request['nine_source_postimages']:
        assert file_id(SOURCE / row['path'])['git_blob'] == row['git_blob']
    ordinary = file_id(SOURCE / '.git/index')
    save('ordinary-index.initial.original.bin', (SOURCE / '.git/index').read_bytes())
    guarded = []
    for row in request['fixed_files']:
        actual = file_id(SOURCE / row['path'])
        assert actual['git_blob'] == row['git_blob']
        guarded.append({'relative_path': row['path'], **actual})
    baseline = {'ordinary_index': ordinary, 'guarded_files': guarded, 'tree_entries': len(tree_rows)}
    save_json('source-baseline.json', baseline)
    source_guard('initial-source')
    metadata_cmd = command('04-full-metadata', ['cargo', 'metadata', '--locked', '--format-version=1'])
    metadata = json.loads(Path(metadata_cmd['stdout']['path']).read_bytes())
    assert metadata['workspace_root'] == str(SOURCE / 'codex-rs')
    assert metadata['target_directory'] == str(TARGET)
    packages = {row['id']: row for row in metadata['packages']}
    nodes = {row['id']: row for row in metadata['resolve']['nodes']}
    selected_ids = [pid for pid in metadata['workspace_members'] if packages[pid]['name'] == PACKAGE]
    assert len(selected_ids) == 1
    closure = set()
    pending = list(selected_ids)
    while pending:
        pid = pending.pop()
        if pid in closure:
            continue
        closure.add(pid)
        pending.extend(row['pkg'] for row in nodes[pid]['deps'])
    closure_rows = sorted((packages[pid]['name'], packages[pid]['version']) for pid in closure)
    assert all(name != 'v8' for name, _ in closure_rows), 'PTY dependency closure unexpectedly includes V8; stop'
    assert collections.Counter(closure_rows) == collections.Counter(tuple(row) for row in request['expected_dependency_packages'])
    save_json('fresh-pty-dependency-closure.json', {'metadata': metadata_cmd['stdout'], 'source_tree': TREE,
              'workspace_members': len(metadata['workspace_members']), 'resolve_nodes': len(nodes),
              'package_ids': sorted(closure), 'packages': closure_rows, 'contains_v8': False})
    scoped = command('05-scoped-metadata', ['cargo', 'metadata', '--no-deps', '--format-version=1', '--locked'])
    catalog_cmd = command('06-project-catalog', ['cargo', 'nextest', 'list', '--locked', '--cargo-profile', 'dev-small',
                          '--cargo-metadata', scoped['stdout']['path'], '-p', PACKAGE, '--message-format=json'])
    catalog = json.loads(Path(catalog_cmd['stdout']['path']).read_bytes())
    assert catalog['rust-build-meta']['target-directory'] == str(TARGET)
    assert sorted(catalog['rust-suites']) == ['codex-utils-pty', 'codex-utils-pty::conpty_search_path']
    assert not catalog['rust-suites']['codex-utils-pty::conpty_search_path']['testcases']
    selected, ignored, unmatched = [], [], []
    for sid, suite in sorted(catalog['rust-suites'].items()):
        assert suite['package-name'] == PACKAGE
        for name, case in suite['testcases'].items():
            row = {'classname': sid, 'name': name, 'ignored': case['ignored']}
            if case['ignored']:
                ignored.append(row)
            elif case['filter-match']['status'] == 'matches':
                selected.append(row)
            else:
                unmatched.append(row)
    counter = lambda rows: collections.Counter((r['classname'], r['name'], r['ignored']) for r in rows)
    assert selected and not ignored and not unmatched
    assert counter(selected) == counter(request['expected_linux_cases']), 'fresh project catalog differs from fixed complete roster'
    binaries, helpers = catalog_artifacts(catalog)
    save_json('pty-project-selection.json', {'source_tree': TREE, 'catalog': catalog_cmd['stdout'],
              'selected': selected, 'ignored': ignored, 'unmatched': unmatched,
              'programs_after_catalog_before_just': binaries, 'helpers_after_catalog_before_just': helpers})
    junit = SOURCE / 'codex-rs/target/nextest/local/junit.xml'
    prior = file_id(junit) if junit.exists() else None
    started_ns = time.time_ns()
    terminal['tests_executed'] = True
    test = command('07-pty-project-test', ['just', 'test', '--locked', '--cargo-profile', 'dev-small',
                   '--no-tests', 'fail', '--retries', '0', '--success-output', 'immediate', '-p', PACKAGE], require_success=False)
    terminal['project_review'] = verify_test_result(catalog, selected, test, prior, started_ns, binaries, helpers)
    before_fix = current_tree
    terminal['fix_executed'] = True
    fix_command = command('08-pty-project-fix', ['just', 'fix', '--locked', '--profile', 'dev-small', '-p', PACKAGE], hygiene=True, require_success=False)
    fix_diff = export_hygiene_diff('fix', before_fix)
    terminal['fix_diff'] = fix_diff
    assert fix_command['exit_code'] == 0, 'original just fix failed; preserve all output and source changes'
    assert not fix_diff['changed_paths'], 'automatic fix changed source; stop for root review before fmt'
    before_fmt = current_tree
    terminal['fmt_executed'] = True
    fmt_command = command('09-original-scoped-fmt', ['just', 'fmt', '--base', BASE_COMMIT], hygiene=True, require_success=False)
    fmt_diff = export_hygiene_diff('fmt', before_fmt)
    terminal['fmt_diff'] = fmt_diff
    assert fmt_command['exit_code'] == 0, 'original just fmt failed; preserve all output and source changes'
    assert not fmt_diff['changed_paths'], 'fmt changed source; stop for root review before final diff checks'
    command('10-worktree-diff-check', ['/usr/bin/git', 'diff', '--check', COMMIT, '--'], cwd=SOURCE)
    command('11-base-diff-check', ['/usr/bin/git', 'diff', '--check', BASE_COMMIT, '--'], cwd=SOURCE)
    terminal['final_guard'] = source_guard('final-source')
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'completed_at': now(), 'success': success, 'final_source_tree': current_tree,
                     'commands': commands, 'records': records, 'tests_after_hygiene': False})
    if created and EVIDENCE.is_dir():
        terminal_id = save_json('terminal.json', terminal)
        print(json.dumps({'success': success, 'terminal': terminal_id, 'source_tree': current_tree,
                          'errors': terminal['errors'], 'tests_after_hygiene': False}), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)
