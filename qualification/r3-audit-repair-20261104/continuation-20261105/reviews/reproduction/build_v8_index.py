from pathlib import Path
import hashlib
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
P = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
plan = json.loads((ROOT / 'hepta-audit-fifth/registration-plan-v8-pending.json').read_text())
assert plan['counts'] == {'CLOSED_SCOPED': 11, 'OPEN': 11, 'SCIENTIFIC_HOLD': 1}
items = []
for row in plan['items']:
    assert row['actual_object_verified'], row['repository_path']
    body = Path(row['local_file']).read_bytes()
    assert len(body) == row['bytes'] <= 512000
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == row['blob']
    assert row['repository_path'].startswith(P)
    items.append({'path': row['repository_path'], 'mode': row['mode'], 'bytes': len(body),
                  'sha256': row['sha256'], 'git_blob': row['blob'],
                  'actual_create_and_complete_GET_verified': True})
assert len({r['path'] for r in items}) == len(items)
index = {'schema': 'hepta-registered-evidence-index-v8',
         'base_audit_commit': plan['base_audit_commit'], 'base_audit_tree': plan['base_audit_tree'],
         'evidence_only': True, 'product_source_or_CI_policy_changed_by_this_commit': False,
         'ledger_counts': plan['counts'], 'all_blockers_closed': False, 'whole_product_qualified': False,
         'original_23_IDs_and_exit_conditions_unchanged': True, 'sole_closure_transition': 'B08 OPEN -> CLOSED_SCOPED',
         'fixed_document_cut': '2026-11-05T17:53:52Z',
         'postcut': 'Separately timed17:54 main API snapshot, native6 original147/7/2 and17:58 counterfactual publication; no negative execution inferred.',
         'prior_index': 'evidence-index-v7-registered.json',
         'verification': 'Every explicit object has actual create plus complete byte-equal GET; root rehashes bytes. Actual composed full Git tree is verified before ref update.',
         'identity_caveat': 'A content SHA inside an original may be computed only; actual materialization is attested only for explicitly listed objects.',
         'entry_count': len(items), 'entry_bytes': sum(x['bytes'] for x in items),
         'maximum_entry_bytes': max(x['bytes'] for x in items), 'items': items}
out = ROOT / 'hepta-audit-fifth/v8-deliverables/evidence-index-v8-registered.json'
out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n')
body = out.read_bytes()
assert len(body) <= 512000
plan['schema'] = 'hepta-evidence-only-registration-plan-v8-all-actual'
plan['all_entries_actual_create_and_full_GET_verified'] = True
(ROOT / 'hepta-audit-fifth/registration-plan-v8-all-actual.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'entries': len(items), 'index_bytes': len(body), 'index_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest(), 'total_bytes': index['entry_bytes']}))
