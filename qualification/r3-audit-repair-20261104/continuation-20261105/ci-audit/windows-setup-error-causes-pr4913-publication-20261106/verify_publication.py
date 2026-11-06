#!/usr/bin/env python3
"""Bind actual publication receipts to the separately frozen independent source review."""
import argparse
import hashlib
import json
from pathlib import Path

HEAD = '340fbc0629d27e3a2bda7c6971be25c60b3bf2bc'
BASE = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
TREE = '78b817fec87e593e0a0f6357d84f895b8574bde5'
MERGE = 'ff2b873c8b907e1e86b1a728c2c18552edfbd0ed'
BRANCH = 'fix/windows-setup-error-causes-20261106'
BASE_BRANCH = 'fix/r3-original-product-contracts-20261104'


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}


def response(raw):
    data = raw['structuredContent']
    if 'content' in data:
        return json.loads(data['content'])
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--review-root', type=Path, required=True)
    ap.add_argument('--review-manifest', type=Path)
    args = ap.parse_args()
    root, dependency = args.root.resolve(), args.review_root.resolve()
    original = root / 'original/publication-originals.json'
    root_get = root / 'original/tree-root-GET.original.json'
    original_bytes, root_bytes = original.read_bytes(), root_get.read_bytes()
    assert identity(original_bytes)['git_blob'] == '2527ad261497f7d9afc0ced4e39214ef5eae41d2'
    assert identity(root_bytes)['git_blob'] == 'da4b2781224d4032885d8063772320e0c9383bb3'
    package = json.loads(original_bytes)
    records = package['records']
    assert len(records) == 16
    for key, record in records.items():
        if isinstance(record, dict) and 'response' in record:
            assert response(record['raw']) == record['response'], key

    proof = (dependency / 'STATIC_VERIFICATION.json').read_bytes()
    review = (dependency / 'REVIEW.json').read_bytes()
    manifest_path = args.review_manifest or dependency / 'bundle/manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    assert identity(proof)['git_blob'] == '338e4fe099156932e9946b0f1a9fa4d44225332c'
    assert identity(review)['git_blob'] == '32b2d5c8a4a0875b92e6e3027d49f09f39e7329e'
    assert identity(manifest_bytes)['git_blob'] == 'fd76389b5c41732bbfe36925d1bae77f95ce261d'
    manifest = json.loads(manifest_bytes)
    members = {m['path']: m['identity'] for m in manifest['members']}
    intended_bytes = (dependency / 'inputs/intended-full-tree.json').read_bytes()
    assert identity(intended_bytes) == members['inputs/intended-full-tree.json']
    intended = json.loads(intended_bytes)
    assert intended['sha'] == TREE
    assert json.loads(proof)['computed_candidate_tree'] == TREE
    assert records['independent']['text'].encode() == review
    assert records['independent']['raw']['structuredContent']['content'].encode() == review
    assert records['independent']['identity'] == identity(review)

    sources = []
    for path, old_sha, new_sha in [
        ('codex-rs/windows-sandbox-rs/src/setup_error.rs',
         'd9104602bc19af88101fbb5b44f839a1d799c174', '37aa38dde9e83ee5f3ce8f267f11afd76fee3400'),
        ('codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs',
         '1d9340c6db26d6d10c1b3edecb1c9fecc908ef1d', '505be9299f9580877449740fd235e988f8c93b7b'),
    ]:
        for prefix, sha, kind in [('preimage', old_sha, 'preimage'), ('postimage', new_sha, 'candidate')]:
            record = records[prefix + '.' + sha]
            data = record['text'].encode()
            assert identity(data) == record['identity']
            assert identity(data)['git_blob'] == sha
            assert data == (dependency / 'inputs' / kind / path).read_bytes()
            get = record['raw'] if prefix == 'preimage' else record['full_GET']
            assert get['structuredContent']['content'].encode() == data
            if prefix == 'postimage':
                assert response(record['create'])['sha'] == sha
            sources.append({'path': path, 'role': prefix, **identity(data), 'full_GET_bytes_equal': True})

    actual_root = response(json.loads(root_bytes))
    assert actual_root['sha'] == TREE and actual_root['truncated'] is False
    field_names = ['path', 'mode', 'type', 'sha']
    observed = [{k: item[k] for k in field_names} for item in actual_root['tree']]
    expected = [{k: item[k] for k in field_names} for item in intended['tree'] if '/' not in item['path']]
    assert len(observed) == len(expected) == 53
    assert sorted(observed, key=lambda x: x['path']) == sorted(expected, key=lambda x: x['path'])
    body = b''
    for item in sorted(observed, key=lambda x: (x['path'] + ('/' if x['type'] == 'tree' else '')).encode()):
        mode = '40000' if item['type'] == 'tree' else item['mode']
        body += mode.encode() + b' ' + item['path'].encode() + b'\0' + bytes.fromhex(item['sha'])
    computed_root = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    assert computed_root == TREE

    before = records['refBefore.1']['response']
    assert before['ref'] == 'refs/heads/' + BASE_BRANCH and before['object']['sha'] == BASE
    assert records['refBefore.2']['response']['error_code'] == 'NOT_FOUND'
    assert records['treeCreated']['response']['sha'] == TREE
    assert records['commitCreated']['response']['sha'] == HEAD
    commit = records['commitActual']['response']
    assert commit['sha'] == HEAD and commit['tree']['sha'] == TREE
    assert [p['sha'] for p in commit['parents']] == [BASE]
    assert records['branchCreated']['response']['branch'] == BRANCH
    after = records['refAfter']['response']
    assert after['ref'] == 'refs/heads/' + BRANCH and after['object']['sha'] == HEAD
    pr = records['prActual']['response']
    created_pr = records['prCreated']['response']
    assert pr['number'] == created_pr['number'] == 4913
    assert pr['draft'] is created_pr['draft'] is True and pr['state'] == 'open'
    assert pr['head']['ref'] == BRANCH and pr['head']['sha'] == HEAD
    assert pr['base']['ref'] == BASE_BRANCH and pr['base']['sha'] == BASE
    assert created_pr['head_sha'] == HEAD and created_pr['base_sha'] == BASE
    assert created_pr['body'] == pr['body'] == records['prBodyIntended']
    assert pr['merge_commit_sha'] == MERGE
    merge = records['mergeActual']['response']
    assert merge['sha'] == MERGE and merge['tree']['sha'] == TREE
    assert [p['sha'] for p in merge['parents']] == [BASE, HEAD]
    result = {
        'schema': 'windows-setup-error-causes-publication-independent-v1',
        'actual_pr': 4913, 'draft': True, 'actual_head': HEAD, 'actual_parent': BASE,
        'actual_merge': MERGE, 'actual_merge_parents': [BASE, HEAD], 'actual_tree': TREE,
        'originals': [{'path': original.name, **identity(original_bytes)}, {'path': root_get.name, **identity(root_bytes)}],
        'original_record_groups': len(records), 'raw_response_projections_equal': True,
        'source_full_bytes_equal': sources, 'actual_root_entry_count': len(observed),
        'actual_root_exactly_equals_independent_full_tree_projection': True,
        'actual_root_git_sha_recomputed': computed_root,
        'PR_body_exactly_equals_intended_body': True,
        'dependency': {'registry_actual': '42748aff2421ab2bee7757158793868f08dd53d9',
            'member_count': 37, 'review_actual': identity(review)['git_blob'], 'static_actual': identity(proof)['git_blob'],
            'manifest_actual': identity(manifest_bytes)['git_blob']},
        'root_published_refs': True, 'reviewer_published_refs': False,
        'CI_or_Rust_or_native_qualification': 'PENDING; no execution queried or triggered by this verifier.',
        'Windows_only_new_tests': ['untyped_setup_report_preserves_context_chain_and_os_error',
                                  'typed_setup_report_preserves_code_and_message_through_context'],
        'ACL_root_cause': 'UNKNOWN; this publication preserves error detail and does not change ACL policy.'
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
