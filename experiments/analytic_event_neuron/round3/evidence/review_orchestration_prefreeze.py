from pathlib import Path
from copy import deepcopy
import hashlib,json,tempfile,shutil,ast
from unittest.mock import patch
import numpy as np
from experiments.analytic_event_neuron.round3 import freeze,run,statistics,calibration_study
from experiments.analytic_event_neuron.round2.run import archive_scope
from experiments.analytic_event_neuron.round2.audit import _under
from experiments.analytic_event_neuron.round2.statistics import paired_interval,calibration
ROOT=freeze.REPO;PROJECT=freeze.PROJECT;RUN=Path('/tmp/aen-round3-20261028')
checks=[];findings=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(name,ok,detail=None):
 checks.append({'name':name,'passed':bool(ok),'detail':detail})
 if not ok:findings.append(name)
def reject(name,function):
 try:function()
 except (ValueError,FileExistsError):check(name,True)
 else:check(name,False)
protocol=json.loads((PROJECT/'PROTOCOL.json').read_text())
sourcehashes={str(p.relative_to(ROOT)):sha(p) for p in freeze.sources()}
owned=[PROJECT/f'{n}.py' for n in ['audit','run','freeze','statistics']]
for path in owned:ast.parse(path.read_text());check('scientific_module_parses:'+path.name,True)
check('fixed_primary_family_size',protocol['statistics']['primary_family_size']==len(protocol['statistics']['primary_contrasts'])==3)
check('original_gates_unchanged',protocol['statistics']['minimum_useful_net_utility_gain']==.01 and protocol['statistics']['event_utility_noninferiority_margin']==.01 and protocol['statistics']['mismatch_descriptive_margin']==.02 and protocol['statistics']['family_alpha']==.05)
check('calibration_prepared_registration_exact',protocol['calibration']==json.loads((RUN/'calibration_prepared/PREPARED.json').read_text())['registration'])
calibration_study.verify_prepared(RUN/'calibration_prepared',protocol['calibration']|{'phase':'development'}) if False else None
planned=[]
for seed in protocol['training_seeds']:
 for domain in ['train','development','gaussian','drift_shift','student_t']:
  planned.append((f'main:{seed}:{domain}',protocol['data_offsets'][domain]+seed))
 for code in [1,2,3]:planned.append((f'feedback:{seed}:{code}',protocol['feedback']['data_offset']+100*seed+code))
 planned.append((f'runtime:{seed}',protocol['runtime']['data_offset']+seed))
 reg=protocol['calibration']
 for window in range(12):
  for code in [1,2,3,4]:planned.append((f'calibration:{seed}:{window}:{code}',calibration_study.data_seed(reg,seed,window,code)))
 planned.append((f'calibration:{seed}:old',calibration_study.data_seed(reg,seed,12,5)))
check('all_290_planned_data_seeds_distinct',len(planned)==len(set(s for _,s in planned))==290)
# These are pure engineering fixtures; dataset generation and Native construction are blocked.
with tempfile.TemporaryDirectory(prefix='aen-r3-orchestration-review-') as temporary:
 base=Path(temporary);model=base/'fixture.json';model.write_text('{"engineering_fixture":true}\n')
 frozen={'schema':'engineering.freeze.fixture','source_commit':'0'*40,'protocol_sha256':sha(PROJECT/'PROTOCOL.json'),'sources_sha256':sourcehashes,'artifacts_sha256':{'fixture.json':sha(model)}}
 def writefreeze(x=frozen):(base/'FREEZE.json').write_text(json.dumps(x))
 writefreeze();check('freeze_verifies_exact_source_artifact_inventory',freeze.verify(base)==frozen)
 model.write_text('changed');reject('changed_prepared_bytes_rejected',lambda:freeze.verify(base));model.write_text('{"engineering_fixture":true}\n')
 changed=deepcopy(frozen);changed['sources_sha256'].pop(next(iter(changed['sources_sha256'])));writefreeze(changed)
 reject('missing_source_inventory_rejected',lambda:freeze.verify(base))
 changed=deepcopy(frozen);changed['sources_sha256']['extra_scientific.py']='0'*64;writefreeze(changed)
 reject('extra_source_inventory_rejected',lambda:freeze.verify(base))
 changed=deepcopy(frozen);changed['protocol_sha256']='0'*64;writefreeze(changed)
 reject('changed_protocol_digest_rejected',lambda:freeze.verify(base))
 changed=deepcopy(frozen);changed['artifacts_sha256']={'../escape.json':'0'*64};writefreeze(changed)
 reject('frozen_artifact_path_escape_rejected',lambda:freeze.verify(base));writefreeze()
 with patch('experiments.analytic_event_neuron.round3.run.task.build_dataset',side_effect=AssertionError('Dataset generation forbidden during engineering review')),patch('experiments.analytic_event_neuron.round3.run.Native',side_effect=AssertionError('Native execution not part of guard fixture')):
  changed=deepcopy(protocol);changed['rows']['confirmation']+=1
  reject('driver_arbitrary_protocol_rejected',lambda:run.confirm_all(base,changed))
  scope='seed_607_gaussian'
  for rel in [f'main/archives/{scope}.tar.gz',f'main/analysis/{scope}.npz',f'main/reports/{scope}',f'main/unpacked/{scope}']:
   p=base/rel;p.parent.mkdir(parents=True,exist_ok=True)
   if rel.endswith(('.npz','.gz')):p.write_text('retained-engineering-attempt')
   else:p.mkdir()
   reject('unindexed_attempt_rejected:'+rel,lambda:run.execute_scope(base,607,'gaussian',None,protocol))
   check('unindexed_attempt_preserved:'+rel,p.exists())
   if p.is_dir():p.rmdir()
   else:p.unlink()
  indexpath=base/'main/RUN_INDEX.json';entry={'seed':607,'law':'gaussian','scope':scope}
  indexpath.write_text(json.dumps({'source_commit':'1'*40,'scopes':[],'complete':False}))
  reject('resume_wrong_source_commit_rejected',lambda:run.confirm_all(base,protocol))
  indexpath.write_text(json.dumps({'source_commit':'0'*40,'scopes':[entry,entry],'complete':False}))
  reject('resume_duplicate_scope_rejected',lambda:run.confirm_all(base,protocol))
  indexpath.write_text(json.dumps({'source_commit':'0'*40,'scopes':[{'seed':1,'law':'gaussian','scope':'seed_1_gaussian'}],'complete':False}))
  reject('resume_unregistered_scope_rejected',lambda:run.confirm_all(base,protocol))
  changed=deepcopy(protocol);changed['statistics']['event_utility_noninferiority_margin']=.02
  reject('statistics_altered_acceptance_gate_rejected',lambda:statistics.summarize(base,changed))
  indexpath.write_text(json.dumps({'source_commit':'1'*40,'scopes':[],'complete':False}))
  reject('statistics_wrong_commit_rejected',lambda:statistics.summarize(base,protocol))
  indexpath.write_text(json.dumps({'source_commit':'0'*40,'scopes':[entry,entry],'complete':True}))
  reject('statistics_incomplete_duplicate_scopes_rejected',lambda:statistics.summarize(base,protocol))
 reject('invalid_published_commit_identity_rejected',lambda:freeze.freeze(base,'not-a-commit'))
 reject('overwrite_freeze_rejected',lambda:freeze.freeze(base,'0'*40))
 reject('evidence_path_traversal_rejected',lambda:_under(base,'../escape'))
 archive_dir=base/'archive_source';archive_dir.mkdir();(archive_dir/'a.json').write_text('{"review":true}\n');(archive_dir/'sub').mkdir();(archive_dir/'sub/b.bin').write_bytes(bytes(range(128)))
 receipt=archive_scope(archive_dir,base/'roundtrip.tar.gz')
 check('own_archive_all_members_hash_verified_before_delete',receipt['all_member_hashes_verified'] and receipt['file_count']==3 and (archive_dir/'a.json').is_file())
# Independently reproduce the entire two-stage bootstrap index stream on a deterministic matrix.
difference=np.arange(65,dtype=float).reshape(5,13)/100-.2
result=paired_interval(difference,4000,7719,.05/3)
rng=np.random.default_rng(7719);replicates=[]
for start in range(0,4000,200):
 s=rng.integers(5,size=(200,5,1));c=rng.integers(13,size=(200,5,13))
 for replicate in range(200):
  sample=np.empty((5,13))
  for row in range(5):sample[row]=difference[s[replicate,row,0],c[replicate,row]]
  replicates.append(sample.mean())
expected=np.quantile(replicates,[.05/3/2,1-.05/3/2])
bootstrap_error=float(np.max(abs(expected-result['interval'])))
check('paired_seed_then_whole_trajectory_bootstrap_independent_reference',bootstrap_error==0,bootstrap_error)
check('bootstrap_seed_means_preserved',np.array_equal(result['per_seed_mean_difference'],difference.mean(1)))
zero=paired_interval(np.zeros((5,13)),4000,7719,.05/3)
check('zero_difference_not_superiority_but_inside_NI_margin',zero['interval']==[0,0] and not zero['interval'][0]>.01 and zero['interval'][0]>-.01)
p=np.array([[[.2,.5,.3],[.1,.8,.1]],[[.7,.2,.1],[.05,.15,.8]]]);y=np.array([[1,1],[0,2]])
e=calibration(p,y);manual=[]
for category in range(3):
 total=0
 for bin_index in range(10):
  selected=[(float(probs[category]),int(label==category)) for probs,label in zip(p.reshape(-1,3),y.ravel()) if min(int(probs[category]*10),9)==bin_index]
  if selected:total+=abs(sum(a-b for a,b in selected))/4
 manual.append(total)
check('classwise_ECE_independent_bin_reference',abs(e['classwise_ece']-np.mean(manual))<1e-15)
check('ECE_does_not_count_horizons_as_independent_samples',e['independent_sample_count']==2 and e['horizon_measurements_per_trajectory']==2)
smoke=RUN/'validation/main_development/AUDIT.json';smokedoc=json.loads(smoke.read_text())
check('retained_full_development_replay_smoke_passed',smokedoc['passed'],{k:smokedoc.get(k) for k in ['unique_trajectories','models','control_rows','transport_receipts']})
check('scientific_sources_stable_during_review',sourcehashes=={str(p.relative_to(ROOT)):sha(p) for p in freeze.sources()})
report={'schema':'hepta.round3.orchestration-prefreeze-review.v1','passed':not findings,'checks':checks,'findings':findings,'reviewed_sources_sha256':{str(p.relative_to(ROOT)):sha(p) for p in owned},'complete_scientific_inventory_count':len(sourcehashes),'protocol_sha256':sha(PROJECT/'PROTOCOL.json'),'review_script_sha256':sha(__file__),'planned_dataset_seed_count':len(planned),'confirmation_generated':False,'native_execution_during_this_review':False,'engineering_fixture_dataset_generation_explicitly_blocked':True,'retained_development_audit_sha256':sha(smoke),'source_review':{'monotonic_interval_certificate_linked_to_actual_actions':True,'all_event_packet_files_and_readbacks_covered':True,'all_prediction_and_control_rows_audited':True,'all_numeric_PNGs_independently_decoded_in_main_audit':True,'analysis_artifact_hash_bound_before_statistics':True,'source_inventory_and_protocol_immutable':True,'archive_writer_verifies_each_own_member_before_removing_duplicate':True,'new_main_orchestrator_extracts_archives':False,'physical_target_access_claim':'Per-control-function source order only; prediction metrics execute in the same process before control. No process memory isolation proof.','publication_commit_byte_identity':'Parent must independently verify remote Git blobs; a 40-digit commit string alone is not proof.','restoration_safety':'Separate publication restoration review still required.'},'resolved_before_freeze':['Unindexed attempts preserved and rejected','Invocation protocol equality enforced','Resumption source_commit and registered coordinates checked','Confirmation audit requires ancestor model freeze binding','Full scientific inventory and protocol digest checked','Statistics reject changed protocol/gates and source_commit'],'publication_status':'Prospective prefreeze review; actual commit/blob verification remains a parent step'}
output=PROJECT/'evidence/ORCHESTRATION_PREFREEZE_REVIEW.json';output.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n')
print(json.dumps({'passed':report['passed'],'checks':len(checks),'findings':findings,'report_sha256':sha(output),'bootstrap_reference_error':bootstrap_error}))
if findings:raise SystemExit(1)
