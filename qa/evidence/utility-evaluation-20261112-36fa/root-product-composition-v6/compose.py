"""Compose only frozen exact bytes; no repository code or H execution."""
from pathlib import Path
import json,hashlib
ROOT=Path('/tmp/hepta-36fa-root-product-composition-v6')
PREV=Path('/tmp/hepta-36fa-root-product-composition-v5')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def unique(pairs):
 d={}
 for k,v in pairs:
  assert k not in d,('duplicate key',k)
  d[k]=v
 return d
def parse(b):return json.loads(b,object_pairs_hook=unique)
b=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(b)['git_blob']=='7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base={e['path']:{k:e[k] for k in ('bytes','sha256','git_blob')} for e in parse(b)['files']}
raw=(PREV/'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(raw)['git_blob']=='59014cde8a2ed41b652260773f81e09d7e3f67eb'
previous=parse(raw); current=base.copy(); sources={}
for e in previous['files']:
 b=(PREV/'after'/e['path']).read_bytes()
 assert pin(b)==e['after'] and e['before']==base.get(e['path'])
 current[e['path']]=e['after'];sources[e['path']]=b
layers=[];splice_count=0
for name,packet_sha in [
 ('remote-clock-rejection-increment-v1','9f780f963b0e9585b5b85a83f87de593f604bfa5'),
 ('feature-clock-rejection-increment-v1','ade9282388680285416c7829000b7081e22550ef'),
 ('feature-clock-regression-tests-v1','b2dc4c80ce5918463f3713fd6d916f0aeb1c85c0'),
]:
 d=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')/name
 packet_raw=(d/'SOURCE_PACKET.json').read_bytes();assert pin(packet_raw)['git_blob']==packet_sha
 packet=parse(packet_raw)
 edits=parse((d/'EXACT_SOURCE_SPLICES.json').read_bytes())
 assert len(edits)==len(packet['entries'])
 used=set();affected=[]
 for e in packet['entries']:
  p=e['path'];before=e['before_utf8'].encode();after=e['after_utf8'].encode()
  assert pin(before)==e['before']==current[p] and pin(after)==e['after']
  if p in sources:assert before==sources[p]
  else:assert e['before']==base[p]
  applicable=[x for x in edits if x['path']==p]
  assert len(applicable)==1 and p not in used;used.add(p);edit=applicable[0]
  assert edit['before']==e['before'] and edit['after']==e['after']
  forward=before
  for s in edit['exact_splices']:
   old,new=s['old'].encode(),s['new'].encode()
   assert forward.count(old)==1,('nonunique old',p)
   forward=forward.replace(old,new,1);splice_count+=1
  assert forward==after
  inverse=after
  for s in reversed(edit['exact_splices']):
   old,new=s['old'].encode(),s['new'].encode()
   assert inverse.count(new)==1,('nonunique new',p)
   inverse=inverse.replace(new,old,1)
  assert inverse==before
  if name=='feature-clock-rejection-increment-v1':
   assert len(after)-len(before)==25
  if name=='feature-clock-regression-tests-v1':
   assert after.startswith(before) and len(after)-len(before)==2011
  sources[p]=after;current[p]=e['after'];affected.append({'path':p,'before':e['before'],'after':e['after']})
 layers.append({'name':name,'packet':pin(packet_raw),'files':affected})
new=sorted(set(current)-set(base));modified=sorted(p for p in base if current[p]!=base[p])
assert set(sources)==set(new+modified) and not set(base)-set(current)
report={'format':'hepta-root-partial-product-composition-v6',
 'base_source':'b6084394a4a38ab495c16eaba09e879f04a96f8e','previous_composition':pin(raw),'layers':layers,
 'all_current_whole_before_images_equal':True,'all_forward_and_inverse_splices_equal':True,'splice_count':splice_count,
 'files_before':len(base),'files_after':len(current),'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),
 'original_files_unchanged':len(base)-len(modified),
 'files':[{'path':p,'before':base.get(p),'after':current[p]} for p in sorted(sources)],
 'clock_fix_scope':['Four remote-path source files reject MAX before its typed consumers.',
 'One original feature-control completed guard rejects MAX through the existing Indeterminate path before receipt construction or settlement.',
 'The complete original feature tests remain an exact prefix; one new regression is source only and unexecuted.',
 'The original local Cell execution body is unchanged. The not-yet-frozen new loader clock must not escape to that path.'],
 'remaining':['independent fixed clock-delta review','complete new task-clock consumer closure and same-session Task/Material/V3 CLI hookup',
 'final CALLERS/protection/contracts/tests registration','original formatter/compiler/source/native gates',
 'real authorized A, independently identified B, new consumer C, daemon and Root process cold recovery'],
 'H_calls_in_this_composition':0,'project_code_executed':False,'source_Git_mutation':False,
 'qualification':False,'real_qualified_chains':0}
for p,b in sources.items():
 target=ROOT/'after'/p;target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('xb') as f:f.write(b)
b=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (ROOT/'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as f:f.write(b)
print(json.dumps({'review':pin(b),'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),'files_after':len(current),'splices':splice_count,'qualification':False}))
