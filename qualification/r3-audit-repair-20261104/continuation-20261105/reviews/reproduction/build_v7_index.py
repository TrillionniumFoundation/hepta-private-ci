"""Create the portable evidence index only after every actual object is verified."""
from pathlib import Path
import hashlib
import json

ROOT=Path('/workspace/scratch/07dd58cc9630')
P='qualification/r3-audit-repair-20261104/continuation-20261105/'
plan=json.loads((ROOT/'hepta-audit-fifth/registration-plan-v7-pending.json').read_text())
assert plan['counts']=={'CLOSED_SCOPED':10,'OPEN':12,'SCIENTIFIC_HOLD':1}
items=[]
for row in plan['items']:
    assert row['actual_object_verified'],row['repository_path']
    data=Path(row['local_file']).read_bytes()
    assert len(data)==row['bytes']<=512000
    assert hashlib.sha256(data).hexdigest()==row['sha256']
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==row['blob']
    assert row['repository_path'].startswith(P)
    items.append({'path':row['repository_path'],'mode':row['mode'],'bytes':len(data),
                  'sha256':row['sha256'],'git_blob':row['blob'],
                  'actual_create_and_complete_GET_verified':True})
assert len({r['path'] for r in items})==len(items)
index={'schema':'hepta-registered-evidence-index-v7',
       'base_audit_commit':plan['base_audit_commit'],'base_audit_tree':plan['base_audit_tree'],
       'evidence_only':True,'product_source_or_CI_policy_changed_by_this_commit':False,
       'ledger_counts':plan['counts'],'all_blockers_closed':False,'whole_product_qualified':False,
       'frozen_archive_cut':'Main old5b0078 / neweed0004 ending2026-11-05T16:39:48.921Z',
       'later_observations':'Separately registered native5 terminal, eed Windows original artifacts/snapshot17:07, donor SQLx originals; no historical original rewritten',
       'entry_count':len(items),'entry_bytes':sum(x['bytes'] for x in items),
       'maximum_entry_bytes':max(x['bytes'] for x in items),
       'verification':'Owning-agent or root actual Git blob creation and full byte-equal GET; root recomputes every local SHA256/Git blob. Actual full tree is separately verified before branch update.',
       'identity_caveat':'A SHA inside an original record may identify content only. This index attests actual materialized blobs only for its explicit entries.',
       'archive_caveat':'Compressed complete artifacts retain original failures, attempts, skipped cases, errors and source limits. Successful job status alone does not qualify business cases.',
       'items':items}
out=ROOT/'hepta-audit-fifth/v7-deliverables/evidence-index-v7-registered.json'
out.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
data=out.read_bytes();assert len(data)<=512000
plan['schema']='hepta-evidence-only-registration-plan-v7-all-actual'
plan['all_entries_actual_create_and_full_GET_verified']=True
(ROOT/'hepta-audit-fifth/registration-plan-v7-all-actual.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'entries':len(items),'index_bytes':len(data),'index_git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),
                  'total_bytes':index['entry_bytes'],'max_entry':index['maximum_entry_bytes']}))
