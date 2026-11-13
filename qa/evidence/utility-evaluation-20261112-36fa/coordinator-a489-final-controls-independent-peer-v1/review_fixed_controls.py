"""Pure byte/AST/record-data review. Never imports a native control module.

The one new record predicate is extracted and invoked against an in-memory
adapter containing previously retrieved immutable original files. Its writes
are dictionary entries. Native prepare/apply/main/stage/lock/filesystem code is
only inspected, not called. No source or author's file is modified.
"""
from __future__ import annotations
import ast,base64,copy,gzip,hashlib,json,pathlib,re,sys,types
from pathlib import Path

HERE=Path(__file__).resolve().parent
PREP=Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
CANON=Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1')
RUNTIME=Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
RECOVERY=Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
MAINT=Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1/driver-maintenance.HOLD.py')
FENCES=Path('/tmp/hepta-36fa-coordinator-a489-final-fences-independent-peer-v1')

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def pin(raw,p):
    assert identity(raw)==p,(identity(raw),p)

def functions(raw):
    lines=raw.splitlines(keepends=True)
    return {n.name:(b''.join(lines[n.lineno-1:n.end_lineno]),n) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}

def pure_data(raw):
    definitions={n.targets[0].id:n.value for n in ast.parse(raw).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    values={}
    def value(node):
        if isinstance(node,ast.Constant):return node.value
        if isinstance(node,ast.Name):
            if node.id not in values:values[node.id]=value(definitions[node.id])
            return values[node.id]
        if isinstance(node,ast.Dict):return {value(k):value(v) for k,v in zip(node.keys,node.values)}
        if isinstance(node,ast.List):return [value(v) for v in node.elts]
        if isinstance(node,ast.Tuple):return tuple(value(v) for v in node.elts)
        if isinstance(node,ast.BinOp):
            a,b=value(node.left),value(node.right)
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div) and isinstance(a,Path) and isinstance(b,str):return a/b
            if isinstance(node.op,ast.Add) and isinstance(a,str) and isinstance(b,str):return a+b
        if isinstance(node,ast.Call) and not node.keywords and len(node.args)==1:
            if isinstance(node.func,ast.Name) and node.func.id=='Path':return Path(value(node.args[0]))
            if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and (node.func.value.id,node.func.attr)==('pathlib','Path'):return Path(value(node.args[0]))
        raise ValueError('not a supported constant expression: '+ast.dump(node))
    return definitions,value

def write(name,obj):
    raw=(json.dumps(obj,sort_keys=True,indent=2)+'\n').encode();p=HERE/name
    if p.exists():assert p.read_bytes()==raw
    else:
        with p.open('xb') as f:f.write(raw)
    return identity(raw)

def main():
    driver=(HERE/'inputs/driver27.HOLD.py').read_bytes();assert driver==(PREP/'driver.HOLD.py').read_bytes()
    assert identity(driver)['git_blob']=='27c0db4e4bceb69bcaafc97f5cc843a37b180941'
    original=(PREP/'inputs/ORIGINAL_NONRUST_FMT_080753.py').read_bytes();assert identity(original)['git_blob']=='080753bf6fa5070c0f71096ace0cf199762ee42c'
    maintenance=MAINT.read_bytes();assert identity(maintenance)['git_blob']=='59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'
    nf,of=functions(driver),functions(original)
    same=['identity','first_read','lock_identity','apply_packet','retain_terminal','main']
    for name in same:assert nf[name][0]==of[name][0] and ast.dump(nf[name][1],include_attributes=False)==ast.dump(of[name][1],include_attributes=False)
    assert set(nf)==(set(of)-{'prove_actual_capture'})|{'prove_actual_maintenance'}
    for name in set(nf)&set(of)-set(same):assert name in ('module_from_original','prepare')
    definitions,resolve=pure_data(driver)
    needed=['EVIDENCE','CONTROL','CONFIG','OUT','LOCK','LOCK_ID','MAINTENANCE','MAINTENANCE_CONFIG','MAINTENANCE_RUN','MAINTENANCE_JOB','MAINTENANCE_PIN','MAINTENANCE_CONFIG_PIN','MAINTENANCE_RESULT_PIN','MAINTENANCE_NORMAL_PIN','MAINTENANCE_GIT_PIN','MAINTENANCE_ARTIFACTS_PIN','MAINTENANCE_INPUTS_PIN','MAINTENANCE_LEASE_PIN','BASELINE','BASELINE_GZIP_PIN','MAINTENANCE_METADATA_GZIP_PIN','MAINTENANCE_METADATA_PIN','BASELINE_TREE','LEAVES','NONRUST_PATHS','PREFLIGHT_SECONDS','RECORD_SECONDS','FMT_SECONDS']
    data={k:resolve(definitions[k]) for k in needed}
    assert (data['PREFLIGHT_SECONDS'],data['FMT_SECONDS'],data['RECORD_SECONDS'])==(600,900,300)
    assert data['MAINTENANCE_PIN']==identity(maintenance) and data['LEAVES']==15243
    exact_paths=('.github/blob-size-allowlist.txt','CALLERS.toml','qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json','qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py')
    assert data['NONRUST_PATHS']==exact_paths
    preparetext=nf['prepare'][0].decode()
    assert 'paths == control[\'allowed_paths\'] == list(NONRUST_PATHS)' in preparetext and 'and set(paths) == safe' in preparetext
    assert "row['path'] in NONRUST_PATHS" in preparetext
    assert "startswith('qa/b4-no-bypass/')" not in preparetext and "endswith('.py')" not in preparetext
    assert 'm.initial_inventory = m.inventory_module.inventory(m.REPO)' in preparetext
    assert "m.check(m.initial_git_metadata == old_metadata" in preparetext
    calls=[n for n in ast.walk(ast.parse(driver)) if isinstance(n,ast.Call)]
    forbidden=[]
    for call in calls:
        f=call.func
        if isinstance(f,ast.Attribute) and isinstance(f.value,ast.Name) and f.value.id=='m' and f.attr in ('main','initial_preflight','validate_config'):
            forbidden.append(f.attr)
    assert forbidden==[]
    stages=[n for n in calls if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='m' and n.func.attr=='stage']
    assert len(stages)==1 and ast.literal_eval(stages[0].args[0])=='fmt'
    assert isinstance(stages[0].args[1],ast.Attribute) and stages[0].args[1].attr=='FMT'
    assert isinstance(stages[0].args[2],ast.Name) and stages[0].args[2].id=='FMT_SECONDS'
    # The strict producer/consumer packet maps exactly to independently reviewed
    # full source proposal bodies; no schema widening or extra target is needed.
    strictraw=(HERE/'inputs/NONRUST_PACKET.exact.json').read_bytes();strict=json.loads(strictraw)
    assert identity(strictraw)['git_blob']=='ab032ffdfd8b540a0d3a82558d8a07e70ab0c548'
    assert set(strict)=={'format','source_identity','base_inventory','base_physical_tree','changes','expected_after_leaf_count','expected_after_physical_tree'}
    assert strict['format']=='hepta-reviewed-nonrust-source-apply-v1'
    proposal=json.loads((FENCES/'inputs/SOURCE_PACKET.exact_from_full_get.json').read_bytes())
    assert [r['path'] for r in strict['changes']]==list(exact_paths)
    assert strict['source_identity']==proposal['source_identity']
    for key in ('base_inventory','base_physical_tree','expected_after_leaf_count','expected_after_physical_tree'):assert strict[key]==proposal[key]
    mapping=[]
    for s,p in zip(strict['changes'],proposal['changes']):
        assert set(s)=={'path','mode','before','after','after_base64'} and s['path']==p['path'] and s['mode']=='100644'
        for side in ('before','after'):
            expected={k:p[side][k] for k in ('bytes','sha256')};expected['git_blob']=p[side]['working_blob'];assert s[side]==expected
        after=base64.b64decode(s['after_base64'],validate=True)
        assert after==base64.b64decode(p['after_raw_base64'],validate=True);pin(after,s['after'])
        mapping.append({k:s[k] for k in ('path','mode','before','after')})
    # Extract only definition code for the immutable original record helpers.
    mdefs,mresolve=pure_data(maintenance)
    constants={k:mresolve(mdefs[k]) for k in ['REPO','TARGET','HEAD','TREE','PARENTS','FIX','FIX_SECONDS','FMT','MAXIMUM_LOG_BYTES']}
    assert constants['FIX_SECONDS']==7200
    assert constants['FMT']==['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f']
    pure_names={'check','sha256','oid','nodup','parse','pin_bytes','parse_supervisor'}
    nodes=[n for n in ast.parse(maintenance).body if isinstance(n,ast.FunctionDef) and n.name in pure_names]
    assert {n.name for n in nodes}==pure_names
    class PurePredicateFailure(Exception):pass
    pure={'json':json,'hashlib':hashlib,'PreconditionError':PurePredicateFailure,'IntegrityError':PurePredicateFailure}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<immutable-original-record-helpers>','exec'),pure)
    namespace={**data,'gzip':gzip}
    exec(compile(ast.Module(body=[nf['prove_actual_maintenance'][1]],type_ignores=[]),'<fixed-new-record-predicate>','exec'),namespace)
    prefix=str(data['MAINTENANCE_RUN']);memory={}
    for name in ['RESULT.json','final.git-state.json','ARTIFACTS.json','INPUT_IDENTITIES.json','SOURCE_GIT_METADATA.after.json.gz']:
        memory[prefix+'/'+name]=(RUNTIME/name).read_bytes()
    memory[str(data['CONTROL']/'MAINTENANCE_NORMAL.original.json')]=(RUNTIME/'STATUS_06.original.json').read_bytes()
    memory[str(data['EVIDENCE']/'SOURCE_COORDINATION_EX.json')]=(RUNTIME/'SOURCE_COORDINATION_EX.json').read_bytes()
    parts=sorted((RECOVERY/'final-inventory-parts').glob('final.inventory.json.gz.part-*.b64'));assert len(parts)==5
    inventory_gzip=b''.join(base64.b64decode(p.read_bytes().rstrip(b'\n'),validate=True) for p in parts)
    pin(inventory_gzip,data['BASELINE_GZIP_PIN']);memory[prefix+'/final.inventory.json.gz']=inventory_gzip
    reads=[];writes={}
    def read_only_memory(path,pinvalue):
        body=memory[str(path)];pin(body,pinvalue);reads.append({'path':str(path),**identity(body)});return body
    def write_only_memory(name,body):
        assert name not in writes;writes[name]=body;return identity(body)
    m=types.SimpleNamespace(**constants,**{k:pure[k] for k in pure_names},read_input=read_only_memory,write=write_only_memory,gzrecord=write_only_memory)
    result,snapshot,git_state,metadata=namespace['prove_actual_maintenance'](m)
    assert len(reads)==len({r['path'] for r in reads})==len(writes)==8
    assert result==json.loads(memory[prefix+'/RESULT.json']) and snapshot==json.loads(gzip.decompress(inventory_gzip))
    assert gzip.decompress(inventory_gzip)==(RECOVERY/'final.inventory.exact_recovered.json').read_bytes()
    pin(metadata,data['MAINTENANCE_METADATA_PIN'])
    assert snapshot['source']==strict['source_identity']
    assert data['BASELINE']==strict['base_inventory'] and data['BASELINE_TREE']==strict['base_physical_tree']
    json_target=next(r for r in mapping if r['path'].endswith('.json'))
    assert json_target['path']=='qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'
    # Frozen HOLD launch: full typed object, all decoded bytes, and complete
    # bootstrap inverse; this is deliberately not an execution approval.
    launch=PREP/'launch-hold-v1';bootstrap=(launch/'ACTUAL_BOOTSTRAP.HOLD.py').read_bytes();bootold=(PREP/'inputs/ORIGINAL_9101_BOOTSTRAP.py').read_bytes()
    assert identity(bootold)['git_blob']=='9ca752893983b582f2394c054e92a0adc265cb8f'
    oldlines=bootold.splitlines(keepends=True);newlines=bootstrap.splitlines(keepends=True)
    restored=bootstrap
    for name in ['BASE','PINS']:
        oldline=[x for x in oldlines if x.startswith((name+' = ').encode())];newline=[x for x in newlines if x.startswith((name+' = ').encode())]
        assert len(oldline)==len(newline)==1 and restored.count(newline[0])==1
        restored=restored.replace(newline[0],oldline[0],1)
    assert restored==bootold
    for name in ['check','identity','real_parents','retain']:assert functions(bootstrap)[name][0]==functions(bootold)[name][0]
    bdefs,bresolve=pure_data(bootstrap);pins=bresolve(bdefs['PINS']);base=bresolve(bdefs['BASE'])
    assert base==data['CONTROL'] and set(pins)=={'driver.py','APPROVED_CONFIG.json','NONRUST_PACKET.json','MAINTENANCE_NORMAL.original.json'}
    typedraw=(launch/'ACTUAL_PROCESS_INPUT.HOLD.json').read_bytes();typed=json.loads(typedraw)
    assert set(typed)=={'args','cwd','executable','host','idempotency_key','stdin','timeout_seconds'}
    assert typed['host']=='desktop' and typed['cwd']=='/home/qian-qi' and typed['executable']=='/usr/bin/python3'
    assert typed['args']==['-B','-c',bootstrap.decode()] and typed['timeout_seconds']==2100
    stdinraw=(launch/'ACTUAL_STDIN.HOLD.json').read_bytes();assert typed['stdin'].encode()==stdinraw
    assert len(typedraw)<=1048576 and len(stdinraw)<=1048576
    stdin=json.loads(stdinraw);assert set(stdin)=={'format','files'} and stdin['format']=='hepta-final-nonrust-format-bootstrap-v1'
    assert set(stdin['files'])==set(pins)
    decoded={}
    for name,encoded in stdin['files'].items():
        raw=base64.b64decode(encoded,validate=True)
        if name=='NONRUST_PACKET.json':raw=gzip.decompress(raw)
        pin(raw,pins[name]);decoded[name]=raw
    assert decoded['driver.py']==driver and decoded['NONRUST_PACKET.json']==strictraw
    assert decoded['MAINTENANCE_NORMAL.original.json']==memory[str(data['CONTROL']/'MAINTENANCE_NORMAL.original.json')]
    config=json.loads(decoded['APPROVED_CONFIG.json']);assert decoded['APPROVED_CONFIG.json']==(launch/'APPROVED_CONFIG.HOLD.json').read_bytes()
    assert config['root_execution_approved'] is False and config['status']=='HOLD_ROOT_EXACT_REVIEW_REQUIRED'
    assert config['nonrust_packet']==identity(strictraw) and config['driver']==identity(driver)
    assert config['allowed_paths']==list(exact_paths) and config['outer_seconds']==2100
    assert config['fix_authorized'] is config['test_commands_authorized'] is config['ref_updates_authorized'] is False
    assert 'fcntl' not in bootstrap.decode() and 'flock' not in bootstrap.decode()
    assert len([n for n in ast.walk(nf['main'][1]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='flock'])==1
    # Canonical driver is a separate future HOLD. Exactly seven constant
    # substitutions, not a present source alignment or ready actual proof.
    canonical=(HERE/'inputs/canonical-e8.HOLD.py').read_bytes();c_old=(PREP/'inputs/ORIGINAL_CANONICAL_765ADA.py').read_bytes()
    assert identity(c_old)['git_blob']=='765ada67a33f4d9aeaf29c9c522898057083cafb'
    replacements=json.loads((CANON/'EXACT_CONSTANT_SUBSTITUTIONS.json').read_bytes())['substitutions'];assert len(replacements)==7
    inverse=canonical
    for r in replacements:
        assert inverse.count(r['after'].encode())==1;inverse=inverse.replace(r['after'].encode(),r['before'].encode(),1)
    assert inverse==c_old
    cf,co=functions(canonical),functions(c_old);assert cf.keys()==co.keys() and len(cf)==46
    for name in cf:assert cf[name][0]==co[name][0]
    waiting=json.loads((CANON/'WAITING_CONFIG.json').read_bytes())
    assert waiting['root_execution_approved'] is False and waiting['actual_final_postimages_reviewed'] is False
    for key in ['after_commit','after_inventory','after_parents','after_tree','before_inventory','canonical_object_count','canonical_packet','expected_before_git_state','reviewed_formatter_changed_paths']:assert waiting[key] is None
    assert (waiting['action_seconds'],waiting['record_seconds'],waiting['outer_seconds'])==(600,180,900)
    # Whole imported module is unchanged, the thin module overrides only its
    # output/record/result bookkeeping. No inherited EX descriptor is staged.
    out={
      'format':'hepta-final-nonrust-canonical-control-independent-static-proof-v1',
      'driver':identity(driver),'original_thin':identity(original),'unchanged_functions':same,
      'unchanged_function_pins':{name:identity(nf[name][0]) for name in same},
      'adapted_functions':['module_from_original','prepare'],'proof_function_replacement':['prove_actual_capture','prove_actual_maintenance'],
      'original_maintenance_module':identity(maintenance),'imported_main_preflight_validate_config_calls':forbidden,
      'only_stage_call':'fmt / original m.FMT / 900','budgets':{'preflight_apply':600,'records':300,'fmt':900,'outer':2100},
      'strict_packet':identity(strictraw),'strict_packet_complete_mapping_to_reviewed_source_proposal':mapping,
      'new_JSON_write_target_requires_explicit_approval':json_target,'not_pure_subset_of_historical_safe_rule':True,
      'generic_qa_python_write_allowance_removed':True,'literal_targets_only':list(exact_paths),
      'pure_actual_producer_predicate':{'input_reads':reads,'all_eight_actual_record_pins_match':True,'record_writes_are_memory_only':sorted(writes),'result_and_inventory_returned_equal':True,'metadata_original_bytes_preserved':identity(metadata),'no_live_native_source_read_or_module_import':True},
      'HOLD_launch':{'typed':identity(typedraw),'bootstrap':identity(bootstrap),'original_bootstrap':identity(bootold),'stdin':identity(stdinraw),'config':identity(decoded['APPROVED_CONFIG.json']),'decoded_four_inputs':pins,'seven_fields':sorted(typed),'idempotency_key':typed['idempotency_key'],'no_env':True,'full_inverse_BASE_PINS_only':True,'unique_EX_owner':'unchanged thin main; bootstrap does not hold a lock','approved':False},
      'canonical_future_HOLD':{'driver':identity(canonical),'original':identity(c_old),'seven_substitutions':replacements,'46_function_bodies_equal':True,'all_future_actual_proofs_still_null':True,'budgets':{'action':600,'records':180,'outer':900},'execution_approved':False},
      'H_calls':0,'project_gates_or_Rust_executions':0,'native_control_entry_points_executed':0,'source_or_ref_mutations':0,'qualification':False,
      'limits':['The record predicate ran only against fixed bytes in memory, not current native source/environment/locks.','The HOLD launch would fail its approval predicate; no dispatch is authorized by this review.','A later two-field approved candidate and its exact stdin/bootstrap/request need final byte binding.','Canonical alignment cannot be performed until the actual final-format result, complete inventory/Git and immutable canonical packet are independently bound.']}
    resultpin=write('FROZEN_CONTROL_BYTE_AND_DATAFLOW.json',out)
    print(json.dumps({'output':str(HERE/'FROZEN_CONTROL_BYTE_AND_DATAFLOW.json'),**resultpin,'unmodified_thin_functions':6,'actual_records':8,'paths':4,'canonical_functions':46,'H_calls':0,'approval':False}))

if __name__=='__main__':main()
