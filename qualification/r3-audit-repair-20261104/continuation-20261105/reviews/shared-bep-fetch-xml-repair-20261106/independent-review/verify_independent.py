#!/usr/bin/env python3
"""Independent fixed-source/patch/full-tree proof; no product or native execution."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import tempfile
from static_helpers import identity, merkle

EXPECTED = {
    'b21': ('ebd31e2b3e38ff72cedaa7b57bee60c1c102da27',
            '46fca3e684217066c260dc10d0dc319a33e0a93c',
            '17ff1640c21876a08396db6a40f131a26870fe84',
            '45858bc96c0edbc366ec77991646b15971129975',8),
    'b23': ('e63ed76c5d8ded046f97caffbdbe2883140e6032',
            'a6831e2607e718f1343b788e5b8062a171d50a71',
            '993d7a76a4fc6c2924e45c7ef403cecd6d108d1f',
            '9a6fd02aa18b2421f6aaec8a5db6ecf82b710c89',10),
}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    root=ap.parse_args().root.resolve();src=root/'author-frozen'
    frozen=(src/'freeze-manifest.json').read_bytes();manifest=json.loads(frozen)
    assert identity(frozen)['git_blob']=='ca91ce1e0d8616ad17eaeeba83542855214f5d91'
    assert len(manifest['files'])==len({r['path'] for r in manifest['files']})==1010
    for row in manifest['files']:
        path=Path(row['path']);assert not path.is_absolute() and '..' not in path.parts
        target=src/path;assert target.is_file() and not target.is_symlink()
        assert identity(target.read_bytes())=={k:row[k] for k in ('bytes','git_blob','sha256')}
    ids=json.loads((src/'candidate-identities.json').read_bytes())
    old=(src/'preimage/collect_attempts.py').read_bytes();new=(src/'collect_attempts.py').read_bytes()
    assert identity(old)['git_blob']=='00dc37697adde6154a347963ab19e8a6edebac07'
    assert identity(new)['git_blob']=='ee1b82877fbd55a2e3838d768014715617e05ea0'
    def definitions(data):
        text=data.decode();return {n.name:ast.get_source_segment(text,n)
            for n in ast.parse(text).body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
    a,b=definitions(old),definitions(new);assert a.keys()==b.keys()
    preserved=[name for name in a if name not in ('collect','reconcile')]
    assert len(preserved)==18 and all(a[name]==b[name] for name in preserved)
    base=json.loads((src/'authority/main67-full-tree.json').read_bytes())
    assert base['sha']=='3982ba56dc5a3f1da0c1de7ea57992f88125c359' and base['truncated'] is False
    rows={r['path']:r for r in base['tree']};assert len(rows)==len(base['tree'])
    leaves={p:r for p,r in rows.items() if r['type']!='tree'}
    before,dirs=merkle(leaves);assert before==base['sha'] and len(leaves)==10582 and len(dirs)==1571
    assert {p:r['sha'] for p,r in rows.items() if r['type']=='tree'}=={p:s for p,s in dirs.items() if p}
    patch_inputs=[('collector','collect_attempts.py',old,new,src/'collector.patch')]
    workflow_results=[];posts={identity(new)['git_blob']:new}
    for label,(parent_sha,parent_tree,post_sha,wanted_tree,indent) in EXPECTED.items():
        item=ids['workflows'][label];path=item['repository_path']
        pre=(src/'preimage'/(label+'-workflow.yml')).read_bytes()
        post=(src/'candidate'/label/path).read_bytes()
        assert identity(pre)==item['preimage'] and identity(post)==item['postimage']
        assert identity(post)['git_blob']==post_sha
        left,right=pre.decode(),post.decode()
        pairs=[]
        for keep_blank in (True,False):
            def embed(body):
                return ''.join(' '*indent+line if keep_blank or line.strip() else line for line in body.decode().splitlines(keepends=True))
            x,y=embed(old),embed(new)
            if left.count(x)==right.count(y)==1:pairs.append((x,y))
        assert pairs
        x,y=pairs[0];reverted=right.replace(y,x)
        flag=' '*(indent+2)+"'--remote_download_regex="+ids['remote_download_regex']+"'\n"
        assert reverted.count(flag)==1;reverted=reverted.replace(flag,'')
        changes=item['source_guard_changes'];assert len(changes)==(6 if label=='b21' else 0)
        for old_guard,new_guard in reversed(changes):
            assert reverted.count(new_guard)==1
            reverted=reverted.replace(new_guard,old_guard)
        assert reverted.encode()==pre
        assert path not in leaves
        parent_leaves={**leaves,path:{'path':path,'mode':'100644','type':'blob','sha':identity(pre)['git_blob']}}
        after={**parent_leaves,path:{**parent_leaves[path],'sha':post_sha}}
        calculated_parent,parent_dirs=merkle(parent_leaves);calculated,new_dirs=merkle(after)
        assert calculated_parent==parent_tree and calculated==wanted_tree and len(after)==10583
        assert [p for p in parent_leaves if parent_leaves[p]!=after[p]]==[path]
        parent=json.loads((src/'authority'/(label+'-parent-commit.actual.json')).read_bytes())
        assert parent['sha']==parent_sha and parent['tree']['sha']==parent_tree
        if label=='b21':assert [p['sha'] for p in parent['parents']]==['cc65856cc0b20d03db506c19495d53d61162102d']
        workflow_results.append({'label':label,'parent':parent_sha,'parent_tree':parent_tree,
            'postimage':identity(post),'complete_candidate_tree':calculated,'directories':len(new_dirs),
            'original_product_leaves_unchanged':10582,'only_parent_leaf_changed':path,
            'full_inverse_after_only_collector_download_flag_parent_guard_edits':True,
            'source_guard_substitutions':len(changes)})
        posts[post_sha]=post;patch_inputs.append((label,path,pre,post,src/(label+'.patch')))
    gets=[]
    for sha,data in posts.items():
        raw=json.loads((root/'original'/('postimage-'+sha+'.GET.json')).read_bytes())
        assert not raw.get('isError') and raw['structuredContent']['content'].encode()==data
        gets.append({'git_blob':sha,'bytes':len(data),'full_GET_equal':True})
    patch_operations=[]
    for label,path,pre,post,patch in patch_inputs:
        with tempfile.TemporaryDirectory(prefix='fetch-xml-independent-patch-') as tmp:
            work=Path(tmp);file=work/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(pre)
            operations=[]
            for flags,want in [(['--check'],None),([],post),(['--reverse','--check'],None),(['--reverse'],pre)]:
                proc=subprocess.run(['git','apply',*flags,str(patch)],cwd=work,capture_output=True,timeout=15)
                assert proc.returncode==0 and not proc.stdout and not proc.stderr
                if want is not None:assert file.read_bytes()==want
                operations.append({'argv':['git','apply',*flags,'<frozen '+label+'.patch>'],'exit':0})
            patch_operations.append({'scope':label,'patch':identity(patch.read_bytes()),'operations':operations,'full_forward_and_reverse_bytes_equal':True})
    replay=(root/'isolated-replay.stdout.json').read_bytes()
    assert replay==(src/'static-final.stdout.json').read_bytes()
    assert (root/'isolated-replay.exit-code.txt').read_text()=='0\n'
    assert not (root/'isolated-replay.stderr.txt').read_bytes()
    reg=json.loads((src/'regressions-01.stdout.json').read_bytes())
    assert [r['actual_attempts'] for r in reg['real_bep']]==[499,8]
    assert [r['after_errors'] for r in reg['real_bep']]==[{'attempt_reference_unavailable':131},{'attempt_reference_unavailable':8}]
    assert all(not r['complete_after'] and r['test_attempts_and_summaries_identical'] for r in reg['real_bep'])
    result={'schema':'fetch-xml-independent-source-proof-v1','freeze':identity(frozen),
        'all_1010_frozen_files_exact':True,'frozen_bytes':sum(r['bytes'] for r in manifest['files']),
        'collector':identity(new),'unchanged_18_function_or_class_bodies':preserved,
        'fresh_complete_postimage_GETs':gets,'workflows':workflow_results,
        'independent_complete_base_Merkle':before,'independent_patch_operations':patch_operations,
        'isolated_original_verifier_and_all_offline_controls_exit':0,'isolated_stdout':identity(replay),
        'isolated_stdout_complete_bytes_equal':True,'original_native_attempts_in_offline_input':507,
        'historical_missing_XML_remains':139,'test_attempts_summaries_original_exits_preserved':True,
        'private_raw_BEP_and_unchanged_upload_privacy_scope':'Only existing sanitized derived BEP is replayed; no raw BEP uploaded.',
        'native_Bazel_Cargo_CI_dispatch_rerun_or_ref_mutation':False,
        'acceptance':'STATIC_AND_OFFLINE_ONLY; real XML materialization and original product failures remain pending.'}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
