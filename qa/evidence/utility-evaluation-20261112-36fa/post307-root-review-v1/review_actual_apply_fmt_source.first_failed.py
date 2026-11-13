import base64
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')
RUN = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def serialize(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def physical_tree(rows):
    tree = {}
    for path, row in rows.items():
        parts = path.split('/')
        assert path and not path.startswith('/') and all(p not in ('', '.', '..') for p in parts)
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        assert mode == row['index_mode']
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (mode, row['working_blob'])

    def digest(node):
        items = []
        for name, value in node.items():
            mode, sha = ('40000', digest(value)) if isinstance(value, dict) else value
            order = name.encode() + (b'/' if mode == '40000' else b'')
            items.append((order, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(raw for _, raw in sorted(items))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

    return digest(tree)


result_raw = (RUN / 'RESULT.json').read_bytes()
assert pin(result_raw) == {'bytes': 26765,
                         'sha256': '45dcfb960717c209e89eb47d8cf1bb5ebf536ad7548198c1f621e0a754bab640',
                         'git_blob': '23c8f1375aa98a4c166a9ff4245d8500f060d97f'}
result = json.loads(result_raw)
base_raw = (REPAIR / 'ACTUAL_FINAL_INVENTORY.exact_recovered.json').read_bytes()
assert pin(base_raw) == result['baseline_inventory']
inventory = json.loads(base_raw)
assert serialize(inventory) == base_raw
rows = {row['path']: row for row in inventory['files']}
assert len(rows) == len(inventory['files']) == inventory['filesystem_entries'] == inventory['tracked_entries'] == 15237
assert all(row['stable'] for row in rows.values())
assert physical_tree(rows) == result['baseline_physical_tree'] == '4ed32552042fee522965ea54caf95bbebb31ad43'
original_rows = copy.deepcopy(rows)

repair_raw = (REPAIR / 'SOURCE_PACKET.json').read_bytes()
assert pin(repair_raw)['git_blob'] == '12a664ce2905feb8107ae66b303c4975f17a9fe3'
repair = json.loads(repair_raw)
assert len(repair['changes']) == 4
for change in repair['changes']:
    path = change['path']
    row = rows[path]
    for side in ('before', 'after'):
        assert pin(change[side + '_text'].encode()) == change[side]
    assert {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']} == change['before']
    row.update(bytes=change['after']['bytes'], sha256=change['after']['sha256'],
               working_blob=change['after']['git_blob'], matches_index=False)
applied_raw = serialize(inventory)
assert pin(applied_raw) == result['application']['inventory']
assert physical_tree(rows) == result['application']['postimages']['all_actual_physical_tree'] == '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1'

fmt_raw = (RUN / 'fmt.after.postimages.json').read_bytes()
assert pin(fmt_raw) == {'bytes': 2175219,
                      'sha256': '3309f2099b3545737f390f16928d5d085177e72a6e8194aa018fe5039121dc22',
                      'git_blob': '43f7dd7eaa1578a4d6d570252939084f80181685'}
fmt = json.loads(fmt_raw)
assert fmt['base_inventory_sha256'] == pin(applied_raw)['sha256']
assert fmt['source_commit_unchanged'] == result['source_commit']
assert fmt['qualification'] is False and fmt['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
changes = fmt['changes']
assert len(changes) == len({c['path'] for c in changes}) == 62
assert [c['path'] for c in changes] == result['formatter_changed_paths']
checked = []
for change in changes:
    path = change['path']
    assert change['before'] == rows[path]
    assert change['after']['path'] == path
    for side in ('before', 'after'):
        raw = base64.b64decode(change[side + '_raw_base64'], validate=True)
        row = change[side]
        assert pin(raw) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
        assert row['stable'] is True
        assert row['matches_index'] == (row['working_blob'] == row['index_blob'])
    for key in ('path', 'kind', 'permissions', 'index_blob', 'index_mode', 'stable'):
        assert change['before'][key] == change['after'][key]
    rows[path].clear()
    rows[path].update(change['after'])
    checked.append({'path': path, 'before': change['before']['working_blob'], 'after': change['after']['working_blob'],
                    'complete_raw_before_after_verified': True, 'source_mode_and_index_identity_unchanged': True})
final_raw = serialize(inventory)
assert pin(final_raw) == result['actual_final_source']['inventory']
assert pin(final_raw)['sha256'] == fmt['after_inventory_sha256']
final_tree = physical_tree(rows)
assert final_tree == result['actual_final_source']['postimages']['all_actual_physical_tree'] == 'f905b18e6b05de1582024548179725a05d932536'
witness = 'codex-rs/hepta-learning-ledger/src/witness.rs'
assert rows[witness] == original_rows[witness]
assert rows[witness]['working_blob'] == 'a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d'
assert all(rows[p] == old for p, old in original_rows.items()
           if p not in {c['path'] for c in changes} | {c['path'] for c in repair['changes']})
(ROOT / 'ACTUAL_FMT_FINAL_INVENTORY.reconstructed.json').write_bytes(final_raw)
review = {
    'format': 'hepta-root-actual-apply-fmt-source-review-v1',
    'scope': 'Pure complete raw-byte, exact inventory reconstruction and mode-aware full-tree verification; no Rust semantic proof, build, test, source activation or H execution.',
    'result': pin(result_raw), 'baseline': pin(base_raw), 'approved_repair': pin(repair_raw),
    'application_inventory_exact_original_pin': pin(applied_raw), 'formatter_packet': pin(fmt_raw),
    'final_inventory_exact_original_pin': pin(final_raw), 'final_inventory_provenance': 'Lossless reconstruction from exact original b190 baseline plus four reviewed edits plus all 62 observed formatter after rows. Whole bytes/hash/Git match the original producer; not a second full native inventory read.',
    'source_leaf_count': len(rows), 'baseline_tree': result['baseline_physical_tree'],
    'applied_tree': result['application']['postimages']['all_actual_physical_tree'], 'final_physical_tree': final_tree,
    'formatter_changes': checked, 'all_other_rows_byte_structure_unchanged': True,
    'actual_fix_witness_preserved': True, 'old_fix_returncode': 101, 'old_fix_lint_success': False,
    'current_fmt_returncode': 0, 'tests_dispatched': 0, 'qualification': False,
    'next_requirements': ['Independent semantic review of actual formatter transitions', 'Original raw Git, input and lease audit receipts', 'Rebind protected source registrations to actual final bytes before exact source gates', 'Separately review and apply any later coordinator layer; do not infer compilation or execution'],
}
(ROOT / 'ROOT_ACTUAL_FMT_SOURCE_REVIEW.json').write_text(json.dumps(review, sort_keys=True, indent=2) + '\n')
print(json.dumps({'review': pin((ROOT / 'ROOT_ACTUAL_FMT_SOURCE_REVIEW.json').read_bytes()),
                  'final_inventory': pin(final_raw), 'final_tree': final_tree, 'checked_formatter_paths': len(checked)}, sort_keys=True))
