#!/usr/bin/env python3
"""Prepare only five reviewed non-Rust candidate postimages; no source activation."""
from pathlib import Path
import ast,base64,copy,difflib,gzip,hashlib,json,re,tomllib

ROOT=Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
BEFORE=ROOT/'source-before'
AFTER=ROOT/'proposal-after'
BASE='246d8cb614770252ee42029a5c014f2a4904176a'
BASE_TREE='d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'

def ident(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def jb(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
def save(p,b):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==b,str(p)
 else:p.write_bytes(b)
def ast_constants(code):
 out={}
 for n in ast.parse(code).body:
  if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
   try:out[n.targets[0].id]=ast.literal_eval(n.value)
   except (ValueError,TypeError):pass
 return out
def tree_sha(leaves):
 root={}
 for path,(mode,sha) in leaves.items():
  cur=root;parts=path.split('/')
  for part in parts[:-1]:cur=cur.setdefault(part,{})
  assert parts[-1] not in cur;cur[parts[-1]]=(mode,sha)
 def walk(d):
  entries=[]
  for name,x in d.items():
   mode,sha=('40000',walk(x)) if isinstance(x,dict) else x
   entries.append((name,mode,sha))
  entries.sort(key=lambda x:(x[0]+('/' if x[1]=='40000' else '')).encode())
  raw=b''.join(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha) for name,mode,sha in entries)
  return hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 return walk(root)

def main():
 invraw=Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json').read_bytes()
 assert ident(invraw)=={'bytes':5611184,'sha256':'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e','git_blob':'663373f936c2ff130aec96ad34654cc9811773c2'}
 inv=json.loads(invraw);pins={r['path']:r for r in inv['files']};changes={};details=[]
 def update(path,post,why):
  before=(BEFORE/path).read_bytes();row=pins[path]
  assert ident(before)=={'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['index_blob']}
  after=post.encode();assert before!=after
  save(AFTER/path,after);changes[path]=(before,after)
  details.append({'path':path,'rationale':why,'before':ident(before),'after':ident(after)})
 path='qa/b4-no-bypass/test_original_circuit_observer_source_closure.py'
 before=(BEFORE/path).read_text();old='        "fn into_command_owner(",\n';new='        "fn into_command_owner(", "fn require_profile(",\n';assert before.count(old)==1
 post=before.replace(old,new,1);assert post.replace(new,old,1)==before
 update(path,post,'Add the already-protected private Sources::require_profile to the exact expected function set. Existing per-sequence mutation loop now attacks its original full-body sequence too; no old expected entry or mutation is removed.')
 path='qa/b4-no-bypass/test_original_selection_readback_source_closure.py'
 before=(BEFORE/path).read_text()
 old1='self.mutate(CLIENT, "fn operation(", "None => OPERATION")'
 old2='self.mutate(CLIENT, "fn operation(", "Some(_)")'
 new1='self.mutate(CLIENT, "fn operation(", "} else {\\n        OPERATION\\n    }")'
 new2='self.mutate(CLIENT, "fn operation(", "context.evaluated.is_some()")'
 assert before.count(old1)==before.count(old2)==1
 extra='\n        self.mutate(\n            CLIENT, "fn operation(",\n            \'"runtime.learning.original-circuit-evaluated-selection.readback.v1"\',\n            \'"runtime.learning.original-circuit-evaluated-selection.readbacK.v1"\',\n        )'
 post=before.replace(old1,new1,1).replace(old2,new2+extra,1);assert post.replace(new1,old1,1).replace(new2+extra,old2,1)==before
 operation=(BEFORE/'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs').read_text().split('fn operation(',1)[1]
 assert operation.count('} else {\n        OPERATION\n    }')==operation.count('context.evaluated.is_some()')==1
 update(path,post,'Translate both original branch-deletion attacks from stale match-arm spellings to the exact pinned if/else body. Legacy fallback removal and evaluated-condition removal both remain. Add one same-length evaluated-return-domain mutation; original mutation helper and all other purpose/action/context assertions are unchanged.')
 path='qa/b4-no-bypass/test_resident_root_source_closure.py'
 before=(BEFORE/path).read_text();constants=ast_constants(before);old_cases=constants['ROOT_ISSUER_CASES'];assert len(old_cases)==6
 workflow=(BEFORE/'.github/workflows/hepta-daemon-learning-native.yml').read_text();parents=ast.literal_eval(re.search(r'parents = (\[[\s\S]*?\n          \])',workflow).group(1))
 suffix='evaluated_version_late_b_loss_keeps_published_material_but_cannot_serve_s_or_start_c'
 actual=[x for x in parents if x.endswith(suffix)];assert len(actual)==1 and len(parents)==33
 new_case=actual[0];assert new_case not in old_cases
 match=re.search(r'(?ms)^ROOT_ISSUER_CASES = \[\n.*?^\]',before);assert match
 pos=match.end()-1;addition='    '+json.dumps(new_case)+',\n';post=before[:pos]+addition+before[pos:]
 assert post[:pos]+post[pos+len(addition):]==before
 new_constants=ast_constants(post);assert new_constants['ROOT_ISSUER_CASES']==old_cases+[new_case]
 assert len(parents)==7+len(new_constants['ROOT_CASES'])+len(new_constants['ROOT_ISSUER_CASES'])
 assert set(new_constants['ROOT_CASES']).issubset(parents) and set(new_constants['ROOT_ISSUER_CASES']).issubset(parents)
 update(path,post,'Append the actual already-registered UID0 issuer case FQN. Keep the original six issuer cases, all Root cases, uniqueness/subset assertions and exact 7+len(ROOT_CASES)+len(ROOT_ISSUER_CASES) equality; no count relaxation.')
 path='CALLERS.toml';before=(BEFORE/path).read_text();old_manifest=tomllib.loads(before)
 starts=[m.start() for m in re.finditer(r'(?m)^\[\[protected_file\]\]$',before)];assert len(starts)==len(old_manifest['protected_file'])==422
 target_paths=['codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs','codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs','codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs']
 edits=[]
 for index,path_name in zip((386,387,388),target_paths):
  row=old_manifest['protected_file'][index];assert row['path']==path_name and 'recover_original_custody' not in row['forbidden']
  a=starts[index];z=starts[index+1];section=before[a:z];array=re.search(r'(?m)^forbidden = \[.*\]$',section);assert array
  insertion=a+array.end()-1;edits.append((insertion,', "recover_original_custody"'))
 post=before
 for at,added in reversed(edits):post=post[:at]+added+post[at:]
 new_manifest=tomllib.loads(post);restored=copy.deepcopy(new_manifest)
 for index in (386,387,388):
  assert restored['protected_file'][index]['forbidden']==old_manifest['protected_file'][index]['forbidden']+['recover_original_custody'];restored['protected_file'][index]['forbidden'].pop()
 assert restored==old_manifest
 assert len(new_manifest['boundary'])==569
 update(path,post,'Three additive complete-identifier prohibitions restore the existing three readonly custody-recovery attacks. Original whole-token matcher, all old forbidden markers and every caller/boundary/authority field remain unchanged. This is not a general recover-prefix detector or evidence of runtime authority acquisition.')
 callers_sha=ident(changes['CALLERS.toml'][1])['sha256'];path='.github/blob-size-allowlist.txt';before=(BEFORE/path).read_text()
 line='sha256:'+callers_sha+' CALLERS.toml\n';assert line not in before
 post=before+'\n# Original Trainer readonly adapters reject actual custody recovery; exact reviewed inventory.\n'+line
 assert post.startswith(before)
 update(path,post,'Append only the exact new CALLERS SHA256 exception; all historical exceptions and the generic size limit remain unchanged.')
 assert set(changes)=={'.github/blob-size-allowlist.txt','CALLERS.toml','qa/b4-no-bypass/test_original_circuit_observer_source_closure.py','qa/b4-no-bypass/test_original_selection_readback_source_closure.py','qa/b4-no-bypass/test_resident_root_source_closure.py'}
 leaves={r['path']:(r['index_mode'],r['index_blob']) for r in inv['files']};assert tree_sha(leaves)==BASE_TREE
 for path,(_,after) in changes.items():leaves[path]=(pins[path]['index_mode'],ident(after)['git_blob'])
 after_tree=tree_sha(leaves)
 diff=''.join(''.join(difflib.unified_diff(a.decode().splitlines(keepends=True),b.decode().splitlines(keepends=True),fromfile='a/'+path,tofile='b/'+path)) for path,(a,b) in sorted(changes.items()))
 save(ROOT/'REPAIR.diff',diff.encode())
 packet={'format':'hepta-246d-source-closure-five-file-repair-proposal-v1','base_commit':BASE,'base_tree':BASE_TREE,'base_inventory':ident(invraw),'expected_after_tree':after_tree,'expected_after_leaf_count':len(leaves),'changes':[{'path':p,'mode':pins[p]['index_mode'],'before':ident(a),'after':ident(b),'after_base64':base64.b64encode(b).decode()} for p,(a,b) in sorted(changes.items())]}
 raw=jb(packet);save(ROOT/'REPAIR_PACKET.json',raw);gz=gzip.compress(raw,compresslevel=9,mtime=0);save(ROOT/'REPAIR_PACKET.json.gz',gz);parts=[]
 for i,start in enumerate(range(0,len(gz),196608),1):
  encoded=base64.b64encode(gz[start:start+196608])+b'\n';name='REPAIR_PACKET.json.gz.part'+str(i).zfill(3)+'.b64';save(ROOT/name,encoded);parts.append({'name':name,**ident(encoded)})
 manifest={'format':'hepta-246d-source-closure-repair-review-v1','status':'PREPARED_NOT_ACTIVATED_NOT_YET_TESTED','base_commit':BASE,'base_tree':BASE_TREE,'expected_after_tree':after_tree,'leaf_count':len(leaves),'changes':details,'actual_original_failure':{'raw':{'bytes':118496,'sha256':'f51a3e278d6e5072b0c13b94c2279eaa890419e8445af5e12eb9021565ecb29f','git_blob':'f84b983ace7dfd3dbe8de0a3972274d0f8a930e3'},'raw_method_counts':{'ok':488,'failed_methods':4,'total':492,'failure_entries':6},'unchanged_runner_counts':{'passed':486,'failed':6}},'packet':ident(raw),'gzip':ident(gz),'encoded_parts':parts,'patch':ident(diff.encode()),'invariants':{'unchanged_boundaries':569,'unchanged_protected_row_count':422,'protected_changes':'only three additive forbidden full identifiers at386/387/388','old_test_methods_removed':0,'new_test_methods':0,'training_test_bytes_changed':False,'Rust_source_changed':False,'verifier_or_typed_helper_changed':False,'workflow_changed':False,'deadlines_budgets_collector_scopes_or_retry_changed':False,'native_H_or_Cargo_executed':False,'commit_ref_PR_activated':False,'qualification_claim':False},'exact_new_root_issuer_case':new_case}
 save(ROOT/'REPAIR_MANIFEST.json',jb(manifest))
 print(json.dumps({'files':5,'after_tree':after_tree,'patch':ident(diff.encode()),'packet':ident(raw),'manifest':ident(jb(manifest)),'changes':[{'path':r['path'],'before':r['before']['git_blob'],'after':r['after']['git_blob']} for r in details]},indent=2))

if __name__=='__main__':main()
