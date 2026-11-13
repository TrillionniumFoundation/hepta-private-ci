#!/usr/bin/env python3
"""Offline verification/assembly of the frozen post2841 evidence payload.

This is not a source qualification gate and does not execute archived programs.
It reads only the explicit frozen evidence and saved readback receipts.
"""
from pathlib import Path
import base64
import collections
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / 'frozen'

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def checked(raw, expected):
    actual=pin(raw)
    for key in actual:
        if key in expected:
            assert actual[key]==expected[key],(key,actual[key],expected[key])
    if 'git_blob_sha' in expected:
        assert actual['git_blob']==expected['git_blob_sha']
    return actual

def read_json(relative):
    return json.loads((FROZEN/relative).read_bytes())

def write_once(name,obj):
    raw=(json.dumps(obj,sort_keys=True,indent=2)+'\n').encode()
    path=ROOT/name
    if path.exists():
        assert path.read_bytes()==raw, ('existing output differs',name)
    else:
        with path.open('xb') as f:f.write(raw)
    return pin(raw)

cutoff=json.loads((ROOT/'CUTOFF_AND_INPUTS.json').read_bytes())
base=json.loads((ROOT/'BASE_FILES.json').read_bytes())
assert len(base)==2841
receipts=[]
for path in sorted((ROOT/'archive-receipts').glob('BATCH-*.json')):
    receipts.extend(json.loads(path.read_bytes())['results'])
by_path={r['path']:r for r in receipts}
assert len(by_path)==len(receipts)==128
assert all(r.get('full_readback_equal') is True for r in receipts)
verified=[]
for row in cutoff['new_frozen_entries']:
    raw=(FROZEN/row['path']).read_bytes()
    checked(raw,row)
    assert row['path'] not in base
    proofs=row['saved_readback_proofs']
    if proofs:
        method='Saved original GitHub create/fetch response independently compared in full with the frozen file.'
        evidence=proofs
    else:
        receipt=by_path[row['path']]
        checked(raw,receipt)
        method=receipt['verification_method']
        evidence=[{'fresh_fetch_full_content_equal':True,
                   'created_in_this_task':receipt['created_in_this_task']}]
    verified.append({'path':row['path'],**pin(raw),'local':str(FROZEN/row['path']),
        'category':row['category'],'full_readback_equal':True,
        'verification_method':method,'readback_evidence':evidence})
assert len(verified)==181

# Base publication and exact PR body receipts are read, never re-issued.
pub='checkpoint-2841-publication/'
anchors=read_json(pub+'PUBLISHED_2841_ANCHORS.json')
commit=read_json(pub+'COMMIT_READ.response.json')
commit=json.loads(commit['structuredContent']['content'])
ref=read_json(pub+'REF_READ.response.json')
ref=json.loads(ref['structuredContent']['content'])
pr=read_json(pub+'PR_READ.original.json')['structuredContent']
pr=json.loads(pr['content'])
assert commit['sha']==ref['object']['sha']==anchors['evidence_head']==cutoff['base_evidence_commit']
assert commit['tree']['sha']==anchors['evidence_root']
assert [p['sha'] for p in commit['parents']]==[anchors['evidence_parent']]
body=(FROZEN/(pub+'PR.PUBLISH.md')).read_bytes()
assert pr['body'].encode()==body and pr['updated_at']=='2026-11-12T23:12:13Z'
checked(body,{'bytes':9848,'git_blob':'1ed37bc19bf14c30d39640e297f871ec350edc24',
    'sha256':'6d4b80b168a322537d245222d13fca0bf8e2d5189125469f9feb32ca6c7b860c'})
assert (FROZEN/'checkpoints/README_2841FILES_BEFORE_POST2841_INCREMENT.md').read_bytes() \
    == (Path('/tmp/hepta-36fa-after2793-20261112')/'README.PUBLISH.md').read_bytes()
assert pin((FROZEN/'checkpoints/README_2841FILES_BEFORE_POST2841_INCREMENT.md').read_bytes())['git_blob']==base['README.md']
encoded_manifest=read_json(pub+'LEAF_READ_RESPONSE_ENCODING_MANIFEST.json')
chunks=[]
for row in encoded_manifest['parts']:
    encoded=(FROZEN/(pub+row['name'])).read_bytes();checked(encoded,row['encoded'])
    assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
    decoded=base64.b64decode(encoded[:-1],validate=True);checked(decoded,row['decoded'])
    chunks.append(decoded)
packed=b''.join(chunks);checked(packed,encoded_manifest['gzip'])
leaf_response=gzip.decompress(packed);checked(leaf_response,encoded_manifest['raw'])
tree_obj=json.loads(json.loads(leaf_response)['structuredContent']['content'])
assert tree_obj['sha']==cutoff['base_evidence_leaf'] and tree_obj['truncated'] is False
assert {r['path']:r['sha'] for r in tree_obj['tree'] if r['type']=='blob'}==base

# Independently reconstruct the exact frozen clone inventory from the five
# already-archived companions, then bind every original inventory reference.
source='final-source-gates-246d-v1/'
recover=source+'inventory-exact-recovery/'
recovery=read_json(recover+'RECOVERY_REVIEW.json')
pieces=[]
for row in recovery['parts']:
    encoded=(FROZEN/(recover+Path(row['companion']['path']).name)).read_bytes()
    checked(encoded,row['companion'])
    assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
    decoded=base64.b64decode(encoded[:-1],validate=True)
    checked(decoded,row['decoded']);pieces.append(decoded)
gz=b''.join(pieces);checked(gz,recovery['gzip'])
inventory=gzip.decompress(gz);checked(inventory,recovery['raw'])
assert len(json.loads(inventory)['files'])==15188
original_matches=[]
for reference in recovery['original_references']:
    manifest=read_json(source+reference['retained_manifest'])
    selected=[r for r in manifest['files'] if r['original_path']==reference['original_path']]
    assert len(selected)==1
    selected=selected[0]
    assert selected['encoding']=='gzip'
    assert selected['original_bytes']==len(inventory)
    assert selected['original_sha256']==pin(inventory)['sha256']
    assert selected['parts']==reference['parts']
    assert len(selected['parts'])==len(pieces)==5
    for actual, expected in zip(pieces,selected['parts']): checked(actual,expected)
    original_matches.append({'manifest':reference['retained_manifest'],
       'original_path':reference['original_path'],'raw_and_all_five_parts_equal':True})
assert len(original_matches)==7
assert pin(inventory)['sha256']=='4db429ba1d54aa7ed6d6ad199694b7410d654ee7f788a631d7f392d7552fc79b'

# No claims about the newer repair's terminal state are derived from admission.
admission=read_json('source-repair-246d/fmt-launch/MAIN_ADMISSION.original.json')
admission=json.loads(admission['content'][0]['text'])
assert admission['job']['id']=='1a1d2107dce-2564-1c98'
assert admission['launch']['ok'] is True and admission['reused'] is False
assert not any(Path(r['path']).name in ['RESULT.original.json','STATUS_01.original.json']
               and '/fmt-launch/' in r['path'] for r in verified)

report={
 'format':'hepta-post2841-frozen-evidence-review-v1',
 'status':'VERIFIED_APPEND_ONLY_PREPARATION_NOT_PUBLISHED',
 'frozen_input_cutoff_utc':cutoff['frozen_cutoff_utc'],
 'base':{'commit':cutoff['base_evidence_commit'],'leaf':cutoff['base_evidence_leaf'],
         'files':2841,'all_four_saved_tree_reads_raw_Git_recomputed':True,
         'saved_commit_ref_and_PR_body_pins_verified':True},
 'payload':{'files':len(verified),'bytes':sum(r['bytes'] for r in verified),
            'fresh_entire_GitHub_content_comparisons':len(receipts),
            'saved_original_entire_GitHub_response_comparisons':sum(bool(r['saved_readback_proofs']) for r in cutoff['new_frozen_entries']),
            'unverified':0,'old_path_replacements':[],
            'categories':dict(sorted(collections.Counter(r['category'] for r in verified).items()))},
 'source_qualification':{'commit':'246d8cb614770252ee42029a5c014f2a4904176a',
     'tree':'d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087','job':'1a1d1e83bd4-2564-1c86',
     'overall':'failed','stages':['source-closure failed','caller self-test passed','full caller verification passed'],
     'source_closure_original_runner':{'tests':492,'passed':486,'failure_entries':6},
     'parser_distinction':'The six failure entries occur in four failed methods; all original runner and raw records are retained.',
     'original_failure_not_reclassified':True,'native_qualification_started_in_this_scope':False,
     'actual_qualified_task_chain_outcomes':0},
 'scope_of_new_reviews':'Static source/control reviews and the already-recorded scoped diagnostic only; no new gate execution.',
 'exact_inventory_recovery':{'raw':pin(inventory),'gzip':pin(gz),'source_files':15188,
     'unique_encoded_parts':5,'original_references_verified':original_matches,
     'is_new_physical_observation':False,'is_native_compact_snapshot':False,
     'canonical14_already_in_base_not_added_again':True},
 'newer_repair_at_cutoff':{'job':'1a1d2107dce-2564-1c98','actual_admission_verified':True,
     'terminal_included':False,'result_included':False,
     'note':'Later outcomes are deliberately outside this fixed evidence cutoff. Approval/admission is not a result or qualification.'},
 'publication_constraints':{'source_changed':False,'H_invoked':False,'tests_or_gates_executed':False,
     'trees_created':False,'commits_created':False,'refs_updated':False,'PR_updated':False,
     'root_must_review_and_publish':True,'README_old_value_preserved':True,
     'root_may_replace_README_after_review':True},
 'base_README_archive':'checkpoints/README_2841FILES_BEFORE_POST2841_INCREMENT.md',
 'cutoff_input_record':pin((ROOT/'CUTOFF_AND_INPUTS.json').read_bytes()),
 'frozen_payload_readback_ledger':'READBACK_LEDGER.json',
}
write_once('READBACK_LEDGER.json',{'format':'hepta-frozen-evidence-payload-readbacks-v1',
    'cutoff_utc':cutoff['frozen_cutoff_utc'],'files':verified})
write_once('PREPARATION_REVIEW.json',report)
write_once('VERIFIED_PAYLOAD_ENTRIES.json',verified)
print(json.dumps({'payload':len(verified),'base':len(base),'unverified':0,
  'recovery_original_references':len(original_matches),'review':pin((ROOT/'PREPARATION_REVIEW.json').read_bytes())}))
