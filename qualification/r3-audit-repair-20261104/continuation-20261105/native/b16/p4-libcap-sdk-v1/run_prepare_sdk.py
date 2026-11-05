import posixpath
import tarfile
import urllib.request
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
EVIDENCE = ROOT / 'evidence/bootstrap-P4-libcap-sdk-v1'
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


SDK = TOOLS / 'libcap-2.75-10ubuntu2'
VERSION = '1:2.75-10ubuntu2'
created = False
success = False
raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-ai395-official-libcap-private-sdk-v1', 'started_at': now(), 'source_tree': TREE,
            'request': bytes_id(raw), 'tests_executed': False, 'build_executed': False, 'system_install': False, 'errors': []}
try:
    assert request['execute'] is True and request['root_execution_guard_blob'] == GUARD_BLOB
    assert os.getuid() == os.geteuid() == 1000 and platform.system() == 'Linux' and platform.machine() == 'x86_64'
    assert not os.path.lexists(EVIDENCE) and not os.path.lexists(SDK)
    capacity()
    raw_baseline = (ROOT / 'evidence/bootstrap-P1-v1/source-baseline.json').read_bytes()
    assert bytes_id(raw_baseline) == request['P1_source_baseline_identity']
    baseline = json.loads(raw_baseline)
    previous = ROOT / 'evidence/bootstrap-P4-openssl-continuation-v2/terminal.json'
    assert equal_content(file_id(previous), request['prior_failed_terminal'])
    old = json.loads(previous.read_text())
    assert not old['success'] and [x['exit_code'] for x in old['commands']] == [0, 0, 101] and not old['tests_executed']
    readonly = ROOT / 'evidence/bootstrap-P4-libcap-readonly-v1/terminal.json'
    assert equal_content(file_id(readonly), request['readonly_terminal'])
    inspected = json.loads(readonly.read_text())
    assert inspected['success'] and inspected['version'] == VERSION
    assert not any(key in env for key in ('CODEX_SKIP_BWRAP_BUILD', 'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR', 'PKG_CONFIG_PATH'))
    EVIDENCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    terminal['initial_guard'] = source_guard('initial')
    installed = run('01-installed-runtime-version', ['/usr/bin/dpkg-query', '-W', '-f=${Version}', 'libcap2'])
    assert Path(installed['stdout']['path']).read_text() == VERSION
    SDK.mkdir(mode=0o700)
    downloads = SDK / 'downloads'
    sysroot = SDK / 'sysroot'
    downloads.mkdir(mode=0o700)
    sysroot.mkdir(mode=0o700)
    packages = []
    for expected in request['packages']:
        package = expected['name']
        assert package in ('libcap-dev', 'libcap2')
        metadata_path = ROOT / ('evidence/bootstrap-P4-libcap-readonly-v1/' + package + '-official-metadata.stdout.original')
        assert equal_content(file_id(metadata_path), expected['metadata'])
        metadata = metadata_path.read_text()
        meta = dict(line.split(': ', 1) for line in metadata.splitlines() if line and not line[0].isspace() and ': ' in line)
        assert meta['Package'] == package and meta['Version'] == VERSION and meta['Architecture'] == 'amd64' and meta['Origin'] == 'Ubuntu'
        assert meta['Filename'] == expected['filename'] and meta['SHA256'] == expected['sha256'] and int(meta['Size']) == expected['bytes']
        assert meta['Filename'].startswith('pool/main/libc/libcap2/')
        save(package + '-official-package-metadata.original', metadata_path.read_bytes())
        url = 'https://archive.ubuntu.com/ubuntu/' + meta['Filename']
        destination = downloads / Path(meta['Filename']).name
        start = time.monotonic()
        with urllib.request.urlopen(url, timeout=60) as response, destination.open('xb') as stream:
            assert response.status == 200
            observed = 0
            while chunk := response.read(1024 * 1024):
                observed += len(chunk)
                assert observed <= expected['bytes']
                stream.write(chunk)
            download = {'url': url, 'final_url': response.url, 'http_status': response.status,
                        'duration_seconds': time.monotonic() - start, 'package': file_id(destination)}
        assert equal_content(download['package'], expected)
        save_json(package + '-download.json', download)
        archive = EVIDENCE / (package + '.data.tar')
        error_path = EVIDENCE / (package + '.data-tar.stderr.original')
        with archive.open('xb') as out, error_path.open('xb') as err:
            result = subprocess.run(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(destination)], stdout=out, stderr=err, check=False)
        records.extend([file_id(archive), file_id(error_path)])
        assert result.returncode == 0
        members = []
        with tarfile.open(archive, 'r:') as data_tar:
            for member in data_tar.getmembers():
                name = posixpath.normpath(member.name)
                assert not name.startswith('/') and name != '..' and not name.startswith('../')
                assert member.isdir() or member.isfile() or member.issym() or member.islnk(), member.name
                if member.issym() or member.islnk():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname)) if member.issym() else posixpath.normpath(member.linkname)
                    assert not member.linkname.startswith('/') and target != '..' and not target.startswith('../')
                members.append({'name': member.name, 'bytes': member.size, 'mode': oct(member.mode), 'type': member.type.decode('ascii'), 'linkname': member.linkname})
        save_json(package + '-data-members.json', members)
        extract = run(package + '-data-only-extract', ['/usr/bin/dpkg-deb', '--extract', str(destination), str(sysroot)])
        packages.append({'name': package, 'version': VERSION, 'official_metadata': file_id(metadata_path),
                         'official_download': download, 'data_archive': file_id(archive), 'extract': extract})
    lib = sysroot / 'usr/lib/x86_64-linux-gnu'
    include = sysroot / 'usr/include'
    assert (include / 'sys/capability.h').is_file()
    headers = []
    for path in sorted(include.rglob('*')):
        if path.is_file():
            assert not path.is_symlink() and path.resolve().is_relative_to(sysroot)
            headers.append(file_id(path))
    private = file_id(lib / 'libcap.so.2.75')
    system = file_id('/usr/lib/x86_64-linux-gnu/libcap.so.2.75')
    assert private['sha256'] == system['sha256'] == 'c5b463a8136dabb152bad8b04e89bf67bd2049ef49777ed0b96bdbc6cb5b9565'
    aliases = []
    for name in ('libcap.so', 'libcap.so.2'):
        path = lib / name
        assert path.is_symlink() and path.resolve() == lib / 'libcap.so.2.75'
        aliases.append({'path': str(path), 'link_target': os.readlink(path), 'resolved_file': private})
    original_pc = lib / 'pkgconfig/libcap.pc'
    original = original_pc.read_bytes()
    save('libcap.pc.official.original', original)
    substitutions = {'prefix': str(sysroot / 'usr'), 'libdir': str(lib), 'includedir': str(include)}
    lines = original.decode().splitlines(keepends=True)
    changes = []
    for variable, value in substitutions.items():
        matches = [i for i, line in enumerate(lines) if line.startswith(variable + '=')]
        assert len(matches) == 1, (variable, matches)
        index = matches[0]
        before = lines[index]
        after = variable + '=' + value + ('\n' if before.endswith('\n') else '')
        lines[index] = after
        changes.append({'variable': variable, 'before': before, 'after': after})
    pc_directory = SDK / 'pkgconfig'
    pc_directory.mkdir(mode=0o700)
    relocated_pc = pc_directory / 'libcap.pc'
    with relocated_pc.open('xb') as out:
        out.write(''.join(lines).encode())
    save_json('libcap-pc-relocation.json', {'official': file_id(original_pc), 'relocated': file_id(relocated_pc), 'only_changed_lines': changes})
    pkg_config_path = Path('/usr/bin/pkg-config')
    pkg_config_identity = {'path': str(pkg_config_path), 'symlink': pkg_config_path.is_symlink(),
                           'link_target': os.readlink(pkg_config_path) if pkg_config_path.is_symlink() else None,
                           'resolved': file_id(pkg_config_path.resolve())}
    env['PKG_CONFIG_PATH'] = str(pc_directory)
    version_command = run('pkg-config-libcap-version', ['/usr/bin/pkg-config', '--modversion', 'libcap'])
    assert Path(version_command['stdout']['path']).read_text().strip() == '2.75'
    flags_command = run('pkg-config-libcap-relocated-flags', ['/usr/bin/pkg-config', '--libs', '--cflags', 'libcap'])
    flags = Path(flags_command['stdout']['path']).read_text().split()
    assert '-I' + str(include) in flags and '-L' + str(lib) in flags and '-lcap' in flags
    assert all(not x.startswith('-I') or x == '-I' + str(include) for x in flags)
    assert all(not x.startswith('-L') or x == '-L' + str(lib) for x in flags)
    terminal['final_guard'] = source_guard('final')
    receipt = {'schema': 'hepta-official-libcap-private-sdk-v1', 'host_alias': 'ai395', 'version': VERSION,
               'source_tree': TREE, 'packages': packages, 'headers': headers, 'library': {'private': private, 'system_readonly': system, 'byte_equal': True},
               'aliases': aliases, 'pkg_config_executable': pkg_config_identity, 'official_pc': file_id(original_pc),
               'relocated_pc': file_id(relocated_pc), 'relocation': changes, 'pkg_config_commands': [version_command, flags_command],
               'environment': {'PKG_CONFIG_PATH': str(pc_directory)}, 'global_sysroot_set': False, 'default_system_search_preserved': True,
               'source_or_lock_change': False, 'system_mutation': False, 'tests_executed': False, 'build_executed': False}
    terminal['sdk_receipt'] = save_json('libcap-sdk.json', receipt)
    success = True
except Exception as e:
    terminal['errors'].append({'type': type(e).__name__, 'message': str(e), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'success': success, 'completed_at': now(), 'commands': commands, 'records': list(records)})
    if created:
        item = save_json('terminal.json', terminal)
        print(json.dumps({'success': success, 'terminal': item, 'sdk_receipt': terminal.get('sdk_receipt'), 'errors': terminal['errors']}), flush=True)
    else:
        print(json.dumps(terminal), flush=True)
sys.exit(0 if success else 1)
