#!/usr/bin/env python3
"""Root lossless static archive verification, without native/project execution."""
import base64,gzip,hashlib,json
from pathlib import Path
R=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
A=Path('/tmp/hepta-36fa-coordinator-a489-static-control-archive-v1')
def pin(b): return {'bytes':len(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'sha256':hashlib.sha256(b).hexdigest()}
def check(b,p): assert pin(b)=={k:p[k] for k in ('bytes','git_blob','sha256')},(pin(b),p)
index_raw=Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1/CLOSED_STATIC_CONTROL_INPUTS.json').read_bytes()
assert pin(index_raw)['git_blob']=='8817a6d9ec4a96b01da373e86c348d78f9941670'
index=json.loads(index_raw)
placement=json.loads((A/'PLACEMENT.json').read_text())
members=json.loads((A/'CLOSED_MEMBER_MAP.json').read_text())['members']
encoding=json.loads((A/'ENCODING_MANIFEST.json').read_text())
ledger={e['path']:e for e in json.loads((R/'ROOT_A489_STATIC_CONTROL_FULLGET_LEDGER.json').read_text())}
assert len(index['entries'])==len(members)==89 and len(placement['entries'])==len(ledger)==104
for e in placement['entries']:
    b=Path(e['local_path']).read_bytes();check(b,{'git_blob':e['blob'],**{k:e[k] for k in ('bytes','sha256')}})
    got=ledger[e['path']]
    assert (got['sha'],got['bytes'],got['sha256'])==(e['blob'],e['bytes'],e['sha256'])
    assert len(b)<=512000
packed={}
for e in encoding['oversized_members']:
    chunks=[];offset=0
    for part in e['parts']:
        b=Path(part['local_path']).read_bytes();check(b,part['encoded'])
        assert b.endswith(b'\n') and not b.endswith(b'\n\n')
        decoded=base64.b64decode(b[:-1],validate=True);check(decoded,part['decoded'])
        assert part['offset']==offset
        offset+=len(decoded);chunks.append(decoded)
    compressed=b''.join(chunks);check(compressed,e['gzip'])
    raw=gzip.decompress(compressed);check(raw,e['raw']);packed[e['name']]=raw
assert len(packed)==6
inputs={e['name']:e for e in index['entries']}
direct=0;total=0
for e in members:
    src=inputs[e['name']]
    assert e['raw']=={k:src[k] for k in ('bytes','git_blob','sha256')}
    original=Path(src['path']).read_bytes();check(original,src)
    if e['representation']=='exact_original_raw_leaf':
        assert len(e['evidence_paths'])==1
        relative=Path(e['evidence_paths'][0]).relative_to('coordinator-a489-static-control-archive-v1')
        raw=(A/relative).read_bytes();direct+=1
    else:
        raw=packed[e['name']]
    assert raw==original
    total+=len(raw)
assert direct==83 and total==5857575
assert index['primary_count']==45 and index['completed_original_sdk_count']==44
report={'format':'hepta-root-static-control-closed-archive-review-v1','qualification':False,'original_index':pin(index_raw),'original_members':89,'primary':45,'completed_original_sdk':44,'original_bytes':total,'exact_raw_leaves':83,'lossless_originals':6,'encoded_parts':12,'all_104_payloads_match_actual_Root_Git_full_GET':True,'complete_original_byte_recovery_equal':True,'maximum_new_leaf_bytes':max(e['bytes'] for e in placement['entries']),'H_calls':0,'new_source_or_control_mutations':0,'future_runtime_or_archive_sdk_added_to_original_closed_set':False}
b=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
(R/'ROOT_A489_STATIC_CONTROL_ARCHIVE_REVIEW.json').write_bytes(b)
print(json.dumps({'review':pin(b),'originals':89,'original_bytes':total,'payloads':104,'result':'LOSSLESS_STATIC_ARCHIVE_ONLY'}))
