"""Metadata-only audit of the previously unallocated test-image reserve.

No image, tensor, model or future outcome is materialized. Large JSON/JSONL
files are scanned in full for bound image identities, without size exclusions.
The complete per-file index stays outside Git; the report retains its digest.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time


WORKSPACE = Path('/workspace/scratch/2b3c256bef7d')
REPO = WORKSPACE / 'hepta-ndu-recovery'
MANIFEST = WORKSPACE / 'abc2-runs/source-recovery-001/source-manifest.json'
MANIFEST_SHA = '60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058'
ID = re.compile(rb'mnist:(?:train|test):[0-9]+:[0-9a-f]{64}')
ROLE = re.compile(rb'"(?:source_role|role|source_roles_read)"\s*:\s*(\[[^\]]*\]|"[^"]*")')
SKIP = {'target', 'cargo-home', 'media', 'node_modules', '.git', '__pycache__'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ids_sha(values):
    return sha('\n'.join(values).encode())


def pixels(values):
    return {value.rsplit(':', 1)[1] for value in values}


def metadata_files():
    roots = sorted(p for p in WORKSPACE.iterdir() if p.is_dir() and p.name.startswith('abc'))
    roots.append(REPO / 'experiments/multimodal_output_portfolio')
    for root in roots:
        for path in sorted(root.rglob('*')):
            if path.suffix not in {'.json', '.jsonl'} or not path.is_file() or set(path.parts) & SKIP:
                continue
            if 'training_repair' in path.parts:
                continue  # This prospective reservation is not prior execution.
            yield root, path


def audit(index_path, output):
    started = time.time_ns()
    manifest_bytes = MANIFEST.read_bytes()
    assert sha(manifest_bytes) == MANIFEST_SHA
    manifest = json.loads(manifest_bytes)
    target = manifest['roles']['unallocated_test']['source_ids']
    target_set, target_pixels = set(target), pixels(target)
    assert len(target) == len(target_set) == len(target_pixels) == 2000
    disjoint = []
    for role, record in manifest['roles'].items():
        if role == 'unallocated_test':
            continue
        values = record['source_ids']
        one, two = target_set & set(values), target_pixels & pixels(values)
        assert not one and not two, role
        disjoint.append({'role': role, 'individual_sources_excluded': len(values),
            'ordered_source_ids_sha256': ids_sha(values), 'individual_id_overlap': 0, 'pixel_sha256_overlap': 0})
    index, candidates, mentions, all_ids = [], [], [], set()
    totals = {}
    for root, path in metadata_files():
        before = path.stat()
        with path.open('rb') as stream:
            data = stream.read(before.st_size)
        after = path.stat()
        used = {match.group().decode() for match in ID.finditer(data)}
        bound = sorted(used & target_set)
        roles = sorted({match.group(1).decode() for match in ROLE.finditer(data)})
        file_hash = sha(data)
        is_catalog = file_hash == MANIFEST_SHA
        if not is_catalog:
            all_ids.update(used)
        relative = str(path.relative_to(WORKSPACE))
        record = {'file': relative, 'sha256': file_hash, 'bytes_read': len(data),
            'complete_file_at_open': len(data) == before.st_size,
            'changed_during_read': before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns,
            'source_catalog_only': is_catalog, 'distinct_bound_source_ids': len(used),
            'bound_source_ids_sha256': ids_sha(sorted(used)), 'candidate_source_id_matches': len(bound),
            'candidate_pixel_matches': len(pixels(used) & target_pixels), 'declared_role_values': roles}
        index.append(record)
        label = str(root.relative_to(WORKSPACE))
        summary = totals.setdefault(label, Counter())
        summary['metadata_files'] += 1; summary['bytes_read'] += len(data)
        summary['large_files_over_200000_bytes'] += len(data) > 200000
        summary['files_growing_during_read'] += record['changed_during_read']
        if bound or record['candidate_pixel_matches']:
            candidates.append(record)
        if b'unallocated_test' in data and not is_catalog:
            mentions.append(record)
    actual_overlap = target_set & all_ids
    actual_pixel_overlap = target_pixels & pixels(all_ids)
    if actual_overlap or actual_pixel_overlap:
        raise ValueError('Non-catalog metadata binds reserve identities; review before allocation: ' +
                         json.dumps(candidates, sort_keys=True))
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_bytes = (json.dumps({'audit_started_unix_ns': started, 'files': index}, sort_keys=True, indent=2)+'\n').encode()
    index_path.write_bytes(index_bytes)
    result = {'schema': 'hepta.abc4.training-repair.source-allocation.v1',
        'audit_started_unix_ns': started, 'audit_completed_unix_ns': time.time_ns(),
        'manifest_sha256': MANIFEST_SHA, 'previous_control_allocation_sha256':
            sha((REPO/'experiments/multimodal_output_portfolio/abc_followup/control/SOURCE_ALLOCATION.json').read_bytes()),
        'allocation': {'source_role': 'unallocated_test', 'pair_start': 0, 'pair_end_exclusive': 1000,
            'source_pairs': 1000, 'individual_sources': 2000, 'unique_pixel_sha256': 2000,
            'pairing': 'No-replacement adjacent IDs [2k,2k+1] in the original manifest order',
            'ordered_source_ids_sha256': ids_sha(target), 'sorted_pixel_hashes_sha256': ids_sha(sorted(target_pixels))},
        'all_other_manifest_roles_excluded': disjoint,
        'exclude_current_test_role_entirely': {'source_pairs': 3000, 'individual_sources': 6000,
            'scope': 'Entire test role, including prior main, current control/training and all native calibration/verification reservations'},
        'metadata_scan': {'directories': totals, 'metadata_files': len(index),
            'bytes_read': sum(row['bytes_read'] for row in index), 'excluded_because_large': 0,
            'distinct_non_catalog_bound_ids': len(all_ids), 'non_catalog_bound_ids_sha256': ids_sha(sorted(all_ids)),
            'candidate_individual_id_overlap': len(actual_overlap), 'candidate_pixel_sha256_overlap': len(actual_pixel_overlap),
            'full_local_file_index_sha256': sha(index_bytes), 'full_local_file_index_bytes': len(index_bytes),
            'catalog_occurrences_containing_reserve_ids': candidates,
            'non_catalog_unallocated_test_mentions_for_review': mentions},
        'new_source_outcomes_opened': False, 'new_source_images_or_tensors_materialized': False,
        'source_units': '1000 original-image pairs; retain each pair across views, draws, policies, arms and training seeds. Original writer clusters unavailable.',
        'snapshot_scope': 'All available JSON/JSONL metadata under local abc* execution/asset roots and repository experiment artifacts, as enumerated at audit. Growing logs are hashed to file-open byte length. Excludes binary weights/media, caches, build trees, new prospective repair directory and unknown external runs.',
        'reservation_not_execution': True,
        'audit_code_sha256': sha(Path(__file__).read_bytes())}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
    print(json.dumps({'output': str(output), 'sha256': sha(output.read_bytes()), 'metadata_files': len(index),
        'metadata_bytes': result['metadata_scan']['bytes_read'], 'unallocated_mentions': len(mentions),
        'catalog_occurrences': len(candidates), 'new_source_outcomes_opened': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); audit(args.index, args.output)
