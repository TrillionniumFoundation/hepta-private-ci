#!/usr/bin/env python3
"""Prepare reviewed non-Rust bytes only; never touch the native source."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

HERE=Path('/tmp/hepta-36fa-postformat-nonrust-v1')
SOURCE=HERE/'source_view'
CANDIDATE=Path('/tmp/hepta-36fa-final-nonrust-review-snapshot-v2')
OUT=Path('/tmp/hepta-36fa-reviewed-final-nonrust-v2')
INV=Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')
CAPTURE=Path('/tmp/hepta-36fa-postformat-capture-launch-v1/RESULT.json')

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def jbytes(value):
    return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode()

def tree_sha(leaves):
    root={}
    for path,row in leaves.items():
        node=root
        parts=path.split('/')
        for name in parts[:-1]:
            node=node.setdefault(name,{})
        assert parts[-1] not in node
        node[parts[-1]]=(row['mode'],row['sha'])
    def encode(node):
        entries=[]
        for name,item in node.items():
            if isinstance(item,dict):
                mode,sha='40000',encode(item)
                sortkey=name.encode()+b'/'
            else:
                mode,sha=item
                sortkey=name.encode()
            entries.append((sortkey,mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
        body=b''.join(raw for _,raw in sorted(entries))
        return hashlib.sha1(b'tree '+str(len(body)).encode()+b'\0'+body).hexdigest()
    return encode(root)

def method_map(text):
    parsed=ast.parse(text)
    out={}
    for cls in parsed.body:
        if isinstance(cls,ast.ClassDef):
            for node in cls.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                    key=cls.name+'.'+node.name
                    assert key not in out
                    out[key]={'source':ast.get_source_segment(text,node),
                              'ast':ast.dump(node,include_attributes=False)}
    return out

def main():
    OUT.mkdir(exist_ok=False)
    invraw=INV.read_bytes();inventory=json.loads(invraw);capture=json.loads(CAPTURE.read_bytes())
    assert pin(invraw)=={'bytes':5614211,'sha256':'3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f','git_blob':'1563de8825fc183d345d10d03e68d79b2d9211ca'}
    assert inventory['source']==capture['source_identity']
    rows={x['path']:x for x in inventory['files']}
    leaves={p:{'mode':x['index_mode'],'sha':x['working_blob'],'bytes':x['bytes'],'sha256':x['sha256']} for p,x in rows.items()}
    assert len(leaves)==15188
    base_tree=tree_sha(leaves)
    assert base_tree=='65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
    snapshot=json.loads((CANDIDATE/'MANIFEST.json').read_bytes())
    for item in snapshot['files']:
        raw=(CANDIDATE/item['path']).read_bytes();p=pin(raw)
        assert {'bytes':p['bytes'],'sha256':p['sha256'],'git_blob_sha':p['git_blob']}=={k:v for k,v in item.items() if k!='path'}
    files=['CALLERS.toml']+sorted(str(p.relative_to(CANDIDATE)) for p in (CANDIDATE/'qa').rglob('*.py'))
    after={rel:(CANDIDATE/rel).read_bytes() for rel in files}
    allowlist='.github/blob-size-allowlist.txt'
    allowbefore=(SOURCE/allowlist).read_bytes()
    allowline='sha256:'+pin(after['CALLERS.toml'])['sha256']+' CALLERS.toml\n'
    assert allowline.encode() not in allowbefore
    after[allowlist]=allowbefore+b'\n# Actual evaluated ordinary owner source protections and exact retained caller inventory.\n'+allowline.encode()
    changes=[];patch=[];before_after={}
    for rel in sorted(after):
        rawbefore=(SOURCE/rel).read_bytes();rawafter=after[rel];row=rows[rel]
        assert row['index_mode']=='100644' and row['permissions']==0o644 and row['kind']=='file'
        assert pin(rawbefore)=={'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']}
        assert rawbefore!=rawafter
        before_pin,after_pin=pin(rawbefore),pin(rawafter)
        changes.append({'path':rel,'mode':'100644','before':before_pin,'after':after_pin,'after_base64':base64.b64encode(rawafter).decode()})
        before_after[rel]={'before':before_pin,'after':after_pin}
        leaves[rel]={'mode':'100644','sha':after_pin['git_blob'],'bytes':after_pin['bytes'],'sha256':after_pin['sha256']}
        for kind,raw in [('before',rawbefore),('after',rawafter)]:
            dest=OUT/kind/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        patch.extend(difflib.unified_diff(rawbefore.decode().splitlines(True),rawafter.decode().splitlines(True),fromfile='a/'+rel,tofile='b/'+rel,n=3))
    original=tomllib.loads((SOURCE/'CALLERS.toml').read_text())
    final=tomllib.loads(after['CALLERS.toml'].decode())
    assert {k:v for k,v in original.items() if k!='protected_file'}=={k:v for k,v in final.items() if k!='protected_file'}
    assert len(original['boundary'])==len(final['boundary'])==569
    assert len(original['protected_file'])==412 and len(final['protected_file'])==422
    fence=json.loads((CANDIDATE/'FENCE_REVIEW.json').read_bytes())
    modified={x['index'] for x in fence['row_changes'] if x['existing']}
    assert len(modified)==39
    for i,row in enumerate(original['protected_file']):
        if i not in modified: assert row==final['protected_file'][i]
        else: assert row.get('forbidden',[])==final['protected_file'][i].get('forbidden',[])
    method_changes=[];old_count=0;new_count=0;unchanged=0
    for path in sorted((SOURCE/'qa/b4-no-bypass').glob('*.py')):
        rel=str(path.relative_to(SOURCE));beforetext=path.read_text();aftertext=after.get(rel,path.read_bytes()).decode()
        before_methods,after_methods=method_map(beforetext),method_map(aftertext)
        assert set(before_methods)<=set(after_methods)
        old_count+=len(before_methods);new_count+=len(set(after_methods)-set(before_methods))
        for key,item in before_methods.items():
            observed=after_methods[key]
            if item==observed:unchanged+=1
            else:method_changes.append({'path':rel,'method':key,'source_equal':item['source']==observed['source'],'ast_equal':item['ast']==observed['ast'],'before':pin(item['source'].encode()),'after':pin(observed['source'].encode())})
    # The 152-method inventory covers 17 relevant QA files; four additional
    # captured QA files are retained verbatim and are counted independently here.
    relevant=json.loads((HERE/'QA_METHOD_INVENTORY.original.json').read_text())
    (OUT/'ALL_CAPTURED_QA_METHOD_REVIEW.json').write_bytes(jbytes({'scope':'all 21 actual captured QA files','original_methods':old_count,'unchanged_methods':unchanged,'explicitly_changed_original_methods':method_changes,'new_methods':new_count,'removed_methods':0}))
    assert len(method_changes)==17 and new_count==18
    after_tree=tree_sha(leaves)
    packet={'format':'hepta-reviewed-nonrust-source-apply-v1','source_identity':capture['source_identity'],'base_inventory':pin(invraw),'base_physical_tree':base_tree,'expected_after_physical_tree':after_tree,'expected_after_leaf_count':len(leaves),'changes':changes}
    raw=jbytes(packet);(OUT/'NONRUST_PACKET.json').write_bytes(raw)
    compressed=gzip.compress(raw,compresslevel=9,mtime=0);(OUT/'NONRUST_PACKET.json.gz').write_bytes(compressed)
    parts=[]
    for n,offset in enumerate(range(0,len(compressed),196605),1):
        chunk=compressed[offset:offset+196605];encoded=base64.b64encode(chunk)+b'\n'
        name=f'NONRUST_PACKET.json.gz.part{n:03}.b64';(OUT/name).write_bytes(encoded)
        parts.append({'path':name,'gzip_offset':offset,'decoded':pin(chunk),'encoded':pin(encoded)})
    patchraw=''.join(patch).encode();(OUT/'EXACT_NONRUST_DELTA.patch').write_bytes(patchraw)
    (OUT/'EXPECTED_AFTER_LEAVES.json').write_bytes(jbytes({'format':'hepta-nonrust-proposal-physical-leaves-v1','tree':after_tree,'files':leaves}))
    for name in ['FENCE_REVIEW.json','OLD_QA_MIGRATIONS.json','NEW_ORDINARY_QA_REVIEW.json','SCOPED_49_VALIDATOR.json']:
        shutil.copyfile(CANDIDATE/name,OUT/name)
    diagnostic=Path('/tmp/hepta-36fa-final-qa18-scoped-diagnostic-v2')
    for name in ['RESULT.json','INPUT_INVENTORY.json','AFTER_INVENTORY.json','new18.raw.log','run_scoped.py']:
        dest=OUT/'diagnostic-new18'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(diagnostic/name,dest)
    summary={'format':'hepta-reviewed-final-nonrust-proposal-v2','status':'prepared_requires_root_and_peer_review_not_applied','qualification':False,'base_source_identity':capture['source_identity'],'base_inventory':pin(invraw),'base_physical_tree':base_tree,'expected_after_physical_tree':after_tree,'expected_after_leaf_count':len(leaves),'changed_paths':before_after,'counts':{'changed_paths':len(changes),'boundaries_before_after':569,'protected_before':412,'protected_after':422,'old_protected_migrated':39,'new_protected':10,'unchanged_old_protected':373,'explicit_old_qa_methods_migrated':17,'new_qa_methods':18,'deleted_methods':0,'all21_old_methods':old_count,'all21_unchanged_old_methods':unchanged},'packet':pin(raw),'packet_gzip':pin(compressed),'packet_parts':parts,'reconstruction':'For ordered packet_parts, base64-decode each encoded file; concatenate decoded bytes by gzip_offset; verify packet_gzip identity, gzip-decompress, verify packet identity. The raw JSON includes full after_base64 and before/after identities for every actual captured existing path.','exact_patch':pin(patchraw),'preservation':{'all_nonprotected_callers_fields_byte_semantics_unchanged':True,'original_verifier_and_typed_helper_unchanged':True,'old_forbidden_arrays_unchanged':True,'original_full_source_collector_not_filtered':True,'new_source_or_verdict_cache':False,'authority_flags_unchanged':True,'original_budgets_unchanged':True,'source_paths_added_or_removed':False,'allowlist_change':'Append exact final CALLERS SHA256 only; all prior bytes preserved.'},'actual_scoped_diagnostics':{'original_protection_validator':'49 selected rows accepted on actual captured source; not complete source verification','new_source_attack_tests':json.loads((diagnostic/'RESULT.json').read_bytes()),'old17_methods':'not run in partial source workspace; full collector requires complete frozen source'},'qualification_gates':{'full_source_closure':'not_run','fullcaller':'not_run','native_rust':'not_run','real_authorized_ABC':'not_established','ordinary_root_daemon_recovery':'not_established'},'required_next_steps':['Root and peer review of exact before/after bytes and physical tree','Authorized native apply under original task source lock','Original just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f with 900 second budget after final code changes','If protected Rust changes, preserve actual postimages and synchronize actual markers before freeze','Freeze exact source, then run original full qualification gates; no scoped result inheritance']}
    summary['supersedes_without_deleting']={'manifest_git_blob':'10dffe87464c5a94cbf7c02f6b6ae1958697cd22','packet_git_blob':'5300dbea46941ff805fb3612a47b6e5f7fe6617a','physical_tree':'74a2fe12be39aba5ab55d537124cd9462673fd9e','reason':'Minimal actual call coverage correction for 21 previously unexecuted scope guards; original preparation and original18pass preserved.'}
    for name in ['V1_TO_V2_SCOPE_COVERAGE.diff','SCOPE_COVERAGE_CORRECTION.json']:
        shutil.copyfile(CANDIDATE/name,OUT/name)
    for name in ['ACTUAL_SCOPE_COVERAGE.json','run_class_with_scope_trace.py']:
        shutil.copyfile(diagnostic/name,OUT/'diagnostic-new18'/name)
    scope=json.loads((diagnostic/'ACTUAL_SCOPE_COVERAGE.json').read_bytes())
    assert scope['all_actual_scopes_observed'] is True and scope['expected_paths']==20 and scope['expected_scope_count']==34
    summary['actual_scoped_diagnostics']['all_actual_root_scopes']={key:value for key,value in scope.items() if key!='calls'}
    summary['actual_scoped_diagnostics']['scope_coverage_record']=pin((diagnostic/'ACTUAL_SCOPE_COVERAGE.json').read_bytes())
    summary['v1_to_v2_exact_delta']=pin((OUT/'V1_TO_V2_SCOPE_COVERAGE.diff').read_bytes())
    (OUT/'MANIFEST.json').write_bytes(jbytes(summary))
    print(json.dumps({'directory':str(OUT),'packet':pin(raw),'gzip':pin(compressed),'parts':parts,'manifest':pin(jbytes(summary)),'patch':pin(patchraw),'counts':summary['counts'],'tree':after_tree},sort_keys=True))

if __name__=='__main__':main()
