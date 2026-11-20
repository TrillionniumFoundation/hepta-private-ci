"""Prepare bounded, lossless host-archive publication files; no Git writes."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'e6_diagnostic_cloud_archive_1'))
from publication_parts_v2 import Publication, put_new


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jb(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def main():
    out = HERE / 'publication-1'
    out.mkdir(exist_ok=False)
    prefix = 'evidence/e6-observation-diagnostic-runtime-20261120/host'
    verified = json.loads((HERE / 'verification-1/RESULT.json').read_bytes())
    assert verified['successful'] and verified['regular_safe_unique_tar_members'] == 1136
    publication = Publication(out, prefix)
    sources = []
    parts = json.loads((HERE / 'retained/archive-parts.json').read_bytes())
    for row in parts['parts']:
        sources.append((HERE / 'retained' / row['name'], row['name']))
    for name in ('RESULT.json', 'archive-parts.json', 'ACTUAL_CORE_READBACK.json', 'OWNER_TERMINAL.json'):
        sources.append((HERE / 'retained' / name, name))
    for name in ('MANIFEST.json', 'SUMMARY.json', 'PHYSICAL_ORIGINALS.json', 'PRIVATE_MATERIAL_SCOPE.json',
                 'EXCLUDED_KEY_METADATA.json', 'CURRENT_NATIVE_ELF_METADATA.json', 'ORIGINAL_FILES.nul', 'INPUT.json'):
        sources.append((HERE / 'restored' / name, name))
    for name in ('RESULT.json', 'ALL_MEMBERS_VERIFIED.json', 'PHYSICAL_RESTORE_MAP.json', 'CROSSCHECK.json'):
        sources.append((HERE / 'verification-1' / name, 'verification/' + name))
    sources.append((HERE / 'DOWNLOAD_RESULT.json', 'verification/DOWNLOAD_RESULT.json'))
    for name in ('persist_receipt.py', 'verify_restore_host.py', 'prepare_host_publication.py'):
        sources.append((HERE / name, 'verification/tools/' + name))
    for name in ('archive_common.py', 'publication_parts_v2.py'):
        sources.append((ROOT / 'e6_diagnostic_cloud_archive_1' / name, 'verification/tools/' + name))
    for path in sorted((HERE / 'receipts').glob('*.json')):
        sources.append((path, 'verification/transport/' + path.name))
    root_readback = ROOT / 'e6_owner_work/observation_diagnostic_runtime_evidence/rev3/ROOT_FULL_MEMBER_READBACK.json'
    assert sha(root_readback.read_bytes()) == '139d92dcb636bbb14fc0d15baad59e9afc27d6e5b22a6f325a0173e3188b3d93'
    sources.append((root_readback, 'verification/ROOT_FULL_MEMBER_READBACK.json'))
    assert len({logical for unused, logical in sources}) == len(sources)
    representations = []
    for path, logical in sources:
        representations.append(publication.stage(path, prefix + '/' + logical))
    index = {
        'status': 'LOSSLESS_REPRESENTATIONS_NOT_PUBLISHED', 'source': verified['source'],
        'archive_sha256': verified['archive_sha256'], 'representations': representations,
        'every_source_preserved_verbatim': True, 'RPC_fields_removed': 0,
        'whole_tar_added_to_Git': False, 'whole_host_or_complete_provenance_claimed': False,
        'archive_meta_source_body_not_equal_to_new_repair_implementation': True,
    }
    put_new(out / 'REPRESENTATIONS.json', jb(index))
    representation_index = publication.stage(out / 'REPRESENTATIONS.json', prefix + '/verification/REPRESENTATIONS.json')
    verify = publication.verify_all()
    prior = json.loads((ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_273_FILES.json').read_bytes())
    assert set(publication.files).isdisjoint(row['path'] for row in prior)
    files = sorted(publication.files.values(), key=lambda row: row['path'])
    file_map = {
        'status': 'PREPARED_NOT_PUBLISHED', 'files': files, 'file_count': len(files),
        'total_bytes': sum(row['bytes'] for row in files),
        'max_file_bytes': max(row['bytes'] for row in files),
        'representation_index': representation_index, 'no_collision_with_frozen273': True,
        'whole_tar_not_added_to_Git': True, 'final_head_gate_not_executed': True,
    }
    put_new(out / 'PUBLICATION_FILES.json', jb(file_map))
    assert (out / 'PUBLICATION_FILES.json').read_bytes() == jb(file_map)
    # The orchestration map is external to its own file set. Preserve and split
    # it too if needed; keep a small recursive pointer instead of self-hashing.
    external = Publication(out / 'external-map', prefix + '/publication-control')
    map_rep = external.stage(out / 'PUBLICATION_FILES.json', prefix + '/publication-control/PUBLICATION_FILES.json')
    assert external.restore(map_rep) == jb(file_map)
    external.verify_all()
    put_new(out / 'PUBLICATION_MAP_STORAGE.json', jb({'representation': map_rep, 'external_to_its_own_file_set': True}))
    publication.verify_all()
    result = {
        'status': 'HOST_PUBLICATION_FILES_PREPARED_AND_VERIFIED_NOT_PUBLISHED',
        'source': verified['source'], 'file_count': len(files),
        'total_bytes': file_map['total_bytes'], 'max_file_bytes': file_map['max_file_bytes'],
        'archive_parts': 7, 'full_transport_RPCs': 60,
        'oversized_metadata_originals_reconstructed': len(publication.restorations),
        'file_map_sha256': sha((out / 'PUBLICATION_FILES.json').read_bytes()),
        'component_validation': verify, 'Git_actions': 0, 'native_or_model_runs': 0,
        'qualification_granted': False, 'final_head_gate_not_executed': True,
    }
    put_new(out / 'PUBLICATION_PREPARATION_RESULT.json', jb(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
