#!/usr/bin/env python3
"""Verify the later archive using the pinned previous safe-member verifier."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True


def main():
    root = Path(__file__).resolve().parent
    previous = root.parent / '20261026-provider-runtime-status' / 'verify_archives.py'
    raw = previous.read_bytes()
    expected = 'fd7b25739a7fdc9e3b5e81a87752fb8dc5241e51c944116a3747fa8d13a77b04'
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Original safe archive verifier changed')
    spec = importlib.util.spec_from_file_location('previous_archive_verifier', previous)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((root / 'ARCHIVE_MANIFEST.json').read_bytes())
    if manifest['schema'] != 'hepta-native-composition-archive-inputs:v1':
        raise ValueError('Unexpected input schema')
    archive = manifest['archive']
    parts = json.loads((root / 'PARTS_MANIFEST.json').read_bytes())
    if (parts['schema'] != 'hepta-exact-archive-parts:v1'
            or parts['archive'] != {key: archive[key] for key in ['bytes', 'sha256']}
            or len(parts['parts']) != 29):
        raise ValueError('Unexpected exact archive parts')
    expected_names = {f'native-composition.part-{index:03d}' for index in range(29)}
    if {path.name for path in (root / 'archives').iterdir()} != expected_names:
        raise ValueError('Unexpected part directory census')
    with tempfile.TemporaryDirectory(prefix='hepta-evidence-byte-verify-') as temporary:
        reconstructed = Path(temporary) / 'original.tar.gz'
        count, total_hash = 0, hashlib.sha256()
        with reconstructed.open('xb') as output:
            for index, part in enumerate(parts['parts']):
                expected = f'archives/native-composition.part-{index:03d}'
                if part['path'] != expected:
                    raise ValueError('Unexpected part path or order')
                path = root / expected
                if not path.is_file() or path.is_symlink():
                    raise ValueError('Expected regular archive part')
                raw = path.read_bytes()
                if (not 0 < len(raw) <= 500000 or len(raw) != part['bytes']
                        or hashlib.sha256(raw).hexdigest() != part['sha256']):
                    raise ValueError('Archive part identity differs')
                count += len(raw)
                total_hash.update(raw)
                output.write(raw)
        if count != archive['bytes'] or total_hash.hexdigest() != archive['sha256']:
            raise ValueError('Concatenated original archive differs')
        result = module.verify_one(reconstructed, archive)
    print(json.dumps({'schema': 'hepta-native-composition-local-byte-review:v1',
                      'passed': True, 'archive': result,
                      'archived_code_or_tests_executed': False,
                      'temporary_reconstruction_only': True,
                      'remote_readback_performed': False}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
