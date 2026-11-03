from pathlib import Path
import hashlib, json, os, subprocess, sys, re, datetime
p=Path('/mnt/data/e0_fix')
expected={
 'e0_feature_normalization.py': 'f6554624b5c6c53f6f46cb827121b428019a47e2',
 'test_e0_feature_normalization.py': '4e85b58c326c730da366159f6e3f412499b613a2',
}
blob_actual={}
for name, sha in expected.items():
    actual=subprocess.check_output(['git','hash-object',str(p/name)],text=True).strip()
    assert actual==sha, (name,actual,sha)
    blob_actual[name]=actual
cmd=[sys.executable, '-m','unittest','discover','-v','-s',str(p),'-p','test_e0_feature_normalization.py']
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
run=subprocess.run(cmd,env=env,capture_output=True,text=True)
raw=(run.stdout+run.stderr).encode()
log=Path('/mnt/data/hepta_e0_d5943cb_local_normalization.log');log.write_bytes(raw)
case_ids=re.findall(r'^test_\w+ \([^)]+\) \.\.\. ok$',run.stderr,re.M)
assert run.returncode==0 and len(case_ids)==9 and len(set(case_ids))==9
assert 'Ran 9 tests' in run.stderr and re.search(r'(?m)^OK$',run.stderr)
stress=subprocess.run([sys.executable, str(p/'check_dyadic_stress.py')],capture_output=True,text=True,env=env,check=True)
stress_report=json.loads(stress.stdout)
assert stress_report['tested_vectors']==1024 and stress_report['status']=='pass'
receipt={
  'schema':'hepta.e0.local-read-only-checkpoint.v1',
  'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'candidate_commit':'d5943cbfa9cee942f21b57aecba3c29744f83190',
  'pr_url':'https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1794',
  'original_github_ci':{
    'old_mechanism_test_commit':'185cb9366267149f45885d4196f7e355bf4b22de',
    'old_full_python_unittest':{'run_id':38550615028,'job_id':115807384107,'tests':55,'status':'passed_on_old_head_not_current'},
    'old_public_model_job':{'run_id':38550615028,'job_id':115807384740,'status':'failed','reason':'ValueError Q24 input outside [-8,8]'},
    'superseded_normalizer_candidate':'0c80793654262865f827af7f92c38634d25b4b69',
    'superseded_candidate_ci':'cancelled_not_success',
    'latest_candidate_ci':{'run_id':38565659725,'status_at_checkpoint':'queued'},
    'v8_canary':'pending_at_checkpoint','blocking_ci':'pending_at_checkpoint'
  },
  'local_independently_executed':{
    'source_git_blob_sha1':blob_actual,
    'python_version':sys.version,
    'test_command':'PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v -s /mnt/data/e0_fix -p test_e0_feature_normalization.py',
    'tests_executed':len(case_ids),'failures':0,'errors':0,'skips':0,
    'test_ids':case_ids,'exit_code':run.returncode,
    'raw_log_sha256':hashlib.sha256(raw).hexdigest(),
    'stress_test':stress_report,
    'scope':'normalizer only; no pretrained model, training, Worker, native Tick, or CI acceptance'
  },
  'not_validated':[
    'all current head Python regressions (about 69)',
    'actual ModernBERT model on new normalization and diagnostic Head',
    'authorized model load / NeuronFeatureDriver',
    'InferenceControlModelPort and native NeuronRuntime tick',
    'durable Q24 journal/CAS and independent Witness',
    'future heldout task utility and resource acceptance',
    'Cell Split promotion / production eligibility'
  ],
  'production_authorized':False,'e0_accepted':False,'e1_e4_accepted':False
}
report=Path('/mnt/data/hepta_e0_d5943cb_read_only_checkpoint.json')
report.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'receipt_path':str(report),'log_path':str(log),'exact_source_blobs':blob_actual,'tests_executed':len(case_ids),'log_sha256':hashlib.sha256(raw).hexdigest(),'stress_n':stress_report['tested_vectors']},indent=2))
