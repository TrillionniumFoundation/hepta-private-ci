"""Read-only R7 audit: independent references, raw scores, weights and no-dense claims."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
import numpy as np


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify(source, root, out):
    sys.path.insert(0,str(source.resolve()))
    import torch
    from run_matrix_free import (digest,dump,save,sources,specs,name_for,panels,probe,
                                 gradient_at,Policy,rule,make_problem,evaluate)
    import reference

    begin=time.process_time(),time.perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((root/'PLAN.json').read_text())
    complete=json.loads((root/'COMPLETE.json').read_text())
    require(complete['plan_sha256']==digest((root/'PLAN.json').read_bytes()),'plan hash mismatch')
    require(plan['source']==sources(),'source mismatch')
    require(plan['specs']==specs(),'experiment specification mismatch')
    require([e['name'] for e in complete['census']]==[name_for(s) for s in specs()],'census mismatch')
    require(complete['completed']==39 and complete['failed']==0,'execution failures')
    require(digest((root/'EVALUATION_LAWS.npz').read_bytes())==plan['evaluation_sha256'],'evaluation law hash mismatch')
    law=np.load(root/'EVALUATION_LAWS.npz',allow_pickle=False)
    plist=list(panels())
    for name,s,w,p,scope in plist:
        require(np.array_equal(s,law[name+'_states']) and np.array_equal(w,law[name+'_weights']),
                'evaluation law content mismatch')
    now=time.process_time()
    p=make_problem();ss=probe(0)[:8];refs=[]
    for state in ss:
        for mode in (0,1):
            r=reference.solve(p,state,mode)
            refs.append({k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in r.items()})
    dump(out/'REFERENCE_BOUNDS.json',refs)
    reference_cpu=time.process_time()-now
    lower=np.array([r['lower'] for r in refs])
    upper=np.array([r['upper'] for r in refs])
    rows=[];summaries={};reports={};maxreplay=0.;entries=0;independent_max=0.;changed=0;panel_count=0
    for entry in complete['census']:
        require(entry['status']=='completed','failed member')
        folder=root/entry['name'];data=(folder/'REPORT.json').read_bytes();r=json.loads(data)
        require(digest(data)==entry['report_sha256'],'report hash mismatch')
        child=json.loads((folder/'PLAN.json').read_text())
        require(r['spec']==child['spec']==entry['spec'],'identity mismatch')
        require(r['source']==child['source']==plan['source'],'child source mismatch')
        require(r['budget']==child['budget']==plan['budget'],'budget mismatch')
        require(r['plan_sha256']==digest((folder/'PLAN.json').read_bytes()),'child plan mismatch')
        require(digest((folder/'TRAIN_LAWS.npz').read_bytes())==r['law_sha256'],'training law hash mismatch')
        tlaw=np.load(folder/'TRAIN_LAWS.npz',allow_pickle=False)
        for rr in ('cc3','cc5'):
            s,w=rule(rr)
            require(np.array_equal(s,tlaw[rr+'_states']) and np.array_equal(w,tlaw[rr+'_weights']),
                    'training law content mismatch')
        policy=Policy('nonlinear',r['spec']['seed'])
        init=np.load(folder/'INITIAL.npz',allow_pickle=False)['theta']
        theta=np.load(folder/'WEIGHTS.npz',allow_pickle=False)['theta']
        require(np.array_equal(init,policy.initial),'initial bytes mismatch')
        require(digest(init.tobytes())==r['initial_sha256'],'initial hash mismatch')
        require(digest(theta.tobytes())==r['weights_sha256'],'weight hash mismatch')
        require(theta.shape==(78,) and np.isfinite(theta).all(),'invalid weights')
        wseal=json.loads((folder/'WEIGHT_SEAL.json').read_text())
        require(wseal['sha256']==r['weights_sha256'],'weight seal mismatch')
        predseal=json.loads((folder/'PREDICTIONS_SEAL.json').read_text())
        require(digest((folder/'PREDICTIONS.npz').read_bytes())==predseal['sha256']==r['prediction_sha256'],
                'prediction hash mismatch')
        require(predseal['weights']==r['weights_sha256'],'prediction weight mismatch')
        delta=not np.array_equal(theta,init);changed+=int(delta)
        require(delta==r['changed'],'changed flag mismatch')
        if r['spec']['method']=='none':
            require(not delta,'untrained control changed')
        if r['spec']['method'] in ('adjoint_ncg','ad_ncg'):
            require(r['fit']['counts']['full_hessians']==0,'matrix-free dense fallback')
            require(r['fit']['counts']['hvp']>0,'matrix-free computation missing')
        z=torch.tensor(theta);raw=np.load(folder/'PREDICTIONS.npz',allow_pickle=False)
        for name,s,w,pp,scope in plist:
            val=raw[name];again=evaluate(policy,z,pp,s)
            diff=float(np.max(np.abs(val-again)))
            require(diff<1e-13,'replay mismatch')
            cost=float(w@val.mean(1))
            require(np.isclose(cost,r['metrics'][name],rtol=1e-12,atol=1e-14),'metric mismatch')
            rows.append(dict(run=entry['name'],**r['spec'],panel=name,scope=scope,cost=cost,
                             training_cost=r['training_cost'],fit_cpu=r['fit']['cpu'],
                             fit_rss=r['fit_peak_rss'],hvp=r['fit']['counts']['hvp'],
                             full_hessians=r['fit']['counts']['full_hessians'],
                             updates=r['fit']['counts']['updates'],child_cpu=entry['child_cpu'],
                             child_wall=entry['child_wall']))
            maxreplay=max(maxreplay,diff);entries+=val.size;panel_count+=1
        with torch.no_grad():
            v,L,_,_,_=policy.tree(z,p,ss[:2])
        require(np.array_equal(v.numpy(),raw['check_costs']),'action check values changed')
        entries+=raw['check_costs'].size
        for k,item in enumerate(L):
            require(np.array_equal(item['u'].numpy(),raw[f'check_actions{k}']),'saved actions mismatch')
            require(float(item['u'].abs().max())<=p.bound+1e-13,'infeasible action')
            entries+=item['u'].numel()
        for j in range(4):
            actions=np.concatenate([raw[f'check_actions{k}'][j*2**k:(j+1)*2**k].flatten() for k in range(3)])
            value=reference.evaluate(actions,p,reference.build(p,ss[j//2],j%2),False)[0]
            discrepancy=abs(value-float(v[j]))
            require(discrepancy<1e-12,'independent action implementation mismatch')
            independent_max=max(independent_max,discrepancy)
        refvalues=evaluate(policy,z,p,ss).reshape(-1)
        require(np.all(refvalues>=lower-1e-10),'reference lower bound violated')
        diag=np.load(folder/'DIAGNOSTICS.npz',allow_pickle=False)
        for rr,key in [('cc5','g5'),('cc9','g9')]:
            grad=gradient_at(policy,z,rr).numpy()
            require(np.allclose(grad,diag[key],atol=1e-12,rtol=1e-11),'gradient diagnostic mismatch')
            require(np.isclose(np.max(np.abs(grad)),r['diagnostics'][key+'_inf'],atol=1e-13),
                    'gradient metric mismatch')
        q=np.array([r['metrics'][f'qmc{k}'] for k in range(4)])
        require(np.isclose(q.mean(),r['integration']['qmc_mean'],atol=1e-14),'QMC mean mismatch')
        require(np.isclose(q.std(ddof=1)/2,r['integration']['qmc_se'],atol=1e-14),'QMC SE mismatch')
        reports[entry['name']]=r
        summaries[entry['name']]=dict(**r['spec'],cost=r['metrics']['cc17'],qmc=float(q.mean()),
            gradient9=r['diagnostics']['g9_inf'],fit_cpu=r['fit']['cpu'],fit_rss=r['fit_peak_rss'],
            reference_subset_regret_lower=float((refvalues-upper).mean()),
            reference_subset_regret_upper=float((refvalues-lower).mean()),
            promotion_reason=r['fit']['promotion_reason'],counts=r['fit']['counts'])
    pairs=[]
    for schedule in ('cc3','cc5','adaptive'):
        for seed in (11,23,47):
            b=reports[f'adam-{schedule}-s{seed}'];c=reports[f'adjoint_ncg-{schedule}-s{seed}']
            require(b['initial_sha256']==c['initial_sha256'],'B/C initialization mismatch')
            if schedule!='adaptive':
                require(b['law_sha256']==c['law_sha256'],'B/C training law mismatch')
            diffs=np.array([c['metrics'][f'qmc{k}']-b['metrics'][f'qmc{k}'] for k in range(4)])
            pairs.append(dict(schedule=schedule,seed=seed,B=b['metrics']['cc17'],C=c['metrics']['cc17'],
                              C_minus_B=c['metrics']['cc17']-b['metrics']['cc17'],
                              qmc_difference=float(diffs.mean()),qmc_difference_se=float(diffs.std(ddof=1)/2)))
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    dump(out/'PAIRED.json',pairs);dump(out/'SUMMARY.json',summaries)
    result=dict(runs=39,changed_models=changed,panels=panel_count,scalar_entries=entries,
                max_replay_difference=maxreplay,paired_initializations=len(pairs),
                independent_action_checks=39*4,independent_cost_max_error=independent_max,
                reference_cases=len(refs),reference_lower=float(lower.mean()),reference_upper=float(upper.mean()),
                reference_max_width=float((upper-lower).max()),reference_cpu=reference_cpu,
                reference_scope='first eight fresh states, richer adapted-action policies, not full population',
                audit_cpu=time.process_time()-begin[0],audit_wall=time.perf_counter()-begin[1],
                source=sources(),production_authorized=False)
    dump(out/'AUDIT.json',result)
    return result


if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--source',type=Path,required=True)
    a.add_argument('--runs',type=Path,required=True)
    a.add_argument('--out',type=Path,required=True)
    v=a.parse_args()
    print(json.dumps(verify(v.source,v.runs,v.out),sort_keys=True))
