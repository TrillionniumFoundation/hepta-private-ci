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
EVIDENCE = ROOT / 'evidence/bootstrap-P4-openssl-sdk-v1'
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


SDK = TOOLS / 'openssl-3.5.5-1ubuntu3.7'
VERSION = '3.5.5-1ubuntu3.7'
created = False
success = False
raw = sys.stdin.buffer.read()
request = json.loads(raw)
terminal = {'schema': 'hepta-ai395-official-openssl-sdk-v1', 'started_at': now(),
            'request': bytes_id(raw), 'source_tree': TREE, 'tests_executed': False,
            'build_executed': False, 'system_install': False, 'errors': []}
try:
    assert request['execute'] is True
    assert request['root_execution_guard_blob'] == GUARD_BLOB
    assert os.getuid() == os.geteuid() == 1000 and platform.system() == 'Linux' and platform.machine() == 'x86_64'
    assert not os.path.lexists(EVIDENCE) and not os.path.lexists(SDK)
    capacity()
    base_bytes = (ROOT / 'evidence/bootstrap-P1-v1/source-baseline.json').read_bytes()
    assert bytes_id(base_bytes) == request['P1_source_baseline_identity']
    baseline = json.loads(base_bytes)
    failed_bytes = (ROOT / 'evidence/bootstrap-P4-v1/terminal.json').read_bytes()
    assert bytes_id(failed_bytes) == request['failed_P4_terminal_identity']
    failed = json.loads(failed_bytes)
    assert not failed['success'] and failed['commands'][0]['exit_code'] == 101
    assert not failed['tests_executed'] and len(failed['commands']) == 1
    EVIDENCE.mkdir(mode=0o700)
    created = True
    save('request.original.json', raw)
    terminal['initial_guard'] = source_guard('initial')
    installed = run('01-installed-runtime-version', ['/usr/bin/dpkg-query', '-W', '-f=${Version}', 'libssl3t64'])
    assert Path(installed['stdout']['path']).read_text() == VERSION
    SDK.mkdir(mode=0o700)
    downloads = SDK / 'downloads'
    downloads.mkdir(mode=0o700)
    sysroot = SDK / 'sysroot'
    sysroot.mkdir(mode=0o700)
    packages = []
    for package in ('libssl-dev', 'libssl3t64'):
        command = run(package + '-metadata', ['/usr/bin/apt-cache', 'show', '--no-all-versions', package + '=' + VERSION])
        metadata = Path(command['stdout']['path']).read_text()
        parsed = []
        for stanza in metadata.strip().split('\n\n'):
            fields = dict(line.split(': ', 1) for line in stanza.splitlines() if line and not line[0].isspace() and ': ' in line)
            if fields.get('Package') == package and fields.get('Version') == VERSION and fields.get('Architecture') == 'amd64' and fields.get('Filename'):
                parsed.append(fields)
        assert len(parsed) == 1, parsed
        meta = parsed[0]
        assert meta.get('Origin') == 'Ubuntu' and meta['Filename'].startswith('pool/main/o/openssl/')
        assert meta['Filename'].split('/')[-1] == package + '_' + VERSION + '_amd64.deb'
        assert len(meta['SHA256']) == 64 and 0 < int(meta['Size']) < 20000000
        if package == 'libssl-dev':
            assert meta['SHA256'] == 'd1cf6cafb141490b7020e392964b1f901835d60cb88c3a68ef0f95ef5e930de4' and int(meta['Size']) == 2936724
        url = 'https://archive.ubuntu.com/ubuntu/' + meta['Filename']
        destination = downloads / Path(meta['Filename']).name
        started = time.monotonic()
        with urllib.request.urlopen(url, timeout=60) as response, destination.open('xb') as stream:
            assert response.status == 200
            observed = 0
            while chunk := response.read(1024 * 1024):
                observed += len(chunk)
                assert observed <= int(meta['Size']), 'official package exceeds pinned size'
                stream.write(chunk)
            download = {'url': url, 'final_url': response.url, 'http_status': response.status,
                        'duration_seconds': time.monotonic() - started, 'package': file_id(destination)}
        assert download['package']['bytes'] == int(meta['Size']) and download['package']['sha256'] == meta['SHA256']
        save_json(package + '-download.json', download)
        archive = EVIDENCE / (package + '.data.tar')
        archive_err = EVIDENCE / (package + '.data-tar.stderr.original')
        with archive.open('xb') as out, archive_err.open('xb') as err:
            result = subprocess.run(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(destination)], stdout=out, stderr=err, check=False)
        records.extend([file_id(archive), file_id(archive_err)])
        assert result.returncode == 0
        members = []
        with tarfile.open(archive, 'r:') as data_tar:
            for member in data_tar.getmembers():
                name = posixpath.normpath(member.name)
                assert not name.startswith('/') and name != '..' and not name.startswith('../')
                assert member.isdir() or member.isfile() or member.issym() or member.islnk(), member.name
                if member.issym() or member.islnk():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname)) if member.issym() else posixpath.normpath(member.linkname)
                    assert not member.linkname.startswith('/') and target != '..' and not target.startswith('../'), member.name
                members.append({'name': member.name, 'bytes': member.size, 'mode': oct(member.mode),
                                'type': member.type.decode('ascii'), 'linkname': member.linkname})
        save_json(package + '-data-members.json', members)
        extract = run(package + '-data-only-extract', ['/usr/bin/dpkg-deb', '--extract', str(destination), str(sysroot)])
        packages.append({'name': package, 'version': VERSION, 'metadata_command': command,
                         'official_download': download, 'data_archive': file_id(archive), 'extract': extract})
    include = SDK / 'include'
    headers = include / 'openssl'
    headers.mkdir(parents=True, mode=0o700)
    header_map = []
    for directory in (sysroot / 'usr/include/openssl', sysroot / 'usr/include/x86_64-linux-gnu/openssl'):
        assert directory.is_dir()
        for path in sorted(directory.iterdir()):
            assert path.is_file() and path.resolve().is_relative_to(sysroot)
            identity = file_id(path.resolve())
            link = headers / path.name
            if os.path.lexists(link):
                assert equal_content(file_id(link.resolve()), identity), 'different official headers share basename'
            else:
                os.symlink(os.path.relpath(path, headers), link)
            assert link.resolve() == path.resolve()
            header_map.append({'exposed_path': str(link), 'link_target': os.readlink(link), 'official_file': identity})
    save_json('unmodified-header-relocation-map.json', header_map)
    lib = sysroot / 'usr/lib/x86_64-linux-gnu'
    runtime = []
    for name, expected_sha in [('libssl.so.3', '63b47f444efa588e291e9b650a5ba2ab02f856356f2d50f13a2e477db9119e09'),
                               ('libcrypto.so.3', '5385f0436ac2e284ba8c5fb1488874057c29c04be72dea32add832694f381e28')]:
        private = file_id(lib / name)
        system = file_id(Path('/usr/lib/x86_64-linux-gnu') / name)
        assert private['sha256'] == system['sha256'] == expected_sha
        runtime.append({'private': private, 'system_readonly': system, 'byte_equal': True})
    for name in ('libssl.so', 'libcrypto.so'):
        assert (lib / name).is_symlink() and (lib / name).resolve().is_relative_to(sysroot)
    pc_files = [file_id(lib / 'pkgconfig' / name) for name in ('openssl.pc', 'libssl.pc', 'libcrypto.pc')]
    for row in pc_files:
        save(Path(row['path']).name + '.original', Path(row['path']).read_bytes())
    # Verify the distribution's real .pc records using pkg-config's supported relocation variables.
    env.update({'PKG_CONFIG_LIBDIR': str(lib / 'pkgconfig'), 'PKG_CONFIG_PATH': ''})
    pc = ['/usr/bin/pkg-config', '--define-variable=prefix=' + str(sysroot / 'usr'),
          '--define-variable=includedir=' + str(include), '--define-variable=libdir=' + str(lib)]
    pc_version = run('pkg-config-version', pc + ['--modversion', 'openssl'])
    assert Path(pc_version['stdout']['path']).read_text().strip() == '3.5.5'
    pc_flags = run('pkg-config-relocated-flags', pc + ['--libs', '--cflags', 'openssl'])
    flags = Path(pc_flags['stdout']['path']).read_text()
    assert '-I' + str(include) in flags and '-L' + str(lib) in flags and '-lssl' in flags and '-lcrypto' in flags
    environment = {'OPENSSL_INCLUDE_DIR': str(include), 'OPENSSL_LIB_DIR': str(lib)}
    terminal['final_guard'] = source_guard('final')
    sdk_receipt = {'schema': 'hepta-official-openssl-private-sdk-v1', 'host_alias': 'ai395',
        'version': VERSION, 'source_tree': TREE, 'packages': packages, 'headers': header_map,
        'libraries': runtime, 'pkg_config_sources': pc_files, 'pkg_config_commands': [pc_version, pc_flags],
        'environment': environment, 'header_bytes_modified': False,
        'header_layout': 'Read-only relative symlinks expose the official common and multiarch headers in one private include directory; original package bytes remain in sysroot.',
        'system_mutation': False, 'cargo_features_changed': False, 'source_or_lock_change': False,
        'tests_executed': False, 'build_executed': False}
    terminal['sdk_receipt'] = save_json('openssl-sdk.json', sdk_receipt)
    success = True
except Exception as error:
    terminal['errors'].append({'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
finally:
    terminal.update({'completed_at': now(), 'success': success, 'commands': commands, 'records': list(records)})
    if created:
        receipt = save_json('terminal.json', terminal)
        print(json.dumps({'success': success, 'terminal': receipt, 'sdk_receipt': terminal.get('sdk_receipt'), 'errors': terminal['errors']}), flush=True)
    else:
        print(json.dumps(terminal, sort_keys=True), flush=True)
sys.exit(0 if success else 1)


