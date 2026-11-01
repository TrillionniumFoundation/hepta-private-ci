import sys,json,hashlib,itertools,math,tarfile,statistics
from pathlib import Path
import numpy as np
from scipy.stats import t
import torch
r=Path('tools/hcsn/unified_cell_r12_20261031').resolve(); sys.path.insert(0,str(r)); torch.set_num_threads(1)
from contract import PROTOCOL,true_model
from data import EvidenceWorld,sequences
from inference import sequence_predictions
p=r/'review/raw.json'; raw=json.loads(p.read_text()); c=json.loads((r/'evidence/CONFIRMATION.json').read_text()); summary=json.loads((r/'evidence/SUMMARY.json').read_text()); freeze=json.loads((r/'evidence/FREEZE.json').read_text())
checks=[]
def check(name,condition,detail=None):
 item={'name':name,'pass':bool(condition)}
 if detail is not None:item['detail']=detail
 checks.append(item)
def close(a,b,tol=1e-12):return abs(float(a)-float(b))<=tol
seeds=PROTOCOL['seeds']; rows=c['results']; check('development_false',c['development'] is False); check('exact_8_unique_seeds',len(seeds)==8 and len(set(seeds))==8); check('exact_8_by_2_rows',sorted((x['seed'],x['domain']) for x in rows)==sorted(itertools.product(seeds,['iid','ood'])))
fits={}; fit_rows=[]
for seed in seeds:
 group={}
 for core in PROTOCOL['cores']:
  doc=json.loads((r/'evidence/fits'/f'{seed}_{core}.json').read_text()); fits[(seed,core)]=doc; group[core]=doc
  check(f'fit_metadata_{seed}_{core}',doc['seed']==seed and doc['core']==core and close(doc['budget_cpu_seconds'],20))
  fit_rows.append({k:doc[k] for k in ['seed','core','parameter_count','fit_cpu_seconds','preparation_cpu_seconds','budget_overshoot_seconds','maximum_update_cpu_seconds','updates','selected_update','train_data_sha256','validation_data_sha256','initial_validation','selected_validation']})
 check(f'paired_training_validation_data_{seed}',len({v['train_data_sha256'] for v in group.values()})==1 and len({v['validation_data_sha256'] for v in group.values()})==1)
 choice=min(PROTOCOL['cores'][1:],key=lambda core:group[core]['selected_validation']['posterior_ce'])
 check(f'preselected_core_{seed}',choice==freeze['ordinary_choices'][str(seed)] and all(x['ordinary_choice']==choice for x in rows if x['seed']==seed))
check('independent_seed_data_hashes',len({fits[(s,'hx_distribution')]['train_data_sha256'] for s in seeds})==8 and len({fits[(s,'hx_distribution')]['validation_data_sha256'] for s in seeds})==8)
check('confirmation_sequence_hashes_unique',len({row['sequence_data_sha256'] for row in rows})==16)
with tarfile.open(r/'evidence/TRAINING_ARTIFACTS.tar.gz') as archive:
 names=archive.getnames(); archive_fit=[]
 for name,expected in freeze['fit_sha256'].items():
  matches=[n for n in names if n==name or n.endswith('/'+name)]
  ok=len(matches)==1 and hashlib.sha256(archive.extractfile(matches[0]).read()).hexdigest()==expected
  archive_fit.append({'fit':name,'matches':matches,'sha256_match':ok})
 check('all_24_archive_fit_hashes',all(x['sha256_match'] for x in archive_fit))
 raw['training_archive']={'sha256':hashlib.sha256((r/'evidence/TRAINING_ARTIFACTS.tar.gz').read_bytes()).hexdigest(),'fits':archive_fit}
raw['fit_audit']=fit_rows
true=true_model(); episode_rows=[]; sequence_rows=[]; max_cost_error=0.; cpu_residual=[]; seq_ties=[]
for row in rows:
 seed,domain=row['seed'],row['domain']; times=PROTOCOL[domain+'_dt']; data_seed=seed+(400000 if domain=='iid' else 500000); shared={k:np.asarray(v) for k,v in fits[(seed,'hx_distribution')]['shared_model'].items()}
 data=sequences(data_seed,PROTOCOL['confirmation_sequences_per_domain'],true,times,PROTOCOL['sequence_length'])
 sha=hashlib.sha256()
 for key,value in sorted(data.items()):sha.update(key.encode()); sha.update(np.ascontiguousarray(value).tobytes())
 check(f'confirmation_data_reproduction_{seed}_{domain}',sha.hexdigest()==row['sequence_data_sha256'])
 for arm,a in row['arms'].items():
  actions=np.asarray(a['actions']); acquired=np.asarray(a['acquired_tokens']); utility=np.asarray(a['utility']); accuracy=np.asarray(a['accuracy']); count=PROTOCOL['confirmation_episodes_per_domain']
  legal=(actions.shape==(count,3) and acquired.shape==(count,3) and utility.shape==(count,) and accuracy.shape==(count,))
  check(f'array_shapes_{seed}_{domain}_{arm}',legal)
  check(f'mean_scores_{seed}_{domain}_{arm}',close(utility.mean(),a['mean_utility']) and close(accuracy.mean(),a['mean_accuracy']))
  check(f'actual_reads_only_{seed}_{domain}_{arm}',np.all((acquired>=0)==(actions==3)) and np.all((acquired>=-1)&(acquired<=6)) and int((actions==3).sum())==a['read_calls'] and int((actions>=2).sum())==a['advance_calls'] and int((acquired==6).sum())==a['recovery_read_calls'])
  check(f'budget_and_terminal_{seed}_{domain}_{arm}',np.all((actions==3).sum(axis=1)<=2) and np.all(((actions==0)|(actions==1)).sum(axis=1)==1) and all(list(v).index(-1)>np.flatnonzero((v==0)|(v==1))[0] if -1 in v else True for v in actions))
  world=EvidenceWorld(data_seed+1000000,count,true,times); replay_u=np.zeros(count); replay_acc=np.zeros(count); final_state=np.full(count,-1); replay_tokens=np.full((count,3),-1); active=np.ones(count,dtype=bool)
  for step in range(3):
   ids=np.flatnonzero(active); terminal=ids[actions[ids,step]<2]; reward,correct=world.answer(terminal,actions[terminal,step]); replay_u[terminal]+=reward; replay_acc[terminal]=correct; final_state[terminal]=world.hidden[terminal]; active[terminal]=False
   advance=ids[actions[ids,step]>=2]
   if len(advance):
    world.advance(step,advance); replay_u[advance]-=.01*np.asarray(times)[world.dt_indices[step,advance]]; read=advance[actions[advance,step]==3]
    replay_tokens[read,step]=world.read(step,read); replay_u[read]-=true['read_cost'][world.hidden[read]]
  replay_ok=(np.max(np.abs(replay_u-utility))<1e-13 and np.array_equal(replay_acc,accuracy) and np.array_equal(replay_tokens,acquired) and np.array_equal(final_state,a['latent_at_answer_for_scoring_only']) and not active.any())
  check(f'episode_world_scores_replay_{seed}_{domain}_{arm}',replay_ok)
  core=a['core']; owner=core if core in PROTOCOL['cores'] else 'hx_distribution'; ownerfit=fits[(seed,owner)]; own=ownerfit['fit_cpu_seconds']+ownerfit['preparation_cpu_seconds']; hx=fits[(seed,'hx_distribution')]; cal=hx['fit_cpu_seconds']+hx['preparation_cpu_seconds']
  if core=='true_bayes':own=cal=0.
  unique=own+(cal if core in PROTOCOL['cores'][1:] else 0.); eq=own+cal; expected_unique=a['inference_cpu_seconds']/count+unique/1000; expected_eq=a['inference_cpu_seconds']/count+eq/1000
  errors=[abs(a['encoder_fit_cpu_seconds']-own),abs(a['shared_controller_calibration_cpu_seconds']-cal),abs(a['fit_and_preparation_cpu_seconds']-unique),abs(a['amortized_cpu_per_episode']-expected_unique),abs(a['equal_shared_charge_cpu_per_episode']-expected_eq)]; max_cost_error=max(max_cost_error,max(errors)); check(f'cost_formula_{seed}_{domain}_{arm}',max(errors)<1e-13)
  residual=a['inference_cpu_seconds']-sum(a['cpu_components'].values()); cpu_residual.append(residual)
  episode_rows.append({'seed':seed,'domain':domain,'arm':arm,'n':count,'mean_utility':float(utility.mean()),'mean_accuracy':float(accuracy.mean()),'read_calls':a['read_calls'],'advance_calls':a['advance_calls'],'recovery_read_calls':a['recovery_read_calls'],'replay_ok':replay_ok,'unique_cpu_per_episode':expected_unique,'equal_shared_cpu_per_episode':expected_eq,'inference_cpu_per_episode':a['inference_cpu_seconds']/count,'unitemized_inference_cpu':residual})
 # Independent sequence predictions from frozen models/data; no training or selection.
 predictions={}
 for core in [*PROTOCOL['cores'],'generic_hmm','true_bayes']:
  prediction=sequence_predictions(core,data,true if core=='true_bayes' else shared,times,r/'evidence/fits'/f'{seed}_{core}.json'); predictions[core]=prediction
  content=prediction.reshape(len(data['dt']),12,2,-1).sum(-1); target=data['posterior'].reshape(len(data['dt']),12,2,-1).sum(-1)
  values={'accuracy':(content.argmax(-1)==data['labels']).mean(-1),'posterior_ce':-(data['posterior']*np.maximum(prediction,1e-12).log()).sum(-1).mean(-1) if False else -(data['posterior']*np.log(np.maximum(prediction,1e-12))).sum(-1).mean(-1),'posterior_content_brier':((content-target)**2).sum(-1).mean(-1)}
  check(f'sequence_replay_{seed}_{domain}_{core}',all(np.max(np.abs(value-np.asarray(row['sequence'][core][metric])))<1e-12 and close(value.mean(),row['sequence'][core]['mean_'+metric]) for metric,value in values.items()))
  sequence_rows.append({'seed':seed,'domain':domain,'core':core,**{'mean_'+k:float(v.mean()) for k,v in values.items()}})
 pp=predictions['hx_distribution']; hh=predictions['generic_hmm']; pc=pp.reshape(192,12,2,-1).sum(-1); hc=hh.reshape(192,12,2,-1).sum(-1); loc=np.argwhere(pc.argmax(-1)!=hc.argmax(-1)); gap=np.maximum(np.abs(pc[...,0]-pc[...,1]),np.abs(hc[...,0]-hc[...,1])); parity=float(np.max(np.abs(pp-hh)))
 check(f'generic_hmm_parity_{seed}_{domain}',close(parity,row['generic_hmm_torch_parity_max'],1e-16))
 seq_ties.append({'seed':seed,'domain':domain,'prediction_max_absolute_difference':parity,'argmax_disagreement_count':len(loc),'maximum_content_gap_at_disagreements':float(max([gap[tuple(x)] for x in loc],default=0)),'examples':[{'sequence_index':int(i),'step':int(j),'hx_content':pc[i,j].tolist(),'hmm_content':hc[i,j].tolist(),'true_label_scoring_only':int(data['labels'][i,j]),'tokens_before_and_current':data['tokens'][i,:j+1].tolist(),'observed_before_and_current':data['observed'][i,:j+1].tolist()} for i,j in loc[:6]]})
 print(json.dumps({'completed':seed,'domain':domain,'sequence_argmax_disagreements':len(loc),'max_gap':seq_ties[-1]['maximum_content_gap_at_disagreements']}),flush=True)
raw['episode_audit']=episode_rows; raw['sequence_replay']=sequence_rows; raw['sequence_ties']=seq_ties; raw['cost_formula_max_abs_error']=max_cost_error; raw['cpu_timing_component_residual_range']=[min(cpu_residual),max(cpu_residual)]
def paired(values):
 values=list(map(float,values)); n=len(values); mu=statistics.mean(values); se=statistics.stdev(values)/math.sqrt(n); quant=float(t.ppf(.975,n-1)); count=0
 for mask in range(1<<n):
  signed=math.fsum((1. if mask&(1<<i) else -1.)*v for i,v in enumerate(values))/n
  if abs(signed)>=abs(mu)-1e-14:count+=1
 return {'n':n,'paired_values':values,'mean':mu,'se':se,'ci95_student':[mu-quant*se,mu+quant*se],'simultaneous_one_sided_lower':mu-quant*se,'sign_flip_extreme_count':count,'sign_flip_total_count':1<<n,'exact_two_sided_sign_flip_p':count/(1<<n)}
domains={}
for domain in ['iid','ood']:
 selected=[v for v in episode_rows if v['domain']==domain]; byseed={s:{v['arm']:v for v in selected if v['seed']==s} for s in seeds}; contrasts={}
 for name,lhs,rhs in [('B_minus_A','B','A'),('D_minus_C','D','C'),('C_minus_A','C','A'),('D_minus_B','D','B'),('D_minus_HMM','D','HMM')]:
  vals=[byseed[s][lhs]['mean_utility']-byseed[s][rhs]['mean_utility'] for s in seeds]; result=paired(vals); registered=summary['domains'][domain]['contrasts'][name]; contrasts[name]=result
  check(f'statistics_{domain}_{name}',np.max(np.abs(np.asarray(vals)-registered['paired_values']))<1e-12 and close(result['mean'],registered['mean']) and np.max(np.abs(np.asarray(result['ci95_student'])-registered['ci95_student']))<1e-12 and close(result['exact_two_sided_sign_flip_p'],registered['exact_sign_flip_p']))
 vals=[byseed[s]['D']['mean_utility']-byseed[s]['C']['mean_utility']-byseed[s]['B']['mean_utility']+byseed[s]['A']['mean_utility'] for s in seeds]; contrasts['interaction']=paired(vals)
 reg=summary['domains'][domain]['contrasts']['interaction'];check(f'interaction_{domain}',close(contrasts['interaction']['mean'],reg['mean']) and close(contrasts['interaction']['exact_two_sided_sign_flip_p'],reg['exact_sign_flip_p']))
 accuracy=paired([byseed[s]['D']['mean_accuracy']-byseed[s]['B']['mean_accuracy'] for s in seeds]); regacc=summary['domains'][domain]['accuracy_D_minus_B'];check(f'accuracy_contrast_{domain}',close(accuracy['mean'],regacc['mean']) and close(accuracy['exact_two_sided_sign_flip_p'],regacc['exact_sign_flip_p']))
 arm_means={arm:{metric:statistics.mean(byseed[s][arm][metric] for s in seeds) for metric in ['mean_utility','mean_accuracy','read_calls','advance_calls','recovery_read_calls','unique_cpu_per_episode','equal_shared_cpu_per_episode','inference_cpu_per_episode']} for arm in byseed[seeds[0]]}
 unique=arm_means['D']['unique_cpu_per_episode']/arm_means['B']['unique_cpu_per_episode']; conservative=arm_means['D']['equal_shared_cpu_per_episode']/arm_means['B']['equal_shared_cpu_per_episode']; ni=contrasts['D_minus_B']['simultaneous_one_sided_lower']>-.01
 check(f'cost_acceptance_{domain}',close(unique,summary['domains'][domain]['unique_actual_cost_ratio_D_over_B']) and close(conservative,summary['domains'][domain]['conservative_cost_ratio_D_over_B']) and ni==summary['domains'][domain]['noninferiority_pass'] and (ni and conservative<=.9)==summary['domains'][domain]['cost_acceptance_pass'])
 domains[domain]={'arm_means':arm_means,'contrasts':contrasts,'accuracy_D_minus_B':accuracy,'unique_actual_cost_ratio_D_over_B':unique,'conservative_cost_ratio_D_over_B':conservative,'noninferiority_pass':ni,'cost_acceptance_pass':ni and conservative<=.9}
ordered=sorted(domains,key=lambda d:domains[d]['contrasts']['D_minus_B']['exact_two_sided_sign_flip_p']); cumulative=0.
for rank,domain in enumerate(ordered):
 z=domains[domain]; result=z['contrasts']['D_minus_B']; cumulative=max(cumulative,min(1.,(2-rank)*result['exact_two_sided_sign_flip_p'])); result['holm_p']=cumulative; z['quality_gain_acceptance_pass']=cumulative<=.05 and result['mean']>=.01
 check(f'holm_and_quality_{domain}',close(cumulative,summary['domains'][domain]['contrasts']['D_minus_B']['holm_p']) and z['quality_gain_acceptance_pass']==summary['domains'][domain]['quality_gain_acceptance_pass'])
raw['independent_statistics']=domains; raw['checks']=checks; raw['all_checks_passed']=all(x['pass'] for x in checks); raw['check_count']=len(checks); raw['status']='numerical_audit_complete_report_pending'; p.write_text(json.dumps(raw,indent=2)+'\n')
print('AUDIT_RESULT',json.dumps({'checks':len(checks),'pass':raw['all_checks_passed'],'failures':[x for x in checks if not x['pass']],'max_cost_error':max_cost_error,'seq_disagreements':sum(x['argmax_disagreement_count'] for x in seq_ties),'max_sequence_gap':max(x['maximum_content_gap_at_disagreements'] for x in seq_ties)}))
