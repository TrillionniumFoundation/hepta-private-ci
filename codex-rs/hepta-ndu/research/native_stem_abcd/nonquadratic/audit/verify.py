"""R5 read-only replay followed by independent convex-reference regret bounds."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import numpy as np

def require(ok,reason):
    if not ok:raise ValueError(reason)

def verify(source,runs,out,precheck=False):
    sys.path.insert(0,str(source.resolve()))
    import torch
    from experiment import Attention,avector,restore_attention,sources,panels,cases,name_for,dump,digest,save
    from problem import initial,initial_weights,make_problem,rollout
    from reference import solve,build,evaluate
    t=time.process_time();wall=time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((runs/'PLAN.json').read_text());comp=json.loads((runs/'COMPLETE.json').read_text())
    require(comp['plan_sha256']==digest((runs/'PLAN.json').read_bytes()),'sweep plan mismatch')
    require(plan['source']==sources(),'source mismatch')
    require(plan['runs']==cases(),'case drift')
    require([r['name'] for r in comp['census']]==[name_for(s) for s in cases()],'incomplete census')
    require(comp['complete']==35 and comp['failed']==0,'failed attempts')
    reports={};predictions={};replayed=0;scalar_values=0;maxerr=0.;pairs=0;changed=0
    for entry in comp['census']:
        root=runs/entry['name'];data=(root/'REPORT.json').read_bytes();r=json.loads(data)
        require(digest(data)==entry['report_sha256'],'report hash mismatch')
        cp=json.loads((root/'PLAN.json').read_text())
        require(digest((root/'PLAN.json').read_bytes())==r['plan_sha256'],'child plan mismatch')
        require(r['spec']==cp['spec']==entry['spec'],'run identity mismatch')
        require(cp['source']==plan['source']==r['source'],'child source mismatch')
        rawbytes=(root/'PREDICTIONS.npz').read_bytes();seal=json.loads((root/'PREDICTIONS_SEAL.json').read_text())
        require(digest(rawbytes)==seal['sha256']==r['prediction_sha256'],'prediction seal mismatch')
        theta=np.load(root/'WEIGHTS.npz',allow_pickle=False)['theta'];init=np.load(root/'INITIAL.npz',allow_pickle=False)['theta']
        require(digest(theta.tobytes())==r['weight_sha256']==seal['weights'],'weight hash mismatch')
        require(digest(init.tobytes())==r['initial_sha256'],'initial hash mismatch')
        s=r['spec'];m=Attention(s['seed']) if s['family']=='attention' else None
        expected=avector(m) if m else initial_weights(s['seed'],s['family'])
        np.testing.assert_array_equal(init,expected)
        require(len(theta)==r['parameters'],'parameter count')
        changed+=int(not np.array_equal(init,theta))
        if s['method']=='none':np.testing.assert_array_equal(init,theta)
        if m:restore_attention(m,theta)
        raw=np.load(root/'PREDICTIONS.npz',allow_pickle=False)
        for name,split,change in panels():
            p=make_problem(change);states=initial(split)
            np.testing.assert_array_equal(raw[name+'_initial'],states)
            with torch.no_grad():v,L,_,end,_=rollout(torch.tensor(theta),p,states,s['family'],m)
            values={'cost':v.numpy(),'states':end['h'].numpy(),'errors':end['errors'].numpy(),'mass':end['mass'].numpy()}
            for k,item in enumerate(L):values[f'actions_{k}']=item['u'].numpy()
            for suffix,array in values.items():
                error=float(np.max(np.abs(array-raw[name+'_'+suffix])))
                require(error<=1e-13,'saved-model replay mismatch');maxerr=max(maxerr,error);scalar_values+=array.size
            masses=raw[name+'_mass'].reshape(len(states)*2,-1)
            np.testing.assert_allclose(masses.sum(1),1.,atol=2e-14)
            for k in range(p.horizon):require(np.max(np.abs(raw[name+f'_actions_{k}']))<=p.bound+1e-13,'infeasible action')
            if name=='train':require(abs(float(v.mean())-r['train_objective'])<=1e-12,'rehashed false metric')
            replayed+=1
        reports[entry['name']]=r;predictions[entry['name']]=raw
    for family,cap in [('nonlinear',2),('nonlinear',8),('matrix',8)]:
        for seed in (11,23,47):
            b=reports[f'{family}-adam-s{seed}-b{cap}'];c=reports[f'{family}-adjoint-s{seed}-b{cap}']
            require(b['initial_sha256']==c['initial_sha256'] and b['parameters']==c['parameters'],'B/C mismatch');pairs+=1
    if precheck:
        receipt=dict(precheck_only=True,replayed=replayed,maxerr=maxerr)
        dump(out/'PRECHECK.json',receipt);return receipt
    replay_cpu=time.process_time()-t;refstart=time.process_time();reference={};refarrays={};refcalls=0
    for name,split,change in panels():
        p=make_problem(change);states=initial(split);rs=[]
        for state in states:
            for mode in (0,1):rs.append(solve(p,state,mode))
        lo=np.array([r['lower'] for r in rs]);hi=np.array([r['upper'] for r in rs])
        reference[name]=dict(lower=float(lo.mean()),upper=float(hi.mean()),
                             max_width=float(np.max(hi-lo)),max_gradient=max(r['gradient_inf'] for r in rs),
                             min_hessian=min(r['hessian_min'] for r in rs),initial_cases=len(rs))
        refarrays[name+'_lower']=lo;refarrays[name+'_upper']=hi
        refarrays[name+'_actions']=np.array([r['actions'] for r in rs])
        refcalls+=sum(r['evaluations'] for r in rs)
    reference_cpu=time.process_time()-refstart;save(out/'REFERENCES.npz',refarrays)
    rows=[];direct_crosscheck=0.;crossstart=time.process_time()
    for entry in comp['census']:
        name=entry['name'];r=reports[name];s=r['spec'];raw=predictions[name]
        for panel,split,change in panels():
            p=make_problem(change);states=initial(split);n=2*len(states)
            costs=raw[panel+'_cost'];lo=refarrays[panel+'_lower'];hi=refarrays[panel+'_upper']
            require(np.min(costs-lo)>-1e-7,'candidate violates independent lower bound')
            errors=raw[panel+'_errors'].reshape(n,-1,3);mass=raw[panel+'_mass'].reshape(n,-1)
            mse=float((mass*(errors**2).mean(-1)).sum(-1).mean())
            # Independent NumPy re-evaluation of actual actions for BOTH first initial regimes.
            for mode in (0,1):
                actions=np.concatenate([raw[panel+f'_actions_{k}'].reshape(n,-1,2)[mode].reshape(-1) for k in range(p.horizon)])
                val=evaluate(actions,p,build(p,states[0],mode),False)[0]
                err=abs(val-costs[mode]);direct_crosscheck=max(direct_crosscheck,err)
                require(err<1e-9,'independent candidate objective mismatch')
            rows.append(dict(run=name,family=s['family'],method=s['method'],seed=s['seed'],budget=s['budget'],panel=panel,
                             objective=float(costs.mean()),regret_lower=float((costs-hi).mean()),regret_upper=float((costs-lo).mean()),
                             reference_width=reference[panel]['upper']-reference[panel]['lower'],task_mse=mse,
                             fit_cpu=r['fitting']['cpu'],gradient_inf=r['diagnostics']['gradient_inf'],
                             hessian_min=r['diagnostics']['hessian_min'],parameters=r['parameters'],
                             child_cpu=entry['child_cpu'],child_wall=entry['child_wall'],peak_rss=r['peak_rss']))
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    dump(out/'REFERENCE_BOUNDS.json',reference)
    receipt=dict(runs=35,replayed_panels=replayed,replayed_scalar_entries=scalar_values,max_replay_error=maxerr,
                 fitted_arrays_changed=changed,bc_pairs=pairs,reference_cases=sum(r['initial_cases'] for r in reference.values()),
                 reference_evaluations=refcalls,max_reference_width=max(r['max_width'] for r in reference.values()),
                 independent_candidate_value_max_error=direct_crosscheck,replay_cpu=replay_cpu,reference_cpu=reference_cpu,
                 metrics_crosscheck_cpu=time.process_time()-crossstart,total_cpu=time.process_time()-t,wall=time.perf_counter()-wall,
                 interval_certified=False,no_training_or_selection=True,production_authorized=False)
    dump(out/'AUDIT.json',receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--precheck',action='store_true');a=p.parse_args()
    print(json.dumps(verify(a.source,a.runs,a.out,a.precheck),sort_keys=True))
