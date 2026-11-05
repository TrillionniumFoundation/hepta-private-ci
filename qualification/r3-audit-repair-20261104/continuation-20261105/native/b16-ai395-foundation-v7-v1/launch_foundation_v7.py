"""Install frozen V7 and execute only a root-enabled ai395 foundation epoch.
Actual current-host build-only evidence remains separate from historical A tests.
"""
import base64
import datetime
import gzip
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

ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
TOOLS = ROOT / 'tools'
TARGET = ROOT / 'target-dev-small'
EVIDENCE = ROOT / 'evidence/b16-foundation-v7-ai395-20261105-v1'
RUNTIME = EVIDENCE / 'runtime'
RUN = EVIDENCE / 'run'
records = []

def need(ok, message):
    if not ok:
        raise RuntimeError(message)

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def bytes_id(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

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

def verify_all_external(label, binding, current):
    observed = {}
    for tool in binding['tools']:
        need(equal_content(file_id(tool['path']), tool) and os.access(tool['path'], os.X_OK), 'tool drift: ' + tool['name'])
    for role, checker in (('openssl', verify_openssl_sdk), ('libcap', verify_libcap_sdk)):
        pin = binding['external_build_prerequisites'][role]['receipt']
        need(pin == current['external_build_prerequisites'][role]['receipt'], role + ' receipt association changed')
        need(equal_content(file_id(pin['path']), pin), role + ' original receipt bytes changed')
        doc = json.loads(Path(pin['path']).read_bytes())
        need(doc['environment'] == current['external_build_prerequisites'][role]['environment'], role + ' effective inputs changed')
        need(all(binding['environment'].get(key) == value for key, value in doc['environment'].items()), role + ' not in actual execution environment')
        observed[role] = checker(label, doc)
    pin = binding['external_build_prerequisites']['v8']['receipt']
    need(Path(pin['path']) == ROOT / 'evidence/bootstrap-P3-supplier-correction-v1/v8-prerequisites.json', 'V8 receipt path changed')
    need(equal_content(file_id(pin['path']), pin), 'V8 original supply receipt bytes changed')
    doc = json.loads(Path(pin['path']).read_bytes())
    need(doc['source_tree'] == binding['final_A_tree'] and doc['variant_unchanged'] is True, 'V8 original source/variant differs')
    need(all(binding['environment'].get(key) == value for key, value in doc['environment'].items()), 'V8 effective inputs changed')
    assets = []
    for row in doc['assets']:
        expected = row['observed']
        need(Path(expected['path']).is_relative_to(TOOLS / 'rusty-v8'), 'V8 supplied artifact escaped owned tool directory')
        actual = file_id(expected['path'])
        need(equal_content(actual, expected), 'V8 supplied artifact bytes changed')
        assets.append(actual)
    checksums = file_id(doc['official_checksums']['path'])
    need(equal_content(checksums, doc['official_checksums']), 'V8 official checksum bytes changed')
    observed['v8'] = save_json(label + '.v8-supply-guard.json', {'receipt': pin, 'assets': assets,
        'official_checksums': checksums, 'environment': doc['environment']})
    observed['tools'] = save_json(label + '.tools-guard.json', [
        {'name': row['name'], **file_id(row['path'])} for row in binding['tools']])
    return observed

request = json.load(sys.stdin)
binding = request['binding']
root_guard = request['root_execution_guard']
need(isinstance(root_guard, str) and re.fullmatch(r'[0-9a-f]{40}', root_guard), 'root execution guard is not bound')
need(binding['execute'] is True and binding['approval_reference'] == root_guard, 'root has not enabled this exact candidate')
need(binding['authorized_epoch'] == 'foundation', 'only foundation is authorized')
need(binding['target_reuse_mode'] == 'BUILD_ONLY_CURRENT_HOST', 'this launcher accepts only actual current-host build-only provenance')
need(binding['final_A_tree'] == binding['initial_tree'] == '4a3374e22e16ce5c764288ad018cd9affadf94ea', 'wrong native A source')
need(binding['ordinary_head'] == '20fd174ded4e5ce01bda34e4f6d1d74803301f49', 'new-host ordinary HEAD changed')
need(binding['source_identity_bridge']['native_code_tree'] == binding['initial_tree'], 'source bridge mismatch')
need(binding['source_directory'] == str(ROOT / 'source') and binding['target_directory'] == str(TARGET), 'source or target path changed')
need(binding['evidence_directory'] == str(RUN), 'owned execution evidence path changed')
need(os.getuid() == 1000 and platform.system() == 'Linux' and platform.machine() == 'x86_64', 'wrong actual native host or user')
need(ROOT.resolve() == ROOT and TARGET.resolve() == TARGET and TARGET.is_dir(), 'owned root/target missing or redirected')
need(EVIDENCE.parent.is_dir() and not EVIDENCE.parent.is_symlink() and not os.path.lexists(EVIDENCE), 'new owned epoch directory required')
free = shutil.disk_usage(TARGET).free
if free < 22000000000:
    print(json.dumps({'state': 'FOUNDATION_NOT_STARTED_RESOURCE_REFUSED', 'actual_free_bytes': free,
        'required_free_bytes': 22000000000, 'source_mutation': False, 'cache_cleanup': False}), flush=True)
    sys.exit(86)

compressed = base64.b64decode(request['install_bundle']['base64'], validate=True)
need(identity(compressed) == request['install_bundle']['compressed_identity'], 'install archive identity mismatch')
raw = gzip.decompress(compressed)
need(identity(raw) == request['install_bundle']['uncompressed_identity'], 'uncompressed install identity mismatch')
objects = json.loads(raw)
need(len(objects) == 29 and len({obj['path'] for obj in objects}) == 29, 'exact29 frozen V7 runtime/input files required')
for obj in objects:
    name = obj['path']
    need(Path(name).name == name and name not in ('', '.', '..'), 'non-flat runtime path refused')
    need(identity(obj['text'].encode()) == obj['identity'], 'runtime/input byte mismatch: ' + name)
installed = {obj['path']: obj for obj in objects}
integrity_bytes = installed['runner-integrity.json']['text'].encode()
need(hashlib.sha256(integrity_bytes).hexdigest() == binding['approved_runner_integrity_sha256'], 'wrong approved V7 integrity')
integrity = json.loads(integrity_bytes)
need(len(integrity['files']) == 25, 'exact25 V7 integrity entries required')
for row in integrity['files']:
    need(installed[row['path']]['identity'] == {key: row[key] for key in ('bytes', 'sha256', 'blob')}, 'integrity does not bind installed input')
need(installed['payload-manifest.json']['identity']['sha256'] == binding['approved_payload_sha256'], 'payload changed')
need(installed['foundation-output-family.json']['identity']['sha256'] == binding['approved_foundation_output_family_sha256'], 'historical output family changed')

current_pin = binding['current_host_build_only_baseline']
need(equal_content(file_id(current_pin['path']), current_pin), 'actual current-host baseline drift')
current = json.loads(Path(current_pin['path']).read_bytes())
need(current['role'] == 'BUILD_ONLY_CURRENT_HOST' and current['tests_executed'] is False and current['test_qualification'] is False, 'build-only must not become tested qualification')
need(current['source_tree'] == binding['final_A_tree'] and current['source_commit'] == binding['ordinary_head'], 'current baseline source differs')
need(current['environment'] == binding['environment'], 'actual P4 environment differs')
need(current['tools'] == binding['tools'], 'all eight actual tool records must match the augmented receipt')
need(current['host'] == binding['build_only_host'] and current['cache_owner'] == binding['build_only_cache_owner'], 'actual current-host identity differs')
for tool in binding['tools']:
    need(equal_content(file_id(tool['path']), tool) and os.access(tool['path'], os.X_OK), 'actual pinned tool changed: ' + tool['name'])
history_pin = binding['last_tested_A_artifacts']
need(Path(history_pin['path']) == ROOT / 'evidence/b16-historical-fb9-input-v1/full-fb9-workspace-selection.original.json', 'historical copied evidence path changed')
need(equal_content(file_id(history_pin['path']), history_pin), 'historical full selection original bytes changed')
history = json.loads(Path(history_pin['path']).read_bytes())
need(history['source'] == binding['last_tested_A_tree'] and history.get('role') != 'BUILD_ONLY_CURRENT_HOST', 'historical tested source relabeled')
transfer_pin = binding['historical_evidence_transfer']['terminal']
need(equal_content(file_id(transfer_pin['path']), transfer_pin), 'original evidence transfer receipt changed')

EVIDENCE.mkdir(exist_ok=False, mode=0o700)
RUNTIME.mkdir(exist_ok=False, mode=0o700)
for obj in objects:
    path = RUNTIME / obj['path']
    with path.open('xb') as stream:
        stream.write(obj['text'].encode())
    os.chmod(path, 0o644)
    need(identity(path.read_bytes()) == obj['identity'], 'installed runtime did not reopen exactly')
binding_raw = (json.dumps(binding, ensure_ascii=False, indent=2) + '\n').encode()
binding_path = EVIDENCE / 'binding.json'
with binding_path.open('xb') as stream:
    stream.write(binding_raw)
receipt = {'schema': 'hepta-ai395-b16-foundation-v7-installation-v1', 'root_execution_guard': root_guard,
    'binding': {'path': str(binding_path), **identity(binding_raw)}, 'source_identity_bridge': binding['source_identity_bridge'],
    'runtime_files': [{'path': obj['path'], **obj['identity']} for obj in objects],
    'actual_free_bytes_before_install': free, 'fresh22GB_still_rechecked_by_frozen_V7': True,
    'other_epochs_authorized': False, 'source_or_target_deleted': False,
    'historical_original_not_relabelled': True}
save_json('installation-receipt.json', receipt)
environment = dict(os.environ)
environment.update(binding['environment'])
argv = ['/usr/bin/python3', str(RUNTIME / 'b16_runner.py'), '--binding', str(binding_path), '--epoch', 'foundation']
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
clock = time.monotonic()
result = None
error = None
prerequisite_records = {}
try:
    prerequisite_records['before'] = verify_all_external('before-foundation', binding, current)
    print(json.dumps({'launch': 'foundation', 'argv': argv, 'binding_sha256': identity(binding_raw)['sha256'],
        'source': binding['initial_tree'], 'root_execution_guard': root_guard, 'current_host_provenance': 'BUILD_ONLY_CURRENT_HOST'}), flush=True)
    result = subprocess.run(argv, cwd=ROOT / 'source', env=environment)
except BaseException as caught:
    error = {'type': type(caught).__name__, 'message': str(caught), 'traceback': traceback.format_exc()}
finally:
    final_guard_error = None
    try:
        prerequisite_records['after'] = verify_all_external('after-foundation', binding, current)
    except BaseException as caught:
        final_guard_error = {'type': type(caught).__name__, 'message': str(caught), 'traceback': traceback.format_exc()}
    child_exit = None if result is None else result.returncode
    final_exit = child_exit if child_exit is not None else 1
    if error or final_guard_error:
        final_exit = 1
    status = {'schema': 'hepta-ai395-b16-foundation-v7-launch-terminal-v1', 'root_execution_guard': root_guard,
        'argv': argv, 'started_at': started, 'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'duration_seconds': time.monotonic() - clock, 'original_runner_exit_code': child_exit,
        'launcher_exit_code': final_exit, 'error': error, 'external_guard_error': final_guard_error,
        'external_prerequisite_guards': prerequisite_records, 'records': list(records),
        'actual_free_bytes_after': shutil.disk_usage(TARGET).free, 'epoch_terminal_path': str(RUN / 'epoch-terminal.json'),
        'status_is_not_replaced_by_launch_or_install_success': True, 'no_other_epoch_started': True}
    terminal_pin = save_json('launcher-terminal.json', status)
    print(json.dumps({'launcher_terminal': terminal_pin, 'original_runner_exit_code': child_exit,
        'launcher_exit_code': final_exit, 'error': error, 'external_guard_error': final_guard_error}), flush=True)
sys.exit(final_exit)
