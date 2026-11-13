#!/usr/bin/env python3
"""Offline exact recovery; no native filesystem observation or gate execution."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).parent
ACTUAL = Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')
BASE = Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json')
def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def store(name,raw):
    with (OUT/name).open('xb') as f:f.write(raw)
    return {'path':str(OUT/name),**pin(raw)}
def parse_sdk(name):
    sdk=json.loads((ACTUAL/name).read_text())
    assert sdk['isError'] is False
    return json.loads(sdk['content'][0]['text'])

base=BASE.read_bytes()
assert pin(base)=={'bytes':5611184,'sha256':'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e','git_blob':'663373f936c2ff130aec96ad34654cc9811773c2'}
initial=json.loads(base)
rejected=copy.deepcopy(initial)
for row in rejected['files']:
    if row['kind']!='symlink':row['permissions'] &= ~0o222
rejected_raw=(json.dumps(rejected,sort_keys=True,separators=(',',':'))+'\n').encode()
assert pin(rejected_raw)['sha256']=='fde42803e745349a1b30220c6bb0194970cdd2e0277f23ddc062508abe16717a'
assert pin(rejected_raw)['sha256']!='4db429ba1d54aa7ed6d6ad199694b7410d654ee7f788a631d7f392d7552fc79b'
prefix=parse_sdk('CLONE_INVENTORY_PREFIX_READ.original.json')
prefix_bytes=base64.b64decode(prefix['data_base64'],validate=True)
assert prefix['offset']==0 and prefix['next_offset']==len(prefix_bytes)==2048
assert hashlib.sha256(prefix_bytes).hexdigest()==prefix['chunk_sha256']
assert b'"permissions":256' in prefix_bytes
value=copy.deepcopy(initial)
changes=[]
for row in value['files']:
    if row['kind']=='file':
        before=row['permissions'];row['permissions'] &= 0o500
        if before!=row['permissions']:changes.append({'path':row['path'],'before':before,'after':row['permissions']})
raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
assert len(raw)==5611184 and hashlib.sha256(raw).hexdigest()=='4db429ba1d54aa7ed6d6ad199694b7410d654ee7f788a631d7f392d7552fc79b'
assert raw[:2048]==prefix_bytes
compressed=gzip.compress(raw,mtime=0)
references=[]
for name in ['source-closure.retained-manifest.original.json','self-test.retained-manifest.original.json','verify.retained-manifest.original.json','run.retained-manifest.original.json']:
    manifest=json.loads((ACTUAL/name).read_text())
    for item in manifest['files']:
        if item['original_path'] not in ['source-before.inventory.json','source-after.inventory.json','source-baseline.inventory.json']:continue
        assert item['encoding']=='gzip' and item['original_bytes']==len(raw) and item['original_sha256']==pin(raw)['sha256']
        offset=0
        for part in item['parts']:
            piece=compressed[offset:offset+part['bytes']];ident=pin(piece)
            assert ident['bytes']==part['bytes'] and ident['sha256']==part['sha256'] and ident['git_blob']==part['git_blob_sha']
            offset+=len(piece)
        assert offset==len(compressed)
        references.append({'retained_manifest':name,'original_path':item['original_path'],'whole_raw_exact':True,'all_original_parts_exact':True,'parts':item['parts']})
assert len(references)==7
raw_meta=store('CLONE_INVENTORY.exact-recovered.json',raw)
gz_meta=store('CLONE_INVENTORY.exact-recovered.json.gz',compressed)
parts=[]
for i,off in enumerate(range(0,len(compressed),262144)):
    piece=compressed[off:off+262144]
    parts.append({'decoded_offset':off,'decoded':pin(piece),'companion':store('CLONE_INVENTORY.original.part%04d.b64'%i,base64.b64encode(piece)+b'\n')})
# The source wrapper's original origin snapshots are the already-established
# canonical clean bytes. Actual file_info proves the stored gzip identities.
origin_gz=gzip.compress(base,mtime=0)
origin_observations=[]
for name in ['SOURCE_INITIAL.complete.inventory.json.gz','SOURCE_FINAL.complete.inventory.json.gz']:
    info=parse_sdk('ORIGIN_'+name+'.FILE_INFO.original.json')
    assert info['size']==len(origin_gz) and info['sha256']==pin(origin_gz)['sha256']
    origin_observations.append({'original_name':name,'actual_file_info':info,'recovered_gzip':pin(origin_gz),'recovered_raw':pin(base)})
report={'format':'hepta-source-gates-original-inventory-exact-recovery-v1',
 'source':'246d8cb614770252ee42029a5c014f2a4904176a','job_id':'1a1d1e83bd4-2564-1c86',
 'raw':raw_meta,'gzip':gz_meta,'parts':parts,'original_references':references,
 'actual_prefix_read':{k:v for k,v in prefix.items() if k!='data_base64'},
 'actual_prefix_equal':True,'changed_metadata_fields':['permissions'],'changed_rows':len(changes),
 'all_other_rows_and_fields_unchanged':True,'prior_rejected_candidate':pin(rejected_raw),
 'rejected_candidate_reason':'Assuming group/world readable permission preservation did not match the actual retained source snapshot. It was not accepted as evidence.',
 'accepted_candidate_basis':'Observed actual prefix has owner-read-only regular files; Git entry executable modes give the owner-execute distinction. The complete raw digest plus every original gzip-part digest/Git identity independently validate the entire reconstructed byte stream. No host umask attribution is made.',
 'origin_snapshots':origin_observations,'native_execution_repeated':False,'source_writes':False,
 'scope':'Exact recovery of previously observed immutable inventories, not a second native full-source read, not an index/stat recovery, and not a new qualification result.'}
store('RECOVERY_REVIEW.json',(json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
print(json.dumps({'raw':raw_meta,'gzip':gz_meta,'original_references':len(references),'part_count':len(parts),'origin_snapshots':len(origin_observations)},indent=2))
