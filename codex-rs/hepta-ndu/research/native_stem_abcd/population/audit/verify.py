"""Read-only R4 audit; scalar/root Hessian inspection is explicitly post hoc."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import numpy as np


def require(ok,message):
    if not ok:raise ValueError(message)


def verify(source,runs,out):
    sys.path.insert(0,str(source.resolve()))
    import torch
    from torch.func import grad,jacfwd
    from experiment import sources,specs,name_for,panels,model_for,digest,write,score,to_arrays
    from problem import (make_problem,initial_states,initial_moments,policy_value,enumerate_policy,riccati,
                         MatrixStem,scalar_lower_bound)
    from reference import dense_tree_reference
    from solve import assign,vector
    t=time.process_time(),time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((runs/'PLAN.json').read_text());complete=json.loads((runs/'COMPLETE.json').read_text())
    require(complete['plan_sha256']==digest((runs/'PLAN.json').read_bytes()),'sweep plan mismatch')
    require(plan['source_sha256']==sources(),'source drift')
    require(plan['runs']==specs(),'different preregistered run list')
    require([r['name'] for r in complete['census']]==[name_for(s) for s in specs()],'incomplete census')
    require(complete['completed']==29 and complete['failed']==0,'incomplete success')
    records={};rows=[];replaymax=0.;leafpaths=0;changed=0;root_checks=[]
    # Independent stochastic-action QPs, not the backward value recursion.
    independent=[]
    for mode in range(2):
        p=make_problem();s=initial_states()[7+mode];K,P,c,_=riccati(p)
        q=dense_tree_reference(p,s,mode)
        require(abs(q['cost']-(s@P[mode]@s+c[mode]))<1e-11,'QP reference disagreement')
        require(np.max(np.abs(q['first_action']-K[0,mode]@s))<1e-11,'QP action disagreement')
        q['first_action']=q['first_action'].tolist();q['mode']=mode;independent.append(q)
    for e in complete['census']:
        folder=runs/e['name'];data=(folder/'REPORT.json').read_bytes();r=json.loads(data)
        require(e['status']=='completed' and digest(data)==e['report_sha256'],'run report failure')
        child=json.loads((folder/'PLAN.json').read_text())
        require(r['run']==e['run']==child['run'],'run identity mismatch')
        require(r['plan_sha256']==digest((folder/'PLAN.json').read_bytes()),'child plan hash')
        require(child['source_sha256']==plan['source_sha256'],'child source identity')
        seal=json.loads((folder/'PREDICTIONS_SEAL.json').read_text())
        require(digest((folder/'PREDICTIONS.npz').read_bytes())==seal['sha256']==r['prediction_sha256'],'prediction bytes')
        weight=np.load(folder/'WEIGHTS.npy',allow_pickle=False)
        require(digest(weight.tobytes())==seal['weights']==r['selected_sha256'],'weight identity')
        s=e['run'];model=model_for(s['family'],s['seed'])
        if model is not None:
            init=np.load(folder/'INITIAL.npy',allow_pickle=False)
            require(np.array_equal(vector(model),init),'initialization mismatch')
            require(digest(init.tobytes())==r['initial_sha256'],'initial hash')
            different=not np.array_equal(init,weight);changed+=int(different)
            require(different==(s['method']!='none'),'false fitted/untrained status')
            assign(model,weight)
        else:require(np.array_equal(weight,riccati(make_problem())[0].reshape(-1)),'direct coefficient identity')
        raw=np.load(folder/'PREDICTIONS.npz',allow_pickle=False)
        with torch.no_grad():
            for name,change,split in panels():
                p=make_problem(change);st=initial_states(split)
                arr={k.split('__')[1]:raw[k] for k in raw.files if k.startswith(name+'__')}
                actual=score(arr,p,st)
                for k,v in actual.items():
                    require(r['metrics'][name][k] is None if v is None else
                            np.isclose(r['metrics'][name][k],v,rtol=1e-12,atol=1e-14),'metric mismatch: '+k)
                gain=torch.tensor(riccati(p)[0]) if model is None else None
                replay=to_arrays(enumerate_policy(model,p,st,gains=gain))
                for k,v in replay.items():
                    err=float(np.max(np.abs(v-arr[k])));require(err<1e-12,'raw replay mismatch')
                    replaymax=max(replaymax,err)
                require(actual['objective_gap']>-1e-10,'violates optimal lower bound')
                mass=np.bincount(arr['origin'],weights=arr['prob'],minlength=actual['initial_cases'])
                require(np.max(np.abs(mass-1))<1e-12,'probability mass failure')
                leafpaths+=actual['leaf_cases']
                rows.append(dict(run=e['name'],**s,panel=name,**actual,fit_cpu=r['fit']['cpu_seconds'],
                                 child_cpu=e['child_cpu'],child_wall=e['child_wall'],peak_rss=r['peak_rss_bytes']))
        if isinstance(model,MatrixStem) and s['method']=='gradient_root':
            p=make_problem();w=p.tensors();M=initial_moments(initial_states());shape=model.weights.shape
            def J(v):
                P,c,_=policy_value(model.gains(v.reshape(shape)),w,p.gamma,3)
                return (P[0]*M).sum()+c[0].mean()
            v=torch.tensor(weight);g=grad(J)(v);H=jacfwd(grad(J))(v)
            root_checks.append(dict(run=e['name'],gradient_max=float(g.abs().max()),
                                    minimum_hessian_eigenvalue=float(torch.linalg.eigvalsh(H).min()),
                                    posthoc=True,used_for_selection=False))
        records[e['name']]=r
    pairs=[]
    for cap in (2,8):
        for seed in (11,23,47):
            b=records[f'matrix-adam-s{seed}-b{cap}'];c=records[f'matrix-adjoint-s{seed}-b{cap}']
            require(b['initial_sha256']==c['initial_sha256'],'B/C initial mismatch')
            pairs.append(dict(cap=cap,seed=seed,B=b['metrics']['new_initial']['objective_gap'],
                              C=c['metrics']['new_initial']['objective_gap']))
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    write(out/'PAIRED.json',pairs);write(out/'ROOT_DIAGNOSTICS.json',root_checks)
    write(out/'INDEPENDENT_QP.json',independent);write(out/'SCALAR_LOWER_BOUND.json',scalar_lower_bound(make_problem()))
    receipt=dict(verified_runs=29,verified_panels=len(rows),verified_leaf_paths=leafpaths,
                 changed_models=changed,saved_weight_files=29,bc_initial_pairs=len(pairs),max_replay_error=replaymax,
                 source_sha256=sources(),cpu_seconds=time.process_time()-t[0],wall_seconds=time.perf_counter()-t[1],
                 posthoc_audit_not_selection=True,production_authorized=False)
    write(out/'AUDIT.json',receipt);print(json.dumps(receipt),flush=True)
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();verify(a.source,a.runs,a.out)
