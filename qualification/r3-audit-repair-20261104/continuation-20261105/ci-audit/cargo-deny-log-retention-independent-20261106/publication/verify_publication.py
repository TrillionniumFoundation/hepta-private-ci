#!/usr/bin/env python3
"""Bind preserved root publication responses to independently accepted exact source."""
import argparse
import importlib.util
import json
from pathlib import Path

BASE='67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
HEAD='476653f8fe5874849e864ab3fd49c792913450ab'
TREE='06c4e2f80884b169e31d8a5edf04438486a9ee81'
MERGE='825779c5bba92a228f8d3cf6add429592acdc4a7'
BRANCH='fix/cargo-deny-evidence-retention-20261106'
BASE_REF='fix/r3-original-product-contracts-20261104'

def unwrap(raw):
    if 'structuredContent' in raw:return raw['structuredContent']
    return json.loads(next(v['text'] for v in raw['content'] if v['type']=='text'))

def api(raw):
    data=unwrap(raw)
    return json.loads(data['content']) if 'content' in data else data

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    root=ap.parse_args().root.resolve()
    spec=importlib.util.spec_from_file_location('independent',root/'verify_independent.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    identity,merkle=module.identity,module.merkle
    raw=(root/'publication/publication-originals.json').read_bytes()
    assert identity(raw)=={'bytes':150280,'git_blob':'be82433cd0ada8e78125b6a1161920a462d4ce32','sha256':'009ec418f8a3a4153dd74653fc3026b0bb0908b7de000b26a0a834ea8e506f10'}
    records=json.loads(raw)['records'];assert len(records)==14
    candidate=(root/'author-frozen/candidate/.github/workflows/cargo-deny.yml').read_bytes()
    review=(root/'REVIEW.json').read_bytes()
    for key,data,sha in [('rootSource',candidate,'57f6095d18c5517c9e7cf7d0de05b9645b106152'),('independentReview',review,'875534b774e4e0f403fce5533ebcd07fb5df4122')]:
        item=records[key]
        assert item['text'].encode()==data and unwrap(item['raw'])['content'].encode()==data
        assert identity(data)['git_blob']==sha
    assert api(records['treeCreated'])['sha']==TREE
    assert api(records['commitCreated'])['sha']==HEAD
    head=api(records['commitActual']);merge=api(records['mergeActual'])
    assert head['sha']==HEAD and head['tree']['sha']==TREE
    assert [p['sha'] for p in head['parents']]==[BASE]
    assert merge['sha']==MERGE and merge['tree']['sha']==TREE
    assert [p['sha'] for p in merge['parents']]==[BASE,HEAD]
    base=api(records['base_ref_before']);ref=api(records['refAfter'])
    assert base['ref']=='refs/heads/'+BASE_REF and base['object']['sha']==BASE
    assert api(records['refBefore'])['error_code']=='NOT_FOUND'
    assert ref['ref']=='refs/heads/'+BRANCH and ref['object']['sha']==HEAD
    pr=api(records['prActual']);created=api(records['prCreated'])
    assert pr['number']==created['number']==4922 and pr['draft'] is True and created['draft'] is True
    assert pr['state']==created['state']=='open' and pr['merge_commit_sha']==MERGE
    assert pr['head']['ref']==created['head']==BRANCH and pr['head']['sha']==created['head_sha']==HEAD
    assert pr['base']['ref']==created['base']==BASE_REF and pr['base']['sha']==created['base_sha']==BASE
    assert pr['head']['repo']['full_name']==pr['base']['repo']['full_name']=='TrillionniumFoundation/hepta-private-ci'
    assert pr['body']==created['body']==records['prBodyIntended']
    tree=json.loads((root/'author-frozen/authority/main67-full-tree.json').read_bytes())
    assert tree['sha']=='3982ba56dc5a3f1da0c1de7ea57992f88125c359' and tree['truncated'] is False
    entries={e['path']:e for e in tree['tree']};assert len(entries)==len(tree['tree'])
    leaves={p:e for p,e in entries.items() if e['type']!='tree'}
    base_hash,dirs=merkle(leaves);assert base_hash==tree['sha']
    assert {p:e['sha'] for p,e in entries.items() if e['type']=='tree'}=={p:s for p,s in dirs.items() if p}
    assert len(leaves)==10582 and len(dirs)==1571
    path='.github/workflows/cargo-deny.yml'
    assert leaves[path]['sha']=='88b6308899357e23b4a4058aecd4527b4edcee9b'
    after=dict(leaves);after[path]={**leaves[path],'sha':identity(candidate)['git_blob']}
    after_hash,after_dirs=merkle(after);assert after_hash==TREE
    expected=[{'path':p,'mode':e['mode'],'type':e['type'],'sha':e['sha']} for p,e in after.items() if '/' not in p]
    expected += [{'path':p,'mode':'040000','type':'tree','sha':s} for p,s in after_dirs.items() if p and '/' not in p]
    root_tree=api(records['treeRootActual'])
    assert root_tree['sha']==TREE and root_tree['truncated'] is False and len(root_tree['tree'])==53
    actual=[{k:e[k] for k in ('path','mode','type','sha')} for e in root_tree['tree']]
    assert sorted(actual,key=lambda e:e['path'])==sorted(expected,key=lambda e:e['path'])
    static=(root/'publication/root-static.stdout.json').read_bytes()
    assert static==(root/'author-frozen/static-01.stdout.json').read_bytes()
    assert identity(static)['git_blob']=='9f6f931ba3aa047aa437e19079d344b29bcb947f'
    result={'schema':'cargo-deny-root-publication-independent-binding-v1','original_responses':identity(raw),
      'response_groups':14,'source':identity(candidate),'independent_review':identity(review),
      'head':HEAD,'head_parent':[BASE],'tree':TREE,'merge':MERGE,'merge_parents':[BASE,HEAD],
      'base_ref':BASE_REF,'head_ref':BRANCH,'PR':4922,'draft':True,'actual_root_entries':53,
      'complete_Merkle_leaves':10582,'directories':1571,'unchanged_leaves':10581,
      'all_root_entries_equal_computed_projection':True,'PR_body_full_bytes_equal_intended':True,
      'root_static_replay_stdout':identity(static),'root_static_full_bytes_equal_author':True,
      'scope':'Preserved actual API publication response binding only; no CI result, native cargo execution, artifact upload or blocker closure is inferred.',
      'new_API_or_ref_mutation_by_this_verifier':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
