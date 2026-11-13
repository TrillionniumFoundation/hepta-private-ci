#!/usr/bin/env python3
"""Independent bytes/AST/JSON review of a non-executable migration specification."""
import ast
import hashlib
import json
from pathlib import Path

P = Path('/tmp/hepta-36fa-final-qualification-admission-successor-hold-v1')
OUT = Path(__file__).resolve().parent
EXPECTED = {
    'ADMISSION_MIGRATION.HOLD.json': '4ab2f06f804ee93beff2ee15bc67603e4f366a03',
    'QUALIFICATION_BINDINGS.HOLD.json': '6ddb2402b7aaa2d63330efe627033b7cac0d3a7c',
    'SOURCE_GATES_CONFIG.HOLD.json': 'e908def6523ea6bbca2381832297d76ea5178073',
    'COMPLETE_METADATA_BRIDGE.HOLD.json': '83af92d3f60dda5f53c3b006b2508c2fb254ce62',
    'PRODUCER_CHAIN_STATIC_CHECKS.json': '9e9d6e6020f58316f89c86f0e7e41f52e569da23',
    'IMMUTABLE_CONTROL_BINDINGS.json': '66a392a2431e7f445fa58f9697a4fa26bc543496',
    'prepare_static_migration.py': '45f60e9f5bd001b823945356d7a1d7bd2af367e7',
}

def ident(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def read_json(path):
    return json.loads(path.read_bytes())

inputs=[]
for name, expected in EXPECTED.items():
    raw=(P/name).read_bytes()
    assert ident(raw)['git_blob']==expected
    inputs.append({'name':name,**ident(raw)})
origin=read_json(P/'ORIGINAL_INPUTS_FULL_GET.json')
origin=origin['entries'] if isinstance(origin,dict) else origin
producer=read_json(P/'PRODUCER_INPUTS_FULL_GET.v2.json')['entries']
assert len(origin+producer)==len({x['name'] for x in origin+producer})==44
for row in origin+producer:
    raw=(P/'inputs'/row['name']).read_bytes()
    assert ident(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    sdk=read_json(P/'github'/(row['name']+'.GET.original.json'))
    assert sdk['structuredContent']['content'].encode()==raw

old=(P/'inputs/ADMISSION_23D412.original.py').read_bytes()
assert ident(old)['git_blob']=='23d412ed67927a6cbfa5f521884e891afc93eb6f'
lines=old.decode().splitlines(keepends=True)
defs={}
def visit(nodes,prefix=''):
    for n in nodes:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            start=min([n.lineno]+[x.lineno for x in n.decorator_list])
            defs[prefix+n.name]={'source':ident(''.join(lines[start-1:n.end_lineno]).encode()),
                'ast_sha256':hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest(),
                'first_line':start,'last_line':n.end_lineno}
        elif isinstance(n,ast.ClassDef):visit(n.body,prefix+n.name+'.')
visit(ast.parse(old).body)
spec=read_json(P/'ADMISSION_MIGRATION.HOLD.json')
assert set(defs)=={x['function'] for x in spec['function_changes']}
assert len(spec['function_changes'])==13
preserved=[];changed=[]
for row in spec['function_changes']:
    assert row['original']==defs[row['function']],row['function']
    (preserved if row['disposition']=='preserve_exact_function_bytes' else changed).append(row['function'])
assert len(preserved)==9
assert set(changed)=={'Admission.__init__','Admission.acquire_and_validate','Admission.validate_materialization','Admission.finish'}
assert spec['source_module_generated'] is False and spec['typed_request_generated'] is False and spec['gate_execution_authorized'] is False

oldcfg=read_json(P/'inputs/historical-source-layout/APPROVED_QUALIFICATION_INPUT.json')
cfg=read_json(P/'QUALIFICATION_BINDINGS.HOLD.json')
assert cfg['runtime_guard']==oldcfg['runtime_guard']
assert cfg['positive_eval_cases']==oldcfg['positive_eval_cases']
assert cfg['coordination_lock']==oldcfg['coordination_lock']
assert cfg['root_execution_approved'] is False and cfg['qualification_execution_dispatched'] is False
for key in ('source','tree','parents','expected_inventory_sha256','full_physical_inventory','full_native_inventory',
            'admission_path','admission_pin','current_final_git_state','canonical_complete_git_metadata','canonical_original_index'):
    assert cfg[key] is None,key
for stage in ('final_format','canonical_alignment'):
    for key in ('job_id','result','supervisor'):
        assert cfg[stage][key] is None,(stage,key)
oldsource=read_json(P/'inputs/historical-source-layout/APPROVED_SOURCE_GATES_CONFIG.json')
source=read_json(P/'SOURCE_GATES_CONFIG.HOLD.json')
source_diff={k for k in oldsource.keys()|source.keys() if oldsource.get(k)!=source.get(k)}
assert source_diff=={'state','object_repository','source_sha','source_tree','source_checkout','records','run_identity'}
assert source['budgets_seconds']=={'self-test':300,'source-closure':600,'verify':4800}

contracts=read_json(P/'IMMUTABLE_CONTROL_BINDINGS.json')
prior=read_json(P/'inputs/STATIC_TEMPLATE_BINDINGS.json')
for key in ('actual_static_native_command_payloads','fourteen_phase_ids','ordinary_packages_argv','outer_budgets_seconds',
            'phase_budgets_seconds','root_exact_expression','source_gate_tuples','workflow_root_parent_count','workflow_root_parents'):
    assert contracts[key]==prior[key],key
assert contracts['runtime_contract']==prior['runtime']
assert len(contracts['fourteen_phase_ids'])==14
assert contracts['workflow_root_parent_count']==len(contracts['workflow_root_parents'])==48
for name, pin in contracts['original_source_and_native_modules'].items():
    assert ident((P/'inputs'/name).read_bytes())==pin,name
pins=contracts['current_source_control_pin_bindings']
plan=read_json(P/'inputs/PLAN_3AEF.json')['unchanged_original_controls']['reviewed_source_pins']['files']
assert [x['path'] for x in pins]==[x['path'] for x in plan]
diff=[]
for row,previous in zip(pins,plan):
    assert row['original_plan_pin']=={k:previous[k] for k in ('bytes','sha256','git_blob')}
    if row['actual_41e_pin']!=row['original_plan_pin']:diff.append(row['path'])
assert diff==['.github/workflows/hepta-daemon-learning-native.yml']
assert cfg['source_control_pin_overrides'][0]['reviewed_current_pin']==pins[8]['actual_41e_pin']
bridge=read_json(P/'COMPLETE_METADATA_BRIDGE.HOLD.json')
assert bridge['future_canonical']['actual'] is None and bridge['v5_projection']['called_with_future_actual_data'] is False
tree=ast.parse((P/'prepare_static_migration.py').read_bytes())
bridge_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='canonical_to_v5_projection')
bridge_calls=sorted({ast.unparse(n.func) for n in ast.walk(bridge_node) if isinstance(n,ast.Call)})
assert not any(x in bridge_calls for x in ('open','exec','eval','compile','os.open','subprocess.run'))
report={'format':'hepta-static-migration-spec-peer-data-v1','inputs':inputs,
        'author_sdk_complete_input_count_checked':44,'independent_predecessor_span_identity_count':13,
        'planned_preserved_functions':preserved,'planned_changed_functions':changed,
        'planned_is_not_executed_or_generated_code':True,'runtime_guard_deep_equal':True,
        'source_configuration_exact_changed_fields':sorted(source_diff),
        'original_gate_bindings_equal_prior_independent_checklist':True,'phase_count':14,'root_parent_count':48,
        'current_source_control_rows':12,'source_pin_changes':diff,
        'bridge_reference_calls':bridge_calls,'bridge_reference_function_executed':False,
        'future_final_subject_and_proofs_null':True,
        'scope':'Offline JSON/hash/AST comparisons only; no author script main, original code import or runtime/gate invocation.',
        'qualification':False}
with (OUT/'MIGRATION_SPEC_BYTE_REVIEW.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
print(json.dumps(ident((OUT/'MIGRATION_SPEC_BYTE_REVIEW.json').read_bytes())))
