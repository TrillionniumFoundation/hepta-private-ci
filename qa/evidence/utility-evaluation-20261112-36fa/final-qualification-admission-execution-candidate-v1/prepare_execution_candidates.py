"""Prepare exact READY bytes only. Root's separate execution approval is absent."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json
import types

BASE = Path(__file__).resolve().parent
HOLD = Path('/tmp/hepta-36fa-final-qualification-admission-actual-binding-v1')
CODE = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def changes(old,new,path=''):
    if isinstance(old,dict) and isinstance(new,dict):
        assert old.keys()==new.keys()
        return [r for key in sorted(old) for r in changes(old[key],new[key],path+'/'+key)]
    return [] if old==new else [{'path':path,'before':old,'after':new}]


def set_field(value,path,replacement):
    parts=path.lstrip('/').split('/')
    for name in parts[:-1]:value=value[name]
    value[parts[-1]]=replacement


def save(name,raw):
    path=BASE/name
    if path.exists():assert path.read_bytes()==raw, name
    else:path.write_bytes(raw)
    return identity(raw)


def main():
    q_before=(HOLD/'QUALIFICATION_CONFIG.HOLD.json').read_bytes()
    s_before=(HOLD/'SOURCE_GATES_CONFIG.HOLD.json').read_bytes()
    assert identity(q_before)['git_blob']=='083694f6a08cb7a9fbaeea2227b2f60f8608219a'
    assert identity(s_before)['git_blob']=='0d3c48853572dc89a823ca9afb5d5487868189e6'
    q_old,s_old=json.loads(q_before),json.loads(s_before)
    q_new,s_new=copy.deepcopy(q_old),copy.deepcopy(s_old)
    s_new['state']='READY_FOR_EXACT_SOURCE_RUN'
    s_after=encoded(s_new)
    q_new['state']='READY_FOR_FINAL_SOURCE_QUALIFICATION'
    q_new['root_execution_approved']=True
    q_new['source_gates_config_pin']=identity(s_after)
    q_after=encoded(q_new)
    q_changes,s_changes=changes(q_old,q_new),changes(s_old,s_new)
    assert {r['path'] for r in q_changes}=={'/state','/root_execution_approved',
        '/source_gates_config_pin/bytes','/source_gates_config_pin/sha256','/source_gates_config_pin/git_blob'}
    assert [r['path'] for r in s_changes]==['/state']
    inverse_q,inverse_s=copy.deepcopy(q_new),copy.deepcopy(s_new)
    for row in q_changes:set_field(inverse_q,row['path'],row['before'])
    for row in s_changes:set_field(inverse_s,row['path'],row['before'])
    assert encoded(inverse_q)==q_before and encoded(inverse_s)==s_before
    assert q_new['normal_native_and_source_results'] is None
    assert q_new['qualification_execution_dispatched'] is False
    assert q_new['not_an_execution_approval'] is True
    code_raw=(CODE/'qualification-admission.HOLD.py').read_bytes()
    assert identity(code_raw)['git_blob']=='c77e3be6230d3267c08333be582f69f23c016fb9'
    module=types.ModuleType('frozen_definitions_only_for_ready_data_check')
    exec(compile(code_raw,'<frozen admission definitions only>','exec'),module.__dict__)
    module.Admission._require_complete_bindings(q_new)
    wrapper=(CODE/'inputs/SOURCE_WRAPPER_8607.py').read_bytes()
    assert identity(wrapper)['git_blob']=='8607fa4bf00fc8cf535849de04d1eb6ff29429b3'
    tests=[node.args[0] for node in ast.walk(ast.parse(wrapper)) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.Attribute) and node.func.attr=='check' and len(node.args)==2
           and isinstance(node.args[1],ast.Constant)
           and node.args[1].value=='unaltered original exact-source gate inputs']
    assert len(tests)==1
    expression=compile(ast.Expression(tests[0]),'<one exact original source-wrapper data predicate>','eval')
    assert eval(expression,{'cfg':s_new,'INPUT':q_new,'module':module}) is True
    assert eval(expression,{'cfg':s_old,'INPUT':q_old,'module':module}) is False
    packet={'format':'hepta-final-qualification-execution-candidate-two-configs-v1',
        'separate_exact_Root_execution_approval_received':False,
        'qualification':{'before':identity(q_before),'after':identity(q_after),'before_utf8':q_before.decode(),'after_utf8':q_after.decode()},
        'source_gates':{'before':identity(s_before),'after':identity(s_after),'before_utf8':s_before.decode(),'after_utf8':s_after.decode()},
        'frozen_admission':identity(code_raw),'source_changes':[],'native_actions':[]}
    report={'format':'hepta-two-config-permission-field-inverse-proof-v1',
        'qualification_before':identity(q_before),'qualification_after':identity(q_after),
        'source_gates_before':identity(s_before),'source_gates_after':identity(s_after),
        'qualification_changes':q_changes,'source_gates_changes':s_changes,
        'all_keys_unchanged':True,'complete_inverse_qualification_bytes_equal':True,
        'complete_inverse_source_gate_bytes_equal':True,'frozen_admission_code_unchanged':identity(code_raw),
        'original_source_wrapper_unchanged':identity(wrapper),
        'original_source_wrapper_single_pure_data_expression':ast.unparse(tests[0]),
        'original_ready_data_predicate_true_for_candidate':True,'same_predicate_false_for_frozen_HOLD':True,
        'source_gate_config_full_pin_exact':q_new['source_gates_config_pin'],
        'normal_native_and_source_results_remains_null':True,'qualification_execution_dispatched_remains_false':True,
        'not_an_execution_approval_remains_true':True,'no_constructor_acquire_finish_live_or_main_called':True,
        'no_H_or_project_gate_or_Rust_execution':True,'source_tree_commit_ref_writes':0,
        'scope':'READY permission bytes prepared only under Root instruction; their preparation does not supply the separate exact engineering approval to stage or execute them.'}
    patch=''.join(difflib.unified_diff(q_before.decode().splitlines(keepends=True),q_after.decode().splitlines(keepends=True),
        'actual-HOLD/QUALIFICATION_CONFIG.HOLD.json','execution-candidate/QUALIFICATION_CONFIG.execution-candidate.json'))
    patch+=''.join(difflib.unified_diff(s_before.decode().splitlines(keepends=True),s_after.decode().splitlines(keepends=True),
        'actual-HOLD/SOURCE_GATES_CONFIG.HOLD.json','execution-candidate/SOURCE_GATES_CONFIG.execution-candidate.json'))
    save('QUALIFICATION_CONFIG.execution-candidate.json',q_after)
    save('SOURCE_GATES_CONFIG.execution-candidate.json',s_after)
    save('FROM_ACTUAL_HOLD.patch',patch.encode())
    save('EXACT_FIELD_AND_INVERSE_REVIEW.json',encoded(report))
    save('CONFIG_PACKET.json',encoded(packet))
    print(json.dumps({'qualification':identity(q_after),'source_gates':identity(s_after),
                      'field_changes':[len(q_changes),len(s_changes)],'inverse':True,
                      'separate_exact_execution_approval_received':False},sort_keys=True))


if __name__=='__main__':main()
