#!/usr/bin/env python3
"""Read-only authentication of all 166 actual Git blob responses and their bytes."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sha = lambda b: hashlib.sha256(b).hexdigest()
def blob(b):
    return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def identity(p):
    b=p.read_bytes()
    return {'path':str(p.relative_to(ROOT)), 'bytes':len(b), 'sha256':sha(b)}
def load(p):
    return json.loads(p.read_bytes())

spec = importlib.util.spec_from_file_location('original_git_provenance', HERE/'review_and_assign.py')
prov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prov)
assert sha((HERE/'review_and_assign.py').read_bytes()) == '0c629f4fb6f0f2d8dd99460a563dc8a5536d055ba1d7751981646093fb9cfce7'
plan_path = ROOT/'model_storage/git-archive-transport-attempt2/transport-plan.json'
assert sha(plan_path.read_bytes()) == 'de5bf769089153d2bfd1fae468cf0af7942da442a9856acc120ee611757e5d5b'
prepared_path = ROOT/'model_storage/git-archive-transport-attempt2/execution/prepared-data-commit.json'
plan, prepared = load(plan_path), load(prepared_path)
publication = prov.verify_publication(None, plan, prepared)
metadata_assignment_path=HERE/'control/metadata-assignment.json'
part_assignment_path=HERE/'control/parts-assignment.json'
assert sha(metadata_assignment_path.read_bytes()) == 'bdaf5347c162a33f0aff97d50cc4fb456e8ab4f6f6c7e9683c9b72f3f363a33d'
assert sha(part_assignment_path.read_bytes()) == 'b57d015fc37e7d7ab19a40c73ae53b3e8e8eb61836f3a1a20965eee0c3cce4a7'
rows = load(metadata_assignment_path)['assignments']
part_assignment=load(part_assignment_path)
for phase in ['H1','H2','H3']:
    rows += part_assignment['assignments'][phase]
assert len(rows)==166
actual_paths={str(p.relative_to(HERE/'data')) for p in (HERE/'data').rglob('*') if p.is_file()}
assert actual_paths == set(prepared['paths']) == {r['transport_path'] for r in rows}
index=load(HERE/'data/transport-index.json')
assert index['route_plan_sha256']==sha(plan_path.read_bytes())
envelopes={r['transport_path']:r for r in index['envelopes']}
assert len(envelopes)==162
result=[]
part_count=0
part_bytes=0
payload_bytes=0
raw_rpc_bytes=0
phase_counts={'H1':0,'H2':0,'H3':0}
for row in rows:
    mp=Path(row['metadata_path']); mb=mp.read_bytes(); meta=json.loads(mb)
    assert sha(mb)==row['metadata_sha256']
    rd=Path(row['receipt_directory']); rp=rd/'receipt.json'; rec=load(rp)
    assert rec['status']=='VERIFIED_ACTUAL_RPC_AND_PAYLOAD_BYTES'
    assert (rd/'metadata.json').read_bytes()==mb
    assert load(rd/'declared-request.json')==row['request']==meta['request']
    assert meta['immutable_commit']==rec['declared_immutable_commit']==prepared['commit']
    assert meta['immutable_tree']==rec['declared_immutable_tree']==prepared['tree']
    assert meta['repository']==rec['repository']=='TrillionniumFoundation/hepta-private-ci'
    assert row['request']['repository_full_name']==meta['repository']
    assert rec['metadata_sha256']==sha(mb)
    payload_path=Path(row['payload_path']); payload=payload_path.read_bytes()
    assert not payload_path.is_symlink()
    assert payload_path.resolve()==(HERE/'data'/row['transport_path']).resolve()
    assert meta['transport_path']==rec['transport_path']==row['transport_path']
    assert len(payload)==meta['transport_bytes']==rec['transport_bytes']
    assert sha(payload)==meta['transport_sha256']==rec['transport_sha256']
    assert blob(payload)==meta['transport_git_blob_sha']==rec['transport_git_blob_sha']==row['request']['blob_sha']==prepared['paths'][row['transport_path']]
    raw=(rd/'rpc-original.raw.json').read_bytes()
    raw_obj=json.loads(raw)
    assert raw_obj.get('isError') is False
    assert raw_obj['structuredContent']['content'].encode('utf-8')==payload
    assert len(raw)==rec['rpc_bytes'] and sha(raw)==rec['rpc_sha256']
    prefix=(rd/'rpc-prefix.bin').read_bytes(); suffix=(rd/'rpc-suffix.bin').read_bytes()
    for label,b in [('prefix',prefix),('suffix',suffix)]:
        assert len(b)==rec[label+'_bytes'] and sha(b)==rec[label+'_sha256']
    codec=rec['reconstruction_codec']
    if codec=='literal-ascii-base64':
        token=payload
    else:
        assert codec in ['json-string-literal-ensure-ascii-false','json-string-literal-ensure-ascii-true']
        token=json.dumps(payload.decode(),ensure_ascii=codec.endswith('-true'),separators=(',',':')).encode()
    assert prefix+token+suffix==raw
    assert rec['complete_original_rpc_retained'] and rec['original_rpc_byte_equality_verified']
    assert rec['native_execution'] is False and rec['old_downloader_state_changed'] is False
    original=None
    if meta['kind']=='base64-original-part':
        assert codec=='literal-ascii-base64'
        decoded=base64.b64decode(payload,validate=True)
        assert base64.b64encode(decoded)==payload and b'\n' not in payload and b'\r' not in payload
        assert decoded==(rd/'actual-part.bin').read_bytes()
        e=envelopes[row['transport_path']]
        p=e['original_part']
        assert len(decoded)==meta['original_bytes']==rec['actual_original_part_bytes']==p['bytes']
        assert sha(decoded)==meta['original_sha256']==rec['actual_original_part_sha256']==p['sha256']
        original={'phase':e['phase'],'index':p['index'],'bytes':len(decoded),'sha256':sha(decoded)}
        part_count+=1;part_bytes+=len(decoded);phase_counts[e['phase']]+=1
    else:
        assert meta['kind']=='json-utf8' and isinstance(json.loads(payload),dict)
    file_proofs=[identity(rd/n) for n in ['receipt.json','metadata.json','declared-request.json','rpc-prefix.bin','rpc-suffix.bin']]
    result.append({'transport_path':row['transport_path'],
        'payload':{'bytes':len(payload),'sha256':sha(payload),'git_blob':blob(payload)},
        'actual_rpc':{'bytes':len(raw),'sha256':sha(raw),'local_original_retained':True},
        'reconstruction_codec':codec,'proof_files':file_proofs,'original_part':original,
        'independent_exact_rpc_reconstruction':True})
    payload_bytes+=len(payload);raw_rpc_bytes+=len(raw)
assert part_count==162 and part_bytes==670306272 and phase_counts=={'H1':32,'H2':62,'H3':68}
assert sum(r['payload']['bytes'] for r in result if r['original_part'])==893742124
report={
    'schema':'root-combined-actual-git-blob-fetch-receipts-v1',
    'status':'VERIFIED_ALL_166_ACTUAL_GIT_RESPONSES_AND_PAYLOADS',
    'publication':publication, 'prepared_record':identity(prepared_path),
    'plan':identity(plan_path), 'assignments':[identity(metadata_assignment_path),identity(part_assignment_path)],
    'actual_git_provenance':[identity(HERE/'control'/n) for n in ['ref.raw.json','commit.raw.json','tree.raw.json']],
    'actual_index':identity(HERE/'data/transport-index.json'),
    'actual_file_count':166,'actual_part_count':part_count,'phase_part_counts':phase_counts,
    'original_archive_part_bytes':part_bytes,'actual_payload_bytes':payload_bytes,
    'actual_original_rpc_bytes':raw_rpc_bytes,
    'all_actual_raw_rpcs_retained_locally':True,'all_payload_git_blobs_and_complete_tree_reconstructed':True,
    'lossless_republication_recipe':'For every entry, fetch exact payload from immutable repository/commit/path, verify bytes/SHA256/Git blob; use the recorded codec and exact saved prefix/suffix to reproduce the actual original RPC SHA256 and bytes. Original complete RPCs are locally retained. The actual payloads are published on the separate data-only Git ref, not duplicated in the review commit.',
    'entries':result,
    'no_native_execution':True,'old_binary_read_state_not_written':True,
    'whole_archive_member_and_H4_parent_consumer':'pending_separate_original_consumer',
    'limitations':['This is complete actual transport-byte validation, not native execution success or missing process capture credit.','Original H1/H2/H3 outcomes and old binary_read PAUSED states remain separate.','Actual tool returns and immutable Git identities are bound; these do not prove external runtime dependency closure.']
}
out=HERE/'root-review';out.mkdir(exist_ok=True)
dest=out/'combined-fetch-receipts-manifest.json'
with dest.open('xb') as f:f.write((json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
print(json.dumps({'status':report['status'],'manifest_path':str(dest),'manifest_bytes':dest.stat().st_size,'manifest_sha256':sha(dest.read_bytes()),'parts':part_count,'original_bytes':part_bytes,'payload_bytes':payload_bytes,'rpc_bytes':raw_rpc_bytes}))
