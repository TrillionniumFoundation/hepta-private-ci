"""Captured-byte and Python AST inspection only; never imports candidate QA/collector."""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import re
import textwrap
import tomllib

D = Path('/tmp/hepta-36fa-e1-registration-independent-peer-v1')
B = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
P = B/'registration-proposal-v1'
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')

def pin(raw):
    if isinstance(raw,str): raw=raw.encode()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def fail(condition,message):
    if not condition: raise AssertionError(message)

def functions(text):
    lines=text.splitlines(keepends=True)
    out={}
    def walk(nodes,prefix=''):
        for node in nodes:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                key=prefix+node.name
                start=min([node.lineno]+[d.lineno for d in node.decorator_list])-1
                out[key]=''.join(lines[start:node.end_lineno])
                walk(node.body,key+'.')
            elif isinstance(node,ast.ClassDef):walk(node.body,prefix+node.name+'.')
    walk(ast.parse(text).body)
    return out

def assignment(text,name):
    found=[]
    for node in ast.parse(text).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            found.append(ast.literal_eval(node.value))
    fail(len(found)==1,'unique literal assignment '+name)
    return found[0]

inventory=json.loads(I.read_bytes())
baseline={r['path']:r for r in inventory['files']}
source_packet=json.loads((B/'assembled-source-v1/SOURCE_PACKET.json').read_bytes())
sources={r['path']:r['after'] for r in source_packet['images']}
import_packet=json.loads((B/'request-type-import-increment-v1/SOURCE_PACKET.json').read_bytes())
for r in import_packet['images']:
    fail(sources[r['path']]==r['before'],'import predecessor')
    sources[r['path']]=r['after']

packet_raw=(P/'SOURCE_PACKET.json').read_bytes()
packet=json.loads(packet_raw)
manifest=json.loads((P/'MANIFEST.json').read_bytes())
review=json.loads((P/'REVIEW.json').read_bytes())
fail(packet['review']==review,'embedded review')
images={r['path']:r for r in packet['images']}
fail(len(images)==len(packet['images'])==6,'six unique registry paths')
fail(set(images)=={r['path'] for r in manifest['entries']},'manifest exact paths')
file_rows=[]
expected_patch=[]
for row in manifest['entries']:
    path=row['path']; image=images[path]
    fail(row['mode']=='100644','regular mode')
    fail(pin(image['after'])==row['after'],'after pin '+path)
    fail((P/'after'/path).read_text()==image['after'],'after full local '+path)
    if image['before'] is None:
        fail(path not in baseline and row['before'] is None,'new path actually absent')
    else:
        r=baseline[path];p=pin(image['before'])
        fail(p==row['before'],'before manifest pin '+path)
        fail((p['bytes'],p['sha256'],p['git_blob'])==(r['bytes'],r['sha256'],r['working_blob']),'before actual b608 pin '+path)
        fail((P/'before'/path).read_text()==image['before'],'before full local '+path)
    expected_patch.extend(difflib.unified_diff((image['before'] or '').splitlines(True),image['after'].splitlines(True),fromfile='a/'+path if image['before'] is not None else '/dev/null',tofile='b/'+path))
    file_rows.append({'path':path,'before':row['before'],'after':row['after'],'actual_baseline_equal':image['before'] is not None,'new_absent_in_actual_inventory':image['before'] is None})
generated=''.join(expected_patch)
saved_patch=(P/'SOURCE_DELTA.patch').read_text()
# Authors may label a new file a/path rather than /dev/null; this is only a patch label.
alternate=generated.replace('--- /dev/null\n','--- a/qa/b4-no-bypass/ROOT_HOST_INITIAL_PRODUCT_SOURCE_CONTRACT.json\n')
fail(saved_patch in (generated,alternate),'all complete unified patch bytes')

before=tomllib.loads(images['CALLERS.toml']['before'])
after=tomllib.loads(images['CALLERS.toml']['after'])
fail(set(before)==set(after),'no new top-level registry policy field')
unchanged_top=[k for k in before if k not in ['boundary','protected_file','privileged_inventory']]
for k in unchanged_top:fail(before[k]==after[k],'unchanged top-level '+k)
fail(all(v is False for v in after['authority'].values()),'no authority flag')
fail(len(before['boundary'])==633 and len(after['boundary'])==650,'633 to 650 boundary count')
changes=[]
for i,old in enumerate(before['boundary']):
    new=after['boundary'][i]
    if old!=new:
        fail({k:v for k,v in old.items() if k!='product_callers'}=={k:v for k,v in new.items() if k!='product_callers'},'old row only product_callers '+str(i))
        fail(new['product_callers'][:len(old['product_callers'])]==old['product_callers'],'caller prefix '+str(i))
        add=new['product_callers'][len(old['product_callers']):]
        fail(add and len(new['product_callers'])==len(set(new['product_callers'])),'caller append unique')
        for path in add:fail(path in sources and '_tests.rs' not in path,'actual new production caller')
        changes.append({'index':i,'id':old['id'],'symbol':old['symbol'],'appended_callers':add,'old_fields_preserved':True})
fail([x['index'] for x in changes]==[125,134,621,624,625,627,628,629,631],'nine exact old row changes')
new_rows=after['boundary'][633:]
fail(len(new_rows)==17,'17 new boundaries')
fail(len(set(r['id'] for r in after['boundary']))==650,'unique ids')
fail(len(set(r['symbol'] for r in after['boundary']))==650,'unique symbols')
for r in new_rows:
    fail(r.get('receiver_type') and 'call_pattern' not in r,'new original typed receiver schema')
    fail(r['receiver_type']==r['symbol'].split('::')[0],'explicit typed receiver name')
    fail(r['definition_path'] in sources,'actual definition path')
    for m in r['definition_markers']:fail(m in sources[r['definition_path']],'definition marker '+r['id'])
    for p in r['product_callers']:fail(p in sources and '_tests.rs' not in p,'caller product path')
old_ids=before['privileged_inventory']['required_boundary_ids']
new_ids=after['privileged_inventory']['required_boundary_ids']
fail(new_ids==old_ids+[r['id'] for r in new_rows],'closed required inventory exact append')
fail(set(new_ids)=={r['id'] for r in after['boundary']} and len(set(new_ids))==650,'required equals declared')
fail(len(before['protected_file'])==442 and len(after['protected_file'])==451,'442 to 451 protection count')
fail(before['protected_file']==after['protected_file'][:442],'every old complete protected object unchanged')
fail(before['boundary'][541:569]==after['boundary'][541:569],'original 28 ordinary slice')
new_guards=[]
for r in after['protected_file'][442:]:
    fail(set(r)=={'path','required','forbidden'},'new guard schema')
    text=sources[r['path']]
    for m in r['required']:fail(m in text,'new required marker '+r['path'])
    raw_hits=[m for m in r['forbidden'] if m in text]
    fail(not raw_hits,'new forbidden literal even raw absent '+str(raw_hits))
    is_new=r['path'] not in baseline
    if is_new:fail(r['required']==[text],'entire new product body required')
    new_guards.append({'path':r['path'],'required_count':len(r['required']),'required_bytes':[len(m.encode()) for m in r['required']],'new_product_full_body_required':is_new,'forbidden':r['forbidden'],'raw_forbidden_hits':raw_hits})

contract_path='qa/b4-no-bypass/ROOT_HOST_INITIAL_PRODUCT_SOURCE_CONTRACT.json'
contract_raw=images[contract_path]['after'].encode()
contract=json.loads(contract_raw)
fail(contract['new_boundary_rows']==new_rows,'contract exact 17 rows')
fail(contract['old_boundary_additions']==review['old_boundary_changes'],'contract old additions')
for r in contract['old_boundary_additions']:
    fail(r['before']==before['boundary'][r['index']] and r['after']==after['boundary'][r['index']],'contract old row before/after')
fail(contract['original_protected_prefix_count']==442,'contract protected count')
fail(contract['original_protected_prefix_sha256']==hashlib.sha256(canonical(before['protected_file'])).hexdigest(),'complete protected prefix digest')
prod={path:text for path,text in sources.items() if '_tests.rs' not in path}
fail(len(prod)==9 and set(contract['production_files'])==set(prod),'all nine product paths')
for path,text in prod.items():fail(pin(text)==contract['production_files'][path],'whole product source pin '+path)
fail({x['path'] for x in new_guards}==set(prod),'new protection path set exact nine')

workflow='.github/workflows/hepta-daemon-learning-native.yml'
def workflow_python(text):
    marker='          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
    return textwrap.dedent(text.split(marker,1)[1].split('          PY\n',1)[0])
old_parents=assignment(workflow_python(images[workflow]['before']),'parents')
new_parents=assignment(workflow_python(images[workflow]['after']),'parents')
fail(len(old_parents)==48 and len(new_parents)==54 and len(set(new_parents))==54,'48+6 exact parents')
fail(new_parents[:48]==old_parents,'old parents exact order')
appended=new_parents[48:]
fail(appended==contract['root_parents'],'contract parents')
insert=''.join('              '+json.dumps(name)+',\n' for name in appended)
fail(images[workflow]['after'].count(insert)==1,'unique workflow insertion')
fail(images[workflow]['after'].replace(insert,'',1)==images[workflow]['before'],'whole workflow inverse exact')
cases=sources['codex-rs/hepta-agentd/src/authority_host_generation_tests.rs']
method_names=re.findall(r'(?m)^async fn (root_host_initial_\w+)\(',cases)
fail(len(method_names)==6 and [n.rsplit('::',1)[1] for n in appended]==method_names,'actual six Rust methods in order')
ignore='#[ignore = "requires original Root host bind and actual signed owner fixtures"]'
fail(cases.count(ignore)==6,'six actual ignored method attributes')

qa_names=['qa/b4-no-bypass/test_evaluated_published_read_source_closure.py','qa/b4-no-bypass/test_resident_root_source_closure.py']
qa_rows=[]
for name in qa_names:
    old,new=images[name]['before'],images[name]['after']
    old_f,new_f=functions(old),functions(new)
    fail(set(old_f)<=set(new_f),'no removed QA function')
    changed={k:(v,new_f[k]) for k,v in old_f.items() if v!=new_f[k]}
    added=sorted(set(new_f)-set(old_f))
    if name.endswith('test_evaluated_published_read_source_closure.py'):
        expected='EvaluatedOrdinaryRetainedClosureTests.test_new_typed_edges_and_old_boundary_inventory_are_exact'
        fail(set(changed)=={expected} and not added,'only one old evaluated method')
        fail(changed[expected][1].replace('self.assertEqual(len(boundaries), 650)','self.assertEqual(len(boundaries), 633)',1)==changed[expected][0],'old method inverse count-only')
        checked={k:after[k] for k in ['boundary','privileged_inventory','authority','source_roots','ignored_path_fragments']}
        digest=hashlib.sha256(canonical(checked)).hexdigest()
        fail(assignment(new,'ORDINARY_COMPLETE_BOUNDARY_SHA256')==digest,'whole boundary digest exact')
        old_digest=assignment(old,'ORDINARY_COMPLETE_BOUNDARY_SHA256')
        fail(new.replace(digest,old_digest,1).replace('self.assertEqual(len(boundaries), 650)','self.assertEqual(len(boundaries), 633)',1)==old,'whole evaluated QA two literal inverse')
    else:
        expected='ResidentRootSourceClosureTests.test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof'
        fail(set(changed)=={expected},'one old resident method')
        v=changed[expected][1]
        v=v.replace('        self.assertTrue(set(ROOT_HOST_GENERATION_CASES).issubset(parents))\n','',1)
        v=v.replace(' + len(ROOT_HOST_GENERATION_CASES)','',1)
        fail(v==changed[expected][0],'old Root method inverse preserves all prior assertions')
        fail(added==['ResidentRootSourceClosureTests.test_root_host_initial_product_exact_source_and_original_guards','ResidentRootSourceClosureTests.test_root_host_initial_product_parents_keep_the_original_privileged_lane'],'two new QA methods exact')
        fail(assignment(new,'ROOT_HOST_GENERATION_CASES')==appended,'new QA parent constants exact')
        fail(hashlib.sha256(contract_raw).hexdigest() in new_f[added[0]],'new QA contract SHA literal exact')
    qa_rows.append({'path':name,'old_functions':len(old_f),'new_functions':len(new_f),'old_test_methods':sum(k.rsplit('.',1)[-1].startswith('test_') for k in old_f),'new_test_methods':sum(k.rsplit('.',1)[-1].startswith('test_') for k in new_f),'unchanged_old_functions':len(old_f)-len(changed),'changed_old_functions':{k:{'before':pin(v[0]),'after':pin(v[1])} for k,v in changed.items()},'new_functions':added})

allow='.github/blob-size-allowlist.txt'
tail='# Exact isolated Root initial-product registration candidate; no wildcard.\nsha256:'+pin(images['CALLERS.toml']['after'])['sha256']+' CALLERS.toml\n'
fail(images[allow]['after']==images[allow]['before']+tail,'only exact CALLERS hash allowlist append')
collector=(D/'inputs/verify_hepta_callers.original.py').read_bytes()
ci=baseline['scripts/verify_hepta_callers.py']
fail(pin(collector)=={'bytes':ci['bytes'],'sha256':ci['sha256'],'git_blob':ci['working_blob']},'actual original collector')
b92path=Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs/NATIVE_DRIVER_B92.py')
b92=b92path.read_bytes();fail(pin(b92)['git_blob']=='b92ddded4fce78aeb076d022471c62bf81ce2e4f','fixed original native B92')

proof={
 'schema':'hepta.evaluation-audit.e1-registration-captured-byte-proof.v1',
 'status':'STATIC_DATA_AND_AST_EQUALITIES_ONLY_NO_QA_COLLECTOR_RUST_OR_H_EXECUTION',
 'source_packet':pin(packet_raw),'manifest':pin((P/'MANIFEST.json').read_bytes()),'author_review':pin((P/'REVIEW.json').read_bytes()),'patch':pin(saved_patch),
 'actual_baseline_inventory':pin(I.read_bytes()),'six_paths':file_rows,
 'boundary_counts':[633,650],'unchanged_old_boundary_rows':624,'changed_old_rows':changes,'new_boundaries':new_rows,
 'unchanged_top_fields':unchanged_top,'privileged_required_ids_exact_append':True,'all_original_forbidden_and_extra_protection_constraints_equal':True,
 'protected_counts':[442,451],'row411':{'path':before['protected_file'][411]['path'],'complete_object_sha256':hashlib.sha256(canonical(before['protected_file'][411])).hexdigest(),'unchanged':True},
 'old28ordinary_slice_equal':True,'new_guards':new_guards,'contract':pin(contract_raw),'whole_product_pins_equal':contract['production_files'],
 'root_parents':{'old_count':48,'new_count':54,'original_order_prefix_equal':True,'added_actual_method_names':appended,'all_other_workflow_bytes_exact_inverse':True},
 'qa':qa_rows,'complete_boundary_digest':digest,'all_existing_qa_mutation_functions_except_two_exact_inverse_count_selection_methods_equal':True,
 'allowlist_only_fixed_new_callers_sha256':True,
 'collector_original':pin(collector),'b92_original':pin(b92),
 'not_claimed':['No imported or executed original collector, QA or authored preparation scripts','No full Rust typed caller enumeration','No static direct-link evidence of normal daemon caller added','No Rust compilation, formatting, native mechanisms or source-gate result','No Git objects/refs/source mutation by reviewer'],
}
raw=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode()
with (D/'BYTE_PROOF.json').open('xb') as f:f.write(raw)
print(json.dumps({'path':str(D/'BYTE_PROOF.json'),**pin(raw)},ensure_ascii=False))
