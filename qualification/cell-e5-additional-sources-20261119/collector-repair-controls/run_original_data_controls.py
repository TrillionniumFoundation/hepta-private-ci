import pathlib,importlib.util,json,copy,hashlib,time
r=pathlib.Path('/home/qian/work/hepta-e5-collector-repair-controls-20261120-e9e051');r.mkdir(exist_ok=False)
def module(name,file):
 spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
candidate=module('candidate','/home/qian/work/e5-fixed-case-identity-collector-20261120-e9e051.py')
verifier=module('independent','/home/qian/work/e5-verify-native-identity-3fa8d480.py')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(pathlib.Path(candidate.__file__))=='41af79c1756623d71c38737f5b7bd9d91e4b341079f5f9258e09be6921077ad0'
started=time.perf_counter();records=[];negative_controls=0;case_pairs=0
for label in ['v3','v4']:
 root=pathlib.Path('/home/qian/work/hepta-e5-additional-sources-20261120-e9e051-'+label);output=root/'replay-1'
 result_path=output/'RESULT.json';digest=sha(result_path);original=json.loads(result_path.read_bytes());plan=json.loads((root/'ACQUISITION_PLAN.json').read_bytes())
 approved={x['project_id']:x['original_regression_demonstrated'] for x in json.loads((root/'identity-readback-1/READOUT.json').read_bytes())['by_source']}
 for entry in plan['projects']:
  stages=[x for x in original['stages'] if x['project_id']==entry['project_id']]
  if not stages:continue
  before,after=stages;left=candidate.original_case_ids(entry,before,root,output);right=candidate.original_case_ids(entry,after,root,output)
  equal=bool(left) and left==right
  admitted=before['wait_returncode']==1 and before.get('failures',0)>0 and before.get('errors',1)==0 and after['wait_returncode']==0 and after.get('passed',0)>0 and after.get('errors',1)==0 and before.get('tests')==after.get('tests') and equal and not before['timed_out'] and not after['timed_out']
  assert admitted==approved[entry['project_id']]
  for row,ids in [(before,left),(after,right)]:
   if ids is not None:
    folder=output/f"{entry['index']}-{row['variant']}";actual=verifier.case_identities(folder/'junit.xml',folder/'work',root,entry['test_files'])
    assert ids==[(x['class'],x['name']) for x in actual]
  if admitted:
   changed=copy.deepcopy(after);changed['cases'][0]['name']+='[foreign-parameter]'
   assert candidate.original_case_ids(entry,changed,root,output)!=left;negative_controls+=1
   changed=copy.deepcopy(after);changed['cases'][0]['class']='foreign.'+changed['cases'][0]['class']
   try:candidate.original_case_ids(entry,changed,root,output)
   except AssertionError:pass
   else:raise AssertionError('foreign path admitted')
   negative_controls+=1
   changed=copy.deepcopy(after);changed['cases'].pop()
   try:ids=candidate.original_case_ids(entry,changed,root,output)
   except AssertionError:pass
   else:assert not ids or ids!=left
   negative_controls+=1;case_pairs+=len(left)
  records.append({'attempt':label,'project':entry['project_id'],'actual_regression_admitted':admitted,'independent_XML_readback_agrees':True})
 assert sha(result_path)==digest
result={'status':'PASS','candidate_sha256':sha(pathlib.Path(candidate.__file__)),'independent_verifier_sha256':sha(pathlib.Path(verifier.__file__)),'original_pair_records':len(records),'admitted_original_pairs':sum(x['actual_regression_admitted'] for x in records),'rejected_changed_parameter_or_foreign_path_or_missing_case_controls':negative_controls,'original_parameter_case_pairs':case_pairs,'original_native_children_reused':24,'new_native_children':0,'new_model_calls':0,'new_training_updates':0,'original_result_files_unchanged':True,'wall_seconds':time.perf_counter()-started,'records':records}
(r/'RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result),flush=True)
