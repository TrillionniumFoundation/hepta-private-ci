"""Reconstruct the exact qualified archive from bounded Git files; execute no model."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_write(root, relative, data):
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(x in ('', '.', '..') for x in parts):
        raise ValueError('Unsafe output name')
    destination = root.joinpath(*parts)
    for parent in (destination, *destination.parents):
        if parent.is_symlink():
            raise ValueError('Symlink output path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != data:
            raise ValueError('Existing output differs; never overwrite: ' + relative)
    else:
        with destination.open('xb') as stream:
            stream.write(data)


def materialize(base, output):
    manifest = json.loads((base / 'artifacts/MANIFEST.json').read_text())
    if manifest['schema'] != 'hcsn-qualified-artifact-multipart-v1':
        raise ValueError('Wrong artifact manifest')
    parts = []
    offset = 0
    for item in manifest['parts']:
        relative = PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts) != 2 or relative.parts[0] != 'artifacts':
            raise ValueError('Unsafe part path')
        data = (base / relative).read_bytes()
        if item['offset'] != offset or len(data) != item['bytes'] or digest(data) != item['sha256']:
            raise ValueError('Part byte identity differs')
        parts.append(data)
        offset += len(data)
    archive = b''.join(parts)
    if len(archive) != manifest['archive']['bytes'] or digest(archive) != manifest['archive']['sha256']:
        raise ValueError('Reconstructed qualification ZIP differs')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        if len(zipped.namelist()) != len(set(zipped.namelist())) or set(zipped.namelist()) != set(manifest['members']):
            raise ValueError('Qualification member roster differs')
        if zipped.testzip() is not None:
            raise ValueError('ZIP CRC failure')
        members = {}
        for name, expected in manifest['members'].items():
            if zipped.getinfo(name).file_size != expected['bytes']:
                raise ValueError('Member size differs')
            data = zipped.read(name)
            if len(data) != expected['bytes'] or digest(data) != expected['sha256']:
                raise ValueError('Member SHA differs: ' + name)
            members[name] = data
    if len(members) != 47:
        raise ValueError('Incomplete original qualification archive')
    safe_write(output, 'qualification/suite-artifacts.zip', archive)
    for relative, member in manifest['materialized_paths'].items():
        safe_write(output, relative, members[member])
    for name, data in members.items():
        safe_write(output, 'qualification/raw/' + name, data)
    result = dict(schema='hcsn-qualified-artifact-materialized-v1',
                  archive_sha256=digest(archive), archive_bytes=len(archive), members_verified=len(members),
                  bundle_sha256=digest(members['evidence/operators-s81.npz']),
                  bundle_metadata_sha256=digest(members['evidence/operators-s81.json']),
                  model_execution=False, task_data_reads=False)
    safe_write(output, 'qualification/MATERIALIZED.json', (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(materialize(Path(__file__).resolve().parent, args.output.resolve()), indent=2))
