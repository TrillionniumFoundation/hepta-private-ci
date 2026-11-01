import sys,json,hashlib,datetime
from pathlib import Path
import numpy as np
import torch
r=Path('tools/hcsn/unified_cell_r12_20261031').resolve(); sys.path.insert(0,str(r)); torch.set_num_threads(1)
from contract import PROTOCOL,true_model
from data import EvidenceWorld
from inference import Estimator
from control.controller import plan
c=json.loads((r/'evidence/CONFIRMATION.json').read_text()); f=json.loads((r/'evidence/FREEZE.json').read_text())
raw={'schema':'hcsn-r12-independent-review-v1','status':'audit_in_progress','review_scope':'Independent audit of frozen primary confirmation; no frozen source/fit/native mutation. Replay is diagnostic, not new held-out evidence.','provenance':{},'ties':[]}
for n in ['FREEZE.json','CONFIRMATION.json','SUMMARY.json']:
 raw['provenance'][n]=hashlib.sha256((r/'evidence'/n).read_bytes()).hexdigest()
for key,base in [('source_sha256',r.parent),('fit_sha256',r/'evidence')]:
 raw['provenance'][key]=[{'path':n,'expected':v,'actual':hashlib.sha256((base/n).read_bytes()).hexdigest(),'match':hashlib.sha256((base/n).read_bytes()).hexdigest()==v} for n,v in f[key].items()]
raw['provenance']['library_sha256']=hashlib.sha256((r/'native/evidence/build/libhcsn_native.so').read_bytes()).hexdigest()
raw['provenance']['library_match']=raw['provenance']['library_sha256']==f['native_library_sha256']
raw['provenance']['confirmation_freeze_match']=c['freeze_sha256']==raw['provenance']['FREEZE.json']
true=true_model()
for row in c['results']:
 diffs=np.flatnonzero(np.any(np.asarray(row['arms']['D']['actions'])!=np.asarray(row['arms']['HMM']['actions']),axis=1))
 if len(diffs)==0: continue
 seed,domain=row['seed'],row['domain']; times=PROTOCOL[domain+'_dt']; data_seed=seed+(400000 if domain=='iid' else 500000)
 fit=json.loads((r/'evidence/fits'/f'{seed}_hx_distribution.json').read_text()); shared={k:np.asarray(v) for k,v in fit['shared_model'].items()}; runs={}
 for arm,core in [('D','hx_distribution'),('HMM','generic_hmm')]:
  world=EvidenceWorld(data_seed+1000000,PROTOCOL['confirmation_episodes_per_domain'],true,times)
  est=Estimator(core,world.count,shared,times,r/'evidence/fits'/f'{seed}_hx_distribution.json')
  active=np.ones(world.count,dtype=bool); budget=np.full(world.count,PROTOCOL['read_budget']); history=np.full((world.count,3),-1,dtype=int); tokens_acq=np.full((world.count,3),-1,dtype=int); states={}
  for step in range(3):
   rows=np.flatnonzero(active); actions=np.full(world.count,-1,dtype=int)
   for j,dt in enumerate(times):
    for remaining in range(3):
     selected=rows[(world.dt_indices[step,rows]==j)&(budget[rows]==remaining)]
     if not len(selected): continue
     planned=plan(est.p[selected],est.transitions[j],shared['emission'],shared['answer_rewards'],shared['read_cost'],horizon=3-step,budget=remaining,dt=dt)
     actions[selected]=planned.action
     for batch,episode in enumerate(selected):
      if episode not in diffs: continue
      qs=planned.qvalues[batch]; p=est.p[episode]
      states[(int(episode),step)]={'step':step,'dt':dt,'remaining_budget':remaining,'history_before':history[episode,:step].tolist(),'tokens_before':tokens_acq[episode,:step].tolist(),'joint_belief':p.tolist(),'belief_mass':float(p.sum()),'content_belief':p.reshape(2,-1).sum(-1).tolist(),'qvalues':[float(x) if np.isfinite(x) else None for x in qs],'q0_minus_q1':float(qs[0]-qs[1]),'action':int(actions[episode])}
   history[rows,step]=actions[rows]; terminal=rows[actions[rows]<2]; active[terminal]=False; advance=rows[actions[rows]>=2]
   if not len(advance):continue
   world.advance(step,advance); indices=world.dt_indices[step,advance]; read=advance[actions[advance]==3]
   tokens=np.zeros(world.count,dtype=int); observed=np.zeros(world.count,dtype=bool); tokens[read]=world.read(step,read); observed[read]=True; tokens_acq[read,step]=tokens[read]; budget[read]-=1
   for j,dt in enumerate(times):
    selected=advance[indices==j]
    if len(selected):est.update(selected,j,dt,tokens[selected],observed[selected])
  assert history.tolist()==row['arms'][arm]['actions'],(seed,domain,arm,'actions')
  assert tokens_acq.tolist()==row['arms'][arm]['acquired_tokens'],(seed,domain,arm,'tokens')
  runs[arm]=states
 for episode in diffs:
  trace=[]
  for step in range(3):
   dd,hh=runs['D'].get((int(episode),step)),runs['HMM'].get((int(episode),step))
   if dd is None or hh is None:continue
   trace.append({'D':dd,'HMM':hh,'belief_max_abs_difference':float(np.max(np.abs(np.array(dd['joint_belief'])-np.array(hh['joint_belief']))))})
  event={'seed':seed,'domain':domain,'episode_index_zero_based':int(episode),'terminal_state_for_scoring':row['arms']['D']['latent_at_answer_for_scoring_only'][episode],'D_utility':row['arms']['D']['utility'][episode],'HMM_utility':row['arms']['HMM']['utility'][episode],'trace':trace,'replay_matches_frozen':True}
  raw['ties'].append(event)
  final=trace[-1]; print(json.dumps({'seed':seed,'domain':domain,'episode':int(episode),'dt':final['D']['dt'],'D_q':final['D']['qvalues'][:2],'HMM_q':final['HMM']['qvalues'][:2],'D_gap':final['D']['q0_minus_q1'],'HMM_gap':final['HMM']['q0_minus_q1'],'belief_maxdiff':final['belief_max_abs_difference'],'D_action':final['D']['action'],'HMM_action':final['HMM']['action']}))
(r/'review').mkdir(exist_ok=True); (r/'review/raw.json').write_text(json.dumps(raw,indent=2)+'\n')
