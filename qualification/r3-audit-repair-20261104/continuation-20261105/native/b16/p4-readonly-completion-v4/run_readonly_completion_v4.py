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
EVIDENCE = ROOT / 'evidence/bootstrap-P4-readonly-completion-v4'
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




def verify_openssl_sdk(label, sdk):
    sdk_root = TOOLS / 'openssl-3.5.5-1ubuntu3.7'
    assert sdk_root.resolve() == sdk_root
    actual = {'headers': [], 'libraries': [], 'pkg_config_sources': [], 'packages': [], 'linker_aliases': []}
    for row in sdk['headers']:
        link = Path(row['exposed_path'])
        assert link.is_relative_to(sdk_root) and link.is_symlink()
        assert os.readlink(link) == row['link_target']
        expected = row['official_file']
        assert link.resolve() == Path(expected['path']) and link.resolve().is_relative_to(sdk_root)
        identity = file_id(link.resolve())
        assert equal_content(identity, expected)
        actual['headers'].append({'exposed_path': str(link), 'link_target': os.readlink(link), 'official_file': identity})
    for row in sdk['libraries']:
        observed = {}
        for role in ('private', 'system_readonly'):
            identity = file_id(row[role]['path'])
            assert equal_content(identity, row[role])
            observed[role] = identity
        assert equal_content(observed['private'], observed['system_readonly'])
        actual['libraries'].append(observed)
    for row in sdk['pkg_config_sources']:
        identity = file_id(row['path'])
        assert equal_content(identity, row)
        actual['pkg_config_sources'].append(identity)
    for row in sdk['packages']:
        expected = row['official_download']['package']
        identity = file_id(expected['path'])
        assert equal_content(identity, expected)
        actual['packages'].append(identity)
    for name in ('libssl.so', 'libcrypto.so'):
        alias = Path(sdk['environment']['OPENSSL_LIB_DIR']) / name
        assert alias.is_symlink() and os.readlink(alias) == name + '.3'
        assert alias.resolve() == alias.parent / (name + '.3')
        actual['linker_aliases'].append({'path': str(alias), 'link_target': os.readlink(alias), 'file': file_id(alias.resolve())})
    return save_json(label + '.openssl-sdk-guard.json', actual)


def verify_libcap_sdk(label, cap_sdk):
    sdk_root = TOOLS / 'libcap-2.75-10ubuntu2'
    assert sdk_root.resolve() == sdk_root
    actual = {'headers': [], 'libraries': {}, 'packages': [], 'aliases': [], 'pkg_config': {}}
    assert cap_sdk['version'] == '1:2.75-10ubuntu2'
    assert cap_sdk['environment'] == {'PKG_CONFIG_PATH': str(sdk_root / 'pkgconfig')}
    for expected in cap_sdk['headers']:
        path = Path(expected['path'])
        assert path.is_relative_to(sdk_root)
        observed = file_id(path)
        assert equal_content(observed, expected)
        actual['headers'].append(observed)
    for role in ('private', 'system_readonly'):
        expected = cap_sdk['library'][role]
        observed = file_id(expected['path'])
        assert equal_content(observed, expected)
        actual['libraries'][role] = observed
    assert equal_content(actual['libraries']['private'], actual['libraries']['system_readonly'])
    for package in cap_sdk['packages']:
        expected = package['official_download']['package']
        path = Path(expected['path'])
        assert path.is_relative_to(sdk_root)
        observed = file_id(path)
        assert equal_content(observed, expected)
        actual['packages'].append(observed)
    for row in cap_sdk['aliases']:
        path = Path(row['path'])
        assert path.is_relative_to(sdk_root) and path.is_symlink()
        assert os.readlink(path) == row['link_target'] and path.resolve() == Path(row['resolved_file']['path'])
        observed = file_id(path.resolve())
        assert equal_content(observed, row['resolved_file'])
        actual['aliases'].append({'path': str(path), 'link_target': os.readlink(path), 'resolved_file': observed})
    for name in ('official_pc', 'relocated_pc'):
        expected = cap_sdk[name]
        assert Path(expected['path']).is_relative_to(sdk_root)
        observed = file_id(expected['path'])
        assert equal_content(observed, expected)
        actual['pkg_config'][name] = observed
    tool = cap_sdk['pkg_config_executable']
    path = Path(tool['path'])
    assert str(path) == '/usr/bin/pkg-config' and path.is_symlink() == tool['symlink']
    if path.is_symlink():
        assert os.readlink(path) == tool['link_target']
    observed = file_id(path.resolve())
    assert equal_content(observed, tool['resolved'])
    actual['pkg_config']['executable'] = {'path': str(path), 'link_target': tool['link_target'], 'resolved': observed}
    return save_json(label + '.libcap-sdk-guard.json', actual)


PRIOR = ROOT / 'evidence/bootstrap-P4-libcap-continuation-v3'
raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-P4-readonly-completion-terminal-v4', 'host_alias': 'ai395',
            'source_commit': COMMIT, 'source_tree': TREE, 'started_at': now(),
            'request': bytes_id(raw), 'tests_executed': False, 'test_qualification': False,
            'build_or_list_repeated': False, 'B_source_applied': False, 'errors': []}
created = False
success = False
sdk = None
cap_sdk = None

try:
    assert request['execute'] is True and request['scope'] == 'readonly-P4-v3-completion'
    assert request['source_commit'] == COMMIT and request['source_tree'] == TREE
    assert not os.path.lexists(EVIDENCE)
    assert os.getuid() == 1000 and platform.system() == 'Linux' and platform.machine() == 'x86_64'
    for name in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GIT_INDEX_FILE'):
        assert not os.environ.get(name), 'unexpected injection environment name: ' + name
    capacity()
    prior_pin = request['prior_terminal']
    assert Path(prior_pin['path']) == PRIOR / 'terminal.json'
    assert equal_content(file_id(prior_pin['path']), prior_pin)
    prior = json.loads(Path(prior_pin['path']).read_bytes())
    assert prior['source_tree'] == TREE and prior['source_commit'] == COMMIT
    assert prior['success'] is False and prior['tests_executed'] is False and prior['B_source_applied'] is False
    assert [item['exit_code'] for item in prior['commands']] == [0, 0, 0]
    assert len(prior['errors']) == 1 and prior['errors'][0]['type'] == 'AssertionError'
    assert prior['errors'][0]['message'] == 'unexpected full catalog filter'
    original_pins = {}
    for pin in prior['records']:
        path = Path(pin['path'])
        assert path.parent == PRIOR and path.resolve() == path and path.name not in original_pins
        actual = file_id(path)
        assert equal_content(actual, pin) and actual['git_blob'] == pin['git_blob'], path.name
        original_pins[path.name] = pin
    prior_request_pin = original_pins['request.original.json']
    assert equal_content(prior_request_pin, request['prior_request'])
    prior_request = json.loads(Path(prior_request_pin['path']).read_bytes())
    assert prior_request['root_execution_guard_blob'] == GUARD_BLOB
    assert hashlib.sha256(prior_request['root_execution_guard_text'].encode()).hexdigest() == GUARD_SHA
    assert hashlib.sha256(prior_request['approved_plan_text'].encode()).hexdigest() == PLAN_SHA
    assert json.loads(prior_request['root_execution_guard_text'])['execute'] is True
    source_bytes = (ROOT / 'evidence/bootstrap-P1-v1/source-baseline.json').read_bytes()
    assert bytes_id(source_bytes) == prior_request['P1_source_baseline_identity']
    baseline = json.loads(source_bytes)
    assert len(prior['source_guards']) == 6 and len({p['path'] for p in prior['source_guards']}) == 6
    for pin in prior['source_guards']:
        assert original_pins[Path(pin['path']).name] == pin
        guard = json.loads(Path(pin['path']).read_bytes())
        assert guard['head'] == COMMIT and guard['head_tree'] == guard['working_tree'] == TREE
        assert equal_content(guard['ordinary_index'], baseline['ordinary_index']) and guard['untracked'] == []
    commands = prior['commands']
    command_source_guards = prior['source_guards']
    expected_helper_argv = ['cargo', 'build', '--locked', '--profile', 'dev-small', '--message-format=json-render-diagnostics']
    for package, binaries in HELPERS.items():
        expected_helper_argv += ['-p', package]
        for binary in binaries:
            expected_helper_argv += ['--bin', binary]
    expected_argvs = [expected_helper_argv, ['cargo', 'metadata', '--locked', '--format-version=1'],
                     ['cargo', 'nextest', 'list', '--locked', '--cargo-profile', 'dev-small', '--message-format=json']]
    for index, (command, expected_argv) in enumerate(zip(commands, expected_argvs, strict=True)):
        assert command['argv'] == expected_argv and command['cwd'] == str(SOURCE / 'codex-rs')
        assert command['source_before'] == command['source_after'] == TREE and command['tests_executed'] is False
        assert command['source_guard_before'] == command_source_guards[index * 2]
        assert command['source_guard_after'] == command_source_guards[index * 2 + 1]
        for stream in ('stdout', 'stderr'):
            assert original_pins[Path(command[stream]['path']).name] == command[stream]
    tools_path = ROOT / 'evidence/bootstrap-P2-version-continuation-v1/installed-tools.json'
    tools_bytes = tools_path.read_bytes()
    assert bytes_id(tools_bytes) == prior_request['installed_tools_identity']
    tools_doc = json.loads(tools_bytes)
    tool_rows = []
    for expected in tools_doc['tools']:
        observed = file_id(expected['path'])
        assert equal_content(observed, expected) and os.access(expected['path'], os.X_OK)
        tool_rows.append({'name': expected['name'], 'version_output': expected['version_output'], **observed})
    assert equal_content(file_id(prior['supply_receipt']['path']), prior['supply_receipt'])
    supply = json.loads(Path(prior['supply_receipt']['path']).read_bytes())
    for row in supply['assets']:
        assert equal_content(file_id(row['observed']['path']), row['observed'])
    assert equal_content(file_id(supply['official_checksums']['path']), supply['official_checksums'])
    sdk_path = Path(prior['openssl_sdk_receipt']['path'])
    assert equal_content(file_id(sdk_path), prior['openssl_sdk_receipt'])
    assert bytes_id(sdk_path.read_bytes()) == prior_request['openssl_sdk_identity']
    sdk = json.loads(sdk_path.read_bytes())
    cap_path = Path(prior['libcap_sdk_receipt']['path'])
    assert equal_content(file_id(cap_path), prior['libcap_sdk_receipt'])
    assert bytes_id(cap_path.read_bytes()) == prior_request['libcap_sdk_identity']
    cap_sdk = json.loads(cap_path.read_bytes())
    expected_environment = dict(tools_doc['task_environment'])
    expected_environment.update({'CARGO_TARGET_DIR': str(TARGET), 'CARGO_INCREMENTAL': '0', 'CARGO_BUILD_JOBS': '4',
        'CARGO_NET_GIT_FETCH_WITH_CLI': 'true', 'NEXTEST_PROFILE': 'local', **supply['environment'],
        **sdk['environment'], **cap_sdk['environment']})
    environment = json.loads(Path(original_pins['effective-task-environment.json']['path']).read_bytes())
    assert environment == expected_environment
    for name in ('OPENSSL_DIR', 'OPENSSL_INCLUDE_DIR', 'OPENSSL_LIB_DIR', 'OPENSSL_STATIC', 'OPENSSL_DYNAMIC',
                 'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR'):
        assert not os.environ.get(name), 'unexpected inherited prerequisite override: ' + name
    env.update(environment)
    host = json.loads(Path(original_pins['host.original.json']['path']).read_bytes())
    assert host == {'alias': 'ai395', 'uname': list(platform.uname()), 'uid': os.getuid(), 'euid': os.geteuid()}
    EVIDENCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    terminal['prior_failed_controller_terminal'] = prior_pin
    terminal['original_records_verified'] = len(original_pins)
    terminal['initial_guard'] = source_guard('completion-initial')
    terminal['openssl_initial_guard'] = verify_openssl_sdk('completion-initial', sdk)
    terminal['libcap_initial_guard'] = verify_libcap_sdk('completion-initial', cap_sdk)
    terminal['tools_initial'] = save_json('tools-initial.json', tool_rows)
    normal_pin = original_pins['normal-six-before-catalog.json']
    normal_doc = json.loads(Path(normal_pin['path']).read_bytes())
    assert normal_doc['source_tree'] == TREE and normal_doc['compiler_output'] == commands[0]['stdout']
    normal_before = normal_doc['artifacts']
    messages = [json.loads(line) for line in Path(commands[0]['stdout']['path']).read_text().splitlines()]
    assert len(messages) == normal_doc['compiler_json_messages']
    assert [m for m in messages if m.get('reason') == 'build-finished'] == [{'reason': 'build-finished', 'success': True}]
    names = {name for values in HELPERS.values() for name in values}
    built = [m for m in messages if m.get('reason') == 'compiler-artifact' and m.get('executable') and m['target']['name'] in names]
    assert len(normal_before) == len(built) == 6 and {row['target'] for row in normal_before} == names
    for row in normal_before:
        matching = [m for m in built if m['target']['name'] == row['target']]
        assert len(matching) == 1 and matching[0]['executable'] == row['path']
        assert matching[0]['target'] == row['target_metadata']
        assert all(matching[0][key] == row[key] for key in ('package_id', 'features', 'fresh'))
        assert row['bytes'] > 0 and len(row['sha256']) == 64
    metadata = json.loads(Path(commands[1]['stdout']['path']).read_bytes())
    assert metadata['workspace_root'] == str(SOURCE / 'codex-rs') and metadata['target_directory'] == str(TARGET)
    assert len(metadata['workspace_members']) == 193 and len(metadata['resolve']['nodes']) == 1501
    assert sorted(metadata['workspace_default_members']) == sorted(metadata['workspace_members'])
    assert {p['id'] for p in metadata['packages']} == {n['id'] for n in metadata['resolve']['nodes']}
    assert canonical_digest(portable_graph(metadata)) == prior_request['portable_A_graph_sha256']
    catalog = json.loads(Path(commands[2]['stdout']['path']).read_bytes())
    assert catalog['rust-build-meta']['target-directory'] == str(TARGET) and len(catalog['rust-suites']) == 363
    roles, cases = [], []
    ignored_cases = []
    filters = collections.Counter()
    for sid, suite in sorted(catalog['rust-suites'].items()):
        roles.append([sid, suite['binary-name'], suite['package-name'], suite['kind'], suite['build-platform']])
        for name, case in suite['testcases'].items():
            assert ((case['ignored'] is False and case['filter-match'] == {'status': 'matches'}) or
                    (case['ignored'] is True and case['filter-match'] == {'status': 'mismatch', 'reason': 'ignored'})), (sid, name, case)
            cases.append([sid, name, case['ignored']])
            if case['ignored'] is True:
                ignored_cases.append([sid, name, True])
            filters[(case['ignored'], json.dumps(case['filter-match'], sort_keys=True))] += 1
    assert collections.Counter(tuple(row) for row in roles) == collections.Counter(tuple(row) for row in prior_request['expected_program_roles'])
    assert canonical_digest(sorted(cases)) == prior_request['complete_A_case_roster_sha256']
    assert collections.Counter(tuple(row) for row in ignored_cases) == collections.Counter(tuple(row) for row in request['exact_original_ignored_cases'])
    counts = {'eligible': sum(row[2] is False for row in cases), 'ignored': sum(row[2] is True for row in cases)}
    assert counts == {'eligible': 19506, 'ignored': 57}
    terminal['catalog_verification'] = save_json('catalog-verification.json', {'source_tree': TREE,
        'catalog': commands[2]['stdout'], 'program_roles': len(roles), 'counts': counts,
        'case_roster_sha256': canonical_digest(sorted(cases)), 'ignored_cases': sorted(ignored_cases),
        'frozen_ignored_reference': request['ignored_reference'], 'nonignored_mismatches': 0,
        'allowed_filter_forms_only': True, 'normal_before_original_pin': normal_pin,
        'original_controller_failure_preserved': True, 'build_or_list_repeated': False})
    programs = []
    for number, (sid, suite) in enumerate(sorted(catalog['rust-suites'].items()), 1):
        programs.append({'binary_id': sid, 'binary_name': suite['binary-name'], 'package_name': suite['package-name'],
            'kind': suite['kind'], 'build_platform': suite['build-platform'], **file_id(suite['binary-path'], artifact=True)})
        if number % 50 == 0:
            print(json.dumps({'phase': 'readonly-current-program-hash', 'completed': number, 'total': 363}), flush=True)
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
    assert collections.Counter(Path(path).name for path in helper_paths) == collections.Counter(prior_request['expected_helper_basename_roster'])
    helpers = [file_id(path, artifact=True) for path in sorted(helper_paths)]
    normal_after = [{'target': row['target'], **file_id(row['path'], artifact=True)} for row in normal_before]
    save_json('normal-six-current-after-catalog.json', normal_after)
    save_json('programs-current-after-catalog.json', programs)
    save_json('helpers-current-after-catalog.json', helpers)
    terminal['openssl_final_guard'] = verify_openssl_sdk('completion-final', sdk)
    terminal['libcap_final_guard'] = verify_libcap_sdk('completion-final', cap_sdk)
    for expected in tool_rows:
        assert equal_content(file_id(expected['path']), expected) and os.access(expected['path'], os.X_OK)
    terminal['final_guard'] = source_guard('completion-final')
    recipes, locks = [], {}
    for expected in baseline['guarded_files']:
        path = expected['relative_path']
        observed = file_id(SOURCE / path)
        if path in ('codex-rs/Cargo.lock', 'MODULE.bazel.lock'):
            locks[path] = observed
        else:
            recipes.append({**observed, 'path': path})
    for path in ('scripts/check-module-bazel-lock.sh', '.bazelrc', 'defs.bzl'):
        assert path not in {row['path'] for row in recipes}
        recipes.append({**file_id(SOURCE / path), 'path': path})
    receipt = {'schema': 'hepta-b16-current-host-build-only-baseline-v1', 'role': 'BUILD_ONLY_CURRENT_HOST',
        'tests_executed': False, 'test_qualification': False, 'host': host,
        'cache_owner': {'owned_root': str(ROOT), 'host_alias': 'ai395', 'uid': os.getuid(), 'euid': os.geteuid(), 'root_creation_guard': GUARD_BLOB},
        'source_directory': str(SOURCE), 'target_directory': str(TARGET), 'source_commit': COMMIT, 'source_tree': TREE,
        'ordinary_index': file_id(SOURCE / '.git/index'), 'locks': locks, 'tools': tool_rows, 'recipe_sources': recipes,
        'cargo_profile': 'dev-small', 'environment': environment, 'commands': commands, 'source_guards': command_source_guards,
        'metadata': commands[1]['stdout'], 'catalog': commands[2]['stdout'],
        'normal_helpers_before_catalog': normal_before, 'normal_helpers_before_catalog_original': normal_pin,
        'normal_helpers_after_catalog': normal_after,
        'normal_helper_initial_hashes_preserved_after_catalog': all(equal_content(a, b) for a, b in zip(normal_before, normal_after, strict=True)),
        'programs_after_catalog': programs, 'helpers_after_catalog': helpers,
        'case_roster_counts': counts, 'case_roster_sha256': canonical_digest(sorted(cases)),
        'initial_guard': terminal['initial_guard'], 'final_guard': terminal['final_guard'],
        'completion_source_guards': [terminal['initial_guard'], terminal['final_guard']],
        'historical_ROG_test_qualification_not_relabelled': True, 'future_B_execution_requires_separate_enabled_binding': True,
        'published_A_head': '0e139b599f0fe451f80fb7db4b2913bb9c679dce',
        'published_A_complete_tree': '091e659e0da6602299fd14cfa93889191405edd8', 'published_A_reference_is_historical_source_freeze': True,
        'prior_failed_P4': prior['prior_failed_P4'], 'prior_successful_commands_controller_failure': prior_pin,
        'readonly_completion': {'original_commands_not_repeated': True, 'completed_at': now(),
            'current_artifacts_observed_after_original_catalog_at_completion': True, 'request': bytes_id(raw),
            'original_environment_unchanged': True, 'original_six_source_guards_unchanged': True},
        'external_build_prerequisites': {
            'openssl': {'receipt': file_id(sdk_path), 'initial_guard': terminal['openssl_initial_guard'],
                'final_guard': terminal['openssl_final_guard'], 'environment': sdk['environment'], 'pkg_config_relocation_is_preparation_only': True},
            'libcap': {'receipt': file_id(cap_path), 'initial_guard': terminal['libcap_initial_guard'],
                'final_guard': terminal['libcap_final_guard'], 'environment': cap_sdk['environment'], 'relocation_is_used_by_actual_cargo_environment': True}},
        'original_external_prerequisite_guards': {key: prior[key] for key in ('openssl_initial_guard', 'openssl_final_guard', 'libcap_initial_guard', 'libcap_final_guard')},
        'warm_cache_preparation': True, 'all_three_commands_use_same_actual_environment': True}
    terminal['build_only_baseline'] = save_json('new-host-build-only-baseline.json', receipt)
    terminal['capacity_final'] = capacity()
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    if created:
        for name, value, checker in (('openssl', sdk, verify_openssl_sdk), ('libcap', cap_sdk, verify_libcap_sdk)):
            if value is not None and name + '_final_guard' not in terminal:
                try:
                    terminal[name + '_final_guard'] = checker('completion-terminal', value)
                except Exception as error:
                    success = False
                    terminal['errors'].append({'type': type(error).__name__, 'message': name + ' final guard: ' + str(error), 'traceback': traceback.format_exc()})
        if baseline is not None and 'final_guard' not in terminal:
            try:
                terminal['final_guard'] = source_guard('completion-terminal')
            except Exception as error:
                success = False
                terminal['errors'].append({'type': type(error).__name__, 'message': 'source terminal guard: ' + str(error), 'traceback': traceback.format_exc()})
    terminal.update({'completed_at': now(), 'success': success, 'records': list(records),
        'original_commands': commands, 'original_source_guards': command_source_guards})
    if created:
        terminal_pin = save_json('terminal.json', terminal)
        print(json.dumps({'success': success, 'terminal': terminal_pin, 'build_only_baseline': terminal.get('build_only_baseline'),
            'tests_executed': False, 'commands_repeated': False, 'errors': terminal['errors']}), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)
