"""Independent byte/AST/TOML review. Never import or execute candidate code."""
import ast
import collections
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

FROZEN = Path('/tmp/hepta-36fa-provider-registration-root86-frozen-v3')
BASE = Path('/tmp/hepta-36fa-provider-registration-rebuilt-v3')
OUT = Path('/tmp/hepta-36fa-provider-registration-root86-native-peer-v1')
READS = []

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def read(path):
    before = path.stat()
    with path.open('rb') as f:
        opened = os.fstat(f.fileno())
        body = f.read()
        after = os.fstat(f.fileno())
    latest = path.stat()
    key = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    assert key(before)==key(opened)==key(after)==key(latest),path
    READS.append({'path':str(path),**pin(body),'stable':True})
    return body

def identities(value):
    return {k:value[k] for k in ('bytes','sha256','git_blob')}

def function_map(text):
    result = {}
    def visit(node, parents=()):
        for item in ast.iter_child_nodes(node):
            if isinstance(item,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                key = parents+(item.name,)
                if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    lines=text.splitlines(keepends=True)
                    start=min([item.lineno]+[x.lineno for x in item.decorator_list])
                    assert key not in result,key
                    result[key]=''.join(lines[start-1:item.end_lineno])
                visit(item,key)
            else:
                visit(item,parents)
    visit(ast.parse(text))
    return result

def assignment_map(text):
    result={}
    for n in ast.parse(text).body:
        if isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name):
                    try: value=ast.literal_eval(n.value)
                    except (ValueError,TypeError): value={'ast':ast.dump(n.value,include_attributes=False)}
                    result[t.id]={'value':value,'source':ast.get_source_segment(text,n)}
    return result

def raw_rows(text,name):
    # All top-level array table delimiters are distinguished from strings by
    # requiring the exact complete line emitted in the fixed CALLERS source.
    rows=[]
    for m in re.finditer(r'(?m)^\[\['+re.escape(name)+r'\]\]\r?$',text):
        tail=text[m.end():]
        nxt=re.search(r'(?m)^\[',tail)
        end=m.end()+nxt.start() if nxt else len(text)
        rows.append(text[m.start():end])
    return rows

packet_body=read(FROZEN/'SOURCE_PACKET.json')
assert pin(packet_body)=={'bytes':4741504,'sha256':'51ddeb15401455365e8f7f6fd63391b7a6b59a9a7f663ec7004417c45a35ebdb','git_blob':'fab488b846bb1b1ef7a42b9b30be5773054e1a6a'}
packet=json.loads(packet_body)
changes={x['path']:x for x in packet['source_changes']}
assert len(changes)==len(packet['source_changes'])==19
for path,row in changes.items():
    for side in ('before','after'):
        body=row[side+'_content']
        if body is None: assert row[side] is None
        else: assert pin(body.encode())==identities(row[side]),(path,side)

old_text=changes['CALLERS.toml']['before_content']
new_text=changes['CALLERS.toml']['after_content']
old,new=map(tomllib.loads,(old_text,new_text))
assert (len(old['boundary']),len(new['boundary']))==(569,621)
assert (len(old['protected_file']),len(new['protected_file']))==(422,437)
for k in old:
    if k not in ('boundary','protected_file','privileged_inventory'):
        assert new[k]==old[k],k
assert set(old)==set(new)
assert set(old['privileged_inventory'])==set(new['privileged_inventory'])
for k,v in old['privileged_inventory'].items():
    if k!='required_boundary_ids': assert new['privileged_inventory'][k]==v,k
old_ids=old['privileged_inventory']['required_boundary_ids']
new_ids=new['privileged_inventory']['required_boundary_ids']
assert new_ids[:len(old_ids)]==old_ids
assert set(new_ids)=={x['id'] for x in new['boundary']}
assert new_ids[569:]==[x['id'] for x in new['boundary'][569:]]
assert len(set(new_ids))==621
boundary_changes=[]
for i,(a,b) in enumerate(zip(old['boundary'],new['boundary'])):
    delta=[k for k in set(a)|set(b) if a.get(k)!=b.get(k)]
    if delta:
        assert delta==['product_callers'],(i,delta)
        assert b['product_callers'][:len(a['product_callers'])]==a['product_callers'],i
        assert len(set(b['product_callers']))==len(b['product_callers']),i
        boundary_changes.append({'index':i,'id':a['id'],'old_callers':a['product_callers'],'new_callers':b['product_callers']})
assert len(boundary_changes)==17

ob,nb=raw_rows(old_text,'protected_file'),raw_rows(new_text,'protected_file')
assert len(ob)==422 and len(nb)==437
protected_changes=[]
for i,(a,b) in enumerate(zip(old['protected_file'],new['protected_file'])):
    assert a['path']==b['path'],i
    assert a['forbidden']==b['forbidden'],i
    assert b['required'][:len(a['required'])]==a['required'],i
    if ob[i]!=nb[i]:
        protected_changes.append({'index':i,'path':a['path'],'changed_fields':[k for k in set(a)|set(b) if a.get(k)!=b.get(k)],'before_raw':pin(ob[i].encode()),'after_raw':pin(nb[i].encode())})
assert len(protected_changes)==21
assert ob[411]==nb[411]

root_map_body=read(FROZEN/'ROOT_86_MAP.original.json')
assert pin(root_map_body)==identities(packet['required_overlay_map'])
root_map=json.loads(root_map_body)
overlay=[]
for row in root_map['rust_files']:
    data=read(BASE/'view-root86'/row['path'])
    assert pin(data)==identities(row),row['path']
    overlay.append({'path':row['path'],**pin(data)})
assert len(overlay)==86
remote=old['protected_file'][411]['path']
assert read(BASE/'view-root86'/remote)==read(BASE/'before'/remote)

qa_files=sorted((BASE/'before/qa/b4-no-bypass').glob('test_*.py'))
assert len(qa_files)==63
qa_rows=[];function_changes=[];assignments=[];method_count=0;unchanged_methods=0
for file in qa_files:
    path=file.relative_to(BASE/'before').as_posix()
    canonical=read(file).decode()
    original=changes[path]['before_content'] if path in changes else canonical
    proposed=changes[path]['after_content'] if path in changes else original
    assert original is not None
    if path!='qa/b4-no-bypass/test_resident_root_source_closure.py': assert original==canonical,path
    bm,am=function_map(original),function_map(proposed)
    assert bm.keys()==am.keys(),path
    methods=[k for k in bm if k[-1].startswith('test_')]
    method_count+=len(methods)
    unchanged_methods+=sum(bm[k]==am[k] for k in methods)
    for key in bm:
        if bm[key]!=am[key]:
            function_changes.append({'path':path,'qualified_name':list(key),'before':pin(bm[key].encode()),'after':pin(am[key].encode()),'diff':''.join(difflib.unified_diff(bm[key].splitlines(True),am[key].splitlines(True),fromfile='before',tofile='after'))})
    ba,aa=assignment_map(original),assignment_map(proposed)
    assert ba.keys()==aa.keys(),path
    for name in ba:
        if ba[name]!=aa[name]:
            assignments.append({'path':path,'name':name,'before':pin(ba[name]['source'].encode()),'after':pin(aa[name]['source'].encode()),'value_changed':ba[name]['value']!=aa[name]['value']})
    qa_rows.append({'path':path,'canonical':pin(canonical.encode()),'layer_preimage':pin(original.encode()),'after':pin(proposed.encode()),'test_methods':len(methods),'functions':len(bm)})
assert method_count==590 and unchanged_methods==587
assert len(function_changes)==3

contract=json.loads(changes['qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json']['after_content'])
check_keys=('boundary','privileged_inventory','authority','source_roots','ignored_path_fragments')
inventory_hash=hashlib.sha256(json.dumps({k:new[k] for k in check_keys},sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert inventory_hash==contract['complete_boundary_sha256']
assert contract['new_boundaries']==new['boundary'][569:]
assert contract['root_source_map']==pin(root_map_body)['git_blob']
assert set(contract['scopes'])==set(contract['module_shapes'])
assert len(contract['scopes'])==41 and sum(map(len,contract['scopes'].values()))==264
assert all(p in {r['path'] for r in overlay} for p in contract['scopes'])
assert sum(map(len,contract['attacks'].values()))==83
new_qa=changes['qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py']['after_content']
new_methods=[k for k in function_map(new_qa) if k[-1].startswith('test_')]
assert len(new_methods)==14
allow=changes['.github/blob-size-allowlist.txt']
assert allow['after_content']==allow['before_content']+'sha256:'+pin(new_text.encode())['sha256']+' CALLERS.toml\n'

result={'status':'STATIC_BYTE_AST_TOML_REVIEW_NO_CANDIDATE_EXECUTION','packet':pin(packet_body),
 'source_changes':19,'root86_verified':overlay,'boundaries':{'before':569,'after':621,'old_only_append_changes':boundary_changes,'new_rows':new['boundary'][569:],'other_top_level_fields_equal':True,'required_ids_old_prefix_exact_new_suffix_exact_complete_set':True},
 'protected':{'before':422,'after':437,'all_422_forbidden_equal':True,'all_required_prefixes_equal':True,'old_raw_identical':401,'changed_old':protected_changes,'row411':{'path':remote,'raw_equal':True,'source_restored_equal':True,'raw_pin':pin(ob[411].encode())},'new_rows_summary':[{'index':i+422,'path':r['path'],'required_count':len(r['required']),'forbidden':r['forbidden'],'function_order_count':len(r.get('required_function_order',[]))} for i,r in enumerate(new['protected_file'][422:])]},
 'old_qa':{'file_count':63,'method_count':method_count,'unchanged_methods':unchanged_methods,'changed_functions':function_changes,'assignment_changes':assignments,'files':qa_rows},
 'new_qa':{'methods':[list(k) for k in new_methods],'scope_paths':41,'scopes':264,'attack_specs':83,'boundary_sha256':inventory_hash,'module_shape_keys_exact':True},
 'reads':READS,'reviewer_initial_assumption_failure':{'claim':'required ID order equals boundary row order','actual':'old569 and new621 both same sets but historical order already differs at446','candidate_changed':False},'candidate_imports':0,'qa_methods_executed':0,'source_scans_executed':0,'formatter_or_rust_commands':0}
target=OUT/'STATIC_BYTE_AST_TOML_REVIEW.json'
with target.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
print(json.dumps({'output':str(target),'pin':pin(target.read_bytes()),'boundaries':621,'protected':437,'old_forbidden_preserved':422,'old_raw_preserved':401,'changed_protected_indices':[x['index'] for x in protected_changes],'old_qa':{'files':63,'methods':method_count,'unchanged':unchanged_methods,'changed':[(x['path'],x['qualified_name']) for x in function_changes]},'assignment_changes':[(x['path'],x['name']) for x in assignments],'root86_verified':len(overlay),'actual_source_or_tests_executed':False},ensure_ascii=False))
