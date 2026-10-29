import json,gzip,hashlib,pathlib,math,datetime
b=pathlib.Path('/workspace/scratch/38ad1e295a60/rrsnn_v4')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
a_path=b/'results/aggregate.json';a=json.loads(a_path.read_text())
variants=['rr_full','ctrnn_state_cpu','ctrnn_state'];seeds=a['training_seeds'];replays=a['latent_replays_per_scenario']
verified=[];out={};checks=[]
def summarize(rows):
 n=len(rows);avg=lambda k:math.fsum(float(r[k]) for r in rows)/n
 z=lambda pred:sum(bool(pred(r)) for r in rows)
 return {'scenario_paths':n,'internal_spikes_mean':avg('internal_spikes'),'semantic_emissions_mean':math.fsum(sum(len(t['outputs']) for t in r['task_trace']) for r in rows)/n,'delivered_task_pulses_mean':avg('task_output_pulses'),'expected_utility_mean':avg('expected_utility'),'budget_spent_mean':avg('budget_spent'),'budget_final_mean':avg('budget_final'),'renewals_mean':avg('renewals'),'dropped_items_mean':avg('dropped'),'zero_internal_spike_paths':z(lambda r:r['internal_spikes']==0),'zero_semantic_output_paths':z(lambda r:r['task_output_pulses']==0),'zero_expected_utility_paths':z(lambda r:r['expected_utility']==0),'zero_realized_query_draws':sum(x==0 for r in rows for x in r['realized_query_utility']),'realized_query_draws':sum(len(r['realized_query_utility']) for r in rows),'internal_spikes_but_zero_output_paths':z(lambda r:r['internal_spikes']>0 and r['task_output_pulses']==0),'zero_output_and_positive_final_budget_paths':z(lambda r:r['task_output_pulses']==0 and r['budget_final']>0),'zero_renewal_paths':z(lambda r:r['renewals']==0),'zero_spend_paths':z(lambda r:r['budget_spent']==0),'initial_budget_mean_inferred_from_conservation':math.fsum(r['budget_final']+r['budget_spent']+r['shock_removed']-r['refill_added'] for r in rows)/n}
for split in ('test','shift','paired'):
 out[split]={}
 for v in variants:
  allrows=[];seedstats=[]
  for seed in seeds:
   rows=[]
   for rep in range(replays):
    rel=f'results/{v}/seed_{seed}/evaluation_{split}_rep{rep}.json.gz';p=b/rel
    assert sha(p)==a['sources_sha256'][rel],rel
    verified.append(rel)
    x=json.load(gzip.open(p,'rt'));i=x['identity'];e=x['evaluation']
    assert i['variant']==v and i['training_seed']==seed and i['dataset']==split and i['latent_replay']==rep
    assert e['all_resource_invariants_passed'] and e['episodes']==256 and len(e['rows'])==256
    for r in e['rows']:
     emissions=sum(len(t['outputs']) for t in r['task_trace'])
     assert emissions==r['task_output_pulses']==len(r['delivered'])
     assert r['budget_spent']==r['renewals']+emissions
     assert sum(r['internal_spikes_per_neuron'])==r['internal_spikes']
     assert r['budget_spent']==sum(t['budget_before']-t['budget_after'] for t in r['task_trace'])
     assert len(r['realized_query_utility'])==4
    rows.extend(e['rows'])
   seedstats.append({'training_seed':seed,**summarize(rows)})
   allrows.extend(rows)
  summary=summarize(allrows);published=a['datasets'][split]['models'][v]
  for key,pkey in [('internal_spikes_mean','internal_spikes_mean'),('delivered_task_pulses_mean','task_output_pulses_mean'),('budget_spent_mean','budget_spent_mean'),('renewals_mean','renewals_mean')]:
   assert math.isclose(summary[key],published[pkey],abs_tol=1e-12,rel_tol=1e-12),(split,v,key)
  assert math.isclose(summary['expected_utility_mean'],published['expected_utility']['mean'],abs_tol=1e-12,rel_tol=1e-12)
  for z,val in zip(seedstats,published['expected_utility']['training_seed_means']):
   assert math.isclose(z['expected_utility_mean'],val,abs_tol=1e-12,rel_tol=1e-12)
  out[split][v]={'summary':summary,'training_seed_summaries':seedstats,'seeds_with_zero_output_on_all_1024_paths':[z['training_seed'] for z in seedstats if z['zero_semantic_output_paths']==z['scenario_paths']],'seeds_with_zero_expected_utility_on_all_1024_paths':[z['training_seed'] for z in seedstats if z['zero_expected_utility_paths']==z['scenario_paths']]}
report={'schema':'rrsnn-v4-read-only-delivery-behavior-diagnostic-1','created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Post-result descriptive audit of original frozen main-table evaluations; no actor execution, retraining, tuning, new task data, or causal experiment. Isolated precision-repair outputs are not substituted.','aggregate_sha256':sha(a_path),'selected_variants':variants,'primary_comparator':a['primary_comparator'],'secondary_reference':'ctrnn_state is the fixed 128-update reference with approximately matched persistent numerical state; it is not the CPU-budget primary.','training_seeds':seeds,'latent_replays':replays,'query_draws_per_path':4,'verified_original_raw_files':len(verified),'source_index':'results/aggregate.json:sources_sha256','verified_source_paths_sha256':hashlib.sha256(json.dumps(sorted(verified),separators=(',',':')).encode()).hexdigest(),'definitions':{'sampling_unit':'Each descriptive path is one scenario x training seed x latent replay. Four latent replays and four terminal query draws are not independent scenarios. Paired conditions share value groups.','internal_spikes':'Actual latent encoder counts; CTRNN references have no internal pulse mechanism and correctly report zero.','semantic_output':'Accepted task action emissions summed from task_trace.outputs, checked equal to len(delivered) and task_output_pulses for every path. It is not the number of nonzero internal spikes.','budget':'One unit per accepted semantic emission or renewal. Every audited path satisfies budget_spent=emissions+renewals. Internal encoder spikes do not debit this task communication budget.','zero_utility':'Exactly zero expected delivered-query utility. Realized zero query draws are separately counted; they may be zero even with output.','budget_interpretation':'Positive terminal budget together with no output describes unused task resources. It does not show that budget was nonbinding at every earlier decision.'},'source_semantics_sha256':{p:sha(b/p) for p in ['evaluate.py','task.py','train.py']},'all_selected_aggregate_means_recomputed_and_matched':True,'all_emission_delivery_and_resource_equalities_verified':True,'datasets':out,'observed_conclusions':[],'hypotheses_not_identified_by_this_audit':['Teacher-forced training versus closed-loop state distribution mismatch is a possible explanation, but these result files contain no intervention separating that effect from optimization, architecture, latent stochasticity, readout quality, or task design.','No semantic output is an observed policy behavior, not evidence that the latent RR neurons never spike.','The success of the longer-trained CPU-budget CTRNN and failure of its fixed-update counterpart are consistent with training-budget sensitivity; they do not isolate a universal architecture or learning-rule cause.','No new loss/gradient analysis, decoder retraining, policy intervention, or alternate seed selection was performed; causes remain untested.']}
for split in ('test','shift','paired'):
 r=out[split]['rr_full'];s=r['summary'];c=out[split]['ctrnn_state_cpu']['summary']
 report['observed_conclusions'].append({'dataset':split,'rr_zero_output_fraction':s['zero_semantic_output_paths']/s['scenario_paths'],'rr_spiking_without_output_fraction':s['internal_spikes_but_zero_output_paths']/s['scenario_paths'],'rr_zero_output_positive_final_budget_fraction':s['zero_output_and_positive_final_budget_paths']/s['scenario_paths'],'rr_spikes_vs_semantic_output_means':[s['internal_spikes_mean'],s['delivered_task_pulses_mean']],'primary_semantic_output_mean':c['delivered_task_pulses_mean'],'rr_zero_output_training_seeds':r['seeds_with_zero_output_on_all_1024_paths']})
p=b/'results/delivery_behavior_diagnostic.json'
with p.open('x') as f: json.dump(report,f,indent=2,ensure_ascii=False);f.write('\n')
print('written',p,'sha256',sha(p),'bytes',p.stat().st_size,'verified_files',len(verified))
for x in report['observed_conclusions']:print(json.dumps(x))
for split in out:
 for v in variants:
  print(split,v,'seed_zero_output_counts',[z['zero_semantic_output_paths'] for z in out[split][v]['training_seed_summaries']],'seed_internal_spikes',[round(z['internal_spikes_mean'],6) for z in out[split][v]['training_seed_summaries']],'mean_final_budget',out[split][v]['summary']['budget_final_mean'])
