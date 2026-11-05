"""Build a registered evidence index and exact, bounded Git-tree publication plan."""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import json
import posixpath
import re

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/v9'
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
PARENT = '0fc276d03e7d90f2e4fc53d67a0de8b942d51559'
BASE_TREE = 'c592f5edf3969f5fc8bf5100b532c2823c4f8f8a'
INDEX = PREFIX + 'evidence-index-v9-registered.json'


def load(path):
    return json.loads(path.read_bytes())


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def imported(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inputs():
    evidence = load(OUT / 'registered-evidence-plan.json')
    assert evidence['base_commit'] == PARENT and evidence['base_tree'] == BASE_TREE
    assert not evidence['missing_local_files']
    documents = load(OUT / 'documents-actual-registration.json')
    assert all(r['actual_create_and_complete_GET_verified'] for r in documents['files'])
    rows = {}
    for row in evidence['items'] + documents['files']:
        assert row['path'].startswith(PREFIX) and '..' not in Path(row['path']).parts
        assert row.get('mode', '100644') == '100644'
        actual = digest(Path(row['local_file']).read_bytes())
        assert {k: row[k] for k in actual} == actual, row['path']
        if row['path'] in rows:
            assert rows[row['path']]['git_blob'] == row['git_blob']
        rows[row['path']] = row
    ledger = load(OUT / 'documents/continuation-blocker-progress-v7.json')
    baseline = load(ROOT / 'hepta-audit-fifth/recovery-2113/ledger-v6.json')
    assert [(x['id'], x['original_exit_condition_zh']) for x in ledger['items']] == [(x['id'], x['original_exit_condition_zh']) for x in baseline['items']]
    assert ledger['counts'] == {'CLOSED_SCOPED': 15, 'OPEN': 7, 'SCIENTIFIC_HOLD': 1}
    assert ledger['all_blockers_closed'] is False and ledger['whole_candidate_qualified'] is False
    return rows, ledger


def links(rows):
    base = load(ROOT / 'hepta-audit-fifth/recovery-2113/trees/auditV8-leaves.json')
    available = {e['path'] for e in base['leaves']} | set(rows) | {INDEX}
    records = []
    missing = []
    for file in sorted((OUT / 'documents').glob('*.md')):
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', file.read_text()):
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
                continue
            path = posixpath.normpath(PREFIX + target.split('#', 1)[0])
            row = {'document': file.name, 'target': target, 'resolved_path': path, 'present_or_planned_index': path in available}
            records.append(row)
            if path not in available:
                missing.append(row)
    assert not missing, missing
    return {'relative_links': len(records), 'missing': missing, 'links': records, 'only_future_file_exception': INDEX}


def index():
    rows, ledger = inputs()
    link_check = links(rows)
    result = {
        'schema': 'hepta-continuation-evidence-index-v9-registered',
        'recorded_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'audit_parent': PARENT, 'audit_parent_tree': BASE_TREE,
        'previous_index': 'evidence-index-v8-registered.json',
        'scope': 'Evidence, root decisions and plans only; product changes are separately published with exact source identities.',
        'actual_registered_objects': len(rows), 'total_registered_bytes': sum(x['bytes'] for x in rows.values()),
        'all_complete_local_bytes_Git_SHA_and_SHA256_verified': True,
        'registrations': 'Each item cites its actual create/full-GET registry or root registration; final tree staging also binds every leaf.',
        'counts': ledger['counts'], 'product': ledger['product'], 'B11_diagnostic': ledger['b11_diagnostic_PR'],
        'original_23_ids_and_exit_conditions_unchanged': True,
        'original_failures_cancelled_skipped_ignored_attempts_preserved': True,
        'closure_transitions': ledger['closure_transitions_v9'],
        'original_native_capacity_gates_unchanged': {'disk_minimum_bytes': 64000000000, 'available_RAM_minimum_bytes': 34359738368, 'jobs': 4},
        'all_blockers_closed': False, 'whole_candidate_qualified': False,
        'link_validation': {'relative_links': link_check['relative_links'], 'missing': 0},
        'items': [rows[k] for k in sorted(rows)],
        'index_not_counted_in_its_own_items': True,
    }
    dump(OUT / 'evidence-index-v9-registered.json', result)
    dump(OUT / 'document-link-check.json', link_check)
    print(json.dumps({'objects': len(rows), 'bytes': result['total_registered_bytes'], 'links': link_check['relative_links'],
                      'index': digest((OUT / 'evidence-index-v9-registered.json').read_bytes())}))


def plan():
    rows, ledger = inputs()
    index_file = OUT / 'evidence-index-v9-registered.json'
    index_registration = load(OUT / 'index-actual-registration.json')
    assert index_registration['actual_create_and_complete_GET_verified'] is True
    assert {k: index_registration[k] for k in digest(index_file.read_bytes())} == digest(index_file.read_bytes())
    idx = load(index_file)
    assert idx['actual_registered_objects'] == len(rows)
    assert {e['path']: e['git_blob'] for e in idx['items']} == {p: r['git_blob'] for p, r in rows.items()}
    rows[INDEX] = {'path': INDEX, 'local_file': str(index_file), 'mode': '100644', **digest(index_file.read_bytes())}
    verifier = imported('oldtree', ROOT / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    builder = imported('newtree', ROOT / 'hepta-audit-fifth/verify_main_format_retention_publication.py')
    old = load(ROOT / 'hepta-audit-fifth/recovery-2113/trees/auditV8.json')
    assert old['sha'] == BASE_TREE
    old_proof = verifier.verify_merkle(old)
    old_leaves = {e['path']: {k: e[k] for k in ['path', 'mode', 'type', 'sha']} for e in old['tree'] if e['type'] != 'tree'}
    overwritten = []
    intended = dict(old_leaves)
    entries = []
    for path in sorted(rows):
        row = rows[path]
        if path in old_leaves:
            assert path == PREFIX + 'LATEST.md', ('historical object overwrite', path)
            overwritten.append({'path': path, 'before': old_leaves[path]['sha'], 'after': row['git_blob']})
        entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': row['git_blob']})
    stages = []
    previous_tree = BASE_TREE
    for start in range(0, len(entries), 160):
        batch = entries[start:start + 160]
        for entry in batch:
            intended[entry['path']] = entry
        full = builder.full_tree_from_leaves(intended)
        proof = verifier.verify_merkle(full)
        stages.append({'stage': len(stages) + 1, 'base_tree': previous_tree, 'expected_tree': full['sha'], 'entries': batch, 'tree_proof': proof})
        previous_tree = full['sha']
    assert {p: v for p, v in intended.items() if not p.startswith(PREFIX)} == {p: v for p, v in old_leaves.items() if not p.startswith(PREFIX)}
    final = builder.full_tree_from_leaves(intended)
    dump(OUT / 'intended-full-audit-tree.json', final)
    result = {'schema': 'hepta-v9-exact-tree-publication-plan-v1', 'parent_commit': PARENT, 'base_tree': BASE_TREE,
              'final_expected_tree': final['sha'], 'objects_including_index': len(entries), 'historical_overwrite_only_LATEST': overwritten,
              'new_paths': len(entries) - len(overwritten), 'removed_paths': [], 'all_changes_inside_continuation': True,
              'all_other_leaves_unchanged': True, 'base_proof': old_proof, 'stages': stages,
              'final_proof': verifier.verify_merkle(final), 'counts': ledger['counts'], 'whole_candidate_qualified': False}
    dump(OUT / 'tree-publication-plan.json', result)
    print(json.dumps({k: result[k] for k in ['final_expected_tree', 'objects_including_index', 'new_paths', 'final_proof']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['index', 'plan'])
    args = parser.parse_args()
    index() if args.phase == 'index' else plan()
