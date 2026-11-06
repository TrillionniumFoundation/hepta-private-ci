#!/usr/bin/env python3
"""Read-only verification of frozen audit publication inputs; no network or native calls."""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re


PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
PARENT = '089c13ab39cedb9fea0f9e9bd03d95317936cd65'
OLD_TREE = 'cd5ad6773d53055ae79cf3a5b79703406161eb69'
COMMIT = '46fd74d98c1cef42e1439920f9ca83361481b3d8'
NEW_TREE = '41d583262bc6ccd794ffb9e8e9ac9d04665ca85d'
INDEX_BLOB = '73365de8c684e33fbdb8f994b44ac4834ed92170'
INDEX_PATH = PREFIX + 'evidence-index-v9-postcut-20261105-registered.json'


def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def load(path):
    return json.loads(path.read_bytes())


def leaf_identity(row):
    return {key: row[key] for key in ['path', 'mode', 'type', 'sha']}


def merkle(leaves):
    directories = collections.defaultdict(dict)
    for path, row in leaves.items():
        assert path == row['path'] and not path.startswith('/') and '..' not in Path(path).parts
        parts = path.split('/')
        for index in range(len(parts) - 1):
            directories['/'.join(parts[:index])][parts[index]] = ('40000', None)
        directories['/'.join(parts[:-1])][parts[-1]] = (row['mode'].lstrip('0'), row['sha'])
    hashes = {}

    def visit(directory):
        entries = []
        for name, (mode, sha) in directories[directory].items():
            if mode == '40000':
                sha = visit((directory + '/' + name).lstrip('/'))
            order = name.encode() + (b'/' if mode == '40000' else b'')
            encoded = mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
            entries.append((order, encoded))
        body = b''.join(encoded for _, encoded in sorted(entries))
        hashes[directory] = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        return hashes[directory]

    return visit(''), hashes


def verify_complete_tree(tree, expected):
    assert tree['sha'] == expected and tree['truncated'] is False
    assert len({row['path'] for row in tree['tree']}) == len(tree['tree'])
    leaves = {row['path']: leaf_identity(row) for row in tree['tree'] if row['type'] != 'tree'}
    actual, directories = merkle(leaves)
    assert actual == expected
    tree_rows = [row for row in tree['tree'] if row['type'] == 'tree']
    assert len(tree_rows) + 1 == len(directories)
    assert all(directories[row['path']] == row['sha'] for row in tree_rows)
    return leaves, directories


def main(root):
    postcut = root / 'hepta-audit-fifth/v9/postcut-root'
    parent_receipt = load(root / 'hepta-audit-fifth/v9/commit-ref-actual.json')
    assert parent_receipt['commit'] == parent_receipt['actualCommit']['sha'] == PARENT
    assert parent_receipt['tree'] == parent_receipt['actualCommit']['tree']['sha'] == OLD_TREE
    assert parent_receipt['after']['object']['sha'] == PARENT
    old = load(root / 'hepta-audit-fifth/v9/intended-full-audit-tree.json')
    new = load(postcut / 'intended-full-audit-tree.json')
    before, old_directories = verify_complete_tree(old, OLD_TREE)
    after, new_directories = verify_complete_tree(new, NEW_TREE)
    assert before.keys() <= after.keys()
    assert all(after[path] == row for path, row in before.items())
    added = sorted(after.keys() - before.keys())
    assert len(added) == 205
    assert all(path.startswith(PREFIX) for path in added)
    assert not any(path in before for path in added)

    index_raw = (postcut / 'evidence-index-v9-postcut-20261105-registered.json').read_bytes()
    index_identity = identity(index_raw)
    index = json.loads(index_raw)
    registration = load(postcut / 'index-actual-registration.json')
    assert index_identity['git_blob'] == INDEX_BLOB == after[INDEX_PATH]['sha']
    assert all(index_identity[key] == registration[key] for key in index_identity)
    assert registration['actual_full_GET_equal'] is True
    assert index['audit_parent'] == PARENT and index['base_tree'] == OLD_TREE
    assert index['registered_objects'] == len(index['items']) == 204
    assert index['registered_bytes'] == sum(row['bytes'] for row in index['items'])
    assert index['index_not_counted_in_its_own_items'] is True
    assert index['counts'] == {'CLOSED_SCOPED': 15, 'OPEN': 7, 'SCIENTIFIC_HOLD': 1}
    assert index['original_exit_conditions_and_frozen_V9_documents_unchanged'] is True
    assert index['all_blockers_closed'] is False and index['whole_candidate_qualified'] is False
    assert index['source_main']['head'] == '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
    assert index['source_main']['tree'] == '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
    assert index['B11_diagnostic']['head'] == '2980fa274c599bd07437a2f5915b86d858f89bcc'
    assert index['B11_diagnostic']['merge'] == '53766cb836b198e2f928b949f148d7a2a10c0d21'
    assert index['B11_diagnostic']['tree'] == '9cb7302777ce018dd022086041c2225d1dd5c8dd'
    assert all(text in index['native_linux67_packet'] for text in ['execute=false', 'guard=null', '64000000000', '34359738368', 'CARGO_BUILD_JOBS=4'])
    assert PREFIX + index['immutable_core_index'] in before
    registered = {}
    for row in index['items']:
        path = row['path']
        assert path not in registered and path != INDEX_PATH and path.startswith(PREFIX)
        assert row['actual_full_GET_verified'] is True
        assert re.fullmatch(r'[0-9a-f]{40}', row['git_blob']) and re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
        assert isinstance(row['bytes'], int) and row['bytes'] >= 0
        assert after[path] == {'path': path, 'mode': '100644', 'type': 'blob', 'sha': row['git_blob']}
        registered[path] = row['git_blob']
    assert set(registered) | {INDEX_PATH} == set(added)
    assert index['link_checks']['missing'] == [] and index['link_checks']['relative_links'] == 11

    # Rebuild every incremental tree from immutable leaves, including the
    # failed initial 160-entry target later reached by four successful 40-entry stages.
    plan = load(postcut / 'incremental-tree-recovery-plan.json')
    stages = load(postcut / 'tree-stages-incremental.actual.json')
    assert plan['parent_commit'] == PARENT and plan['base_tree'] == OLD_TREE and plan['final_tree'] == NEW_TREE
    assert plan['new_paths'] == 205 and plan['batch_limit'] == 40 and plan['all_prior_leaves_unchanged'] is True
    assert len(plan['stages']) == len(stages) == 6
    current, previous_root, inserted, stage_results = dict(before), OLD_TREE, set(), []
    for wanted, actual in zip(plan['stages'], stages):
        assert wanted['base_tree'] == actual['base'] == previous_root
        entries = wanted['entries']
        assert 1 <= len(entries) <= 40 and actual['entries'] == len(entries)
        for row in entries:
            assert row['path'] not in current and row['path'] not in inserted
            assert leaf_identity(row) == after[row['path']]
            current[row['path']] = leaf_identity(row)
            inserted.add(row['path'])
        computed, directories = merkle(current)
        assert computed == wanted['expected_tree'] == actual['expected'] == actual['actual']['sha']
        assert wanted['proof']['tree'] == computed
        assert wanted['proof']['leaves'] == len(current) and wanted['proof']['directory_nodes'] == len(directories)
        assert wanted['proof']['all_Merkle_nodes_match'] is True
        stage_results.append({'base': previous_root, 'entries': len(entries), 'actual_and_recomputed_tree': computed})
        previous_root = computed
    assert current == after and inserted == set(added) and previous_root == NEW_TREE
    timeout = load(postcut / 'tree-timeout-reconciliation.json')
    assert timeout['attempted_stage']['base_tree'] == OLD_TREE
    assert timeout['attempted_stage']['entries'] == 160
    assert timeout['attempted_stage']['expected_tree'] == stage_results[3]['actual_and_recomputed_tree']
    assert '422' in timeout['initial_create_tree_result']
    failed_get = timeout['reconciliation'][0]['value']
    assert failed_get['isError'] is True and failed_get['structuredContent']['error_data']['status'] == '404'
    ref_snapshot = json.loads(timeout['reconciliation'][1]['value']['structuredContent']['content'])
    assert ref_snapshot['object']['sha'] == PARENT

    actual_root = load(postcut / 'final-tree-root.actual.json')['response']
    assert actual_root['sha'] == NEW_TREE and actual_root['truncated'] is False
    expected_top = {row['path']: leaf_identity(row) for row in new['tree'] if '/' not in row['path']}
    assert {row['path']: leaf_identity(row) for row in actual_root['tree']} == expected_top
    publication = load(postcut / 'commit-ref-actual.json')
    assert publication['commit'] == publication['created']['sha'] == publication['actualCommit']['sha'] == COMMIT
    assert publication['parent'] == PARENT and publication['tree'] == NEW_TREE
    assert publication['actualCommit']['tree']['sha'] == NEW_TREE
    assert [row['sha'] for row in publication['actualCommit']['parents']] == [PARENT]
    assert publication['before']['ref'] == publication['after']['ref'] == 'refs/heads/audit/r3-evidence-20261105'
    assert publication['before']['object']['sha'] == PARENT and publication['after']['object']['sha'] == COMMIT
    assert publication['new_paths'] == 205 and publication['registered_evidence_objects'] == 204
    assert publication['no_historical_or_source_overwrites'] is True

    prior_pr = {
        4797: load(root / 'hepta-audit-fifth/v9/pr4797-update.actual.json')['after']['body'],
        4884: load(root / 'hepta-audit-fifth/b11-host-neither-publication/pr4884-update.actual.json')['body'],
    }
    pr_results = []
    for number, head in [(4797, '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'), (4884, '2980fa274c599bd07437a2f5915b86d858f89bcc')]:
        record = load(postcut / f'pr{number}-postcut-update.actual.json')
        actual = record['update']['structuredContent']
        assert record['update']['isError'] is False
        assert record['number'] == actual['number'] == number and record['head'] == actual['head_sha'] == head
        assert actual['draft'] is True and actual['state'] == 'open'
        assert record['body'] == actual['body'] and record['full_actual_body_GET_equal'] is True
        assert record['prior_body_unchanged_as_history'] is True and record['body'].endswith(prior_pr[number])
        urls = re.findall(r'https://github\.com/TrillionniumFoundation/hepta-private-ci/blob/' + COMMIT + r'/([^\s)#]+)', record['body'])
        assert urls and all(path in after for path in urls)
        pr_results.append({'number': number, 'historical_cut_head': head, 'full_body': identity(record['body'].encode()),
            'previous_body': identity(prior_pr[number].encode()), 'entire_prior_body_preserved_as_suffix': True,
            'actual_record_body_equal': True, 'current_audit_commit_links': sorted(set(urls)), 'all_current_commit_links_exist': True})

    result = {
        'schema': 'v9-postcut-publication-independent-readonly-proof',
        'decision': 'EXACT_APPEND_PUBLICATION_BOUND_NO_QUALIFICATION_EXPANSION',
        'parent_commit': PARENT, 'parent_tree': OLD_TREE, 'commit': COMMIT, 'actual_tree': NEW_TREE,
        'prior_leaf_count': len(before), 'published_leaf_count': len(after),
        'prior_directory_nodes': len(old_directories), 'published_directory_nodes': len(new_directories),
        'new_paths': added, 'new_path_count': 205, 'modified_prior_paths': [], 'removed_prior_paths': [],
        'all_prior_source_and_evidence_leaves_byte_identity_unchanged': True,
        'registered_item_paths': 204, 'unique_registered_blob_hashes': len(set(registered.values())),
        'registered_bytes_as_indexed': index['registered_bytes'], 'index_identity': index_identity,
        'complete_added_paths_equal_registered_items_plus_index': True,
        'index_actual_registration_bound': True,
        'actual_root_entries_bound': True, 'actual_commit_parent_and_tree_bound': True,
        'before_after_ref_readback_bound': True, 'six_incremental_stages_recomputed': stage_results,
        'initial_timeout_summary_preserved': True, 'initial_expected_tree_404_original_preserved': True,
        'initial_ref_still_parent_original_preserved': True,
        'initial_422_raw_response_limit': 'The frozen root receipt preserves a summary of 422; it explicitly states the original raw error is in the tool transcript. This proof does not invent that raw response.',
        'PR_full_readback_and_history': pr_results,
        'underlying_204_items_re_fetched_or_requalified': False,
        'all_204_existing_registration_flags_retained': True,
        'counts': index['counts'], 'all_blockers_closed': False, 'whole_candidate_qualified': False,
        'linux_preparation_execute_false_guard_null': True,
        'network_access': False, 'native_execution': False, 'resource_queries': False,
        'product_compilation_or_formatting': False, 'ref_mutation': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent / 'root')
    main(parser.parse_args().root.resolve())
