from pathlib import Path
import json,hashlib,base64,zlib,tomllib
D=Path('/tmp/hepta-36fa-e2-registration-full-git-readback-v2')
original=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/registration-components-frozen-v2')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
manifest=(D/'LOSSLESS_REPRESENTATIONS.json').read_bytes()
assert pin(manifest)['git_blob']=='dfd73377e44e3d42a68120aca5141bc3d99e4a0d'
items=json.loads(manifest);assert len(items)==3
verified=[];leaf_count=1
for item in items:
 chunks=[];offset=0
 for part in item['parts']:
  b=(D/part['path']).read_bytes()
  assert pin(b)=={k:part[k] for k in ('bytes','sha256','git_blob')}
  assert len(b)<=262145 and b.endswith(b'\n') and b.count(b'\n')==1
  chunk=base64.b64decode(b[:-1],validate=True)
  assert len(chunk)<=196608 and pin(chunk)==part['decoded'] and part['offset']==offset
  offset+=len(chunk);assert offset<=item['gzip']['bytes']
  chunks.append(chunk);leaf_count+=1
 compressed=b''.join(chunks);assert pin(compressed)==item['gzip']
 decoder=zlib.decompressobj(wbits=31)
 decoded=decoder.decompress(compressed,item['raw']['bytes']+1)
 assert len(decoded)==item['raw']['bytes'] and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
 assert pin(decoded)==item['raw']
 assert decoded==(original/item['raw_path']).read_bytes()
 if item['raw_path'].endswith('.json'):json.loads(decoded)
 else:
  projection=tomllib.loads(decoded.decode());assert len(projection['boundary'])==741 and len(projection['protected_file'])==512
 target=D/'reconstructed'/item['raw_path'];target.parent.mkdir(exist_ok=True)
 with target.open('xb') as f:f.write(decoded)
 verified.append({'path':item['raw_path'],'complete':pin(decoded),'gzip':item['gzip'],'parts':len(item['parts']),'matches_frozen_local_original':True})
report={'format':'hepta-root-e2-registration-actual-git-reconstruction-v1','manifest':pin(manifest),'actual_Git_full_GET_leaves':leaf_count,
 'complete_reconstructed_files':verified,'bounded_base64_and_gzip_decode':True,
 'scope':'Exact readable content at these Git GETs, not continuous availability, final registration union, a scanner result or scientific/task qualification.',
 'known_dependencies':'The original v2 declaration metadata and Material3 test pin retain their historical deficiencies; successors are separate and must be applied at final integration.',
 'project_code_executed':False,'H_calls':0,'qualification':False}
raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (D/'ROOT_GIT_READBACK_REVIEW.json').open('xb') as f:f.write(raw)
print(json.dumps({'review':pin(raw),'files':3,'Git_leaves':leaf_count,'qualification':False}))
