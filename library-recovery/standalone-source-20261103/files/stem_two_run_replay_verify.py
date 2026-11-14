import hashlib,json,zipfile,re,collections,statistics,pathlib
base=pathlib.Path('/mnt/data')
ids=[38114716982,38116089672]
expected={38114716982:('1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8','675970bb610c70bb0ec30a2dee05c025440510e6',130),38116089672:('a3322c5dec5f0d2a7453e90a97095e746e206a01c102749b458e3ed816573cc6','95a20c4287bd6e9ab3fefd95774a2d9c8212d73f',133)}
rows_by_run=[]; receipts=[]; archives=[]
for id in ids:
 p=base/f'memory-stem-native-matrix-{id}.zip'
 want,commit,cnt=expected[id]; h=hashlib.sha256(p.read_bytes()).hexdigest();assert h==want
 with zipfile.ZipFile(p) as z:
  entries=z.infolist()
  assert len(entries)==cnt+1
  names=set(z.namelist());assert len(names)==len(entries)
  assert all(not n.startswith('/') and '..' not in pathlib.PurePosixPath(n).parts for n in names)
  checks={}
  for ln in z.read('SHA256SUMS').decode().splitlines():
   match=re.fullmatch(r'([0-9a-f]{64})  (?:\./)?(.+)',ln)
   assert match,ln
   ha,n=match.groups(); assert n not in checks and n in names
   checks[n]=ha;assert hashlib.sha256(z.read(n)).hexdigest()==ha,n
  assert set(checks)==names-{'SHA256SUMS'} and len(checks)==cnt
  tested=z.read('tested-commit.txt').decode().strip();assert tested==commit
  scored=json.loads(z.read('comparison/scored-policy-attempts.json'))
  assert len(scored)==576
  assert all(x['status']=='succeeded' for x in scored)
  assert json.loads(z.read('comparison/report.json'))['production_accepted'] is False
  assert json.loads(z.read('comparison/report.json'))['census']==dict(planned=576,recorded=576,complete=True)
  key=lambda x:(x['stage'],x['phase'],x['arm'],x['cell'],x['question_id'])
  m={key(x):x for x in scored};assert len(m)==576
  rows_by_run.append(m)
  weight_hashes={k:hashlib.sha256(z.read(k)).hexdigest() for k in names if k.endswith('.safetensors')}
  assert len(weight_hashes)==3
  arch=dict(run_id=id,sha256=h,tested_commit=tested,manifest_verified_files=len(checks),logical_policy_rows=len(scored),actual_success_rows=sum(x['status']=='succeeded' for x in scored),safetensor_sha256=weight_hashes)
  archives.append(arch)
  rec=json.loads(z.read('comparison/adapter-training.json'))
  receipts.append(rec)
  print('run',id,'read',len(scored),'checks',cnt,'tensors',len(weight_hashes))
keys=set(rows_by_run[0]);assert keys==set(rows_by_run[1]);all_keys=sorted(keys)
for i in [0,1]:
 m=rows_by_run[i]; frozen={(stage,phase,cell,qid):row for (stage,phase,arm,cell,qid),row in m.items() if arm=='frozen_rerank'}
 assert len(frozen)==96
 print('frozen count',len(frozen))
 for arm in ['prototype','linear','gated','lineage_lora_gated','independent_lora_gated']:
  heldout=[(stage,phase,arm,cell,qid) for stage,phase,arm0,cell,qid in keys if arm0==arm and phase in ('test','transfer')]
  assert len(heldout)==48,(arm,len(heldout))
  for k in heldout:
   stage,phase,a,cell,qid=k; model=m[k]; fr=frozen[(stage,phase,cell,qid)]
   for field in ('selected','answer','source_choice_correct','status'):
    assert model[field]==fr[field],('frozen-vs-learned',i,arm,k,field)
  print(' arm',arm,'heldout matched',len(heldout))
# Strong observed field equality across independent reruns (no time comparisons).
fields=['answer','citation_structure','diagnostic_answer_f1','encoder_identity','feature_digest','head_sha256','pool_digest','selected','source_choice_correct','status']
metrics={k:sum(rows_by_run[0][id].get(k)!=rows_by_run[1][id].get(k) for id in all_keys) for k in fields}
print('diff metrics:',metrics)
# model scores on actual heldout outcomes, compare across arms at each stage and cell; per arm 48 outcomes
scores={}
for arm in sorted({key[2] for key in keys}):
 rows=[row for key,row in rows_by_run[1].items() if key[2]==arm and key[1] in ('test','transfer')]
 scores[arm]=dict(planned=len(rows),mean_f1=round(sum((row.get('diagnostic_answer_f1') or 0) for row in rows)/len(rows),6),source_choice_correct_true=sum(row.get('source_choice_correct') == 1 for row in rows),source_choice_correct_false=sum(row.get('source_choice_correct') == 0 for row in rows),source_choice_correct_unknown=sum(row.get('source_choice_correct') is None for row in rows),observed_nonnull_f1=sum(row.get('diagnostic_answer_f1') is not None for row in rows),cited_answer_markers=sum(bool(re.search(r'\[E[1-9]\d*\]',str(row['answer']))) for row in rows))
print('scores',json.dumps(scores,ensure_ascii=False))
# Train-fit evidence; do not confuse training updates with task gains.
train_receipts=receipts[1]
print('adapter training keys',train_receipts.keys(),'receipts',len(train_receipts['receipts']),'failures',len(train_receipts['failures']))
# weight blob integrity
same_weights=(archives[0]['safetensor_sha256']==archives[1]['safetensor_sha256'])
assert same_weights
assert all(v==0 for v in metrics.values())
assert all(all(model[field]==row for field,row in []) for model in [])
result=dict(schema='hepta.memorycell.independent-two-native-runs.v1',research_only=True,archives=archives,cross_run_repeated_policy_rows=len(all_keys),cross_run_field_mismatches=metrics,heldout_development_paired_per_learned_arm=48,heldout_learned_arms=['prototype','linear','gated','lineage_lora_gated','independent_lora_gated'],heldout_learned_selected_answer_or_source_improvements=0,heldout_merged_train_test_source_families_independent=False,backend_weights_sha_equal=same_weights,second_run_heldout_arm_metrics=scores,has_independent_entailment_verdict=False,trained_model_advantage_established=False,semantic_citation_99pct_certified=False,production_accepted=False,interpretation='Completed authored native development attempts and exact repeatability are real observations. Learned heads/LoRA produce no changed heldout selections/answers relative to the frozen reference in 48 stage-scoped paired observations per arm; 576 rows are not independent tasks or 576 unique reader calls. Not a future family generalization certificate.')
out=base/'stem_two_run_independent_gate_20261011.json';out.write_text(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+'\n')
print('wrote',out,out.stat().st_size)
