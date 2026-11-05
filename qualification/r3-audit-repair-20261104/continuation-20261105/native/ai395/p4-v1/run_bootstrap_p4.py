import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
SOURCE = ROOT / 'source'
TARGET = ROOT / 'target-dev-small'
TOOLS = ROOT / 'tools'
EVIDENCE = ROOT / 'evidence/bootstrap-P4-v1'
COMMIT = '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
GUARD_BLOB = '967ef896907e698a07e8028e049a47e934570b1d'
GUARD_SHA = '189adc8deb54a5c53a444de491407b5c4fb3da359cac3a53942cca06adc94f77'
PLAN_SHA = '8fffcd480b6708b16e6bf98182679de5f82f5e5c4567478258aaa37f704a85d8'
HELPERS = {
    'codex-arg0': ['test_arg0_preflight'],
    'codex-code-mode-host': ['codex-code-mode-host'],
    'codex-shell-escalation': ['codex-execve-wrapper'],
    'codex-rmcp-client': ['test_stdio_server', 'test_streamable_http_server'],
    'codex-exec': ['codex-exec'],
}
records = []
commands = []
command_source_guards = []
baseline = None
env = dict(os.environ)


def now():
    return datetime.now(timezone.utc).isoformat()


def bytes_id(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_id(path, artifact=False):
    path = Path(path)
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode), f'not a regular file: {path}'
    if artifact:
        assert path.resolve() == path and path.is_relative_to(TARGET) and os.access(path, os.X_OK)
    else:
        assert info.st_nlink == 1, f'not an independent owned source/evidence file: {path}'
    digest = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
    count = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            blob.update(chunk)
            count += len(chunk)
    after = path.stat()
    assert (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    assert count == info.st_size
    return {'path': str(path), 'bytes': count, 'sha256': digest.hexdigest(), 'git_blob': blob.hexdigest(),
            'mode': oct(stat.S_IMODE(info.st_mode)), 'dev': info.st_dev, 'inode': info.st_ino,
            'nlink': info.st_nlink}


def equal_content(actual, expected):
    return all(actual[key] == expected[key] for key in ('bytes', 'sha256'))


def save(name, content):
    if isinstance(content, str):
        content = content.encode()
    path = EVIDENCE / name
    with path.open('xb') as stream:
        stream.write(content)
    item = file_id(path)
    records.append(item)
    return item


def save_json(name, value):
    return save(name, json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')


def capacity():
    info = os.statvfs(ROOT)
    result = {'at': now(), 'path': str(ROOT), 'f_bavail': info.f_bavail, 'f_frsize': info.f_frsize,
              'available_bytes': info.f_bavail * info.f_frsize, 'minimum_bytes': 64000000000}
    assert result['available_bytes'] >= result['minimum_bytes'], f'capacity guard: {result}'
    return result


def git(args, index=None):
    actual_env = dict(env)
    actual_env['GIT_OPTIONAL_LOCKS'] = '0'
    if index is not None:
        actual_env['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(['/usr/bin/git', '-C', str(SOURCE), *args], env=actual_env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, f'guard git {args}: exit {result.returncode}: {result.stderr.decode(errors="replace")}'
    return result.stdout


def source_guard(label):
    assert ROOT.resolve() == ROOT and SOURCE.resolve() == SOURCE and TARGET.resolve() == TARGET
    ordinary = file_id(SOURCE / '.git/index')
    assert equal_content(ordinary, baseline['ordinary_index']), 'new-host ordinary index drift; do not reset'
    head = git(['rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
    assert head == [COMMIT, TREE]
    private = EVIDENCE / (label + '.index')
    git(['read-tree', TREE], private)
    git(['add', '-u', '--'], private)
    actual = git(['write-tree'], private).decode().strip()
    assert actual == TREE, f'whole-source drift: {actual}'
    others = git(['ls-files', '--others', '--exclude-standard', '-z'], private)
    assert not others, 'unexpected untracked source input; preserve and stop'
    checked = []
    for expected in baseline['guarded_files']:
        current = file_id(SOURCE / expected['relative_path'])
        assert equal_content(current, expected), expected['relative_path']
        checked.append(current)
    assert equal_content(file_id(SOURCE / '.git/index'), ordinary)
    return save_json(label + '.guard.json', {'head': head[0], 'head_tree': head[1], 'working_tree': actual,
                     'ordinary_index': ordinary, 'guarded_files': checked, 'untracked': [], 'capacity': capacity()})


def run(label, argv):
    before = source_guard(label + '-before')
    command_source_guards.append(before)
    item = {'label': label, 'argv': argv, 'cwd': str(SOURCE / 'codex-rs'), 'started_at': now(),
            'source_before': TREE, 'source_guard_before': before, 'capacity_before': capacity(),
            'cargo_profile': 'dev-small', 'tests_executed': False}
    save_json(label + '.command.json', item)
    stdout = EVIDENCE / (label + '.stdout.original')
    stderr = EVIDENCE / (label + '.stderr.original')
    start = time.monotonic()
    print(json.dumps({'phase_start': label, 'argv': argv, 'source_tree': TREE}), flush=True)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        result = subprocess.run(argv, cwd=SOURCE / 'codex-rs', env=env, stdout=out, stderr=err, check=False)
    out_id, err_id = file_id(stdout), file_id(stderr)
    records.extend([out_id, err_id])
    item.update({'completed_at': now(), 'duration_seconds': time.monotonic() - start,
                 'exit_code': result.returncode, 'stdout': out_id, 'stderr': err_id})
    commands.append(item)
    save_json(label + '.execution.json', item)
    after = source_guard(label + '-after')
    command_source_guards.append(after)
    item.update({'source_after': TREE, 'source_guard_after': after, 'capacity_after': capacity()})
    save_json(label + '.status.json', item)
    print(json.dumps({'phase_terminal': label, 'exit_code': result.returncode,
                      'seconds': item['duration_seconds'], 'source_tree': TREE}), flush=True)
    assert result.returncode == 0, f'{label}: exit {result.returncode}; complete original stdout/stderr preserved'
    return item


def portable_graph(metadata):
    prefix = 'path+file://' + str(SOURCE)
    def normalize(value):
        if value.startswith(prefix + '/'):
            return 'path+file://<SOURCE>' + value[len(prefix):]
        return value
    nodes = []
    for node in metadata['resolve']['nodes']:
        dependencies = [{'name': dep['name'], 'pkg': normalize(dep['pkg']),
                         'dep_kinds': sorted(dep['dep_kinds'], key=lambda x: json.dumps(x, sort_keys=True))}
                        for dep in node['deps']]
        nodes.append({'id': normalize(node['id']), 'features': sorted(node['features']),
                      'deps': sorted(dependencies, key=lambda x: (x['name'], x['pkg']))})
    return {'members': sorted(normalize(x) for x in metadata['workspace_members']),
            'default_members': sorted(normalize(x) for x in metadata['workspace_default_members']),
            'nodes': sorted(nodes, key=lambda x: x['id'])}


def normal_artifacts(command):
    names = {name for binaries in HELPERS.values() for name in binaries}
    messages = [json.loads(line) for line in Path(command['stdout']['path']).read_text().splitlines()]
    assert [m for m in messages if m.get('reason') == 'build-finished'] == [{'reason': 'build-finished', 'success': True}]
    selected = [m for m in messages if m.get('reason') == 'compiler-artifact' and m.get('executable') and m['target']['name'] in names]
    assert len(selected) == 6 and {m['target']['name'] for m in selected} == names
    rows = []
    for message in sorted(selected, key=lambda x: x['target']['name']):
        rows.append({'target': message['target']['name'], 'target_metadata': message['target'],
                     'package_id': message['package_id'], 'features': message['features'],
                     'fresh': message['fresh'], **file_id(message['executable'], artifact=True)})
    save_json('normal-six-before-catalog.json', {'source_tree': TREE, 'compiler_output': command['stdout'],
              'compiler_json_messages': len(messages), 'artifacts': rows})
    return rows


raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-ai395-cold-bootstrap-P4-terminal-v1', 'host_alias': 'ai395',
            'source_commit': COMMIT, 'source_tree': TREE, 'root_execution_guard_blob': GUARD_BLOB,
            'started_at': now(), 'request': bytes_id(raw), 'tests_executed': False,
            'test_qualification': False, 'B_source_applied': False, 'errors': []}
created = False
success = False
try:
    assert request['stage'] == 'P4' and request['root_execution_guard_blob'] == GUARD_BLOB
    assert hashlib.sha256(request['root_execution_guard_text'].encode()).hexdigest() == GUARD_SHA
    assert hashlib.sha256(request['approved_plan_text'].encode()).hexdigest() == PLAN_SHA
    assert json.loads(request['root_execution_guard_text'])['execute']
    assert not os.path.lexists(EVIDENCE)
    assert os.getuid() == 1000 and platform.system() == 'Linux' and platform.machine() == 'x86_64'
    for name in ['RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GIT_INDEX_FILE']:
        assert not os.environ.get(name), f'unexpected nonempty injection environment name: {name}'
    capacity()
    source_bytes = (ROOT / 'evidence/bootstrap-P1-v1/source-baseline.json').read_bytes()
    assert bytes_id(source_bytes) == request['P1_source_baseline_identity']
    baseline = json.loads(source_bytes)
    p3_path = ROOT / 'evidence/bootstrap-P3-supplier-correction-v1/terminal.json'
    p3_bytes = p3_path.read_bytes()
    assert bytes_id(p3_bytes) == request['P3_success_terminal_identity']
    p3 = json.loads(p3_bytes)
    assert p3['success'] and p3['ready_for_P4']
    supply_path = Path(p3['artifact_receipt']['path'])
    assert equal_content(file_id(supply_path), p3['artifact_receipt'])
    supply = json.loads(supply_path.read_bytes())
    for row in supply['assets']:
        assert equal_content(file_id(row['observed']['path']), row['observed'])
    assert equal_content(file_id(supply['official_checksums']['path']), supply['official_checksums'])
    tools_path = ROOT / 'evidence/bootstrap-P2-version-continuation-v1/installed-tools.json'
    tools_bytes = tools_path.read_bytes()
    assert bytes_id(tools_bytes) == request['installed_tools_identity']
    tools_doc = json.loads(tools_bytes)
    tool_rows = []
    for expected in tools_doc['tools']:
        actual = file_id(expected['path'])
        assert equal_content(actual, expected) and os.access(expected['path'], os.X_OK)
        tool_rows.append({'name': expected['name'], 'version_output': expected['version_output'], **actual})
    assert not list(TARGET.iterdir()), 'cold target is not empty before first P4 build; preserve and stop'
    EVIDENCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    save('root-guard.original.json', request['root_execution_guard_text'])
    save('approved-plan.original.json', request['approved_plan_text'])
    host = {'alias': 'ai395', 'uname': list(platform.uname()), 'uid': os.getuid(), 'euid': os.geteuid()}
    save_json('host.original.json', host)
    environment = dict(tools_doc['task_environment'])
    environment.update({'CARGO_TARGET_DIR': str(TARGET), 'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '4',
                        'CARGO_NET_GIT_FETCH_WITH_CLI': 'true', 'NEXTEST_PROFILE': 'local', **supply['environment']})
    env.update(environment)
    save_json('effective-task-environment.json', environment)
    terminal['initial_guard'] = source_guard('initial')
    terminal['tools'] = tool_rows
    terminal['supply_receipt'] = file_id(supply_path)
    helper_argv = ['cargo', 'build', '--locked', '--profile', 'dev-small', '--message-format=json-render-diagnostics']
    for package, binaries in HELPERS.items():
        helper_argv += ['-p', package]
        for binary in binaries:
            helper_argv += ['--bin', binary]
    helper_command = run('01-normal-six-helper-build', helper_argv)
    normal_before = normal_artifacts(helper_command)
    metadata_command = run('02-full-metadata', ['cargo', 'metadata', '--locked', '--format-version=1'])
    metadata = json.loads(Path(metadata_command['stdout']['path']).read_bytes())
    assert metadata['workspace_root'] == str(SOURCE / 'codex-rs') and metadata['target_directory'] == str(TARGET)
    assert len(metadata['workspace_members']) == 193 and len(metadata['resolve']['nodes']) == 1501
    assert sorted(metadata['workspace_default_members']) == sorted(metadata['workspace_members'])
    assert {p['id'] for p in metadata['packages']} == {n['id'] for n in metadata['resolve']['nodes']}
    graph = portable_graph(metadata)
    assert canonical_digest(graph) == request['portable_A_graph_sha256'], 'new-host original full dependency/features graph changed'
    save_json('portable-graph-verification.json', {'source_tree': TREE, 'actual_metadata': metadata_command['stdout'],
              'sha256': canonical_digest(graph), 'normalization': 'Only exact current path+file source prefix becomes <SOURCE>; all registry/git IDs, active features and typed dependency edges retained.',
              'historical_reference': request['graph_reference']})
    catalog_command = run('03-full-unfiltered-catalog', ['cargo', 'nextest', 'list', '--locked', '--cargo-profile', 'dev-small', '--message-format=json'])
    catalog = json.loads(Path(catalog_command['stdout']['path']).read_bytes())
    assert catalog['rust-build-meta']['target-directory'] == str(TARGET)
    assert len(catalog['rust-suites']) == 363
    roles = []
    cases = []
    for sid, suite in sorted(catalog['rust-suites'].items()):
        roles.append([sid, suite['binary-name'], suite['package-name'], suite['kind'], suite['build-platform']])
        for name, case in suite['testcases'].items():
            assert case['filter-match']['status'] == 'matches', 'unexpected full catalog filter'
            cases.append([sid, name, case['ignored']])
    assert collections.Counter(tuple(x) for x in roles) == collections.Counter(tuple(x) for x in request['expected_program_roles'])
    assert canonical_digest(sorted(cases)) == request['complete_A_case_roster_sha256'], 'complete eligible/ignored roster differs'
    counts = {'eligible': sum(not row[2] for row in cases), 'ignored': sum(row[2] for row in cases)}
    assert counts == {'eligible': 19506, 'ignored': 57}
    print(json.dumps({'phase': 'catalog-produced', 'program_roles': len(roles), 'case_roster': counts, 'tests_executed': False}), flush=True)
    programs = []
    for number, (sid, suite) in enumerate(sorted(catalog['rust-suites'].items()), 1):
        programs.append({'binary_id': sid, 'binary_name': suite['binary-name'], 'package_name': suite['package-name'],
                         'kind': suite['kind'], 'build_platform': suite['build-platform'], **file_id(suite['binary-path'], artifact=True)})
        if number % 50 == 0:
            print(json.dumps({'phase': 'hash-current-programs', 'completed': number, 'total': 363}), flush=True)
    helper_paths = {row['path'] for row in normal_before}
    def visit(value):
        if isinstance(value, dict):
            if value.get('kind') == 'bin-exe' and isinstance(value.get('path'), str):
                path = Path(value['path'])
                helper_paths.add(str(path if path.is_absolute() else TARGET / path))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(catalog['rust-build-meta']['non-test-binaries'])
    assert len(helper_paths) == 33
    assert collections.Counter(Path(path).name for path in helper_paths) == collections.Counter(request['expected_helper_basename_roster'])
    helpers = [file_id(path, artifact=True) for path in sorted(helper_paths)]
    normal_after = [{'target': row['target'], **file_id(row['path'], artifact=True)} for row in normal_before]
    save_json('normal-six-after-catalog.json', normal_after)
    final_guard = source_guard('final')
    recipes = []
    locks = {}
    for expected in baseline['guarded_files']:
        path = expected['relative_path']
        actual = file_id(SOURCE / path)
        if path in ('codex-rs/Cargo.lock', 'MODULE.bazel.lock'):
            locks[path] = actual
        else:
            recipes.append({**actual, 'path': path})
    receipt = {'schema': 'hepta-b16-current-host-build-only-baseline-v1', 'role': 'BUILD_ONLY_CURRENT_HOST',
               'tests_executed': False, 'test_qualification': False, 'host': host,
               'cache_owner': {'owned_root': str(ROOT), 'host_alias': 'ai395', 'uid': os.getuid(), 'euid': os.geteuid(),
                               'root_creation_guard': GUARD_BLOB},
               'source_directory': str(SOURCE), 'target_directory': str(TARGET),
               'source_commit': COMMIT, 'source_tree': TREE, 'ordinary_index': file_id(SOURCE / '.git/index'),
               'locks': locks, 'tools': tool_rows, 'recipe_sources': recipes,
               'cargo_profile': 'dev-small', 'environment': environment, 'commands': commands,
               'source_guards': command_source_guards, 'metadata': metadata_command['stdout'], 'catalog': catalog_command['stdout'],
               'normal_helpers_before_catalog': normal_before, 'normal_helpers_after_catalog': normal_after,
               'normal_helper_initial_hashes_preserved_after_catalog': all(equal_content(a, b) for a, b in zip(normal_before, normal_after)),
               'programs_after_catalog': programs, 'helpers_after_catalog': helpers,
               'case_roster_counts': counts, 'case_roster_sha256': canonical_digest(sorted(cases)),
               'initial_guard': terminal['initial_guard'], 'final_guard': final_guard,
               'published_A_head': '0e139b599f0fe451f80fb7db4b2913bb9c679dce',
               'published_A_complete_tree': '091e659e0da6602299fd14cfa93889191405edd8',
               'historical_ROG_test_qualification_not_relabelled': True,
               'future_B_execution_requires_separate_enabled_binding': True}
    assert len(command_source_guards) == 6
    terminal['build_only_baseline'] = save_json('new-host-build-only-baseline.json', receipt)
    terminal['final_guard'] = final_guard
    terminal['capacity_final'] = capacity()
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'completed_at': now(), 'success': success, 'commands': commands,
                     'source_guards': command_source_guards, 'records': list(records)})
    if created:
        terminal_id = save_json('terminal.json', terminal)
        print(json.dumps({'stage': 'P4', 'success': success, 'terminal': terminal_id,
                          'tests_executed': False, 'test_qualification': False, 'errors': terminal['errors']}), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)
