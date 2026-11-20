"""Independently verify and restore the exact completed dbd6 host archive.

No host operations, source execution, database opens, key-body reads or tests.
All restored paths are regular files created under a new owned directory.
"""
import base64
import hashlib
import json
import tarfile
import time
import traceback
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = 'dbd6a00992b60f4b33e8f10c2defda031d123bcb'
TREE = 'fe037f5b6617fb647d416e0523685fa4ce08ef2f'
SHA = '561f8f855db8776bdfb7feb7a13c52703df1492cf8355d83b7549519fc2f7e10'
MANIFEST_SHA = 'ae7f11b3b434bc304e0a5b9284e272ec007014f58a5008802aec2f447763ff16'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def save(path, value):
    put(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())


def safe(name):
    p = PurePosixPath(name)
    assert name and str(p) == name and not p.is_absolute()
    assert '..' not in p.parts and '.' not in p.parts and '\\' not in name and '\0' not in name
    assert not p.name.lower().endswith(('.key', '.pem', '.p12', '.pfx', '.jks'))
    assert p.name.lower() not in {'id_rsa', 'id_dsa', 'id_ed25519', 'id_ecdsa'}


def private_marker_check(data, name):
    for marker in (b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----',
                   b'-----BEGIN EC PRIVATE KEY-----', b'-----BEGIN OPENSSH PRIVATE KEY-----'):
        assert marker not in data, 'Private PEM marker in declared non-key physical material'
    if not name.endswith('.json') or data == b'':
        return
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.lower().replace('-', '_')
                if normalized in {'private_key', 'private_key_bytes', 'secret_key', 'secret_key_bytes',
                                  'signing_key_bytes', 'private_seed', 'secret_seed', 'keypair_bytes'}:
                    assert item in (None, '', [], {}), 'Private body field in declared non-key material'
                if normalized == 'signing_key':
                    assert isinstance(item, str) and item.startswith('/'), 'Signing key must be a path'
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(json.loads(data))


def main():
    out = HERE / 'verification-1'
    restored = HERE / 'restored'
    out.mkdir(exist_ok=False)
    restored.mkdir(exist_ok=False)
    started = time.monotonic()
    result = {'status': 'VERIFYING', 'successful': False, 'source': SOURCE, 'tree': TREE,
              'native_or_model_or_training_executions': 0, 'host_processes_or_calls': 0,
              'Git_actions': 0, 'qualification_granted': False}
    try:
        archive = HERE / 'retained/original-evidence.tar.xz'
        archive_bytes = archive.read_bytes()
        assert len(archive_bytes) == 3201316 and sha(archive_bytes) == SHA
        terminal = json.loads((HERE / 'retained/RESULT.json').read_bytes())
        parts = json.loads((HERE / 'retained/archive-parts.json').read_bytes())
        assert terminal['successful'] and terminal['source'] == SOURCE and terminal['tree'] == TREE
        assert terminal['archive_sha256'] == parts['archive_sha256'] == SHA
        assert terminal['parts'] == parts['parts'] and len(parts['parts']) == 7
        joined = []
        for row in parts['parts']:
            safe(row['name'])
            data = (HERE / 'retained' / row['name']).read_bytes()
            assert len(data) == row['bytes'] <= 480000 and sha(data) == row['sha256']
            joined.append(data)
        assert b''.join(joined) == archive_bytes
        with tarfile.open(archive, 'r:xz') as tar:
            members = tar.getmembers()
            names = [m.name for m in members]
            assert len(names) == len(set(names)) == 1136
            for member in members:
                safe(member.name)
                assert member.isfile() and not member.linkname and member.size >= 0
            manifest_raw = tar.extractfile('MANIFEST.json').read()
            assert len(manifest_raw) == 547652 and sha(manifest_raw) == MANIFEST_SHA
            assert terminal['manifest_sha256'] == MANIFEST_SHA
            manifest = json.loads(manifest_raw)
            assert manifest['source'] == SOURCE and manifest['tree'] == TREE
            indexed = {r['path']: r for r in manifest['files']}
            assert len(indexed) == len(manifest['files']) == terminal['original_files'] == 1134
            assert sum(r['bytes'] for r in manifest['files']) == terminal['original_bytes'] == 136744516
            assert set(names) == set(indexed) | {'MANIFEST.json', 'ORIGINAL_FILES.nul'}
            assert manifest['private_key_file_bodies_read'] is False
            meta_raw = tar.extractfile('INPUT.json').read()
            meta = json.loads(meta_raw)
            assert meta_raw == (ROOT / 'e6_owner_work/observation_diagnostic_runtime_evidence/rev3/ARCHIVE_META.json').read_bytes()
            assert (meta['source'], meta['tree']) == (SOURCE, TREE)
            key_paths = {r['path'] for r in meta['excluded_keys']}
            assert len(key_paths) == len(meta['excluded_keys']) == 12
            assert not key_paths.intersection(r.get('original_path') for r in indexed.values())
            physical_names = set()
            capture_rows = []
            for capture in meta['physical_captures']:
                prefix = 'raw/' + capture['directory'] + '/'
                raw = tar.extractfile(prefix + capture['manifest_file']).read()
                assert sha(raw) == capture['manifest_sha256']
                rows = json.loads(raw)
                assert len(rows) == capture['count'] and sum(r['bytes'] for r in rows) == capture['bytes']
                assert {r['path'] for r in rows} == set(capture['expected_paths'])
                for row in rows:
                    assert row['path'] not in key_paths
                    safe(Path(row['path']).name)
                    name = prefix + Path(row['captured_path']).name
                    assert name not in physical_names
                    physical_names.add(name)
                    assert indexed[name]['bytes'] == row['bytes'] and indexed[name]['sha256'] == row['sha256']
                    capture_rows.append(dict(row, capture_directory=capture['directory']))
            assert [r['count'] for r in meta['physical_captures']] == [12, 5, 635]
            assert len(physical_names) == terminal['physical_original_count'] == 652
            verified = []
            for member in members:
                data = tar.extractfile(member).read()
                assert len(data) == member.size
                if member.name in indexed:
                    row = indexed[member.name]
                    assert len(data) == row['bytes'] and sha(data) == row['sha256'], member.name
                if member.name in physical_names:
                    private_marker_check(data, member.name)
                target = restored / member.name
                assert target.is_relative_to(restored)
                put(target, data)
                assert target.read_bytes() == data
                verified.append({'path': member.name, 'bytes': len(data), 'sha256': sha(data),
                                 'regular': True, 'restored_byte_equal_to_tar_member': True})
        assert (restored / 'MANIFEST.json').read_bytes() == manifest_raw
        nul = (restored / 'ORIGINAL_FILES.nul').read_bytes()
        assert sha(nul) == manifest['original_files_nul_sha256']
        listed = [x.decode() for x in nul.split(b'\0') if x]
        assert len(listed) == len(set(listed)) == 1134 and set(listed) == set(indexed)
        assert json.loads((restored / 'PHYSICAL_ORIGINALS.json').read_bytes()) == capture_rows
        keys = json.loads((restored / 'EXCLUDED_KEY_METADATA.json').read_bytes())
        assert keys == meta['excluded_keys']
        assert all(row['sha256'] is None and row['body_exported'] is False for row in keys)
        assert sha((restored / 'SUMMARY.json').read_bytes()) == terminal['summary_sha256']
        assert json.loads((restored / 'PRIVATE_MATERIAL_SCOPE.json').read_bytes())['captured_non_key_files_checked'] == 652
        for path, digest in meta['result_sha256'].items():
            assert indexed['raw/' + path]['sha256'] == digest
        for row in meta['source_files']:
            data = (restored / 'source-dbd6' / row['path']).read_bytes()
            assert len(data) == row['bytes'] and sha(data) == row['sha256'] and blob(data) == row['git_blob_oid']
        for row in meta['host_driver_files']:
            assert indexed['drivers/' + row['path']]['sha256'] == row['sha256']
        for name, row in meta['supplied_cloud_files'].items():
            data = base64.b64decode(row['base64'], validate=True)
            assert len(data) == row['bytes'] and sha(data) == row['sha256']
            assert (restored / 'original-cloud-inputs' / name).read_bytes() == data
        for session, observation in meta['terminals'].items():
            assert observation['status']['state'] == 'exited' and observation['output_complete'] is True
            assert observation['status'].get('capture_error') is None
            assert indexed['terminals/' + session + '/output.log']['bytes'] == observation['available_end']
        physical_map = []
        for row in capture_rows:
            name = 'raw/' + row['capture_directory'] + '/' + Path(row['captured_path']).name
            physical_map.append({'original_path': row['path'], 'remote_captured_path': row['captured_path'],
                                 'workspace_relative_path': str((restored / name).relative_to(ROOT)),
                                 'member': name, 'bytes': row['bytes'], 'sha256': row['sha256'],
                                 'capture_directory': row['capture_directory']})
        save(out / 'ALL_MEMBERS_VERIFIED.json', verified)
        save(out / 'PHYSICAL_RESTORE_MAP.json', physical_map)
        crosscheck = {'physical_originals': 652, 'physical_batches': [12, 5, 635],
                      'physical_bytes': sum(r['bytes'] for r in capture_rows), 'business_paths': 640,
                      'stdio_paths': 12, 'excluded_key_metadata': 12, 'source_files': len(meta['source_files']),
                      'terminal_logs': len(meta['terminals']), 'result_pins': len(meta['result_sha256']),
                      'host_drivers': len(meta['host_driver_files']), 'supplied_cloud_files': len(meta['supplied_cloud_files']),
                      'known_private_marker_check': 'Known PEM and explicit JSON key fields only; empty JSON placeholders preserve zero bytes. Not a universal secret detector.',
                      'no_SQLite_open_or_source_execution': True, 'whole_host_or_complete_provenance_claimed': False}
        save(out / 'CROSSCHECK.json', crosscheck)
        result.update({'status': 'PASS', 'successful': True, 'archive_path': str(archive),
                       'archive_bytes': len(archive_bytes), 'archive_sha256': SHA,
                       'manifest_sha256': MANIFEST_SHA, 'original_files': 1134,
                       'original_bytes': 136744516, 'regular_safe_unique_tar_members': 1136,
                       'all_member_bytes_and_sha_verified': True, 'all_restored_files_byte_identical': True,
                       'restored_root': str(restored), 'parts': 7, 'crosscheck': crosscheck})
    except BaseException as exc:
        result.update({'status': 'FAIL_PRESERVED', 'successful': False, 'error': repr(exc)})
        put(out / 'exception.txt', traceback.format_exc().encode())
    result['wall_seconds'] = time.monotonic() - started
    save(out / 'RESULT.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'crosscheck'}, ensure_ascii=False))
    return 0 if result['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
