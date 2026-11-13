"""Compose fixed second task-input loader; all repository code remains unexecuted."""
from pathlib import Path
import json,hashlib
OUT=Path('/tmp/hepta-36fa-root-product-composition-v7')
PREV=Path('/tmp/hepta-36fa-root-product-composition-v6')
LAYER=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/task-inputs-layer-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def unique(pairs):
 d={}
 for k,v in pairs:
  assert k not in d,('duplicate key',k)
  d[k]=v
 return d
def parse(b):return json.loads(b,object_pairs_hook=unique)
raw=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/PROPOSED_NONRUST_8EBB_GRAPH.json').read_bytes()
assert pin(raw)['git_blob']=='7c515dbe48ae3ab42ccc85d916e38675db06ced2'
base={e['path']:{k:e[k] for k in ('bytes','sha256','git_blob')} for e in parse(raw)['files']}
prevraw=(PREV/'PREQUALIFICATION_COMPOSITION_REVIEW.json').read_bytes()
assert pin(prevraw)['git_blob']=='cbf945f1d602aa8545d18a1a2c2fce72fcea755b'
previous=parse(prevraw);current=base.copy();sources={}
for e in previous['files']:
 b=(PREV/'after'/e['path']).read_bytes()
 assert pin(b)==e['after'] and e['before']==base.get(e['path'])
 sources[e['path']]=b;current[e['path']]=e['after']
raw=(LAYER/'SOURCE_PACKET.json').read_bytes()
assert pin(raw)['git_blob']=='77b05d5ec3f8d3b10a4024b63103e97e8f3fe996'
packet=parse(raw)
mount_raw=(LAYER/'FINAL_MOUNT_SPLICES.json').read_bytes()
assert pin(mount_raw)['git_blob']=='9df2125591031c389e55a3983e731129668ea1d7'
mounts=parse(mount_raw)['changes'];assert len(mounts)==7
affected=[];splice_count=0;old_count=0;new_count=0
for e in packet['entries']:
 path=e['path'];after=e['after_utf8'].encode();assert pin(after)==e['after']
 assert current.get(path)==e['before'],('whole current preimage differs',path)
 if e['before'] is None:
  assert path not in sources and path not in base and e.get('before_utf8') is None
  new_count+=1
 else:
  before=e['before_utf8'].encode();assert pin(before)==e['before'] and before==sources[path]
  edits=[x for x in mounts if x['path']==path];assert len(edits)==1
  edit=edits[0];assert edit['before']==e['before'] and edit['after']==e['after']
  forward=before
  for s in edit['splices']:
   anchor=s['anchor'].encode();addition=s['addition'].encode()
   assert forward.count(anchor)==1,('anchor not unique',path)
   forward=forward.replace(anchor,anchor+addition,1);splice_count+=1
  assert forward==after
  inverse=after
  for s in reversed(edit['splices']):
   anchor=s['anchor'].encode();addition=s['addition'].encode()
   assert inverse.count(anchor+addition)==1
   inverse=inverse.replace(anchor+addition,anchor,1)
  assert inverse==before;old_count+=1
 sources[path]=after;current[path]=e['after'];affected.append({'path':path,'before':e['before'],'after':e['after']})
assert len(affected)==13 and old_count==7 and new_count==6 and splice_count==8
new=sorted(set(current)-set(base));modified=sorted(p for p in base if current[p]!=base[p])
assert set(sources)==set(new+modified) and not set(base)-set(current)
report={'format':'hepta-root-partial-product-composition-v7',
 'base_source':'b6084394a4a38ab495c16eaba09e879f04a96f8e','previous_composition':pin(prevraw),
 'layer':{'packet':pin(raw),'final_mounts':pin(mount_raw),'files':affected},
 'all_current_whole_before_images_equal':True,'all_eight_insertions_full_forward_and_inverse_equal':True,
 'files_before':len(base),'files_after':len(current),'changed_paths':len(sources),'new_files':len(new),
 'modified_original_files':len(modified),'original_files_unchanged':len(base)-len(modified),
 'files':[{'path':p,'before':base.get(p),'after':current[p]} for p in sorted(sources)],
 'review_scope':'Exact bytes and composition only. The second loader semantic/consumer review is separate and pending.',
 'remaining':['same-session Task/Material/V3 protected CLI and Material process hookup',
 'final CALLERS/protection/source-contract/test-name union','second loader independent semantic and clock-consumer closure review',
 'original formatting/compilation/source/native gates','real A-independent B-C and actual daemon/Root process cold recovery'],
 'H_calls_in_this_composition':0,'project_code_executed':False,'source_Git_mutation':False,
 'qualification':False,'real_qualified_chains':0}
for path,b in sources.items():
 p=OUT/'after'/path;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
b=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'PREQUALIFICATION_COMPOSITION_REVIEW.json').open('xb') as f:f.write(b)
print(json.dumps({'review':pin(b),'changed_paths':len(sources),'new_files':len(new),'modified_original_files':len(modified),'files_after':len(current),'qualification':False}))
