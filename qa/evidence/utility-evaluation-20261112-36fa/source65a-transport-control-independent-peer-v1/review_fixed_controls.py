#!/usr/bin/env python3
"""Read only frozen local bytes. Never import or execute a candidate module."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

D = Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1/review-candidate-v1')
E = D.parent / 'execution-candidate-v1'
OUT = Path(__file__).parent
OLD_ADMISSION = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/qualification-admission.HOLD.py')
OLD_V5 = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs/V5_GUARD_6632.original.py')
OLD_CFG = Path('/tmp/hepta-36fa-final-qualification-admission-execution-candidate-v1/QUALIFICATION_CONFIG.execution-candidate.json')
OLD_SOURCE_CFG = Path('/tmp/hepta-36fa-final-qualification-admission-execution-candidate-v1/SOURCE_GATES_CONFIG.execution-candidate.json')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def no_duplicates(pairs):
    value = {}
    for k, v in pairs:
        assert k not in value, ('duplicate JSON key', k)
        value[k] = v
    return value

def parse(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)

def load_json(path):
    return parse(path.read_bytes())

def pin_fields(value):
    return {k: value[k] for k in ('bytes', 'sha256', 'git_blob')}

def same_pin(raw, expected):
    actual = identity(raw)
    assert actual == pin_fields(expected), (actual, expected)
    return actual

def node_text(source, node):
    lines = source.splitlines(keepends=True)
    first = min([node.lineno] + [x.lineno for x in getattr(node, 'decorator_list', [])])
    return ''.join(lines[first - 1:node.end_lineno])

def definitions(source):
    result = {}
    def visit(nodes, prefix=''):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                result[name] = {'node': node, 'raw': node_text(source, node)}
                visit(node.body, name + '.')
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + '.')
    visit(ast.parse(source).body)
    return result

def literal(node, known):
    """Closed AST data resolver; no eval/exec, no module imports, no filesystem."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [literal(v, known) for v in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else set(values) if isinstance(node, ast.Set) else values
    if isinstance(node, ast.Dict):
        assert all(k is not None for k in node.keys)
        return {literal(k, known): literal(v, known) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -literal(node.operand, known)
    if isinstance(node, ast.BinOp):
        a, b = literal(node.left, known), literal(node.right, known)
        if isinstance(node.op, ast.Div) and isinstance(a, PurePosixPath):
            return a / b
        if isinstance(node.op, ast.Add) and isinstance(a, (str, int)) and isinstance(b, type(a)):
            return a + b
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        fn = ast.unparse(node.func)
        if fn in ('Path', 'pathlib.Path'):
            return PurePosixPath(literal(node.args[0], known))
    raise ValueError(ast.dump(node))

def constants(source):
    values, nodes = {}, {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            nodes[name] = node_text(source, node)
            try:
                values[name] = literal(node.value, values)
            except ValueError:
                pass
    return values, nodes

def strict_patch(source, patch, reverse=False):
    """Apply a unified diff in memory with every context/deleted byte checked."""
    src = source.splitlines(keepends=True)
    lines = patch.splitlines(keepends=True)
    assert lines[0].startswith('--- ') and lines[1].startswith('+++ ')
    output, cursor, i, hunks = [], 0, 2, 0
    while i < len(lines):
        header = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n', lines[i])
        assert header, lines[i]
        start = int(header.group(3 if reverse else 1)) - 1
        assert start >= cursor
        output.extend(src[cursor:start]); cursor = start
        i += 1; hunks += 1
        old_count = new_count = 0
        while i < len(lines) and not lines[i].startswith('@@ '):
            tag, body = lines[i][:1], lines[i][1:]
            assert tag in (' ', '+', '-'), lines[i]
            if tag != '+': old_count += 1
            if tag != '-': new_count += 1
            if reverse:
                tag = '+' if tag == '-' else '-' if tag == '+' else tag
            if tag in (' ', '-'):
                assert cursor < len(src) and src[cursor] == body, ('context mismatch', cursor, lines[i])
                cursor += 1
            if tag in (' ', '+'):
                output.append(body)
            i += 1
        assert old_count == int(header.group(2) or 1)
        assert new_count == int(header.group(4) or 1)
    output.extend(src[cursor:])
    return ''.join(output), hunks

def diff_values(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for key in sorted(set(a) | set(b)):
            p = path + '/' + str(key)
            if key not in a:
                result.append({'path': p, 'operation': 'added', 'after': b[key]})
            elif key not in b:
                result.append({'path': p, 'operation': 'removed', 'before': a[key]})
            else:
                result.extend(diff_values(a[key], b[key], p))
        return result
    return [] if a == b else [{'path': path, 'operation': 'changed', 'before': a, 'after': b}]

def full_get(path):
    sdk = Path(str(path) + '.PUBLISH_GET.original.json')
    if not sdk.is_file():
        return None
    value = load_json(sdk)
    assert value.get('isError') is False
    body = value['structuredContent']['content']
    assert isinstance(body, str) and body.encode() == path.read_bytes()
    return {'file': str(path), 'body': identity(body.encode()), 'sdk': identity(sdk.read_bytes()),
            'saved_actual_full_get_equal': True}

manifest = load_json(D / 'MANIFEST.json')
assert identity((D / 'MANIFEST.json').read_bytes())['git_blob'] == '7b7aa021cdc0f75f9a18edc210f7e540e55663c4'
assert len(manifest['files']) == len({r['name'] for r in manifest['files']}) == 59
verified_files, full_gets = [], []
for row in manifest['files']:
    path = D / row['name']
    assert path == Path(row['path']) and path.is_relative_to(D)
    verified_files.append({'name': row['name'], **same_pin(path.read_bytes(), row)})
    observed = full_get(path)
    if observed: full_gets.append(observed)
full_gets.append(full_get(D / 'MANIFEST.json'))
assert full_gets[-1]

old_h = OLD_V5.read_text()
new_h = (D / 'historical-runtime-guard.HOLD.py').read_text()
old_a = OLD_ADMISSION.read_text()
new_a = (D / 'qualification-admission.HOLD.py').read_text()
assert identity(old_h.encode())['git_blob'] == '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
assert identity(old_a.encode())['git_blob'] == 'c77e3be6230d3267c08333be582f69f23c016fb9'
definition_reports = {}
expected_changes = {
    'historical_v5': ['validate_runtime_restoration', 'environment_preflight'],
    'admission': ['Admission.__init__', 'Admission.observed_proof', 'Admission.acquire_and_validate',
                  'Admission.before_native_stage', 'Admission.finish', 'Admission._fixed',
                  'Admission._artifact', 'Admission._validate_canonical']}
for label, before, after, patchname in [
    ('historical_v5', old_h, new_h, 'HISTORICAL_V5_FROM_6632.patch'),
    ('admission', old_a, new_a, 'ADMISSION_FROM_C77E.patch')]:
    olddefs, newdefs = definitions(before), definitions(after)
    changed = [n for n in olddefs if olddefs[n]['raw'] != newdefs[n]['raw']]
    assert changed == expected_changes[label], changed
    assert not (olddefs.keys() - newdefs.keys())
    patch = (D / patchname).read_text()
    forward, hunks = strict_patch(before, patch)
    backward, _ = strict_patch(after, patch, reverse=True)
    assert forward == after and backward == before
    ov, on = constants(before); nv, nn = constants(after)
    assert all(nn.get(name) == text for name, text in on.items()), ('old global changed', label)
    definition_reports[label] = {
        'before': identity(before.encode()), 'after': identity(after.encode()),
        'old_definition_count': len(olddefs), 'unchanged_definition_count': len(olddefs)-len(changed),
        'changed_definitions': changed, 'added_definitions': sorted(newdefs.keys()-olddefs.keys()),
        'all_old_top_level_assignments_byte_equal': True,
        'exact_whole_file_forward_and_inverse': True, 'strict_patch_hunks': hunks,
        'definitions': [{'name': name, 'before': identity(v['raw'].encode()),
                         'after': identity(newdefs[name]['raw'].encode()),
                         'byte_equal': v['raw'] == newdefs[name]['raw']} for name,v in olddefs.items()]}

# Verify the only changed expressions in the two historical guard functions.
oh, nh = definitions(old_h), definitions(new_h)
h_calls = []
for name, roles in [('validate_runtime_restoration', ['runtime.result','runtime.supervisor','runtime.environment_ready']),
                    ('environment_preflight', ['historical_environment.started'])]:
    oldcalls = [x for x in ast.walk(oh[name]['node']) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == 'read_input']
    newcalls = [x for x in ast.walk(nh[name]['node']) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == 'read_transported_historical_input']
    oldcalls.sort(key=lambda x:(x.lineno,x.col_offset));newcalls.sort(key=lambda x:(x.lineno,x.col_offset))
    assert len(oldcalls) == len(newcalls) == len(roles)
    reconstructed = nh[name]['raw']
    for oldcall,newcall,role in zip(oldcalls,newcalls,roles):
        assert isinstance(newcall.args[0],ast.Constant) and newcall.args[0].value == role
        assert [ast.dump(x) for x in oldcall.args] == [ast.dump(x) for x in newcall.args[1:]]
        assert [ast.dump(x) for x in oldcall.keywords] == [ast.dump(x) for x in newcall.keywords]
        oldexpr = ast.get_source_segment(old_h,oldcall)
        newexpr = ast.get_source_segment(new_h,newcall)
        assert reconstructed.count(newexpr)==1
        reconstructed=reconstructed.replace(newexpr,oldexpr,1)
        h_calls.append({'function':name,'role':role,'before':oldexpr,'after':newexpr})
    assert reconstructed==oh[name]['raw']

ac, _ = constants(new_a)
hc, _ = constants(new_h)
stager = (D/'TRANSPORT_STAGER.HOLD.py').read_text()
sc, _ = constants(stager)
tm = load_json(D/'TRANSPORT_MANIFEST.HOLD.json')
wm = load_json(D/'STAGING_WRITE_MANIFEST.HOLD.json')
rows = {r['role']:r for r in tm['rows']}
assert len(rows)==55 and ac['HISTORY_ROLES']==[r['role'] for r in tm['rows']]
assert ac['HISTORY_MANIFEST_PIN']==hc['HISTORY_MANIFEST_PIN']==sc['MANIFEST_PIN']==identity((D/'TRANSPORT_MANIFEST.HOLD.json').read_bytes())
assert ac['HISTORY_TRANSPORT_CONTROL']==hc['HISTORY_TRANSPORT_CONTROL']==str(sc['BASE'])==tm['control']
assert sc['ORIGINAL_NAMES']==[r+'.original' for r in ac['HISTORY_ROLES']]
assert set(hc['HISTORY_RUNTIME_ROLES'])=={'runtime.result','runtime.supervisor','runtime.environment_ready','historical_environment.started'}
assert all(rows[role]==spec for role,spec in hc['HISTORY_RUNTIME_ROLES'].items())
assert ac['HISTORY_RUNTIME_GUARD_PIN']==sc['HISTORICAL_GUARD_PIN']==identity(new_h.encode())
assert ac['HISTORY_STAGER_PIN']==identity(stager.encode())
assert set(ac['HISTORY_FIXED_ROLES'])==set(ac['FIXED_INPUTS'])
mapping_proof=[]
for name,role in ac['HISTORY_FIXED_ROLES'].items():
    spec=ac['FIXED_INPUTS'][name]
    assert str(spec['path'])==rows[role]['original_path'] and spec['pin']==rows[role]['pin']
    mapping_proof.append({'consumer':name,'role':role,'kind':'fixed_input','path':str(spec['path'])})
for path,role in ac['HISTORY_ARTIFACT_ROLES'].items():
    assert path==rows[role]['original_path']
    mapping_proof.append({'consumer':'_artifact','role':role,'kind':'artifact','path':path})
cfg=load_json(D/'QUALIFICATION_CONFIG.HOLD.json')
for prefix,key in [('ARCHIVE_V3','archive_restoration'),('CANONICAL_ALIGNMENT','canonical_alignment'),
                    ('FINAL_FORMAT','final_format'),('ISOLATED_MATERIALIZATION','isolated_materialization'),
                    ('MAINTENANCE_41E','actual_maintenance')]:
    for role,kind in zip(ac['HISTORY_PROOF_ROLES'][prefix],('result','supervisor')):
        assert cfg[key][kind+'_path']==rows[role]['original_path'] and cfg[key][kind]==rows[role]['pin']
        mapping_proof.append({'consumer':prefix+'.'+kind,'role':role,'kind':'observed_proof','path':rows[role]['original_path']})
canonical_specs={
    'canonical.driver':('driver.py',ac['CANONICAL_DRIVER_PIN']),
    'canonical.config':('APPROVED_CONFIG.json',cfg['canonical_alignment']['approved_config']),
    'canonical.packet':('CANONICAL_PACKET.json',cfg['canonical_alignment']['canonical_packet']),
    'canonical.artifacts':('run/ARTIFACTS.json',cfg['canonical_alignment']['artifacts']),
    'canonical.commands':('run/COMMANDS.json',cfg['canonical_alignment']['commands']),
    'canonical.progress':('run/MUTATION_PROGRESS.json',cfg['canonical_alignment']['progress']),
    'canonical.inputs':('run/INPUTS.final.json',cfg['canonical_alignment']['inputs'])}
for role,(suffix,pin) in canonical_specs.items():
    assert str(ac['CANONICAL_CONTROL']/suffix)==rows[role]['original_path'] and pin==rows[role]['pin']
    mapping_proof.append({'consumer':'_validate_canonical','role':role,'kind':'canonical_control','path':rows[role]['original_path']})
for role in hc['HISTORY_RUNTIME_ROLES']:
    mapping_proof.append({'consumer':'historical_V5','role':role,'kind':'historical_runtime','path':rows[role]['original_path']})
assert {r['role'] for r in mapping_proof}==set(rows)
assert all(r['original_path'].startswith(ac['HISTORY_EVIDENCE_PARENT']+'/') and '/.git/' not in r['original_path'] and not r['original_path'].endswith('.lock') for r in tm['rows'])

oldcfg=load_json(OLD_CFG); oldsourcecfg=load_json(OLD_SOURCE_CFG)
assert identity(OLD_CFG.read_bytes())['git_blob']=='720abbdfa96bca8c7e6aaf633a800693960d80db'
assert identity(OLD_SOURCE_CFG.read_bytes())['git_blob']=='b97682c5a95bb7f09241e54f0b3d13bf7fa791a4'
sourcecfg=load_json(D/'SOURCE_GATES_CONFIG.HOLD.json')
cfgchanges=diff_values(oldcfg,cfg);sourcechanges=diff_values(oldsourcecfg,sourcecfg)
cfg_allowed={'/admission_path','/admission_pin/bytes','/admission_pin/sha256','/admission_pin/git_blob',
             '/historical_runtime_guard_path','/historical_runtime_guard_pin','/history_transport',
             '/native_driver_path','/plan_path','/records','/root_execution_approved','/root_parent','/run_identity',
             '/source_gates_config_path','/source_gates_config_pin/bytes','/source_gates_config_pin/sha256',
             '/source_gates_config_pin/git_blob','/source_gates_handoff_records','/state'}
assert {x['path'] for x in cfgchanges}==cfg_allowed
assert {x['path'] for x in sourcechanges}=={'/records','/run_identity','/source_checkout','/state'}
assert cfg['runtime_guard']==oldcfg['runtime_guard']==ac['RUNTIME_GUARD']
for key in ('coordination_lock','repo','source','tree','maintenance_guard_path','inventory_driver_path','target',
            'full_physical_inventory','full_native_inventory','expected_inventory_sha256',
            'current_final_git_state','canonical_complete_git_metadata','canonical_original_index'):
    assert cfg[key]==oldcfg[key]
assert cfg['root_execution_approved'] is False
assert all(cfg['history_transport'][key] is None for key in ('staging_job_id','staging_payload','staging_result','staging_supervisor'))
assert manifest['source_request'] is None and manifest['native_request'] is None

typed=load_json(D/'STAGING_PROCESS_INPUT.HOLD.json')
stage_input=load_json(D/'STAGING_INPUT.HOLD.json')
assert set(typed)=={'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
assert typed['host']=='desktop' and typed['executable']=='/usr/bin/python3' and typed['cwd']=='/home/qian-qi'
assert typed['args']==['-B','-c',stager] and typed['timeout_seconds']==900
assert typed['stdin'].encode()==(D/'STAGING_INPUT.HOLD.json').read_bytes()
assert set(stage_input)=={'format','status','root_execution_approved','manifest_base64','historical_guard_base64'}
assert stage_input['root_execution_approved'] is False and stage_input['status']=='HOLD_ROOT_EXACT_REVIEW_REQUIRED'
assert base64.b64decode(stage_input['manifest_base64'],validate=True)==(D/'TRANSPORT_MANIFEST.HOLD.json').read_bytes()
assert base64.b64decode(stage_input['historical_guard_base64'],validate=True)==new_h.encode()
argv_raw=(json.dumps([typed['executable']]+typed['args'],sort_keys=True,indent=2)+'\n').encode()
assert identity(argv_raw)==ac['HISTORY_STAGER_ARGV_PIN']
assert ac['HISTORY_PART_INPUTS']==sc['PART_INPUTS']==[{'path':r['native_path'],'pin':r['decoded_pin']} for r in wm['writes']]
assert ac['HISTORY_PACKET_PIN']==sc['PACKET_PIN']==wm['packet'] and ac['HISTORY_GZIP_PIN']==sc['GZIP_PIN']==wm['gzip']
compressed_parts=[]
for i,row in enumerate(wm['writes'],1):
    request_path=D/'write-requests'/f'STAGE_{i:03d}.REQUEST.HOLD.json'
    request=load_json(request_path)
    assert set(request)=={'host','path','data_base64','expected_version'}
    assert request['host']=='desktop' and request['expected_version']=='absent' and request['path']==row['native_path']
    raw=base64.b64decode(request['data_base64'],validate=True)
    same_pin(raw,row['decoded_pin'])
    assert row['decoded_offset']==sum(map(len,compressed_parts))
    assert len(raw)<=307200 and len(request_path.read_bytes())<=1048576
    encoded=(D/'parts'/f'PART_{i:03d}.b64').read_bytes()
    assert encoded==request['data_base64'].encode()+b'\n'
    same_pin(encoded,row['encoded_part']);same_pin(request_path.read_bytes(),row['request'])
    compressed_parts.append(raw)
compressed=b''.join(compressed_parts);same_pin(compressed,wm['gzip'])
rawpacket=gzip.decompress(compressed);same_pin(rawpacket,wm['packet'])
packet=parse(rawpacket)
assert packet['manifest']==ac['HISTORY_MANIFEST_PIN']
assert [x['role'] for x in packet['files']]==ac['HISTORY_ROLES']
original_identities=[]
for entry,row in zip(packet['files'],tm['rows']):
    raw=base64.b64decode(entry['data_base64'],validate=True)
    same_pin(raw,row['pin'])
    original_identities.append({'role':row['role'],**identity(raw)})
assert sum(x['bytes'] for x in original_identities)==7976106

# Only static syntax/call inventory: never run the stager's top-level try block.
stree=ast.parse(stager)
for node in ast.walk(stree):
    if isinstance(node,ast.Call):
        fn=ast.unparse(node.func)
        assert fn not in {'exec','eval','os.execv','os.execve','os.rename','os.replace','os.remove','os.unlink','os.symlink','os.link'},fn
        assert not fn.startswith(('subprocess.','shutil.')),fn
stager_calls=[{'call':ast.unparse(n.func),'line':n.lineno,'source':ast.get_source_segment(stager,n)}
              for n in ast.walk(stree) if isinstance(n,ast.Call) and ast.unparse(n.func) in {'os.open','os.mkdir','os.fsync','retain'}]
new_methods=[v for k,v in definitions(new_a).items() if k not in definitions(old_a)]
assert not any(isinstance(n,ast.Call) and ast.unparse(n.func).startswith(('m.git','self.m.git','self.inventory','self.m.run_readonly'))
               for v in new_methods for n in ast.walk(v['node']))
remaining_reads=[{'scope':name,'line':n.lineno,'source':ast.get_source_segment(new_a,n)}
                 for name,v in definitions(new_a).items() for n in ast.walk(v['node'])
                 if isinstance(n,ast.Call) and ast.unparse(n.func) in ('m.read_input','self.m.read_input','self.h.read_input','self.read')]

em=load_json(E/'MANIFEST.json');execution_files=[]
for row in em['files']:
    p=E/row['name'];execution_files.append({'name':row['name'],**same_pin(p.read_bytes(),row)})
    g=full_get(p)
    if g:full_gets.append(g)
g=full_get(E/'MANIFEST.json');assert g;full_gets.append(g)
ready_input=load_json(E/'STAGING_INPUT.execution-candidate.json')
ready_typed=load_json(E/'STAGING_PROCESS_INPUT.execution-candidate.json')
assert {x['path'] for x in diff_values(stage_input,ready_input)}=={'/root_execution_approved','/status'}
assert ready_input['root_execution_approved'] is True and ready_input['status']=='ROOT_APPROVED_TO_STAGE_ONLY'
inverse=dict(ready_input);inverse['root_execution_approved']=False;inverse['status']='HOLD_ROOT_EXACT_REVIEW_REQUIRED'
assert inverse==stage_input
assert (json.dumps(inverse,sort_keys=True,indent=2)+'\n').encode()==(D/'STAGING_INPUT.HOLD.json').read_bytes()
assert {x['path'] for x in diff_values(typed,ready_typed)}=={'/stdin'}
assert ready_typed['stdin'].encode()==(E/'STAGING_INPUT.execution-candidate.json').read_bytes()
assert ready_typed['args']==typed['args']
inverse=dict(ready_typed);inverse['stdin']=typed['stdin']
assert (json.dumps(inverse,sort_keys=True,indent=2)+'\n').encode()==(D/'STAGING_PROCESS_INPUT.HOLD.json').read_bytes()
assert all(v is None for v in em['actual_stage_fields'].values())
assert em['source_request'] is None and em['native_request'] is None and em['not_an_execution_approval'] is True

result={
    'format':'hepta-independent-transported-original-control-byte-review-v1',
    'scope':'Frozen cloud bytes, saved actual Git full-GET bodies, restricted AST/literal analysis only.',
    'candidate_or_guard_functions_executed':0,'H_calls':0,'source_writes':0,'git_writes':0,
    'hold_manifest':identity((D/'MANIFEST.json').read_bytes()),'verified_frozen_files':verified_files,
    'saved_actual_git_full_get_checks':full_gets,
    'definition_preservation':definition_reports,'four_historical_call_replacements':h_calls,
    'role_mapping':mapping_proof,'unique_consumed_roles':len({x['role'] for x in mapping_proof}),
    'mapping_edges':len(mapping_proof),'originals':original_identities,
    'qualification_config_diff':cfgchanges,'source_config_diff':sourcechanges,
    'current_live_baselines_and_budget_contracts_preserved':True,
    'stager':{'pin':identity(stager.encode()),'typed_hold':identity((D/'STAGING_PROCESS_INPUT.HOLD.json').read_bytes()),
              'typed_fields':sorted(typed),'outer_seconds':typed['timeout_seconds'],'no_env':True,
              'actual_argv_pin':identity(argv_raw),'file_write_calls':stager_calls,
              'part_count':len(compressed_parts),'max_decoded_part':max(map(len,compressed_parts)),
              'packet':identity(rawpacket),'gzip':identity(compressed),'receipt_file_count':55+5,
              'hold_payload_flags_reject_before_any_filesystem_write':True},
    'unchanged_or_new_exact_reads':remaining_reads,
    'execution_candidate':{'manifest':identity((E/'MANIFEST.json').read_bytes()),'files':execution_files,
        'two_leaf_input_inverse_and_stdin_only_typed_inverse':True,
        'seventeen_part_writes_unchanged':True,'source_and_native_request':None,
        'actual_staging_bindings':em['actual_stage_fields'],'authorization':'No H authorization asserted.'},
    'limits':['The candidate modules, guards, constructor, acquire, main and finish were not run.',
              'No actual native origin availability, transport-stage completion, qualification or source change is inferred.',
              'No adversarial same-UID filesystem race or durability-under-crash execution was performed.']}
output=OUT/'BYTE_AND_MAPPING_PROOF.json'
with output.open('xb') as stream:
    stream.write((json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode())
print(json.dumps({'result':str(output),**identity(output.read_bytes()),
                  'verified_files':len(verified_files),'full_get_bodies':len(full_gets),
                  'historical_v5':{k:v for k,v in definition_reports['historical_v5'].items() if k!='definitions'},
                  'admission':{k:v for k,v in definition_reports['admission'].items() if k!='definitions'},
                  'roles':len(rows),'mapping_edges':len(mapping_proof)},ensure_ascii=False,indent=2))
