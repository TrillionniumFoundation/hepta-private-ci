"""Static guard/slot scope proof. No H, constructor, gate, or live observation."""
import ast,base64,hashlib,json
from pathlib import Path

OUT=Path('/tmp/hepta-36fa-final-source-b608-transported-preparation-v1')
OLD=Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1/review-candidate-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def jb(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def definitions(s):
 result={}
 def visit(node,prefix=()):
  for child in ast.iter_child_nodes(node):
   if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
    path=prefix+(child.name,)
    if not isinstance(child,ast.ClassDef):result['.'.join(path)]=ast.get_source_segment(s,child)
    visit(child,path)
   else:visit(child,prefix)
 visit(ast.parse(s));return result
old_req_raw=(OUT/'inputs/SOURCE_PROCESS_INPUT.65a.original.json').read_bytes();old_req=json.loads(old_req_raw)
new_req_raw=(OUT/'execution-candidate-v1/SOURCE_PROCESS_INPUT.candidate.json').read_bytes();new_req=json.loads(new_req_raw)
old_boot=old_req['args'][2];new_boot=new_req['args'][2]
assert definitions(old_boot)==definitions(new_boot) and len(definitions(old_boot))==5
marker='# Main failure is owned by the unchanged original wrapper, not the stager.'
assert old_boot.count(marker)==new_boot.count(marker)==1
assert old_boot.split(marker,1)[1]==new_boot.split(marker,1)[1]
module=ast.parse(new_boot)
last=module.body[-1]
assert isinstance(last,ast.Expr) and isinstance(last.value,ast.Call) and isinstance(last.value.func,ast.Name) and last.value.func.id=='exec'
assert all(not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='exec' for n in ast.walk(t)) for t in module.body if isinstance(t,ast.Try))
old_files={k:base64.b64decode(v,validate=True) for k,v in json.loads(old_req['stdin'])['files'].items()}
new_files={k:base64.b64decode(v,validate=True) for k,v in json.loads(new_req['stdin'])['files'].items()}
fixed_names=['source-gates-wrapper.py','native-wrapper.py','native-driver.original.py','PLAN.original.json']
for k in fixed_names:assert new_files[k]==old_files[k]
assert len(old_files)==len(new_files)==8
assert set(new_files)==(set(old_files)-{'CANONICAL_SUPERVISOR.original.json'})|{'TRANSPORT_SUPERVISOR.original.json'}
base_cfg=json.loads((OLD/'QUALIFICATION_CONFIG.HOLD.json').read_bytes())
cfg=json.loads(new_files['APPROVED_QUALIFICATION_INPUT.json'])
changed_keys=[k for k in base_cfg if base_cfg[k]!=cfg[k]]
assert set(changed_keys)=={'history_transport','admission_pin','state','root_execution_approved','source_gates_config_pin'}
live_keys=['source','tree','parents','repo','target','current_final_git_state','canonical_complete_git_metadata','canonical_original_index','full_physical_inventory','full_native_inventory','expected_inventory_sha256','expected_file_count','coordination_lock','runtime_guard','maintenance_guard_path','inventory_driver_path','historical_source_repo','historical_runtime_guard_path','historical_runtime_guard_pin','source_control_pin_overrides']
live=[]
for k in live_keys:
 assert cfg[k]==base_cfg[k]
 live.append({'field':k,'value_unchanged':True,'canonical_value_pin':pin(jb(cfg[k]))})
source=json.loads(new_files['SOURCE_GATES_CONFIG.json']);old_source=json.loads((OLD/'SOURCE_GATES_CONFIG.HOLD.json').read_bytes())
assert {k for k in old_source if source[k]!=old_source[k]}=={'state'}
assert source['budgets_seconds']=={'source-closure':600,'self-test':300,'verify':4800}
assert new_req['timeout_seconds']==old_req['timeout_seconds']==7200
assert set(new_req)==set(old_req)=={'host','executable','args','cwd','idempotency_key','stdin','timeout_seconds'}
for k in ('host','executable','cwd','timeout_seconds'):assert old_req[k]==new_req[k]
old_admission=(OLD/'qualification-admission.HOLD.py').read_text();selected=new_files['qualification-admission.py'].decode()
assert pin(old_admission.encode())['git_blob']=='299c3d79987abcde03e83c271bee91c568e0a5ab'
assert pin(selected.encode())['git_blob']=='fd67cb043f7b6cb8cf042104ac202cb5f0842196'
a,b=definitions(old_admission),definitions(selected)
assert set(a)==set(b) and len(a)==51
assert [k for k in a if a[k]!=b[k]]==['Admission.finish']
for k in ('Admission.__init__','Admission.acquire','Admission.before_native_stage','Admission._verify_transport_stability','Admission._read_transport_file','Admission._read_historical'):
 assert a[k]==b[k]
assert 'class InitialBaselineUnavailable(RuntimeError):' in selected
assert 'class InitialBaselineUnavailable(SourceChanged)' not in selected
finish=b['Admission.finish']
assert finish.count('if self.initial_git is None:')==1 and finish.count('if self.initial_raw is None:')==1
# Every original nonblank source line survives in order through the two explicit
# unavailable-baseline guards; known-baseline comparisons are not removed.
cursor=0;new_lines=finish.splitlines()
for line in a['Admission.finish'].splitlines():
 if not line.strip():continue
 while cursor<len(new_lines) and new_lines[cursor]!=line:cursor+=1
 assert cursor<len(new_lines),('old finish line missing',line)
 cursor+=1
manifest_raw=(Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1/FILE_004.readback.bin')).read_bytes()
manifest=json.loads(manifest_raw);canonical=next(x for x in manifest['rows'] if x['role']=='canonical.supervisor')
assert canonical['pin']==pin(old_files['CANONICAL_SUPERVISOR.original.json'])
assert canonical['original_consumers']==['cfg.canonical_alignment.supervisor']
assert cfg['canonical_alignment']['supervisor']==canonical['pin']
assert cfg['canonical_alignment']['supervisor_path']==canonical['original_path']
assert new_files['TRANSPORT_SUPERVISOR.original.json']==(OUT/'inputs/TRANSPORT_SUPERVISOR.actual.json').read_bytes()
assert pin(new_files['TRANSPORT_SUPERVISOR.original.json'])==cfg['history_transport']['staging_supervisor']
value={'schema':'hepta-b608-transport-source-guard-and-slot-static-proof-v1',
       'old_request':pin(old_req_raw),'candidate_request':pin(new_req_raw),
       'eight_input_slot_adaptation':{'before':list(old_files),'after':list(new_files),
         'canonical_supervisor_removed_only_from_bootstrap_duplication':True,
         'canonical_original_still_exactly_required_by_55_role_mapping':canonical,
         'new_stage_supervisor':pin(new_files['TRANSPORT_SUPERVISOR.original.json']),
         'new_stage_supervisor_path_not_yet_staged':cfg['history_transport']['staging_supervisor_path']},
       'four_original_full_controls_unchanged':{k:pin(new_files[k]) for k in fixed_names},
       'all_five_bootstrap_definitions_byte_unchanged':True,
       'bootstrap_pre_execution_checks_unchanged':['UID1000','real non-symlink parents','owned evidence parent','absent private control directory','eight exact base64 payload identities','O_EXCL and O_NOFOLLOW writes','0600 owner regular single-link records','full readback and fstat/lstat stability','directory fsync'],
       'source_exec_outside_staging_try_byte_unchanged':True,
       'current_live_source_git_environment_and_lock_config':live,
       'admission_299c_to_selected_fd67':{'qualified_definitions':51,'unchanged':50,'changed':['Admission.finish'],
         'original_finish_nonblank_lines_all_preserved_in_order':True,'new_exception_is_not_SourceChanged':True,
         'missing_baseline_route':'Future absent initial Git/physical baseline is InitialBaselineUnavailable; actual after evidence retained first. No retrospective change to 65a.',
         'all_other_constructor_acquire_before_stage_transport_guards_byte_unchanged':True},
       'pre_and_post_live_checks_are_future_required_original_execution_not_this_pure_proof':True,
       'original_source_wrapper_failure_routes_preserved_by_full_bytes':True,
       'original_native_wrapper_failure_routes_preserved_by_full_bytes':True,
       'source_budgets':{'admission':600,'source-closure':600,'self-test':300,'verify':4800,'final':300,'outer':7200},
       'native_driver_retained_only_for_future_separate_approval':{'phases':14,'root_parents':48,'outer':45000},
       'no_automatic_retry_budget_override_environment_override_or_new_fallback':True,
       'new_h_calls':0,'qualification':False,'root_exact_source_execution_approval_still_required':True,
       'script':pin((OUT/'prove_guard_scope.py').read_bytes())}
p=OUT/'LIVE_GUARD_AND_SLOT_PROOF.json'
with p.open('xb') as f:f.write(jb(value))
print(json.dumps({'path':str(p),**pin(p.read_bytes())}))
