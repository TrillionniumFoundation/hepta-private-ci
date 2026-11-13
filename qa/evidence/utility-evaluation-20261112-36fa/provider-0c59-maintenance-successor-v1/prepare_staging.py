#!/usr/bin/env python3
"""Prepare exact create-only control staging bytes. Does not execute the staged code."""
import ast,base64,difflib,hashlib,json
from pathlib import Path
ROOT=Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1')
OLD=Path('/tmp/hepta-36fa-new-source-materializer-hold-v1/MATERIALIZATION_BOOTSTRAP.candidate.py')
BASE='/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def jbytes(x):return (json.dumps(x,ensure_ascii=False,indent=2)+'\n').encode()

def save(name,b):
    p=ROOT/name
    if p.exists():assert p.read_bytes()==b,'never replace a frozen file: '+name
    else:p.write_bytes(b)
    return {'name':name,'path':str(p),**pin(b)}

def once(s,a,b):
    assert s.count(a)==1,(a,s.count(a))
    return s.replace(a,b,1)

source_files={
 'driver-maintenance.py':ROOT/'driver-maintenance.HOLD.py',
 'APPROVED_MAINTENANCE_CONFIG.json':ROOT/'MAINTENANCE_CONFIG.HOLD.json',
 'inventory-driver.original.py':Path('/tmp/hepta-36fa-full-candidate-graph-v1/inputs/INVENTORY_DRIVER_5118.original.py'),
 'MAINTENANCE_STARTED.original.json':ROOT/'inputs/MAINTENANCE_STARTED.original.json',
 'MATERIALIZATION_SUPERVISOR.original.json':ROOT/'inputs/MATERIALIZATION_SUPERVISOR.original.json',
 'V8_RESTORATION_SUPERVISOR.original.json':ROOT/'inputs/RESTORE_V3_NORMAL.original.json'}
files={k:p.read_bytes() for k,p in source_files.items()}
pins={k:pin(b) for k,b in files.items()}
original=OLD.read_text()
save('inputs/STAGING_TEMPLATE.original.py',original.encode())
tree=ast.parse(original)
definitions={n.name:ast.get_source_segment(original,n) for n in tree.body if isinstance(n,ast.FunctionDef)}
code=original
for key,value in [('BASE','pathlib.Path('+repr(BASE)+')'),('PINS',repr(pins))]:
    n=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==key for t in n.targets))
    code=once(code,ast.get_source_segment(original,n),key+' = '+value)
code=once(code,"packet['format'] == 'hepta-complete-candidate-materialization-bootstrap-v1'",
          "packet['format'] == 'hepta-original-maintenance-control-staging-v1'")
code=once(code,"'exact five input files'","'exact six input files'")
begin=code.index("        if name == 'MATERIALIZATION_PACKET.json':\n")
end=code.index("        check(identity(raw) == pin",begin)
code=code[:begin]+code[end:]
code=once(code,"'hepta-complete-candidate-materialization-bootstrap-readback-v1'",
          "'hepta-original-maintenance-control-staging-readback-v1'")
code=once(code,"'fixed_candidate_materialization_bootstrap_verified'","'fixed_maintenance_controls_staged_only'")
code=once(code,"    os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(BASE / 'driver.py')])\n",
          "    # Staging ends here. The separately reviewed original EX launcher is the only maintenance entry.\n")
ast.parse(code);compile(code,'STAGING_BOOTSTRAP.HOLD.py','exec')
new_defs={n.name:ast.get_source_segment(code,n) for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)}
assert new_defs==definitions and len(definitions)==4
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('execv','execve','system') for n in ast.walk(ast.parse(code)))
payload={'format':'hepta-original-maintenance-control-staging-v1',
         'files':{k:base64.b64encode(b).decode() for k,b in files.items()}}
payload_bytes=jbytes(payload)
assert len(payload_bytes)<1048576
for k,encoded in payload['files'].items():assert base64.b64decode(encoded,validate=True)==files[k]
bootstrap=save('STAGING_BOOTSTRAP.HOLD.py',code.encode())
payload_info=save('STAGING_PAYLOAD.HOLD.json',payload_bytes)
typed={'host':'desktop','executable':'/usr/bin/python3','args':['-B','-c',code],
       'cwd':'/home/qian-qi','timeout_seconds':900,
       'idempotency_key':'hepta-utility-36fa-provider-0c59-maintenance-control-staging-v1',
       'stdin':payload_bytes.decode()}
typed_info=save('STAGING_REQUEST.HOLD.json',jbytes(typed))
save('STAGING_FROM_MATERIALIZER_BOOTSTRAP.diff',''.join(difflib.unified_diff(
 original.splitlines(True),code.splitlines(True),fromfile='actual-materializer/BOOTSTRAP.py',
 tofile='stage-only/STAGING_BOOTSTRAP.HOLD.py')).encode())
contract={
 'format':'hepta-maintenance-control-staging-contract-v1','status':'HOLD_UNAPPROVED',
 'base':BASE,'operation':'create only six external controls; no maintenance/source or lock operation',
 'original_template':pin(original.encode()),'four_helpers_byte_equal':list(definitions),
 'bootstrap':bootstrap,'payload':payload_info,'typed_request':typed_info,
 'files':[{'name':k,'native_path':BASE+'/'+k,'local_source':str(source_files[k]),**pins[k]} for k in files],
 'bounded_input_bytes':1048576,'all_six_strict_base64_and_three_identity_fields_checked':True,
 'directory_mode':448,'files_mode':384,'all_creates_exclusive':True,
 'partial_created_controls_preserved_on_error':True,'original_failure_recording_retained':True,
 'separate_preparation_outer_seconds':900,
 'budget_scope':'This exact staging-only request retains the observed materializer bootstrap outer limit; it is not fix/fmt, preflight, record or qualification execution. Main maintenance retains the original separate 9300/7200/900/600/300 contract.',
 'actual_creation_or_execution_observed':False,'formal_execution_approval':False,'qualification':False,
 'future_formal_binding':'Root-approved final config changes its pin/base64 and the launcher PINS/request. Freeze and review those exact successor bytes before any native dispatch; this HOLD config remains false.'}
save('STAGING_CONTRACT.HOLD.json',jbytes(contract))
print(json.dumps({'bootstrap':bootstrap,'payload':payload_info,'request':typed_info,'files':len(files)},indent=2))
