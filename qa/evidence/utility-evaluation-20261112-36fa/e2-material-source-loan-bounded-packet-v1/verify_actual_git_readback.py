from pathlib import Path
import base64,json,hashlib
D=Path('/tmp/hepta-36fa-e2-material-source-loan-bounded-packet-v1/root-git-readback')
def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def unique(pairs):
 d={}
 for k,v in pairs:
  assert k not in d,('duplicate_json_key',k)
  d[k]=v
 return d
manifest_bytes=(D/'MANIFEST.json').read_bytes()
assert pin(manifest_bytes)=={'bytes':1992,'sha256':'a7c3197c8481ee886fd9518eb5de9d7644a3a94e5dc41de6ae727c8b5381fad9','git_blob':'e5dd4790be42709192760505d555595c581cea03'}
m=json.loads(manifest_bytes,object_pairs_hook=unique)
assert len(m['parts'])==m['part_count']==3
chunks=[];offset=0
for p in m['parts']:
 assert p['offset']==offset
 b=(D/p['name']).read_bytes();assert pin(b)==p['encoded']
 assert b.endswith(b'\n') and b.count(b'\n')==1
 decoded=base64.b64decode(b[:-1],validate=True)
 assert len(decoded)<=m['maximum_decoded_part_bytes']==196608
 assert pin(decoded)==p['decoded']
 chunks.append(decoded);offset+=len(decoded)
 assert offset<=m['original']['bytes']==532571
raw=b''.join(chunks)
assert pin(raw)==m['original']
original=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/material-source-loan-layer-v1/SOURCE_PACKET.json').read_bytes()
assert raw==original
packet=json.loads(raw,object_pairs_hook=unique)
assert len(packet['entries'])==22
paths=set();before_count=0
for e in packet['entries']:
 assert e['path'] not in paths
 paths.add(e['path'])
 assert pin(e['after_utf8'].encode())==e['after']
 if e.get('before') is not None:
  assert pin(e['before_utf8'].encode())==e['before'];before_count+=1
assert before_count==14
report={'format':'hepta-root-material-packet-actual-git-readback-v1','actual_Git_full_GET_parts':3,'manifest':pin(manifest_bytes),'parts':[p['encoded'] for p in m['parts']],'whole_packet':pin(raw),'whole_equals_frozen_author_packet':True,'all_22_after_and_14_before_full_text_pins_verified':True,'duplicate_JSON_keys_rejected':True,'bounded_decode':True,'repository_code_executed':False,'H_executed':False,'qualification':False,'scope':'Content retrieval and exact reconstruction only; not legal authorization, continuing availability, actual Material consumption, IPC execution, or runtime qualification.'}
out=json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
target=D/'ROOT_ACTUAL_GIT_READBACK_REVIEW.json'
assert not target.exists()
target.write_text(out)
print(json.dumps({'review':pin(out.encode()),'paths':22,'before':before_count,'new':22-before_count}))
