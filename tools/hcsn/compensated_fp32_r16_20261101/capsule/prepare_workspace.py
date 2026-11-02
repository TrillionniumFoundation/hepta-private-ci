"""Verify this additive bundle and materialize an isolated reproduction tree."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath


def relative_file(name):
    if not isinstance(name,str) or not name or '\\' in name or '\x00' in name:
        raise ValueError('Expected a canonical relative POSIX file path')
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name or name=='.' or ':' in path.parts[0]:
        raise ValueError('Unsafe manifest path: '+name)
    if name=='BUNDLE_MANIFEST.json':
        raise ValueError('The manifest is reserved')
    return path


def main(destination):
    source = Path(__file__).resolve().parent
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Use a new directory outside the frozen bundle')
    manifest_bytes=(source/'BUNDLE_MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    decoded, copied, output_names = {}, {}, set()
    for entry in manifest['files']:
        name=relative_file(entry['path']).as_posix()
        if name in output_names:
            raise ValueError('Duplicate output: '+name)
        output_names.add(name)
        source_path=source/name
        if not source_path.resolve().is_relative_to(source) or not source_path.is_file():
            raise ValueError('Source file escapes the bundle: '+name)
        data = source_path.read_bytes()
        if 'bytes' in entry and len(data)!=entry['bytes']:
            raise ValueError('Stored artifact length mismatch: '+name)
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Artifact seal mismatch: '+entry['path'])
        copied[name]=data
        if 'uncompressed_file' in entry:
            target=relative_file(entry['uncompressed_file']).as_posix()
            if target in output_names:
                raise ValueError('Duplicate output: '+target)
            output_names.add(target)
            raw = gzip.decompress(data)
            if 'uncompressed_bytes' in entry and len(raw)!=entry['uncompressed_bytes']:
                raise ValueError('Uncompressed artifact length mismatch: '+name)
            if hashlib.sha256(raw).hexdigest() != entry['uncompressed_sha256']:
                raise ValueError('Uncompressed artifact seal mismatch: '+entry['path'])
            decoded[target] = raw
    for name in output_names:
        if any(parent.as_posix() in output_names for parent in PurePosixPath(name).parents):
            raise ValueError('File/directory output collision: '+name)
    destination.mkdir(parents=True)
    for name,data in {**copied,**decoded,'BUNDLE_MANIFEST.json':manifest_bytes}.items():
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as handle:
            handle.write(data)
    print(json.dumps({'verified_files':len(manifest['files']), 'workspace':str(destination)}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,required=True)
    main(parser.parse_args().destination)
