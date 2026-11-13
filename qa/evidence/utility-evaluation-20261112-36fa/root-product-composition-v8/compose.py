"""Compose two fixed narrow successors; no project compilation or gate execution."""
from pathlib import Path
import json,hashlib
OUT=Path('/tmp/hepta-36fa-root-product-composition-v8')
PREV=Path('/tmp/hepta-36fa-root-product-composition-v7')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
base_raw=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(base_raw)['git_blob']=='7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base={e['path']:{k:e[k] for k in ('bytes','sha256','git_blob')} for e in json.loads(base_raw)['files']}
prev_raw=(PREV/'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(prev_raw)['git_blob']=='eeeab2a320b8d2d5aed0299b31fc3be3922d118f'
current=base.copy();sources={}
for e in json.loads(prev_raw)['files']:
 b=(PREV/'after'/e['path']).read_bytes()
 assert pin(b)==e['after'] and e['before']==base.get(e['path'])
 current[e['path']]=e['after'];sources[e['path']]=b
layers=[]
for name,sha,kind in [
 ('explicit-bootstrap-caller-increment-v1','67668543482066659f910346d23b53408c12e165','exact'),
 ('material-test-closure-increment-v1','0cefd50845cb790b581553b47e84bdcdb1015e91','append'),
]:
 d=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')/name
 raw=(d/'SOURCE_PACKET.json').read_bytes();assert pin(raw)['git_blob']==sha
 packet=json.loads(raw);assert len(packet['entries'])==1
 e=packet['entries'][0];path=e['path'];before=e['before_utf8'].encode();after=e['after_utf8'].encode()
 assert pin(before)==e['before']==current[path] and before==sources[path]
 assert pin(after)==e['after']
 edit=json.loads((d/'EXACT_SOURCE_SPLICES.json').read_bytes())
 if kind=='append':
  assert edit['path']==path and edit['offset']==len(before)
  assert edit['before']==e['before'] and edit['after']==e['after']
  assert edit['append_utf8']=='}\n' and after==before+b'}\n' and after[:-2]==before
 else:
  assert len(edit)==1 and edit[0]['path']==path and len(edit[0]['exact_splices'])==1
  s=edit[0]['exact_splices'][0];old,new=s['old'].encode(),s['new'].encode()
  assert before.count(old)==1 and after.count(new)==1
  assert before.replace(old,new,1)==after and after.replace(new,old,1)==before
  assert len(after)-len(before)==39
 current[path]=e['after'];sources[path]=after
 layers.append({'name':name,'packet':pin(raw),'path':path,'before':e['before'],'after':e['after'],'full_forward_and_inverse_equal':True})
new=sorted(set(current)-set(base));modified=sorted(p for p in base if current[p]!=base[p])
assert set(sources)==set(new+modified) and not set(base)-set(current)
report={'format':'hepta-root-partial-product-composition-v8','base_source':'b6084394a4a38ab495c16eaba09e879f04a96f8e',
 'previous_composition':pin(prev_raw),'layers':layers,'files_before':len(base),'files_after':len(current),
 'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),
 'original_files_unchanged':len(base)-len(modified),
 'files':[{'path':p,'before':base.get(p),'after':current[p]} for p in sorted(sources)],
 'remaining':['pre-freeze authorized same-source observation/intake path','same-session Task/Material/V3 actual CLI wiring',
 'final caller/protection/contract/test/workflow union','original compiler/source/native gates',
 'real authorized A-independent B-C and daemon/Root cold recovery'],
 'repository_code_executed':False,'H_calls_in_this_composition':0,'source_Git_mutation':False,
 'qualification':False,'real_qualified_chains':0}
for p,b in sources.items():
 f=OUT/'after'/p;f.parent.mkdir(parents=True,exist_ok=True)
 with f.open('xb') as handle:handle.write(b)
b=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as f:f.write(b)
print(json.dumps({'review':pin(b),'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),'files_after':len(current),'qualification':False}))
