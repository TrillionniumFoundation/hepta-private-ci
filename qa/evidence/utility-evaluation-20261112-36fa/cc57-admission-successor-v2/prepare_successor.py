"""Bind the existing admission predicate to the actual 1c98 formatter ancestry.

Offline preparation only: no H calls, source checkout writes, native execution,
test-gate invocation, ref change, timeout change or authority fallback.
"""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path

OUT=Path('/tmp/hepta-36fa-cc57-admission-successor-v2')
OLD=Path('/tmp/hepta-36fa-final-qualification-hold-v1/qualification-admission.HOLD.py')
ROOT=Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
V1=Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v1')
FMT=Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/RESULT.original.json')
NEW_CONTROL='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2'

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def save(name,raw):
    p=OUT/name
    if p.exists():assert p.read_bytes()==raw,name
    else:p.write_bytes(raw)
    return pin(raw)

def jsave(name,value):return save(name,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())

def first_predicate(source):
    candidates=[n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Name) and n.func.id=='check' and len(n.args)==2
                and isinstance(n.args[1],ast.Constant) and n.args[1].value=='actual final original format prerequisite']
    assert len(candidates)==1
    return compile(ast.Expression(candidates[0].args[0]),'<unchanged-format-prerequisite-expression>','eval')

def main():
    prior_raw=OLD.read_bytes();prior=prior_raw.decode()
    assert pin(prior_raw)['git_blob']=='5208cfa83a1f279c7fb76c4536adfa41c1df5f6f'
    fmt_raw=FMT.read_bytes();fmt=json.loads(fmt_raw)
    assert pin(fmt_raw)['git_blob']=='6cb1b8d6af25907ca0fea5d9bd0f787062dbef94'
    result_raw=(V1/'RESULT.json').read_bytes();result=json.loads(result_raw)
    assert pin(result_raw)['git_blob']=='171e45f701c04443a6addbf2017e6b20a672884d'
    assert result['status']=='unknown' and result['driver_main_entered'] is False and result['driver_returncode'] is None
    assert result['error']=='RuntimeError: actual final original format prerequisite'
    assert result['final_evidence_error']=='ValueError: unchanged detached HEAD/no refs'
    replacements=[
        ("final_format['source_commit'] == '9c4a11f61d30e9cc352bf44d56c98909d202a55d'", "final_format['source_commit'] == '246d8cb614770252ee42029a5c014f2a4904176a'"),
        ("final_format['source_tree'] == 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'", "final_format['source_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'"),
        ("final_format['parents'] == ['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']", "final_format['parents'] == ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']")]
    successor=prior
    for before,after in replacements:
        assert successor.count(before)==1
        successor=successor.replace(before,after,1)
    inverse=successor
    for before,after in replacements:
        assert inverse.count(after)==1
        inverse=inverse.replace(after,before,1)
    assert inverse==prior
    old_ast=ast.parse(prior);new_ast=ast.parse(successor)
    old_nodes=list(ast.walk(old_ast));new_nodes=list(ast.walk(new_ast))
    assert len(old_nodes)==len(new_nodes)
    differences=[]
    for old,new in zip(old_nodes,new_nodes):
        assert type(old) is type(new)
        if isinstance(old,ast.Constant) and old.value!=new.value:
            differences.append({'old':old.value,'new':new.value,'line':new.lineno})
            new.value=old.value
    assert len(differences)==3 and ast.dump(new_ast)==ast.dump(old_ast)
    successor_pin=save('qualification-admission.cc57.HOLD.py',successor.encode())
    save('EXACT_THREE_ANCHORS.diff',''.join(difflib.unified_diff(prior.splitlines(True),successor.splitlines(True),fromfile='5208-original-admission',tofile='cc57-actual-format-ancestry-admission')).encode())
    cfg=json.loads((ROOT/'APPROVED_FINAL_QUALIFICATION_INPUT.json').read_bytes())
    source_cfg=json.loads((ROOT/'APPROVED_FINAL_SOURCE_GATES_CONFIG.json').read_bytes())
    source_cfg.update(source_checkout='/home/qian-qi/hepta-utility-36fa-source-gates-cc57-v2',
                      records=NEW_CONTROL+'/source-gates-records',run_identity='hepta-utility-36fa-source-gates-cc57-v2')
    source_pin=jsave('SOURCE_GATES_CONFIG.cc57-v2.HOLD.json',source_cfg)
    cfg.update(admission_path=NEW_CONTROL+'/qualification-admission.py',admission_pin=successor_pin,
               native_driver_path=NEW_CONTROL+'/native-driver.original.py',plan_path=NEW_CONTROL+'/PLAN.original.json',
               records=NEW_CONTROL+'/native-records',root_parent='/run/hepta-utility-36fa-final-cc57-v2',
               run_identity='hepta-utility-36fa-native-cc57-v2',
               source_gates_config_path=NEW_CONTROL+'/APPROVED_SOURCE_GATES_CONFIG.json',source_gates_config_pin=source_pin,
               source_gates_handoff_records=NEW_CONTROL+'/source-handoff')
    cfg['canonical_alignment']['supervisor_path']=NEW_CONTROL+'/CANONICAL_ALIGNMENT_NORMAL.original.json'
    cfg_pin=jsave('QUALIFICATION_INPUT.cc57-v2.HOLD.json',cfg)
    old_pred=first_predicate(prior);new_pred=first_predicate(successor)
    assert eval(old_pred,{'__builtins__':{}},{'final_format':fmt,'cfg':cfg}) is False
    assert eval(new_pred,{'__builtins__':{}},{'final_format':fmt,'cfg':cfg}) is True
    mutations={
        'wrong_source_commit':('source_commit','9c4a11f61d30e9cc352bf44d56c98909d202a55d'),
        'wrong_source_tree':('source_tree','ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'),
        'wrong_parents':('parents',['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']),
        'wrong_schema':('format','unrecognized'), 'failed_status':('status','failed'),
        'wrong_source_repo':('source_repo','/tmp/unapproved-source'),
        'qualification_claim':('qualification',True), 'fix_started':('fix_dispatched',True),
        'test_started':('test_commands_dispatched',1), 'extra_command':('attempted_commands',['fix','fmt']),
        'missing_fmt':('not_run_commands',['fmt']), 'ref_updated':('source_ref_updates',True)}
    observations=[]
    for name,(field,value) in mutations.items():
        candidate=copy.deepcopy(fmt);candidate[field]=value
        actual=eval(new_pred,{'__builtins__':{}},{'final_format':candidate,'cfg':cfg})
        assert actual is False,name
        observations.append({'synthetic_negative_probe':name,'predicate_returned':actual})
    # Every other acquire/finish proof, full snapshot, input guard, runtime seed,
    # resource condition, budget and error path is covered by exact inverse text.
    normal=json.loads(json.loads((V1/'STATUS_01.original.json').read_bytes())['content'][0]['text'])
    assert normal['job_id']=='1a1d2325df6-2564-1cae' and normal['exit_code']==1 and normal['timed_out'] is False
    review={
        'format':'hepta-cc57-exact-admission-ancestry-successor-v2',
        'status':'PREPARED_ACTUAL_ANCESTRY_CORRECTED_PENDING_PEER_AND_EXACT_LAUNCH_REVIEW',
        'old_admission':pin(prior_raw),'new_admission':successor_pin,'exact_three_ast_constant_changes':differences,
        'inverse_three_replacements_restores_full_original_bytes':True,
        'actual_final_format':pin(fmt_raw),'actual_format_source_commit':fmt['source_commit'],
        'actual_format_source_tree':fmt['source_tree'],'actual_format_parents':fmt['parents'],
        'actual_prior_attempt_job':normal['job_id'],'actual_prior_attempt_result':pin(result_raw),
        'prior_attempt_status':'unknown; original source driver main never entered',
        'first_error':result['error'],'secondary_error':result['final_evidence_error'],
        'secondary_error_limit':'The old maintenance HEAD expectation was still installed because admission failed before assigning the qualified source. It is not evidence of an actual source change. No fresh full-source equality is claimed from this rejected admission.',
        'review_correction':'Prior bootstrap byte/AST comparisons did not detect the retained historical formatter ancestry in admission5208. Root and the static compatibility review failed to validate that seam; both prior approvals and actual Unknown are retained.',
        'original_predicate_rejects_actual_1c98':True,'successor_predicate_accepts_actual_1c98':True,
        'synthetic_negative_predicate_probes':observations,
        'scope_of_probes':'Offline evaluation of the exact existing prerequisite expression against an already-observed formatter result and12 single-field synthetic corruptions; no source/native test gate or new real outcome.',
        'source':cfg['source'],'tree':cfg['tree'],'full_inventory':cfg['full_physical_inventory'],
        'source_config':source_pin,'qualification_input':cfg_pin,'new_control':NEW_CONTROL,
        'source_gate_limits':source_cfg['budgets_seconds'],'source_outer_seconds':7200,'native_outer_seconds':45000,
        'original_V5_5118_b92_wrappers_plan_runtime_guards_unchanged':True,
        'no_predicate_removed_or_bypassed':True,'original_fixture_or_owner_substitution':False,
        'source_or_ref_mutation':False,'H_or_main_dispatched':False,'qualification':False,'real_qualified_task_chains':0}
    review_pin=jsave('SUCCESSOR_REVIEW.json',review)
    print(json.dumps({'admission':successor_pin,'source_config':source_pin,'qualification_input':cfg_pin,'review':review_pin},sort_keys=True,indent=2))

if __name__=='__main__':main()
