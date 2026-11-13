#!/usr/bin/env python3
"""Create-only local report closure; no target code is imported."""
import hashlib
import json
from pathlib import Path

D=Path(__file__).resolve().parent
def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def save(name,value):
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with (D/name).open('xb') as f:f.write(raw)
    return pin(raw)
p=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/references/codex-rs/hepta-contracts/src/authority_trust.rs')
raw=p.read_bytes()
assert len(raw)==2313 and pin(raw)['git_blob']=='043ffd75a20c42935959a98d37f40e3d7229c407'
inv=json.loads(Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json').read_bytes())
row=next(x for x in inv['files'] if x['path']=='codex-rs/hepta-contracts/src/authority_trust.rs')
assert pin(raw)=={'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']}
assert b'pub trait AuthorityClock: Send + Sync {' in raw
assert b'pub trait AuthorityFrontierStore<F>: Send + Sync {' in raw
addendum=save('SEND_SYNC_TRAITS_ADDENDUM.json',{
 'format':'hepta-material22-original-auto-trait-source-addendum-v1',
 'source':{'path':str(p),**pin(raw)},
 'canonical_b608_identity_exact':True,
 'reviewed':'Complete original 2,313-byte file read. AuthorityClock and AuthorityFrontierStore explicitly require Send + Sync, including the trait-object store variant inspected in the main review.',
 'relation':'Additional concrete source evidence for REVIEW M02. The original BYTE_AND_CONTROL_FLOW_PROOF remains unchanged.',
 'limits':'Source trait constraints are not compiler execution or a full auto-trait proof for the final composed loader.',
 'project_execution':False,'h_calls':0,'git_created_by_reviewer':False})
review=json.loads((D/'REVIEW.json').read_bytes())
proof=json.loads((D/'BYTE_AND_CONTROL_FLOW_PROOF.json').read_bytes())
assert review['independent_byte_proof']['git_blob']==pin((D/'BYTE_AND_CONTROL_FLOW_PROOF.json').read_bytes())['git_blob']
assert proof['counts']['source_paths']==22 and proof['counts']['exact_replacements']==23
assert json.loads((D/'VERIFY_COMPLETION.original.json').read_bytes())['exit_code']==0
files=['verify_material_layer.py','BYTE_AND_CONTROL_FLOW_PROOF.json','REVIEW.json',
       'VERIFY_START.original.json','VERIFY_POLL_01.original.json','VERIFY_COMPLETION.original.json',
       'SEND_SYNC_TRAITS_ADDENDUM.json','seal_review.py']
entries=[{'name':name,'local_path':str(D/name),**pin((D/name).read_bytes()),
          'git_state':'computed_content_identity_only'} for name in files]
assert max(x['bytes'] for x in entries)<=512000
index=save('CLOSED_FILE_INDEX.json',{
 'format':'hepta-material22-independent-static-review-closed-index-v1',
 'entries':entries,'payload_count':len(entries),'including_this_index':len(entries)+1,
 'scope':'Fixed Material22 production layer only; loader and later mechanism-test layers excluded.',
 'publication':'Local complete bytes only. No Git upload/full GET claim by this reviewer.',
 'candidate_changed':False,'h_calls':0,'project_code_executed':False,
 'new_concrete_static_blockers':0})
print(json.dumps({'review':pin((D/'REVIEW.json').read_bytes()),'byte_proof':pin((D/'BYTE_AND_CONTROL_FLOW_PROOF.json').read_bytes()),'traits_addendum':addendum,'index':index,'files':len(entries)+1},sort_keys=True))
