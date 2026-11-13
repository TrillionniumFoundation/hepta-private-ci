"""Freeze metadata after complete local-byte and Git-content verification."""
from pathlib import Path
import hashlib
import json

root = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1')


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def jwrite(name, value):
    path = root / name
    assert not path.exists(), 'Never overwrite a frozen map'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


local = json.loads((root / 'LOCAL_COMPOSITION.json').read_text())
readback = json.loads((root / 'GIT_FULL_READBACK.json').read_text())
rows = local['rust_files'] + local['non_rust_prepared']
expected = {row['path']: {key: row[key] for key in ('bytes', 'sha256', 'git_blob')} for row in rows}
assert len(expected) == len(rows)
assert readback['source_entries'] == len(rows)
assert readback['all_complete_gets_and_all_three_identities_equal'] is True
assert len(readback['sources']) == len(expected)
for item in readback['sources']:
    assert item['complete_full_get'] is True and item['all_three_local_identities_equal'] is True
    assert item['observed'] == expected[item['path']]
    data = (root / 'overlay' / item['path']).read_bytes()
    assert pin(data) == item['observed']
for item in readback['inputs']:
    assert item['complete_full_get'] is True and item['identity_equal'] is True
    assert pin((root / 'inputs' / item['name']).read_bytes()) == item['observed']

final = dict(local)
final['git_full_readback_status'] = 'All final source and input blobs returned complete content; all local size/SHA-256/Git identities match.'
final['git_full_readback'] = pin((root / 'GIT_FULL_READBACK.json').read_bytes())
final['local_full_byte_verification'] = pin((root / 'LOCAL_BYTE_VERIFICATION.json').read_bytes())
final['composition_source'] = pin((root / 'LOCAL_COMPOSITION.json').read_bytes())
final['historical_candidate_removals'] = final.pop('explicit_removals')
assert all(row['original_git_blob'] is None for row in final['removal_classification'])
final['candidate_only_exclusions'] = final['removal_classification']
final['canonical_source_deletions'] = []
final['materializer_delete_operations'] = []
final.pop('inherited_conditional_inventory_numbers_not_promoted')
final['prior_conditional_arithmetic'] = {
    'retained_in_original_input': 'inputs/ROOT89_MAP.json',
    'original_input_git_blob': '23d710dbda6f7d88ef6b693c1e77933d168b0177',
    'not_inherited_as_final_counts': True,
    'reason': 'The old helper is absent from canonical cc57; its historical prepared-layer exclusion '
              'must not subtract a canonical file or become a sha:null tree deletion.',
}
final['materializer_graph_contract'] = {
    'base': final['source_commit'],
    'overlay': 'Apply exactly the non-null final git_blob for each covered path; all complete contents are already in Git.',
    'deletions': [],
    'new_path_marker': 'original_git_blob:null classifies a new overlay path, never a deletion instruction.',
    'full_source_counts': 'Must be computed from the complete canonical graph and then actual isolated inventory.',
    'permission': 'This map does not authorize a materializer launch or source activation.',
}
jwrite('EXACT_COMPOSED_OVERLAY.json', final)
print(json.dumps({'map': pin((root / 'EXACT_COMPOSED_OVERLAY.json').read_bytes()),
                  'rust': len(final['rust_files']), 'non_rust': len(final['non_rust_prepared']),
                  'coverage': len(rows), 'canonical_source_deletions': [],
                  'B_peer': final['B_independent_peer_status'], 'qualification': False}, indent=2))
