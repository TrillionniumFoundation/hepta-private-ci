"""Static review of exact legacy migration; no candidate functions executed."""
import ast,base64,difflib,gzip,hashlib,json,re,textwrap
from pathlib import Path
OUT=Path('/tmp/hepta-36fa-provider-registration-root86-native-peer-v1')
FROZEN=Path('/tmp/hepta-36fa-provider-registration-root86-frozen-v3')
BASE=Path('/tmp/hepta-36fa-provider-registration-rebuilt-v3')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
packet_raw=(FROZEN/'SOURCE_PACKET.json').read_bytes();packet=json.loads(packet_raw);changes={r['path']:r for r in packet['source_changes']}
import tomllib
old,new=[tomllib.loads(changes['CALLERS.toml'][s+'_content'])for s in ('before','after')]
oldb={r['id']:r for r in old['boundary']};newb={r['id']:r for r in new['boundary']}

def expected_entries(s):
    for n in ast.parse(s).body:
        if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='EXPECTED'for t in n.targets):
            assert isinstance(n.value,ast.Dict)
            return {ast.literal_eval(k):v for k,v in zip(n.value.keys,n.value.values)}
    return {}

caller_updates=[]
for path,row in changes.items():
    if not path.endswith('.py')or row['before_content']is None:continue
    a,b=[expected_entries(row[s+'_content'])for s in ('before','after')]
    assert a.keys()==b.keys()
    for key in a:
        if ast.dump(a[key],include_attributes=False)==ast.dump(b[key],include_attributes=False):continue
        av,bv=ast.literal_eval(a[key]),ast.literal_eval(b[key])
        assert tuple(av)==tuple(oldb[key]['product_callers'])
        assert tuple(bv)==tuple(newb[key]['product_callers'])
        caller_updates.append({'path':path,'boundary':key,'before':av,'after':bv})
assert len(caller_updates)==26

byte_review=json.loads((OUT/'STATIC_BYTE_AST_TOML_REVIEW.json').read_text())
binding_path=FROZEN/'baseline-addendum/CANONICAL_QA_BASELINE_BINDING.json'
directory_path=FROZEN/'baseline-addendum/CANONICAL_QA_DIRECTORY_GET.original.json'
binding_body=binding_path.read_bytes();directory_body=directory_path.read_bytes()
assert pin(binding_body)['git_blob']=='527c4fdd3d439d614103faca3c2956ceb89e6d59'
assert pin(directory_body)['git_blob']=='c3f0a395046a4cdb77eec358fae07b75f5b76852'
directory=json.loads(directory_body);assert directory['isError']is False
assert directory['structuredContent']['url'].endswith('?ref=cc57c7198db6293ccca562253c42fffbe2a04633')
entries=json.loads(directory['structuredContent']['content']);index={r['path']:r for r in entries if r['type']=='file'and r['name'].startswith('test_')and r['name'].endswith('.py')}
assert len(index)==63
for row in byte_review['old_qa']['files']:
    assert index[row['path']]['sha']==row['canonical']['git_blob']
    assert index[row['path']]['size']==row['canonical']['bytes']
    if row['path'].endswith('test_resident_root_source_closure.py'):
        assert row['layer_preimage']['git_blob']=='8223265bdcea271661fd46d448943484a28d5703'

projection_script=(OUT/'review_scope_closure.py').read_text()
namespace={}
prefix=projection_script.split('path_rows=[];gaps=[];all_spans={};attack_rows=[]')[0]
exec(compile(prefix,'our_review_projection_initialization','exec'),namespace)
lexical_view=namespace['lexical_view'];select=namespace['select']
scope_updates=json.loads((OUT/'OLD_QA_CONSTANT_REVIEW.json').read_text())['scope_updates']
assert len(scope_updates)==5
for row in scope_updates:
    for side,root in [('before',BASE/'before'),('after',BASE/'view-root86')]:
        code,raw,depths,removed=lexical_view((root/row['path']).read_text())
        start,end=select(code,depths,row[side]['selector'])
        assert hashlib.sha256(code[start:end].encode()).hexdigest()==row[side]['masked_sha256']

methods=byte_review['old_qa']['changed_functions'];method_changes=[]
def find_method(text,name):
    for n in ast.walk(ast.parse(text)):
        if isinstance(n,ast.FunctionDef)and n.name==name:return ast.get_source_segment(text,n)
    raise AssertionError(name)
for item in methods:
    row=changes[item['path']];name=item['qualified_name'][-1]
    before,after=[find_method(row[s+'_content'],name)for s in ('before','after')]
    if name=='test_new_typed_edges_and_old_boundary_inventory_are_exact':
        expected=before.replace('len(boundaries), 569','len(boundaries), 621').replace('["boundary"][-28:]','["boundary"][541:569]')
        assert expected==after
        old_assign={t.id:ast.literal_eval(n.value)for n in ast.parse(row['before_content']).body if isinstance(n,ast.Assign)for t in n.targets if isinstance(t,ast.Name)and t.id=='ORDINARY_NEW_BOUNDARIES'}
        new_assign={t.id:ast.literal_eval(n.value)for n in ast.parse(row['after_content']).body if isinstance(n,ast.Assign)for t in n.targets if isinstance(t,ast.Name)and t.id=='ORDINARY_NEW_BOUNDARIES'}
        assert old_assign['ORDINARY_NEW_BOUNDARIES']==old['boundary'][541:569]
        assert new_assign['ORDINARY_NEW_BOUNDARIES']==new['boundary'][541:569]
        assert [r['id']for r in old_assign['ORDINARY_NEW_BOUNDARIES']]==[r['id']for r in new_assign['ORDINARY_NEW_BOUNDARIES']]
        method_changes.append({'method':name,'exact_two_text_replacements':True,'original28_identity_order_preserved':True})
        continue
    bt,at=[ast.parse(textwrap.dedent(s))for s in (before,after)]
    bc,ac=[[n for n in ast.walk(t)if isinstance(n,ast.Constant)]for t in (bt,at)]
    assert len(bc)==len(ac)
    delta=[]
    for x,y in zip(bc,ac):
        if x.value!=y.value:
            assert isinstance(x.value,str)and isinstance(y.value,str)
            delta.append({'before':x.value,'after':y.value});y.value=x.value
    assert ast.dump(bt,include_attributes=False)==ast.dump(at,include_attributes=False)
    assert len(delta)==(2 if name.startswith('test_both_live')else 1)
    source_name='circuit_next_use_receipt_owner.rs'if name.startswith('test_both_live')else'circuit_evaluated_next_use_command_service.rs'
    function='predecessors'if name.startswith('test_both_live')else'observe_original'
    src=(BASE/'view-root86/codex-rs/hepta-agentd/src'/source_name).read_text();code,_,_,_=lexical_view(src)
    span=namespace['scope_ns']['ordinary_select_scope'](namespace['proof'],code,{'kind':'unique_function','name':function})
    for d in delta:
        pattern=r'\s*'.join(re.escape(x)for x in re.findall(r'\w+|[^\w\s]',d['after']))
        assert re.search(pattern,code[span['start']:span['end']]),d
    method_changes.append({'method':name,'only_string_constants_changed':delta,'all_other_ast_equal':True,'new_markers_present_in_real_original_function':True,'actual_source':pin(src.encode())})

rule_changes=[]
for i,(a,b)in enumerate(zip(old['protected_file'],new['protected_file'])):
    if a==b:continue
    aa,bb=a.get('required_function_order',[]),b.get('required_function_order',[])
    oldnames=[r['function']for r in aa];newnames=[r['function']for r in bb]
    assert all(n in newnames for n in oldnames)
    rule_changes.append({'index':i,'path':a['path'],'all_old_function_names_retained':True,'changed_original_function_guards':[r['function']for r in aa if r not in bb],'added_function_guards':[n for n in newnames if n not in oldnames]})

encoding_body=(FROZEN/'ENCODING_MANIFEST.json').read_bytes();assert pin(encoding_body)['git_blob']=='3a34227fd9af96f99f4dd81cd24793cadca2ec95'
encoding=json.loads(encoding_body)['items'][0];joined=[];part_pins=[]
for part in encoding['parts']:
    body=(FROZEN/part['name']).read_bytes();assert pin(body)=={k:part['encoded'][k]for k in ('bytes','sha256','git_blob')}
    assert body.endswith(b'\n')and body.count(b'\n')==1
    raw=base64.b64decode(body[:-1],validate=True);assert pin(raw)==part['decoded'];assert base64.b64encode(raw)+b'\n'==body
    joined.append(raw);part_pins.append(pin(body))
z=b''.join(joined);assert pin(z)==encoding['gzip'];assert gzip.decompress(z)==packet_raw

result={'status':'STATIC_MIGRATION_AND_SOURCE_BINDING_REVIEW_NO_QA_EXECUTION','packet':pin(packet_raw),'canonical_qa_directory_sdk':pin(directory_body),'canonical_qa_binding':pin(binding_body),'canonical_qa_count_and_all_local_body_sha_match':63,'root_qa_preimage_is_prepared822326':True,'caller_constant_updates_exact':caller_updates,'old_scope_hash_updates_recomputed':scope_updates,'three_method_migrations':method_changes,'function_guard_names_preserved':rule_changes,'three_original_git_parts':part_pins,'strict_local_reconstruction_matches_complete_packet':True,'direct_packet_get_not_claimed':True,'candidate_imports':0,'candidate_functions_executed':0,'qa_methods_executed':0,'new_scope_checks':'Only unchanged original lexical/scope helpers loaded and used on fixed partial source bytes, not candidate tests or complete source scanner.'}
target=OUT/'LEGACY_MIGRATION_AND_SOURCE_BINDING_REVIEW.json';target.open('x').write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'output':str(target),'pin':pin(target.read_bytes()),'qa_files':63,'caller_constants':len(caller_updates),'scope_hashes':len(scope_updates),'migrated_methods':len(method_changes),'function_guard_name_losses':0,'strict_packet_reconstruction':True,'candidate_or_qa_executions':0}))
