"""Pure-data producer/consumer proof, not a native admission or project test.

Only selected original parsing/predicate function definitions are compiled.
Admission.__init__, acquire, finish, live file-stat methods and source/main are
never called. Every file read below is a fixed cloud evidence file.
"""
import ast
import base64
import copy
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

OUT=Path('/tmp/hepta-36fa-final-source-b608-transported-preparation-v1')
RUNTIME=Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def jb(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def put(name,b):
 p=OUT/name
 with p.open('xb') as f:f.write(b)
 return {'name':name,'local_path':str(p),**pin(b)}

admission=(OUT/'inputs/qualification-admission.fd67.selected.py').read_text()
assert pin(admission.encode())['git_blob']=='fd67cb043f7b6cb8cf042104ac202cb5f0842196'
tree=ast.parse(admission);cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Admission')
namespace={'json':json,'re':re,'Path':Path}
constant_names=[]
for node in tree.body:
 if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
  try:value=ast.literal_eval(node.value)
  except (ValueError,TypeError):continue
  namespace[node.targets[0].id]=value;constant_names.append(node.targets[0].id)
nodes=[];selected=[]
for name in ('check','pin_fields','exact_pin'):
 node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
 nodes.append(copy.deepcopy(node));selected.append({'name':name,'source':pin(ast.get_source_segment(admission,node).encode())})
for name in ('_require_complete_bindings','_require_transport_bindings','_load_transport_manifest','_require_transport_staging'):
 node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
 copied=copy.deepcopy(node);copied.decorator_list=[];nodes.append(copied)
 selected.append({'name':'Admission.'+name,'source':pin(ast.get_source_segment(admission,node).encode())})
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<selected-original-pure-predicates>','exec'),namespace)

v5=(RUNTIME/'FILE_005.readback.bin').read_text();v5_tree=ast.parse(v5)
normal_namespace={'json':json};normal_nodes=[];normal_selected=[]
for name in ('check','nodup','parse','parse_supervisor'):
 n=next(n for n in v5_tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
 normal_nodes.append(copy.deepcopy(n));normal_selected.append({'name':name,'source':pin(ast.get_source_segment(v5,n).encode())})
exec(compile(ast.fix_missing_locations(ast.Module(body=normal_nodes,type_ignores=[])),'<original-V5-pure-normal-parser>','exec'),normal_namespace)

hold_raw=(OUT/'actual-binding-hold-v1/QUALIFICATION_CONFIG.HOLD.json').read_bytes();hold=json.loads(hold_raw)
ready_raw=(OUT/'execution-candidate-v1/QUALIFICATION_CONFIG.execution-candidate.json').read_bytes();ready=json.loads(ready_raw)
plan=json.loads((RUNTIME/'FIXED_61_READBACK_PLAN.json').read_bytes())
memory={};observed_rows=[]
for row in plan['remaining_fixed_files']:
 raw=(RUNTIME/f"FILE_{row['number']:03d}.readback.bin").read_bytes()
 assert pin(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')}
 memory[row['path']]=raw;observed_rows.append({'native_path':row['path'],**pin(raw)})
result_path=hold['history_transport']['staging_result_path']
memory[result_path]=(RUNTIME/'STAGING_READBACK.json').read_bytes()
assert pin(memory[result_path])==hold['history_transport']['staging_result']
supervisor_path=hold['history_transport']['staging_supervisor_path']
memory[supervisor_path]=(RUNTIME/'STATUS_01.original.json').read_bytes()
assert pin(memory[supervisor_path])==hold['history_transport']['staging_supervisor']
assert len(memory)==62
assert supervisor_path not in {x['native_path'] for x in observed_rows}
assert all(path.startswith(hold['history_transport']['control']+'/') for path in memory if path!=supervisor_path)
assert all('/.git/' not in path and not path.endswith('.lock') for path in memory)

def run_case(cfg,material):
 reads=[];historical=[];outputs={}
 def read_input(path,expected,maximum=None):
  path=str(path);assert path in material, ('not a fixed memory-only proof input',path)
  raw=material[path]
  assert pin(raw)==expected, ('memory input pin mismatch',path)
  if maximum is not None:assert len(raw)<=maximum
  reads.append({'path':path,**pin(raw)})
  return raw
 def write(name,raw):
  assert name=='TRANSPORT_SUPERVISOR.original.json'
  assert name not in outputs;outputs[name]=pin(raw)
 def jwrite(name,value):
  assert name=='TRANSPORTED_ORIGINAL_PROVENANCE.json'
  assert name not in outputs;outputs[name]=copy.deepcopy(value)
 stub=SimpleNamespace(cfg=copy.deepcopy(cfg))
 stub.m=SimpleNamespace(parse=normal_namespace['parse'],read_input=read_input,
                        parse_supervisor=normal_namespace['parse_supervisor'],write=write,jwrite=jwrite)
 stub._read_transport_file=read_input
 def read(path,expected,label):
  assert label=='TRANSPORT_STAGING.original.json'
  raw=read_input(path,expected);outputs[label]=pin(raw);return normal_namespace['parse'](raw)
 stub.read=read
 namespace['_require_complete_bindings'](stub.cfg)
 namespace['_require_transport_bindings'](stub.cfg)
 stub._history_rows=namespace['_load_transport_manifest'](stub)
 def historical_read(role,old_path,expected):
  row=stub._history_rows[role]
  assert row['original_path']==old_path and row['pin']==expected
  historical.append(role)
  return read_input(row['transport_path'],expected)
 stub._read_historical=historical_read
 namespace['_require_transport_staging'](stub)
 assert historical==namespace['HISTORY_ROLES'] and len(historical)==55
 assert len(reads)==62 and len({x['path'] for x in reads})==62
 assert outputs['TRANSPORTED_ORIGINAL_PROVENANCE.json']['qualification'] is False
 return {'memory_read_count':len(reads),'complete_historical_roles':len(historical),'reads':reads,'memory_only_outputs':outputs}

positive=run_case(hold,memory)
positive_ready=run_case(ready,memory)
assert positive==positive_ready
negative=[]
def reject(label,mutate):
 cfg=copy.deepcopy(ready);values=dict(memory);mutate(cfg,values)
 try:run_case(cfg,values)
 except (AssertionError,ValueError,TypeError,KeyError) as e:
  negative.append({'case':label,'rejected':True,'exception_type':type(e).__name__,'message':str(e)})
 else:raise AssertionError('negative case unexpectedly accepted: '+label)
def replace_receipt(cfg,values,mutate):
 path=cfg['history_transport']['staging_result_path'];v=json.loads(values[path]);mutate(v)
 values[path]=jb(v);cfg['history_transport']['staging_result']=pin(values[path])
def replace_normal(cfg,values,mutate):
 path=cfg['history_transport']['staging_supervisor_path'];v=json.loads(values[path]);terminal=json.loads(v['content'][0]['text']);mutate(terminal)
 v['content'][0]['text']=json.dumps(terminal,indent=2,sort_keys=True)
 values[path]=jb(v);cfg['history_transport']['staging_supervisor']=pin(values[path])
reject('missing actual stage result binding',lambda c,m:c['history_transport'].__setitem__('staging_result',None))
reject('wrong actual stage job',lambda c,m:c['history_transport'].__setitem__('staging_job_id','unrelated-observation'))
reject('wrong future supervisor control path',lambda c,m:c['history_transport'].__setitem__('staging_supervisor_path','/not-the-frozen-control/normal.json'))
reject('changed exact manifest binding',lambda c,m:c['history_transport']['manifest'].__setitem__('bytes',1))
reject('missing one staged file with matching altered receipt pin',lambda c,m:replace_receipt(c,m,lambda v:v['files'].pop()))
reject('source write asserted by staged receipt',lambda c,m:replace_receipt(c,m,lambda v:v.__setitem__('source_writes',True)))
reject('qualification asserted by staged receipt',lambda c,m:replace_receipt(c,m,lambda v:v.__setitem__('qualification',True)))
reject('changed staged file content identity',lambda c,m:replace_receipt(c,m,lambda v:v['files'][5].__setitem__('bytes',1)))
reject('failed supervisor with matching altered normal pin',lambda c,m:replace_normal(c,m,lambda v:v.__setitem__('state','failed')))
reject('non-durable supervisor with matching altered normal pin',lambda c,m:replace_normal(c,m,lambda v:v.__setitem__('output_durable',False)))
reject('wrong supervisor job with matching altered normal pin',lambda c,m:replace_normal(c,m,lambda v:v.__setitem__('job_id','wrong-job')))
manifest=json.loads(memory[hold['history_transport']['manifest_path']]);last=manifest['rows'][-1]['transport_path']
reject('historical original body changed',lambda c,m:m.__setitem__(last,m[last]+b' '))
guard_path=hold['historical_runtime_guard_path']
reject('historical guard changed',lambda c,m:m.__setitem__(guard_path,m[guard_path]+b' '))
report={'schema':'hepta-b608-actual-transport-pure-consumer-proof-v1',
        'selected_admission':pin(admission.encode()),'original_actual_historical_v5':pin(v5.encode()),
        'selected_predicates':selected,'original_normal_parser_definitions':normal_selected,
        'hold':pin(hold_raw),'execution_candidate':pin(ready_raw),'actual_stage_job':hold['history_transport']['staging_job_id'],
        'actual_completed_native_inputs':61,'future_supervisor_path_not_observed':supervisor_path,
        'future_supervisor_bytes_are_actual_original_sdk':pin(memory[supervisor_path]),
        'future_supervisor_is_exact_eighth_bootstrap_payload':True,
        'hold_and_ready_transport_predicates_accept_same_actual_proof':True,'positive_result':positive,
        'negative_case_count':len(negative),'negative_cases':negative,
        'memory_adapters':'Exact fixed-path/pin reads and output capture only; no native file opens or lstat; no claim to have executed those live guards.',
        'not_executed':['Admission.__init__','acquire','finish','source wrapper','native wrapper','live V5 preflight','source/Git/material/lock observation','source/native project tests'],
        'qualification':False,'new_h_calls':0,'root_exact_approval_required':True,
        'script':pin((OUT/'verify_actual_stage_binding.py').read_bytes())}
row=put('ACTUAL_TRANSPORT_PRODUCER_CONSUMER_PROOF.json',jb(report))
print(json.dumps(row))
