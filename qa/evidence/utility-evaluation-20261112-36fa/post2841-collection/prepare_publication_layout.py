#!/usr/bin/env python3
"""Map verified frozen payloads to bounded evidence files without changing bytes."""
from pathlib import Path
import base64,gzip,hashlib,json
ROOT=Path(__file__).resolve().parent

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
      'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def save(name,raw):
    p=ROOT/'frozen'/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==raw
    else:
        with p.open('xb') as f:f.write(raw)
    return {'path':name,'local':str(p),**pin(raw),'saved_readback_proofs':[],
      'known_remote':False,'utf8':True,'category':'derived_encoding_or_preparation_metadata'}

rows=json.loads((ROOT/'VERIFIED_PAYLOAD_ENTRIES.json').read_text())
direct=[];derived=[];encoded=[]
for row in rows:
    if row['bytes']<=500000:
        direct.append(row);continue
    raw=Path(row['local']).read_bytes();assert pin(raw)=={k:row[k] for k in pin(raw)}
    packed=gzip.compress(raw,mtime=0);parts=[]
    for i,offset in enumerate(range(0,len(packed),196608),1):
        chunk=packed[offset:offset+196608];ascii_part=base64.b64encode(chunk)+b'\n'
        name=str(Path(row['path']).parent/'encoded'/(Path(row['path']).name+f'.gz.part{i:03d}.b64'))
        item=save(name,ascii_part);derived.append(item)
        parts.append({'path':name,'encoded':pin(ascii_part),'decoded':pin(chunk),'decoded_offset':offset})
    reconstructed=b''.join(base64.b64decode(Path(r['local']).read_bytes()[:-1],validate=True)
       for r in derived[-len(parts):])
    assert reconstructed==packed and gzip.decompress(reconstructed)==raw
    encoded.append({'original_path':row['path'],'original':pin(raw),'original_Git_blob_full_readback_verified':True,
      'gzip':pin(packed),'parts':parts})
assert len(encoded)==2
encoding_manifest={'format':'hepta-bounded-original-input-encoding-v1',
  'files':encoded,'raw_originals_remain_immutable_Git_blobs':True,'original_bytes_changed':False,
  'observations_after_frozen_cutoff_added':False,
  'reconstruction':'For each original independently: in listed part order remove the single terminal LF, base64-decode each part, concatenate, verify gzip, gunzip once, verify original size/SHA256/Git blob. This changes only evidence storage layout.'}
derived.append(save('source-repair-246d/fmt-launch/ENCODED_ORIGINAL_INPUTS.json',
  (json.dumps(encoding_manifest,sort_keys=True,indent=2)+'\n').encode()))
for name in ['CUTOFF_AND_INPUTS.json','READBACK_LEDGER.json','PREPARATION_REVIEW.json','freeze_inputs.py','verify_frozen_increment.py','prepare_publication_layout.py']:
    derived.append(save('post2841-collection/'+name,(ROOT/name).read_bytes()))
for name,obj in [('PUBLICATION_DIRECT_ENTRIES.json',direct),('FINALIZATION_UPLOADS.json',derived)]:
    raw=(json.dumps(obj,sort_keys=True,indent=2)+'\n').encode();p=ROOT/name
    if p.exists():assert p.read_bytes()==raw
    else:
        with p.open('xb') as f:f.write(raw)
print(json.dumps({'direct_files':len(direct),'derived_files':len(derived),'publication_increment':len(direct)+len(derived),
  'proposed_full_count':2841+len(direct)+len(derived),'oversized_originals_losslessly_encoded':len(encoded),
  'maximum_new_file_size':max(r['bytes'] for r in direct+derived)}))
