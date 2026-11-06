#!/usr/bin/env python3
"""Verify actual root PR4923 publication responses against fixed reviewed source."""
import argparse
import importlib.util
import json
from pathlib import Path

BASE='67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
HEAD='3c9e2bba4e7e84616509d6320a9ae013a274532c'
TREE='e60df9b57046df73cc1af53d8773cff48eafd311'
MERGE='65e1ec7164063b139db291562dd6093c3008b403'
BRANCH='fix/arg0-preflight-clippy-20261106'
BASE_REF='fix/r3-original-product-contracts-20261104'

def unwrap(value):
    raw=value.get('raw',value)
    return raw.get('structuredContent') or json.loads(next(x['text'] for x in raw['content'] if x['type']=='text'))

def api(value):
    data=unwrap(value)
    obj=json.loads(data['content']) if 'content' in data else data
    if 'parsed' in value:assert value['parsed']==obj
    return obj

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    root=ap.parse_args().root.resolve()
    spec=importlib.util.spec_from_file_location('source_review',root/'verify_independent.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    raw=(root/'publication/publication-originals.json').read_bytes()
    assert m.identity(raw)=={'bytes':164508,'git_blob':'9668551375aaaf04670e0c3498a4c30bba034fad','sha256':'835c1165004766d87d454113f410744ad379235ba3aaf3adc6728f2220736d2a'}
    obj=json.loads(raw);assert obj['head']==HEAD and obj['pr']==4923
    records={r['key']:r['value'] for r in obj['records']};assert len(records)==len(obj['records'])==16
    review=(root/'REVIEW.json').read_bytes()
    assert m.identity(review)['git_blob']=='f77d29800fa1f5fd9e84bb327da092015c3a5013'
    assert unwrap(records['independentReview'])['content'].encode()==review==records['independentReview']['text'].encode()
    assert records['independentReview']['parsed']==json.loads(review)
    source_records=[]
    for label,path in [('arg0_bin','codex-rs/arg0/src/bin/test_arg0_preflight.rs'),('arg0_tests','codex-rs/arg0/src/preflight_tests.rs')]:
        data=(root/'author-frozen/candidate'/path).read_bytes();ident=m.identity(data)
        assert api(records['postimage.'+label+'.created'])['sha']==ident['git_blob']
        assert unwrap(records['postimage.'+label+'.fullGET'])['content'].encode()==data
        source_records.append({'path':path,**ident,'root_actual_create_and_full_GET_equal':True})
    assert api(records['treeCreated'])['sha']==TREE
    assert api(records['commitCreated'])['sha']==HEAD
    head=api(records['commitActual']);merge=api(records['mergeActual'])
    assert head['sha']==HEAD and head['tree']['sha']==TREE and [p['sha'] for p in head['parents']]==[BASE]
    assert merge['sha']==MERGE and merge['tree']['sha']==TREE and [p['sha'] for p in merge['parents']]==[BASE,HEAD]
    base=api(records['prepub.base']);ref=api(records['refAfter'])
    assert base['ref']=='refs/heads/'+BASE_REF and base['object']['sha']==BASE
    assert api(records['prepub.branch'])['error_code']=='NOT_FOUND'
    assert ref['ref']=='refs/heads/'+BRANCH and ref['object']['sha']==HEAD
    pr,created=api(records['prActual']),api(records['prCreated'])
    assert pr['number']==created['number']==4923 and pr['draft'] is True and created['draft'] is True
    assert pr['state']==created['state']=='open' and pr['merge_commit_sha']==MERGE
    assert pr['head']['sha']==created['head_sha']==HEAD and pr['head']['ref']==created['head']==BRANCH
    assert pr['base']['sha']==created['base_sha']==BASE and pr['base']['ref']==created['base']==BASE_REF
    assert pr['head']['repo']['full_name']==pr['base']['repo']['full_name']=='TrillionniumFoundation/hepta-private-ci'
    assert pr['body']==created['body']
    leaves,dirs,tree_identity=m.tree_input(root/'author-frozen/intended-full-tree.json',TREE)
    expected=[{'path':p,'mode':e['mode'],'type':e['type'],'sha':e['sha']} for p,e in leaves.items() if '/' not in p]
    expected += [{'path':p,'mode':'040000','type':'tree','sha':s} for p,s in dirs.items() if p and '/' not in p]
    actual_root=api(records['prepub.tree'])
    assert actual_root['sha']==TREE and actual_root['truncated'] is False and len(actual_root['tree'])==53
    actual=[{k:e[k] for k in ('path','mode','type','sha')} for e in actual_root['tree']]
    assert sorted(actual,key=lambda e:e['path'])==sorted(expected,key=lambda e:e['path'])
    result={'schema':'arg0-clippy-publication-independent-binding-v1','original_responses':m.identity(raw),
       'response_groups':16,'sources':source_records,'independent_review':m.identity(review),
       'head':HEAD,'head_parents':[BASE],'tree':TREE,'merge':MERGE,'merge_parents':[BASE,HEAD],
       'head_ref':BRANCH,'base_ref':BASE_REF,'PR':4923,'draft':True,'actual_root_entries':53,
       'full_candidate_tree_input':tree_identity,'root_entries_equal_full_Merkle_projection':True,
       'PR_created_and_full_GET_body_exact':True,
       'PR_intended_argument_separately_present':False,
       'scope':'Published immutable source/review/commit/ref/PR/merge binding only. No GNU clippy or Linux fixture pass is inferred.',
       'new_CI_or_ref_calls':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
