#!/usr/bin/env python3
"""Pure bytes and actual-record predicate validation; no native imports/main/I/O."""
import ast
import base64
import gzip
import hashlib
import json
import pathlib
import types
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
RECOVERY = Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
PACKET = Path('/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1/NONRUST_PACKET.json')
MAINT = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1/driver-maintenance.HOLD.py')

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def save(path, value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    if path.exists():assert path.read_bytes()==raw
    else:
        with path.open('xb')as stream:stream.write(raw)

driver_raw=(ROOT/'driver.HOLD.py').read_bytes()
module_raw=MAINT.read_bytes()
assert identity(driver_raw)['git_blob']=='27c0db4e4bceb69bcaafc97f5cc843a37b180941'
assert identity(module_raw)['git_blob']=='59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'
driver_ast=ast.parse(driver_raw)
module_ast=ast.parse(module_raw)
# Compile only fixed global data and the one proof predicate. No runtime entry,
# module loader, preflight, apply, formatter, native I/O or cleanup is imported.
selected_globals=[node for node in driver_ast.body if isinstance(node,ast.Assign)]
selected_proof=[node for node in driver_ast.body if isinstance(node,ast.FunctionDef)and node.name=='prove_actual_maintenance']
namespace={'Path':Path,'gzip':gzip}
exec(compile(ast.Module(body=selected_globals+selected_proof,type_ignores=[]),'<fixed proof predicate>','exec'),namespace)
pure_names={'check','sha256','oid','nodup','parse','pin_bytes','parse_supervisor','actual_leaf_map','merkle'}
pure_nodes=[node for node in module_ast.body if isinstance(node,ast.FunctionDef)and node.name in pure_names]
assert len(pure_nodes)==len(pure_names)
pure={'hashlib':hashlib,'json':json,'pathlib':pathlib}
exec(compile(ast.Module(body=pure_nodes,type_ignores=[]),'<original pure helper definitions>','exec'),pure)
definitions={node.targets[0].id:node.value for node in module_ast.body
             if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)}
def pure_constant(node):
    if isinstance(node,ast.Constant):return node.value
    if isinstance(node,ast.Name):return pure_constant(definitions[node.id])
    if isinstance(node,ast.List):return [pure_constant(item) for item in node.elts]
    if isinstance(node,ast.Tuple):return tuple(pure_constant(item) for item in node.elts)
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Mult):return pure_constant(node.left)*pure_constant(node.right)
    raise ValueError('unsupported constant-only AST: '+ast.dump(node))
constants={key:pure_constant(definitions[key])for key in
           ['HEAD','TREE','PARENTS','FIX','FIX_SECONDS','FMT','MAXIMUM_LOG_BYTES']}
for key in ['REPO','TARGET']:
    node=definitions[key]
    assert isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords
    assert isinstance(node.func,ast.Attribute)and isinstance(node.func.value,ast.Name)
    assert (node.func.value.id,node.func.attr)==('pathlib','Path')
    constants[key]=Path(pure_constant(node.args[0]))
assert len(constants)==9
data={}
prior=str(namespace['MAINTENANCE_RUN'])
for name in ['RESULT.json','final.git-state.json','ARTIFACTS.json','INPUT_IDENTITIES.json','SOURCE_GIT_METADATA.after.json.gz']:
    data[prior+'/'+name]=(RUNTIME/name).read_bytes()
data[str(namespace['CONTROL']/'MAINTENANCE_NORMAL.original.json')]=(RUNTIME/'STATUS_06.original.json').read_bytes()
data[str(namespace['EVIDENCE']/'SOURCE_COORDINATION_EX.json')]=(RUNTIME/'SOURCE_COORDINATION_EX.json').read_bytes()
part_paths=sorted((RECOVERY/'final-inventory-parts').glob('final.inventory.json.gz.part-*.b64'))
assert len(part_paths)==5
gz=b''.join(base64.b64decode(path.read_bytes().rstrip(b'\n'),validate=True)for path in part_paths)
assert identity(gz)==namespace['BASELINE_GZIP_PIN']
data[prior+'/final.inventory.json.gz']=gz
written={}
reads=[]

def memory_read(path,pin,*args):
    path=str(path);raw=data[path]
    assert identity(raw)==pin,('fixed actual read',path)
    reads.append({'path':path,**identity(raw)})
    return raw

def memory_write(name,raw):
    assert name not in written
    written[name]=raw
    return identity(raw)

m=types.SimpleNamespace(**constants,**{name:pure[name]for name in pure_names})
m.read_input=memory_read;m.write=memory_write;m.gzrecord=memory_write
observed,snapshot,git_state,metadata_raw=namespace['prove_actual_maintenance'](m)
assert observed==json.loads(data[prior+'/RESULT.json'])
raw_inventory=gzip.decompress(gz)
assert raw_inventory==(RECOVERY/'final.inventory.exact_recovered.json').read_bytes()
assert git_state==json.loads(data[prior+'/final.git-state.json'])
assert identity(metadata_raw)==namespace['MAINTENANCE_METADATA_PIN']
assert len(reads)==8 and len({row['path']for row in reads})==8
assert len(written)==8
packet_raw=PACKET.read_bytes()
packet=pure['parse'](packet_raw)
assert identity(packet_raw)=={'bytes':2998722,'sha256':'b1b9ec7658cdc474c99bb3b8dab42c016fae7d6fa46bbb8b141322f1c07594b3','git_blob':'ab032ffdfd8b540a0d3a82558d8a07e70ab0c548'}
assert set(packet)=={'format','source_identity','base_inventory','base_physical_tree','changes','expected_after_leaf_count','expected_after_physical_tree'}
assert packet['format']=='hepta-reviewed-nonrust-source-apply-v1'
assert packet['source_identity']==snapshot['source']
assert packet['base_inventory']==namespace['BASELINE']
assert packet['base_physical_tree']==namespace['BASELINE_TREE']
leaves=pure['actual_leaf_map'](raw_inventory)
assert len(leaves)==namespace['LEAVES']==15243
assert pure['merkle'](leaves)==namespace['BASELINE_TREE']
rows={row['path']:row for row in snapshot['files']}
changes=packet['changes'];paths=[row['path']for row in changes]
assert paths==sorted(set(paths))==list(namespace['NONRUST_PATHS'])
after_map=dict(leaves)
for row in changes:
    assert set(row)=={'path','mode','before','after','after_base64'}
    original_row=rows[row['path']]
    assert row['mode']==leaves[row['path']]['mode']=='100644'
    assert original_row['kind']=='file' and original_row['permissions']==0o644
    assert row['before']=={'bytes':original_row['bytes'],'sha256':original_row['sha256'],'git_blob':original_row['working_blob']}
    after=base64.b64decode(row['after_base64'],validate=True)
    assert identity(after)==row['after'] and row['before']!=row['after']
    after_map[row['path']]={'mode':row['mode'],'sha':row['after']['git_blob'],
                         'bytes':row['after']['bytes'],'sha256':row['after']['sha256']}
assert len(after_map)==packet['expected_after_leaf_count']==15243
assert pure['merkle'](after_map)==packet['expected_after_physical_tree']=='8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
hold=json.loads((ROOT/'WAITING_CONFIG.json').read_bytes())
bound=dict(hold)
bound['nonrust_packet']=identity(packet_raw)
bound['expected_after_physical_tree']=packet['expected_after_physical_tree']
bound['waiting_for']=['Root exact inputs and source/control peer review; exact staged bootstrap/payload/request still absent']
assert bound['root_execution_approved']is False
save(ROOT/'WAITING_INPUT_BOUND_CONFIG.json',bound)
permission_delta={
    'format':'hepta-explicit-last-nonrust-path-adaptation-v1',
    'status':'PREPARED_NOT_EXECUTION_AUTHORITY',
    'old_path_rule':'Captured historical paths limited to CALLERS.toml, .github/blob-size-allowlist.txt, or qa/b4-no-bypass/*.py.',
    'new_path_rule':'Exactly the four literal existing paths listed below. No wildcard allowance remains.',
    'is_pure_subset_of_old_rule':False,
    'necessary_new_target':next({key:row[key]for key in ['path','mode','before','after']}for row in changes if row['path'].endswith('PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json')),
    'all_exact_changes':[{key:row[key]for key in ['path','mode','before','after']}for row in changes],
    'removed_general_scope':'Any other historical captured QA .py path, including the three unchanged reviewed fences, cannot be applied by this successor.',
    'unchanged_checks':['complete source and raw Git baseline','real parent directories','O_NOFOLLOW single-link regular reads','owned mode 100644','exact before bytes and exact after bytes','atomic replacement only after repeated preimage check','no new/deleted paths or Rust edits','full expected 15243-leaf Merkle','single EX and global guard','original fmt900 and retention/complete audits'],
    'pending_exact_approval':True,'H_calls':0,
}
save(ROOT/'EXPLICIT_JSON_PATH_ADAPTATION.json',permission_delta)
report={
    'format':'hepta-last-nonrust-pure-actual-predicate-and-packet-review-v1',
    'driver':identity(driver_raw),'original_module':identity(module_raw),
    'actual_input_reads':reads,'actual_producer_predicate_passed':True,
    'producer_result_returned_unchanged':True,'full_original_inventory_raw_equal':True,
    'git_metadata_comparison':'Original raw bytes and Python arbitrary-precision integers; no JavaScript JSON reserialization.',
    'memory_only_output_names':sorted(written),'strict_packet':identity(packet_raw),
    'exact_paths':paths,'complete_base_tree':namespace['BASELINE_TREE'],
    'independent_expected_after_tree':pure['merkle'](after_map),'complete_leaf_count':len(after_map),
    'unchanged_source_entries':len(after_map)-len(changes),
    'new_json_path_is_explicit_permission_target_adaptation':True,
    'local_source_reads_only':True,'native_functions_executed':False,
    'not_executed':['module_from_original','prepare','apply_packet','main','stage','environment_preflight','any canonical function','any H tool'],
    'scope':'Actual pinned historical producer predicate and complete four-file pure-data Merkle validated offline. No live native filesystem/process/lock condition has been observed by this script and no future success result is created.',
    'H_calls':0,'qualification':False,
}
save(ROOT/'ACTUAL_PROOF_AND_PACKET_REVIEW.json',report)
print(json.dumps({'predicate_passed':True,'input_count':len(reads),'packet':identity(packet_raw),
                  'after_tree':pure['merkle'](after_map),'native_calls':0,'approved':False},indent=2))
