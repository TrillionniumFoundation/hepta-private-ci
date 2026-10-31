"""Independent restored-byte identity check without decoding or model access."""

import hashlib
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
ADVANCE = HERE.parents[1]
WORK = ADVANCE.parents[3]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    allocation_path = ADVANCE / 'SOURCE_ALLOCATION.json'
    allocation = json.loads(allocation_path.read_text())
    if sha(allocation_path) != '42d0c47056dda930cb851c9ae59f330747de8bb863f18b79c47eea830f69b262':
        raise ValueError('Frozen allocation changed')
    manifest_path = WORK / 'ndu-next-assets/shared/abc2-runs/source-recovery-001/source-manifest.json'
    if sha(manifest_path) != allocation['original_mnist_manifest_sha256']:
        raise ValueError('Original MNIST identity ledger changed')
    old = json.loads(manifest_path.read_text())
    old_pixels = {identity.rsplit(':', 1)[1] for role in old['roles'].values() for identity in role['source_ids']}
    new_pixels = {row['pixel_sha256'] for role in allocation['roles'].values()
                  for row in role.get('source_records', [])}
    if old_pixels & new_pixels:
        raise ValueError('A new role shares an exact old MNIST pixel identity')
    receipt_path = ADVANCE / 'evidence/AUDIO_RESTORE_001.json'
    receipt = json.loads(receipt_path.read_text())
    root = Path(receipt['output'])
    rows = {}
    for role in allocation['roles'].values():
        for row in role.get('audio_rows_by_source_digit', role.get('recordings', [])):
            if row['path'] in rows and rows[row['path']] != row:
                raise ValueError('Repeated source path has conflicting identity')
            rows[row['path']] = row
    if set(receipt['restored']) != rows.keys() or len(rows) != 954:
        raise ValueError('Restoration census differs from the registered cohort')
    actual = {}
    for name, row in rows.items():
        path = root / name
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Actual restored source bytes differ: ' + name)
        actual[name] = row['sha256']
    result = {'schema': 'hepta.advance.independent-source-byte-addendum.v1',
        'status': 'passed', 'recorded_ns': time.time_ns(),
        'allocation_sha256': sha(allocation_path), 'original_mnist_manifest_sha256': sha(manifest_path),
        'original_mnist_unique_pixel_identities': len(old_pixels),
        'new_declared_unique_pixel_identities': len(new_pixels),
        'new_original_mnist_pixel_identity_intersection': 0,
        'actual_restored_audio_files_independently_hashed': len(actual),
        'actual_restored_audio_total_bytes': sum(row['bytes'] for row in rows.values()),
        'actual_path_sha_census_digest': hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest(),
        'root_restoration_receipt_sha256': sha(receipt_path), 'review_source_sha256': sha(__file__),
        'source_waveforms_decoded_or_scored': False, 'models_or_role_loaders_called': False,
        'scope': 'Exact declared image identity exclusion against the full original MNIST manifest plus actual restored WAV byte hashes. No new source model outcomes or natural-OOD correctness claim.'}
    output = HERE / 'SOURCE_BYTES_ADDENDUM.json'
    with output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
