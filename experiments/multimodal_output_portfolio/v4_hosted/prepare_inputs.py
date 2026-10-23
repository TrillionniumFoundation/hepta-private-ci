"""Package exact frozen synthetic inputs; never execute a model or native binary."""

import hashlib
import json
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


REPO = Path('/tmp/hepta-portfolio-work')
DEST = Path('/tmp/hepta-v4-hosted-inputs-001')
SCIENCE = '7713023e604746a3947e0e0e2d31e8eaef6e48b1'
V4 = 'experiments/multimodal_output_portfolio/v4/'
CHUNK_SIZE = 512 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob_digest(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def frozen_file(relative):
    data = (REPO / relative).read_bytes()
    row = subprocess.check_output(
        ['git', 'ls-tree', SCIENCE, '--', relative], cwd=REPO, text=True
    ).strip()
    assert row.split()[2] == blob_digest(data), relative
    return data, {
        'path': relative,
        'bytes': len(data),
        'sha256': digest(data),
        'git_blob_sha1': blob_digest(data),
    }


def canonical(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and path.as_posix() == name
    assert all(part not in ('', '.', '..') for part in path.parts)
    assert '\\' not in name and ':' not in name and '\0' not in name


def execute():
    assert not DEST.exists(), 'Refuse to overwrite any earlier package.'
    protocol_raw, protocol_binding = frozen_file(V4 + 'protocol.json')
    build_raw, build_binding = frozen_file(V4 + 'evidence/native_build_final.json')
    protocol, build = json.loads(protocol_raw), json.loads(build_raw)
    assert protocol_binding['sha256'] == (
        '4f90f435e3ce419a09f42412af1fc6fe3515f3c198e5e8555115b1996c1aab0b'
    )
    fixture = Path('/dev/shm/hepta-v4/native-bridge-development-001')
    licenses = Path('/tmp/hepta-v4-native-licenses')
    fixture_files = sorted(p for p in fixture.rglob('*') if p.is_file())
    assert {p.relative_to(fixture).as_posix() for p in fixture_files} == {
        'receipt.json', 'actual-arrays.npz', 'native.tsv.gz'
    }
    fixture_receipt = json.loads((fixture / 'receipt.json').read_text())
    assert fixture_receipt['status'] == 'passed'
    assert fixture_receipt['schema'] == 'hepta-v4-four-action-development-v1'
    assert fixture_receipt['checkpoint_sha256'] == protocol['source_checkpoints']['17']['sha256']
    assert fixture_receipt['native']['binary_sha256'] == build['binary']['sha256']
    for name, expected in fixture_receipt['artifact_sha256'].items():
        assert digest((fixture / name).read_bytes()) == expected
    for name, expected in fixture_receipt['source_sha256'].items():
        raw, unused = frozen_file(V4 + name)
        assert digest(raw) == expected
    inputs = []
    for seed in (17, 29, 43):
        pin = protocol['source_checkpoints'][str(seed)]
        path = Path('/tmp/hepta-v3-confirmation-001') / pin['path']
        assert path.stat().st_size == pin['bytes']
        assert digest(path.read_bytes()) == pin['sha256']
        inputs.append(('source-run/' + pin['path'], path, 'frozen_synthetic_checkpoint'))
    binary = Path('/tmp/hepta-native-target/debug/ndu-modality-portfolio')
    assert binary.stat().st_size == build['binary']['bytes']
    assert digest(binary.read_bytes()) == build['binary']['sha256']
    inputs.append(('native/ndu-modality-portfolio', binary, 'frozen_native_executable'))
    inputs.extend(('bridge-fixture/' + p.relative_to(fixture).as_posix(), p,
                   'original_four_action_fixture') for p in fixture_files)
    license_files = sorted(p for p in licenses.rglob('*') if p.is_file())
    assert len(license_files) == 71
    inputs.extend(('licenses/' + p.relative_to(licenses).as_posix(), p,
                   'original_native_license') for p in license_files)
    inputs.sort(key=lambda item: item[0])
    assert len({name for name, path, role in inputs}) == len(inputs) == 78
    records = []
    for name, path, role in inputs:
        canonical(name)
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode) and not path.is_symlink()
        mode = stat.S_IMODE(metadata.st_mode)
        assert mode == (0o755 if role == 'frozen_native_executable' else 0o644)
        raw = path.read_bytes()
        records.append({'path': name, 'bytes': len(raw), 'sha256': digest(raw),
                        'unix_mode': mode, 'role': role})
    DEST.mkdir()
    (DEST / 'chunks').mkdir()
    archive = DEST / 'hepta-v4-exact-inputs.zip'
    with zipfile.ZipFile(archive, 'x') as z:
        for (name, path, role), record in zip(inputs, records):
            raw = path.read_bytes()
            assert digest(raw) == record['sha256']
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | record['unix_mode']) << 16
            z.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    archive_raw = archive.read_bytes()
    chunks = []
    for index, offset in enumerate(range(0, len(archive_raw), CHUNK_SIZE)):
        data = archive_raw[offset:offset + CHUNK_SIZE]
        name = f'chunks/part-{index:05d}.bin'
        with (DEST / name).open('xb') as handle:
            handle.write(data)
        chunks.append({'path': name, 'index': index, 'offset': offset,
                       'bytes': len(data), 'sha256': digest(data),
                       'git_blob_sha1': blob_digest(data)})
    manifest = {
        'schema': 'hepta.v4.hosted-inputs.v1',
        'science_commit': SCIENCE,
        'protocol_sha256': protocol_binding['sha256'],
        'native_build_receipt_sha256': build_binding['sha256'],
        'frozen_sources': [protocol_binding, build_binding],
        'scope': 'Exact synthetic checkpoints, original native executable, original four-action fixture, and native licenses only.',
        'source_identity_check': 'Local bytes matched Git blob SHA1 in the frozen science commit tree; inputs matched its protocol and native build receipt.',
        'zip': {'filename': archive.name, 'bytes': len(archive_raw),
                'sha256': digest(archive_raw), 'compression': 'deflate',
                'member_count': len(records)},
        'total_uncompressed_bytes': sum(row['bytes'] for row in records),
        'chunk_size_bytes': CHUNK_SIZE,
        'chunk_paths_relative_to': 'manifest parent directory',
        'files': records,
        'chunks': chunks,
        'entrypoints': {'source_run': 'source-run',
                        'native_binary': 'native/ndu-modality-portfolio',
                        'bridge_fixture': 'bridge-fixture', 'licenses': 'licenses'},
        'mode_encoding': 'unix_mode is an integer: 420 means 0644 and 493 means 0755; ZIP external_attr includes regular-file type.',
    }
    manifest_raw = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    with (DEST / 'manifest.json').open('xb') as handle:
        handle.write(manifest_raw)
    rebuilt = b''.join((DEST / row['path']).read_bytes() for row in chunks)
    assert rebuilt == archive_raw
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.namelist() == [row['path'] for row in records]
        for info, row in zip(z.infolist(), records):
            assert info.file_size == row['bytes']
            assert stat.S_ISREG(info.external_attr >> 16)
            assert stat.S_IMODE(info.external_attr >> 16) == row['unix_mode']
            assert digest(z.read(info)) == row['sha256']
    for (name, path, role), row in zip(inputs, records):
        assert digest(path.read_bytes()) == row['sha256']
        assert stat.S_IMODE(path.stat().st_mode) == row['unix_mode']
    verification = {
        'schema': 'hepta-v4-hosted-input-packaging-check-v1', 'status': 'passed',
        'science_commit': SCIENCE, 'manifest_sha256': digest(manifest_raw),
        'zip_sha256': digest(archive_raw), 'zip_bytes': len(archive_raw),
        'total_uncompressed_bytes': manifest['total_uncompressed_bytes'],
        'members': len(records), 'chunks': len(chunks),
        'checks': ['frozen Git tree identity', 'three protocol checkpoint byte identities',
                   'native build receipt byte identity', 'complete original fixture and source hashes',
                   'canonical paths, regular files, exact modes, unique whitelist',
                   'raw chunk concatenation, SHA256 and Git blob SHA1',
                   'ZIP CRC, exact member bytes and permissions', 'original inputs unchanged'],
        'model_executed': False, 'native_executed': False,
        'uploaded_or_triggered': False,
    }
    with (DEST / 'verification.json').open('x') as handle:
        json.dump(verification, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps(verification, indent=2, sort_keys=True))


if __name__ == '__main__':
    execute()
