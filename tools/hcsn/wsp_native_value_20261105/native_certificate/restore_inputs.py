#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Restore the original native certificate input bytes in a new directory.

This transport helper does not run a model, verifier, or scientific exporter.
Every source byte is validated before the destination directory is created.
"""
import argparse
import hashlib
import json
from pathlib import Path

INPUT_MANIFEST_SHA256 = '946cf867a362eb5bc3d25290b48bf94207849171eb2c2f4406a398bbfc26e7da'
PACKAGE_MANIFEST_SHA256 = 'eed1c56391f60c621048e1efaa4c4fc897c413f355f29401e6f425ec8b91c952'
CHUNK_BYTES = 479000
FITS = (11, 23, 37, 53, 71)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def restore(source, output, package_source=None):
    source, output = Path(source), Path(output)
    require(not output.exists(), 'destination must be a new directory')
    manifest_bytes = (source / 'INPUT_MANIFEST.json').read_bytes()
    require(digest(manifest_bytes) == INPUT_MANIFEST_SHA256, 'input manifest digest mismatch')
    manifest = json.loads(manifest_bytes)
    names = {f'fit_{fit}_{kind}.json.gz' for fit in FITS for kind in ('REQUEST', 'REFERENCE')}
    require(len(manifest['files']) == len(names), 'input file count mismatch')
    require({item['name'] for item in manifest['files']} == names, 'input file names mismatch')
    payloads = [('INPUT_MANIFEST.json', manifest_bytes)]
    restored = []
    for item in manifest['files']:
        name = item['name']
        if name.endswith('_REQUEST.json.gz'):
            parts = json.loads((source / (name + '.parts.json')).read_bytes())
            require(set(parts) == {'bytes', 'sha256', 'parts'}, 'parts manifest shape mismatch')
            require(parts['bytes'] == item['bytes'] and parts['sha256'] == item['sha256'],
                    'whole input identity mismatch: ' + name)
            count = (item['bytes'] + CHUNK_BYTES - 1) // CHUNK_BYTES
            require(len(parts['parts']) == count, 'part count mismatch: ' + name)
            pieces = []
            for index, part in enumerate(parts['parts']):
                expected_name = name + f'.part{index:04d}'
                expected_size = min(CHUNK_BYTES, item['bytes'] - index * CHUNK_BYTES)
                require(set(part) == {'name', 'bytes', 'sha256'}, 'part record shape mismatch')
                require(part['name'] == expected_name, 'part name/order mismatch: ' + name)
                require(type(part['bytes']) is int and part['bytes'] == expected_size,
                        'part size declaration mismatch: ' + expected_name)
                data = (source / expected_name).read_bytes()
                require(len(data) == expected_size, 'part byte length mismatch: ' + expected_name)
                require(digest(data) == part['sha256'], 'part digest mismatch: ' + expected_name)
                pieces.append(data)
            data = b''.join(pieces)
        else:
            data = (source / name).read_bytes()
        require(len(data) == item['bytes'] and digest(data) == item['sha256'],
                'reconstructed input digest mismatch: ' + name)
        payloads.append((name, data))
        restored.append({'name': name, 'bytes': len(data), 'sha256': digest(data)})
    logical_package_files = None
    if package_source is not None:
        package_source = Path(package_source)
        package_manifest_bytes = (package_source / 'FINAL_PUBLISH_MANIFEST.json').read_bytes()
        require(digest(package_manifest_bytes) == PACKAGE_MANIFEST_SHA256,
                'original package manifest digest mismatch')
        package_manifest = json.loads(package_manifest_bytes)
        require(package_manifest['file_count'] == len(package_manifest['files']) == 143,
                'original package file count mismatch')
        reconstructed_inputs = {'inputs/' + name: data for name, data in payloads}
        package_payloads = []
        seen = set()
        for item in package_manifest['files']:
            name = item['path']
            relative = Path(name)
            require(not relative.is_absolute() and '..' not in relative.parts
                    and name not in seen, 'invalid package path')
            seen.add(name)
            data = (reconstructed_inputs[name] if name in reconstructed_inputs
                    else (package_source / name).read_bytes())
            require(len(data) == item['bytes'] and digest(data) == item['sha256'],
                    'original logical package file mismatch: ' + name)
            package_payloads.append((name, data))
        require(set(reconstructed_inputs).issubset(seen), 'package input coverage mismatch')
        package_payloads.append(('FINAL_PUBLISH_MANIFEST.json', package_manifest_bytes))
        payloads = package_payloads
        logical_package_files = len(payloads)
    # No final-name output exists if any input, part, or full-file check failed.
    output.mkdir(parents=False, exist_ok=False)
    for name, data in payloads:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    for name, data in payloads:
        require((output / name).read_bytes() == data, 'destination readback mismatch: ' + name)
    return {'schema': 'hepta-native-input-byte-restoration-v1', 'status': 'PASS',
            'input_manifest_sha256': INPUT_MANIFEST_SHA256, 'files': restored,
            'mode': 'complete_logical_package' if package_source is not None else 'inputs_only',
            'original_logical_package_files_restored': logical_package_files,
            'original_package_manifest_sha256': PACKAGE_MANIFEST_SHA256 if package_source is not None else None,
            'input_json_reserialized': False, 'gzip_recompressed': False,
            'model_or_native_execution': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--source', type=Path, help='Restore only the input directory.')
    sources.add_argument('--package-source', type=Path,
                         help='Restore the full original logical package, including its fixed inputs path.')
    parser.add_argument('--output', type=Path, required=True,
                        help='New directory outside the checkout; parent must already exist.')
    args = parser.parse_args()
    source = (args.package_source / 'inputs' if args.package_source is not None
              else args.source or Path(__file__).resolve().parent / 'inputs')
    print(json.dumps(restore(source, args.output, args.package_source), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
