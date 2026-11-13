from pathlib import Path
import ast
import base64
import gzip
import hashlib
import json
import types

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
RUNTIME = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

raw=(ROOT/'driver-apply-fmt.HOLD.py').read_bytes()
tree=ast.parse(raw.decode())
ns={'gzip':gzip,'base64':base64}
for node in tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
        try:ns[node.targets[0].id]=ast.literal_eval(node.value)
        except (ValueError,TypeError):pass
proof=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prove_actual_failed_maintenance')
# Only this pure parser is compiled. Its read/write helpers below are an in-memory
# lookup of fixed already-preserved originals; no native module or runtime enters.
exec(compile(ast.Module(body=[proof],type_ignores=[]),'frozen-proof-function-only','exec'),ns)
inventory=(REPAIR/'ACTUAL_FINAL_INVENTORY.exact_recovered.json').read_bytes()
assert pin(inventory)==ns['BASELINE']
bodies={n:(RUNTIME/n).read_bytes() for n in ns['FAILED_PROOFS'] if (RUNTIME/n).is_file()}
bodies['fix.raw.log']=(RUNTIME/'fix.raw.exact_recovered.log').read_bytes()
if 'final.inventory.json.gz' not in bodies:
    candidate=gzip.compress(inventory,mtime=0)
    assert pin(candidate)==ns['FAILED_PROOFS']['final.inventory.json.gz']
    bodies['final.inventory.json.gz']=candidate
bodies['FAILED_MAINTENANCE_SUPERVISOR.original.json']=(RUNTIME/'MAIN_STATUS_06.original.json').read_bytes()
read_records=[];write_records=[]
def check(condition,message):
    if not condition:raise AssertionError(message)
def read_input(path,expected):
    body=bodies[Path(path).name]
    check(pin(body)==expected,'frozen body '+str(path))
    read_records.append({'name':Path(path).name,**pin(body)})
    return body
def pin_bytes(body,expected,label):
    check(pin(body)==expected,label)
    return body
cfg=json.loads(Path('/tmp/hepta-36fa-provider-0c59-maintenance-dispatch-prefetch-v1/CONFIG.original.txt').read_bytes())
ns['PREVIOUS_RUN']=Path('/memory-only-fixed-native-originals')
ns['CONTROL']=Path('/memory-only-fixed-native-normal')
m=types.SimpleNamespace(read_input=read_input,parse=json.loads,check=check,
    write=lambda name,body:write_records.append({'name':name,**pin(body)}),
    sha256=lambda body:hashlib.sha256(body).hexdigest(),pin_bytes=pin_bytes,
    REPO=Path(ns['CURRENT_REPO']),FIX=cfg['fix_argv'],FIX_SECONDS=cfg['fix_seconds'],
    MAXIMUM_LOG_BYTES=67108864,cfg=cfg,SUCCESSOR_INVENTORY=cfg['source_inventory'],result={})
actual=ns['prove_actual_failed_maintenance'](m)
assert actual['inventory']==inventory
assert actual['metadata']==(RUNTIME/'SOURCE_GIT_METADATA.after.json').read_bytes()
assert actual['git_state']==json.loads((RUNTIME/'final.git-state.json').read_bytes())
assert pin(actual['witness_raw'])==ns['WITNESS_PIN']
assert m.result['historical_fix']['returncode']==101
assert m.result['historical_fix']['already_consumed'] is True
for node in ast.walk(tree):
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='headers' for t in node.targets):
        calls=[x for x in ast.walk(node.value) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='split']
        assert sorted(x.args[0].value for x in calls)==[b'\n',b'\n\n']

source_raw=Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1/driver-maintenance.HOLD.py').read_text()
source_ast=ast.parse(source_raw)
pure_names={'check','actual_leaf_map','merkle','parse','nodup','sha256','oid'}
pure_nodes=[n for n in source_ast.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in pure_names|{'PreconditionError','IntegrityError'}]
pure_ns={'json':json,'hashlib':hashlib,'os':__import__('os')}
exec(compile(ast.Module(body=pure_nodes,type_ignores=[]),'original-pure-source-map-only','exec'),pure_ns)
leaves=pure_ns['actual_leaf_map'](inventory)
assert len(leaves)==ns['LEAVES'] and pure_ns['merkle'](leaves)==ns['BASELINE_TREE']
proposal=json.loads((REPAIR/'SOURCE_PACKET.json').read_bytes())
inv_rows={x['path']:x for x in json.loads(inventory)['files']}
for item in proposal['changes']:
    before=item['before_text'].encode();after=item['after_text'].encode()
    assert pin(before)==item['before'] and pin(after)==item['after']
    row=inv_rows[item['path']]
    assert row['matches_index'] is True and row['kind']=='file' and row['permissions']==0o644
    assert row['bytes']==len(before) and row['sha256']==pin(before)['sha256'] and row['working_blob']==pin(before)['git_blob']
    leaves[item['path']]={'mode':item['mode'],'sha':pin(after)['git_blob'],'bytes':len(after),'sha256':pin(after)['sha256']}
assert pure_ns['merkle'](leaves)==ns['EXPECTED_APPLY_TREE']==proposal['expected_successor_physical_tree']
assert leaves[ns['WITNESS_PATH']]['sha']==ns['WITNESS_PIN']['git_blob']
report={'format':'hepta-fix101-proof-schema-and-pure-mapping-review-v1','driver':pin(raw),
    'actual_frozen_failed_producer_records_match_consumer':True,
    'historical_failed_fix_retained':m.result['historical_fix'],
    'read_lookup_records':read_records,'would_archive_records':write_records,
    'exact_dirty_inventory':pin(inventory),'exact_metadata':pin(actual['metadata']),
    'head_commit_split_literals_correct':True,
    'complete_before_physical_tree':ns['BASELINE_TREE'],'complete_after_apply_tree':ns['EXPECTED_APPLY_TREE'],
    'leaf_count':len(leaves),'manual_change_count':4,'preserved_witness':ns['WITNESS_PIN'],
    'scope':'Offline actual-schema and pure object-map evaluation only. No native control main, runtime preflight, source mutation, Cargo, formatter, gate or H call.',
    'does_not_establish_future_execution_success':True}
out=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
p=ROOT/'FROZEN_PROOF_SCHEMA_REVIEW.json'
if p.exists():assert p.read_bytes()==out
else:
    with p.open('xb') as f:f.write(out)
print(json.dumps({'review':pin(out),'driver':pin(raw),'actual_schema_match':True,'complete_tree':ns['EXPECTED_APPLY_TREE'],'runtime_execution':False}))
