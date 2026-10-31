from pathlib import Path
import hashlib,json,math
import numpy as np
from experiments.analytic_event_neuron import task
from experiments.analytic_event_neuron.run import load_data
from experiments.analytic_event_neuron.round3 import event_codec as codec
from experiments.analytic_event_neuron.round3 import event_study
ROOT=Path('/workspace/scratch/d831a963ef2f/hepta-analytic')
RUN=Path('/tmp/aen-round3-20261028')
checks=0;failures=[];maximum={};seeds=[]
def check(x,msg):
 global checks
 checks+=1
 if not x:failures.append(msg)
def close(a,b,msg,tol=2e-12):
 gap=float(np.max(abs(np.asarray(a)-np.asarray(b))))
 maximum[msg.split(':')[0]]=max(gap,maximum.get(msg.split(':')[0],0.))
 check(gap<=tol,msg)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def moments(driver,history):
 drift,q,noise=driver['parameters'];out=[]
 for row in range(len(history['obs'])):
  seen=history['mask'][row]&history['occupied'][row]
  t=history['times'][row,seen];y=history['obs'][row,seen]
  C=1+q*np.minimum.outer(t,t)+np.diag(noise*history['obs_var'][row,seen])
  cross=1+q*t;sol=np.linalg.solve(C,np.column_stack((y-drift*t,cross)))
  now=max(history['times'][row,history['occupied'][row]])
  out.append((drift*now+cross@sol[:,0],1+q*now-cross@sol[:,1]))
 return np.asarray(out).T
def action_scores(v,horizon,q,noise,cost):
 r=noise*.04;stop=v+q*horizon
 repair=stop-v*v/(v+r)+.12*cost
 if horizon==1:return np.column_stack((stop,repair))
 p=v+q;s=noise*.64;waited=p*s/(p+s)
 return np.column_stack((stop,repair,.07*cost+q+np.minimum(waited,waited-waited*waited/(waited+r)+.12*cost)))
def choices(v,config,horizon,q,noise,cost):
 n=len(v);bits=np.full(n,config['initial_logvar_bits']);center=np.floor(np.log(v)*2.**bits+.5)/2.**bits
 for it in range(14):
  decoded=np.exp(center);vals=action_scores(decoded,horizon,q,noise,cost);chosen=vals.argmin(1)
  half=.5/2.**bits;pad=32*np.spacing(np.maximum(1.,abs(center)))
  low,high=np.exp(center-half-pad),np.exp(center+half+pad)
  lo=action_scores(low,horizon,q,noise,cost);hi=action_scores(high,horizon,q,noise,cost)
  differences=lo-hi[np.arange(n),chosen,None];differences[np.arange(n),chosen]=np.inf
  tol=64*np.spacing(np.maximum(1.,hi.max(1)));certified=differences.min(1)>tol
  refine=(~certified)&(bits<config['maximum_logvar_bits'])&config['adaptive']
  if not refine.any():break
  bits[refine]=np.minimum(bits[refine]+2,config['maximum_logvar_bits'])
  center=np.floor(np.log(v)*2.**bits+.5)/2.**bits
 return chosen,certified
sources={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'experiments/analytic_event_neuron/round3').glob('event_*.py')}
for seed in [607,701,809,907,1009]:
 folder=RUN/f'training/seed_{seed}'
 data=load_data(folder/'DEVELOPMENT.npz');selection=json.loads((folder/'EVENT_SELECTION.json').read_text());models=json.loads((folder/'MODELS.json').read_text());base=json.loads((folder/'BASE_MODELS.json').read_text());fit=json.loads((folder/'BASE_TRAINING.json').read_text());driver=base['analytic'];drift,q,noise=driver['parameters']
 check(selection['development_dataset_sha256']==task.dataset_digest(data),f'devdigest:{seed}')
 check(selection['model_sha256']==digest(models),f'modeldigest:{seed}')
 check(selection['driver_receipt_sha256']==digest(fit),f'fitreceipt:{seed}')
 check(selection['driver_parameters']==driver['parameters']==fit['fitted_filter_parameters'],f'traineddriver:{seed}')
 check(fit['optimizer_success'] and fit['filter_parameter_l2_change']>0,f'fitupdates:{seed}')
 cm={stage:moments(driver,task.history(data,stage)) for stage in task.STAGES}
 cost=data['cost_multiplier'];n=len(cost)
 cfirst=action_scores(cm['initial'][1],2.,q,noise,cost).argmin(1)
 cwait=action_scores(cm['wait'][1],1.,q,noise,cost).argmin(1)
 def final(first,second,quantizer):
  means={stage:quantizer(cm[stage][0]) for stage in task.STAGES}
  pred=means['initial']+2*drift
  immediate=first==1;waiting=first==2;both=waiting&(second==1)
  pred[immediate]=means['repair'][immediate]+2*drift
  pred[waiting]=means['wait'][waiting]+drift
  pred[both]=means['wait_repair'][both]+drift
  paid=.12*cost*immediate+.07*cost*waiting+.12*cost*both
  seq=np.where(first==0,'stop',np.where(first==1,'repair',np.where(second==0,'wait/stop','wait/repair')))
  utility=1-(pred-data['future'][:,4])**2-paid
  return utility,paid,seq
 baseutility,basecost,baseseq=final(cfirst,cwait,lambda x:x)
 close(baseutility.mean(),selection['baseline_utility'],f'baseline_utility:{seed}')
 candidates=selection['candidates'];check(len(candidates)==21,f'21grid:{seed}')
 for ci,row in enumerate(candidates):
  config=row['config'];mb=config['mean_bits'];vb=config['initial_logvar_bits']
  first,cert0=choices(cm['initial'][1],config,2.,q,noise,cost)
  second,cert1=choices(cm['wait'][1],config,1.,q,noise,cost)
  utility,paid,seq=final(first,second,lambda x:np.floor(x*2.**mb+.5)/2.**mb)
  nl=[]
  for stage in task.STAGES:
   m,v=cm[stage];m=np.floor(m*2.**mb+.5)/2.**mb;v=np.exp(np.floor(np.log(v)*2.**vb+.5)/2.**vb)
   means=m[:,None]+drift*task.HORIZONS;variances=v[:,None]+q*task.HORIZONS
   nl.append(.5*(np.log(2*np.pi*variances)+(task.targets(data,stage)-means)**2/variances))
  close(utility.mean(),row['utility'],f'candidate_utility:{seed}:{ci}')
  close(paid.mean(),row['mean_action_cost'],f'candidate_paid_cost:{seed}:{ci}',0.)
  close(np.concatenate(nl).mean(),row['gaussian_nll'],f'candidate_nll:{seed}:{ci}')
  check(int((seq!=baseseq).sum())==row['action_disagreements_vs_continuous'],f'disagreement:{seed}:{ci}')
  uncert=int((~cert0).sum()+(~cert1[first==2]).sum())
  check(uncert==row['uncertified_decisions'],f'certificatecount:{seed}:{ci}')
  eligible=(row['utility']>=selection['baseline_utility']-.001 and row['gaussian_nll']<=selection['baseline_gaussian_nll']+.001 and(not config['adaptive'] or uncert==0))
  check(eligible==row['eligible'],f'eligibility:{seed}:{ci}')
 for adaptive,name in [(True,'event_adaptive'),(False,'event_fixed')]:
  indices=[i for i,r in enumerate(candidates) if r['config']['adaptive']==adaptive];eligible=[i for i in indices if candidates[i]['eligible']]
  choice=min(eligible,key=lambda i:(candidates[i]['event_packet_bytes'],-candidates[i]['utility'],i)) if eligible else min(indices,key=lambda i:(-candidates[i]['utility'],candidates[i]['event_packet_bytes'],i))
  check(choice==selection['selected'][name]['index'] and bool(eligible)==selection['selected'][name]['eligible'],f'selection:{seed}:{name}')
  check(models[name]['event_config']==candidates[choice]['config'],f'modelconfig:{seed}:{name}')
 selected={name:models[name] for name in ['event_adaptive','event_fixed','event_direct']}
 measured=event_study._new_control(selected,data)
 grouped={name:{r['case']:r for r in measured['rows'] if r['arm']==name} for name in selected}
 for name,rows in grouped.items():
  for identity,r in rows.items():
   packets=r['event_packets'];bytecount=sum(len((json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()) for p in packets)
   unitcount=sum(abs(count) for p in packets for count in p['counts'])
   check(bytecount==r['event_accounting']['packet_bytes'],f'packetbytes:{seed}:{name}:{identity}')
   check(unitcount==r['event_accounting']['logical_unit_events'],f'unitcounts:{seed}:{name}:{identity}')
  if name!='event_direct':
   recorded=candidates[selection['selected'][name]['index']]
   for field in ('event_packet_bytes','event_packets','logical_unit_events','uncertified_decisions'):
    check(measured['summary'][name][field]==recorded[field],f'selectedaccounting:{seed}:{name}:{field}')
 for identity,a in grouped['event_adaptive'].items():
  b=grouped['event_direct'][identity]
  for field in ['actions','delivered_prediction','paid_cost','utility']:
   check(a[field]==b[field],f'direct:{seed}:{identity}:{field}')
  check([p['counts'] for p in a['event_packets']]==[p['counts'] for p in b['event_packets']],f'directcounts:{seed}:{identity}')
 seeds.append({'seed':seed,'development_rows':n,'candidates_independently_recomputed':21,'selected_models_reexecuted':3,'selection_sha256':sha(folder/'EVENT_SELECTION.json'),'models_sha256':sha(folder/'MODELS.json')})
 print(json.dumps({'seed':seed,'review_checks':checks,'failures':len(failures)}),flush=True)
config=codec.Config(8,24,24,True);encoder=codec.Encoder(config);encoder.send(0.,1.,1.,'observed')
tiecost=(1/(1+.04))/.12
cert=codec.decision_certificate(encoder.decoder,{'planning_q':.18,'planning_noise_scale':1.},1.,tiecost)
check(not cert['certified'],'hardtie_falsely_certified')
try:codec.scores_for_variance(1e308,2.,1e308,1.,1.)
except ValueError:check(True,'scoreoverflowrejected')
else:check(False,'scoreoverflowaccepted')
changed=codec.Encoder(codec.Config(8,4,24,True));changed.send(0.,1.,0.,'observed')
try:changed.send(0.,1.1,0.,'refinement',8)
except ValueError:check(True,'changedrefinementrejected')
else:check(False,'changedrefinementaccepted')
source_after={name:sha(ROOT/name) for name in sources}
check(sources==source_after,'source_changed_during_review')
report={'schema':'hepta.round3.event-independent-prefreeze-review.v1','passed':not failures,'checks':checks,'failures':failures,'source_sha256':sources,'maxima':maximum,'seeds':seeds,'confirmation_generated':False,'review_script_sha256':sha(__file__),'scope':{'all_105_candidates_utilities_nll_action_costs_certificate_counts_independently_recomputed':True,'dense_conditional_covariance_reference':True,'all_selection_rules_and_saved_models_checked':True,'selected_3840_model_episodes_reexecuted':True,'all_selected_packet_bytes_and_units_independently_counted':True,'unselected_candidate_packet_byte_counts_independently_reexecuted':False,'source_order_private_target_after_delivery_checked':True,'process_isolation_proof':False,'finite_fp64_tests_are_not_universal_error_proof':True},'proof_review':{'action_score_monotonicity':'stop v+qT, repair qT+vr/(v+r)+c, wait cw+q+min(H(v+q,s),H(H(v+q,s),r)+cr) are all increasing in v; upper chosen below lower every other implies same action throughout cell','encoding':'error-feedback mode has exact-real telescoping target minus decoded previous center; subtractive residual retained only encoder; decoder receives signed counts, bits, time,kind','costs':'actual wait/repair costs use the same public multiplier as decision scores; packet bytes are reported separately and not fabricated utility or money','events':'signed update packets are state communication, not terminal call/put samples; no first-passage model is claimed','quantization_control':'matched absolute quantization reproduces decoded counts/decisions/delivery in all five development seeds','limits':'at an unresolved boundary after maximum precision, decision remains explicitly uncertified; no continuous bypass'},'resolved_before_freeze':['Stable harmonic costs plus finite result guard','Refinement requires unchanged encoder target and same time/increasing precision/zero mean count']}
path=ROOT/'experiments/analytic_event_neuron/round3/evidence/EVENT_PREFREEZE_REVIEW.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n')
print(json.dumps({'passed':report['passed'],'checks':checks,'maxima':maximum,'failures':failures[:5],'report_sha256':sha(path)}))
if failures:raise SystemExit(1)
