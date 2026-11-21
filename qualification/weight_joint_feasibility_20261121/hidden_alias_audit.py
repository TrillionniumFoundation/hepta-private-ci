"""One0.5CPU metadata scan of saved checked H; no model/solver execution."""
import time
import signal
signal.setitimer(signal.ITIMER_PROF,max(.001,.5-time.process_time()))
from pathlib import Path
import json,hashlib
import numpy as np

ROOT=Path(__file__).resolve().parent
out=ROOT/'posthoc_hidden_alias';out.mkdir(exist_ok=False)
p=json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text());records=[]
for fit in p['fits']:
    spec=p['inputs'][str(fit)];source=ROOT/'posthoc_continuation_only'
    result=json.loads((source/f'fit_{fit}.json').read_text())
    hp=source/result['checked_H_path'];assert hashlib.sha256(hp.read_bytes()).hexdigest()==result['checked_H_sha256']
    H=np.load(hp,allow_pickle=False)
    ap=source/result['solver_arrays_path'];assert hashlib.sha256(ap.read_bytes()).hexdigest()==result['solver_arrays_sha256']
    with np.load(ap,allow_pickle=False) as z:ids=z['H_row_ids']
    with np.load(spec['data'],allow_pickle=False) as z:mask=z['legal_masks']
    with np.load(spec['teacher'],allow_pickle=False) as z:q=z['own_optimal_targets'][:,:3];post=z['own_posterior']
    with np.load(spec['discovery_arrays'],allow_pickle=False) as z:target=z['own_actions'];occ=z['incumbent_eligible_occupancy']
    own=np.column_stack([np.zeros(len(target)),q,1-2*post,2*post-1]);groups={}
    for k,row in enumerate(ids):groups.setdefault(H[k].tobytes()+mask[row].tobytes(),[]).append(int(row))
    conflicts=[];mass=0.;miss=0.;regret=0.
    for key,items in groups.items():
        ix=np.asarray(items);t=target[ix]
        if len(np.unique(t))<2:continue
        legal=np.flatnonzero(mask[ix[0]]);w=occ[ix]
        per=np.maximum(0.,own[ix,t,None]-own[ix][:,legal])
        m=float(w.sum());error=max(0.,m-float(np.bincount(t,weights=w,minlength=6).max()));value=float((w[:,None]*per).sum(0).min())
        mass+=m;miss+=error;regret+=value
        conflicts.append(dict(H_plus_mask_sha256=hashlib.sha256(key).hexdigest(),rows=ix.tolist(),targets=t.tolist(),
            mask=mask[ix[0]].tolist(),occupied_mass=m,minimum_unavoidable_target_disagreement=error,
            minimum_unavoidable_own_Q_regret=value,own_scores=own[ix].tolist(),common_exact_optimal_actions=legal[np.all(per==0,axis=0)].tolist()))
    record=dict(fit=fit,selected_rows=len(ids),groups=len(groups),conflicting_groups=len(conflicts),
        involved_occupied_mass=mass,minimum_unavoidable_target_disagreement=miss,minimum_unavoidable_own_Q_regret=regret,
        conflicts=conflicts,source_full_H_sha256=result['source_hidden_sha256'],source_selected_H_sha256=result['checked_H_sha256'])
    with (out/f'fit_{fit}.json').open('x') as f:json.dump(record,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    records.append(record)
r=dict(schema='hepta-saved-hidden-alias-posthoc-v1',status='COMPLETED',posthoc=True,model_forwards=0,optimizer_calls=0,
    original_H_not_recovered_again=True,CPU_seconds=time.process_time(),CPU_hard_timer_seconds=.5,
    same_full_legal_mask_required=True,records=records,scope='Only stored positive-occupancy continuation-target H rows from the necessary subset; exact target mismatch and own-Q regret kept separate.')
with (out/'SUMMARY.json').open('x') as f:json.dump(r,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
print(json.dumps({'status':r['status'],'CPU_seconds':r['CPU_seconds'],'conflicting_groups':[x['conflicting_groups'] for x in records]}))
