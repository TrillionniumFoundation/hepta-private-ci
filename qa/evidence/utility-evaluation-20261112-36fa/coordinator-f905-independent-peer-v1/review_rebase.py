"""Frozen source proposal comparisons only. No H, Rust, fmt, QA, Git CLI or source writes."""
import base64
import difflib
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
AUTHOR=Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1')
INVENTORY=Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')
LAYERS=[
 (Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1/PRODUCTION_PACKET.json'),'3ffcac56096eb06214963ab1fdc5898e2b7eebb2'),
 (Path('/tmp/hepta-36fa-root-generation-custody-tests-v1/SOURCE_PACKET.json'),'ae05b4ca793a24a164d08e247a8faec62f690750'),
 (Path('/tmp/hepta-36fa-root-generation-custody-cold-v2/SOURCE_PACKET.json'),'a7256a2eea8df3af2c927f728b2c38c9342cc830'),
]

def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def body(row,side):
 if row[side] is None:
  assert row.get(side+'_base64') is None and row.get(side+'_text') is None
  return None
 b=base64.b64decode(row[side+'_base64'],validate=True) if side+'_base64' in row else row[side+'_text'].encode()
 assert pin(b)==row[side]
 return b

def tree(leaves):
 root={}
 for path,(mode,oid) in leaves.items():
  parts=path.split('/');d=root
  for part in parts[:-1]:d=d.setdefault(part,{})
  assert parts[-1] not in d
  d[parts[-1]]=(mode,oid)
 def build(d):
  out=[]
  for name,value in d.items():
   mode,oid=('40000',build(value)) if isinstance(value,dict) else value
   out.append(((name+('/' if mode=='40000' else '')).encode(),mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(oid)))
  raw=b''.join(v for _,v in sorted(out))
  return hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 return build(root)

def insertion(a,b):
 aa=a.decode().splitlines(keepends=True);bb=b.decode().splitlines(keepends=True)
 changed=[x for x in difflib.SequenceMatcher(a=aa,b=bb,autojunk=False).get_opcodes() if x[0]!='equal']
 assert len(changed)==1 and changed[0][0]=='insert'
 _,i,j,k,l=changed[0];assert i==j
 assert ''.join(bb[:k]+bb[l:]).encode()==a
 return ''.join(bb[k:l])

def main():
 raw=(HERE/'inputs/SOURCE_PACKET.json').read_bytes()
 assert raw==(AUTHOR/'SOURCE_PACKET.json').read_bytes()
 assert pin(raw)['git_blob']=='773d67128190fd2e1c3271c372f72e2a5537d1e8'
 sdk=json.loads((HERE/'inputs/SOURCE_PACKET.json.GITHUB_GET.original.json').read_bytes())
 assert sdk['structuredContent']['content'].encode()==raw
 packet=json.loads(raw)
 assert packet['qualification'] is False and packet['H_calls']==0
 assert packet['format_compile_test_calls']==0 and packet['source_or_ref_writes'] is False
 assert packet['canonical_source_deletions']==[]
 invraw=INVENTORY.read_bytes();inv=json.loads(invraw)
 assert pin(invraw)==packet['base_complete_inventory']
 assert pin(invraw)['git_blob']=='e1e48f35bb6cf5a3dd86c59472da77df87154b6a'
 rows={x['path']:x for x in inv['files']}; assert len(rows)==15237
 leaves={}
 for path,row in rows.items():
  mode='120000' if row['kind']=='symlink' else '100755' if row['permissions']&0o111 else '100644'
  leaves[path]=(mode,row['working_blob'])
 assert tree(leaves)==packet['base_actual_physical_tree']=='f905b18e6b05de1582024548179725a05d932536'
 old_before={};old_after={};input_pins=[]
 for path,oid in LAYERS:
  data=path.read_bytes();assert pin(data)['git_blob']==oid;input_pins.append(pin(data))
  for row in json.loads(data)['source_changes']:
   before=body(row,'before');after=body(row,'after');name=row['path']
   if name in old_after:assert old_after[name]==before
   else:old_before[name]=before
   old_after[name]=after
 assert len(old_after)==9
 output=[];inserted=[];preimage_diffs=[]
 assert len(packet['source_changes'])==9
 for row in packet['source_changes']:
  name=row['path'];before=body(row,'before');after=body(row,'after')
  assert name in old_after and after==(AUTHOR/'after'/name).read_bytes()
  if before is None:assert name not in rows and old_before[name] is None
  else:
   actual=rows[name]
   assert pin(before)=={'bytes':actual['bytes'],'sha256':actual['sha256'],'git_blob':actual['working_blob']}
   if before!=old_before[name]:preimage_diffs.append(name)
   text=insertion(before,after);inserted.append({'path':name,'text':text,'bytes':len(text.encode()),'inverse_recovers_complete_actual_preimage':True})
  if name.endswith('/lib.rs'):
   assert text==insertion(old_before[name],old_after[name])
   assert text.count('#[cfg(target_os = "linux")]')==5
   assert text.count('pub use neuron_generation_initial::')==5
   assert 'use ' not in text.replace('pub use neuron_generation_initial::','')
  else:assert after==old_after[name]
  leaves[name]=(row['mode'],row['after']['git_blob'])
  output.append({'path':name,'before':row['before'],'after':row['after'],
                 'actual_preimage_exact_or_path_absent':True,'after_equal_original_frozen_layer':after==old_after[name]})
 assert preimage_diffs==['codex-rs/hepta-agentd/src/lib.rs']
 expected=tree(leaves)
 assert len(leaves)==packet['expected_after_leaf_count']==15243
 assert expected==packet['expected_after_physical_tree']=='a0bd2241a3a005b68a4682a339d2be016fa3fa72'
 report={'format':'hepta-independent-coordinator-actual-f905-rebase-proof-v1','proposal':pin(raw),'actual_base_inventory':pin(invraw),'actual_base_tree':packet['base_actual_physical_tree'],
 'original_layers':input_pins,'rows':output,'exact_insertions_into_existing_actual_files':inserted,
 'only_changed_preimage':preimage_diffs,'eight_after_files_exact_original_layers':True,
 'new_paths_absent_from_complete_actual_inventory':6,'expected_leaves':15243,'expected_tree':expected,
 'expected_tree_is_projection_only':True,'source_or_ref_changes':False,'H_Rust_formatter_QA_calls':0,
 'scope':'Complete byte identities, source absence/preimage and Merkle projection only. Existing semantic review 04aaf3 remains applicable to unchanged production/tests; no execution or format result is inferred for the proposal.'}
 data=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
 with (HERE/'FROZEN_REBASE_PROOF.json').open('xb') as f:f.write(data)
 print(json.dumps(pin(data)))

if __name__=='__main__':main()
