"""Append registered post-cut evidence without changing frozen V9 documents."""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import json
import posixpath
import re

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/v9/postcut-root'
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
PARENT = '089c13ab39cedb9fea0f9e9bd03d95317936cd65'
BASE_TREE = 'cd5ad6773d53055ae79cf3a5b79703406161eb69'
INDEX_NAME = 'evidence-index-v9-postcut-20261105-registered.json'


def load(path):
    return json.loads(path.read_bytes())


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def imported(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize(row, registry):
    path = row.get('path', row.get('repo_path', row.get('repository_path')))
    assert path and path.startswith(PREFIX) and '..' not in Path(path).parts
    assert all(row[key] == path for key in ['path', 'repo_path', 'repository_path'] if key in row)
    local = Path(row['local_file'])
    raw = local.read_bytes()
    actual = identity(raw)
    assert all(row[k] == v for k, v in actual.items()), path
    flags = ['actual_full_GET_equal', 'actual_full_GET_byte_equal',
             'actual_create_and_full_GET_byte_equal', 'create_get_equal',
             'actual_create_and_complete_GET_verified']
    assert any(row.get(k) is True for k in flags), ('missing actual GET attestation', path)
    for key in ['actual_blob_sha', 'actual_create_blob_sha']:
        assert key not in row or row[key] == actual['git_blob']
    return {'path': path, 'local_file': str(local.resolve()), **actual,
            'actual_full_GET_verified': True, 'registration': registry,
            'materialization_method': row.get('actual_materialization_method', row.get('method', row.get('create_encoding', 'As recorded in source registry')))}


def inputs():
    config = load(OUT / 'registry-inputs.json')
    rows = {}
    for item in config['registries']:
        file = ROOT / item['local_file']
        raw = file.read_bytes()
        assert identity(raw)['git_blob'] == item['git_blob'], file
        registry = json.loads(raw)
        source_rows = registry.get('files', registry.get('items'))
        assert isinstance(source_rows, list) and len(source_rows) == item['items']
        for source in source_rows:
            row = normalize(source, {'local_file': str(file), 'git_blob': item['git_blob']})
            assert row['path'] not in rows or rows[row['path']]['git_blob'] == row['git_blob']
            rows[row['path']] = row
        self_row = {'path': PREFIX + item['repo_suffix'], 'local_file': str(file),
                    **identity(raw), 'actual_full_GET_equal': item['root_or_agent_actual_registry_GET_equal']}
        assert self_row['path'] not in rows or rows[self_row['path']]['git_blob'] == self_row['git_blob']
        rows[self_row['path']] = normalize(self_row, {'source': 'Actual registry self readback', 'git_blob': item['git_blob']})
    for filename in config['individual_registration_files']:
        row = normalize(load(ROOT / filename), {'local_file': filename})
        assert row['path'] not in rows or rows[row['path']]['git_blob'] == row['git_blob']
        rows[row['path']] = row
    base = load(ROOT / 'hepta-audit-fifth/v9/intended-full-audit-tree.json')
    assert base['sha'] == BASE_TREE
    prior = {r['path']: r for r in base['tree'] if r['type'] != 'tree'}
    assert not (set(rows) & set(prior)), 'Post-cut must not overwrite frozen evidence or documents'
    available = set(rows) | set(prior) | {PREFIX + INDEX_NAME}
    links = []
    for row in rows.values():
        if not row['path'].endswith('.md'):
            continue
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', Path(row['local_file']).read_text()):
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(row['path']), target.split('#', 1)[0]))
            links.append({'document': row['path'], 'target': target, 'resolved': resolved, 'present': resolved in available})
    missing = [r for r in links if not r['present']]
    assert not missing, missing
    return rows, base, links


def index():
    rows, _, links = inputs()
    data = {'schema': 'hepta-v9-postcut-registered-evidence-index-v1',
            'frozen_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'audit_parent': PARENT, 'base_tree': BASE_TREE,
            'immutable_core_index': 'evidence-index-v9-registered.json',
            'source_main': {'head': '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed', 'merge': 'b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae', 'tree': '3982ba56dc5a3f1da0c1de7ea57992f88125c359'},
            'B11_diagnostic': {'head': '2980fa274c599bd07437a2f5915b86d858f89bcc', 'merge': '53766cb836b198e2f928b949f148d7a2a10c0d21', 'tree': '9cb7302777ce018dd022086041c2225d1dd5c8dd', 'qualification': 'Two-path observation candidate; native10 results belong to its prior source. B11 remains OPEN.'},
            'counts': {'CLOSED_SCOPED': 15, 'OPEN': 7, 'SCIENTIFIC_HOLD': 1},
            'original_exit_conditions_and_frozen_V9_documents_unchanged': True,
            'all_blockers_closed': False, 'whole_candidate_qualified': False,
            'CI_snapshot_semantics': 'Every snapshot retains its own observation interval and source/merge identity. API success and prepared packets do not close product gates.',
            'native_linux67_packet': 'Prepared and offline-verified only; execute=false, guard=null, original disk 64000000000 bytes, available RAM 34359738368 bytes, CARGO_BUILD_JOBS=4. No new host capacity evidence or native execution.',
            'items': [rows[k] for k in sorted(rows)], 'registered_objects': len(rows),
            'registered_bytes': sum(r['bytes'] for r in rows.values()),
            'index_not_counted_in_its_own_items': True,
            'link_checks': {'relative_links': len(links), 'missing': []}}
    dump(OUT / INDEX_NAME, data)
    dump(OUT / 'document-links.json', links)
    print(json.dumps({'objects': len(rows), 'bytes': data['registered_bytes'], 'links': len(links), 'index': identity((OUT / INDEX_NAME).read_bytes())}))


def plan():
    rows, base, _ = inputs()
    index_file = OUT / INDEX_NAME
    idx = load(index_file)
    assert {r['path']: r['git_blob'] for r in idx['items']} == {p: r['git_blob'] for p, r in rows.items()}
    reg = load(OUT / 'index-actual-registration.json')
    assert reg['actual_full_GET_equal'] is True
    assert all(reg[k] == v for k, v in identity(index_file.read_bytes()).items())
    rows[PREFIX + INDEX_NAME] = {'path': PREFIX + INDEX_NAME, 'local_file': str(index_file), **identity(index_file.read_bytes())}
    builder = imported('postcut_builder', ROOT / 'hepta-audit-fifth/verify_main_format_retention_publication.py')
    checker = imported('postcut_checker', ROOT / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    checker.verify_merkle(base)
    leaves = {r['path']: builder.ident(r) for r in base['tree'] if r['type'] != 'tree'}
    old = dict(leaves)
    entries = [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': rows[p]['git_blob']} for p in sorted(rows)]
    stages = []
    previous_tree = BASE_TREE
    for start in range(0, len(entries), 160):
        batch = entries[start:start + 160]
        for row in batch:
            assert row['path'] not in leaves
            leaves[row['path']] = row
        tree = builder.full_tree_from_leaves(leaves)
        proof = checker.verify_merkle(tree)
        stages.append({'base_tree': previous_tree, 'expected_tree': tree['sha'], 'entries': batch, 'proof': proof})
        previous_tree = tree['sha']
    assert all(leaves[p] == value for p, value in old.items())
    final = builder.full_tree_from_leaves(leaves)
    dump(OUT / 'intended-full-audit-tree.json', final)
    data = {'schema': 'hepta-v9-postcut-exact-tree-plan-v1', 'parent_commit': PARENT,
            'base_tree': BASE_TREE, 'final_tree': final['sha'], 'new_paths': len(entries),
            'overwritten_paths': [], 'removed_paths': [], 'all_prior_leaves_unchanged': True,
            'stages': stages, 'full_tree_proof': checker.verify_merkle(final)}
    dump(OUT / 'tree-publication-plan.json', data)
    print(json.dumps({k: data[k] for k in ['final_tree', 'new_paths', 'full_tree_proof']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['index', 'plan'])
    args = parser.parse_args()
    index() if args.phase == 'index' else plan()
