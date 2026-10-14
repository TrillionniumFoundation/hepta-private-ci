"""R6 read-only raw replay, integration diagnostics and finite-subset reference bounds."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import numpy as np


def require(ok,message):
    if not ok: raise ValueError(message)


def verify(source,root,out):
    sys.path.insert(0,str(source.resolve()))
    import torch
    from domain import Policy,make_problem,rule,probe,evaluate
    from run_continuous import digest,dump,save,sources,specs,name_for,panels,gradient_at
    import reference
    t=time.process_time(),time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((root/'PLAN.json').read_text());complete=json.loads((root/'COMPLETE.json').read_text())
    require(complete['plan_sha256']==digest((root/'PLAN.json').read_bytes()),'plan hash mismatch')
    require(plan['source']==sources(),'source mismatch')
    require(plan['runs']==specs(),'spec mismatch')
    require([r['name'] for r in complete['census']]==[name_for(s) for s in specs()],'census mismatch')
    require(complete['complete']==43 and complete['failed']==0,'incomplete run')
    require(digest((root/'EVALUATION_LAWS.npz').read_bytes())==plan['evaluation_laws_sha256'],'evaluation law hash mismatch')
    laws=np.load(root/'EVALUATION_LAWS.npz',allow_pickle=False);plist=list(panels())
    for name,s,w,p,scope in plist:
        np.testing.assert_array_equal(s,laws[name+'_states']);np.testing.assert_array_equal(w,laws[name+'_weights'])
    # Reference is first requested after the complete sweep and seals exist.
    now=time.process_time();p=make_problem();ss=probe(0)[:16];refs=[]
    for state in ss:
        for mode in (0,1):
            r=reference.solve(p,state,mode);refs.append({k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in r.items()})
    dump(out/'REFERENCE_BOUNDS.json',refs);refcpu=time.process_time()-now
    lower=np.array([r['lower'] for r in refs]);upper=np.array([r['upper'] for r in refs])
    rows=[];reports={};replaymax=0.;array_entries=0;npmax=0.;changed=0;panelcount=0
    for entry in complete['census']:
        folder=root/entry['name'];require(entry['status']=='complete','failed run')
        data=(folder/'REPORT.json').read_bytes();r=json.loads(data)
        require(digest(data)==entry['report_sha256'],'report hash mismatch')
        child=json.loads((folder/'PLAN.json').read_text());spec=entry['spec']
        require(r['spec']==child['spec']==spec,'identity mismatch')
        require(r['source']==child['source']==plan['source'],'child source mismatch')
        require(r['budget']==child['budget']==plan['budget'],'budget mismatch')
        require(r['plan_sha256']==digest((folder/'PLAN.json').read_bytes()),'child plan mismatch')
        law=np.load(folder/'TRAIN_LAW.npz',allow_pickle=False);s,w=rule(spec['rule'])
        require(digest((folder/'TRAIN_LAW.npz').read_bytes())==r['law_sha256'],'training law hash mismatch')
        require(np.array_equal(law['states'],s) and np.array_equal(law['weights'],w),'training integration weights mismatch')
        pol=Policy(spec['family'],spec['seed']);init=np.load(folder/'INITIAL.npz',allow_pickle=False)['theta']
        z=np.load(folder/'WEIGHTS.npz',allow_pickle=False)['theta']
        np.testing.assert_array_equal(pol.initial,init)
        require(digest(init.tobytes())==r['initial_sha256'],'initial hash mismatch')
        require(digest(z.tobytes())==r['weight_sha256'],'weight hash mismatch')
        seal=json.loads((folder/'PREDICTIONS_SEAL.json').read_text())
        require(digest((folder/'PREDICTIONS.npz').read_bytes())==r['prediction_sha256']==seal['sha256'],'prediction hash mismatch')
        require(seal['weights']==r['weight_sha256'],'prediction weight mismatch')
        delta=not np.array_equal(z,init);changed+=int(delta)
        if spec['method']=='none':require(not delta,'untrained control changed')
        raw=np.load(folder/'PREDICTIONS.npz',allow_pickle=False);theta=torch.tensor(z);costs={}
        for name,state,weight,pp,scope in plist:
            val=raw[name];again=evaluate(pol,theta,pp,state)
            err=float(np.max(np.abs(val-again)));require(err<=1e-13,'replay mismatch')
            require(np.isfinite(val).all(),'nonfinite raw')
            cost=float(weight@val.mean(1));require(np.isclose(cost,r['metrics'][name],atol=1e-14,rtol=1e-12),'metric mismatch')
            costs[name]=cost;panelcount+=1;array_entries+=val.size;replaymax=max(replaymax,err)
            rows.append(dict(run=entry['name'],**spec,panel=name,scope=scope,cost=cost,
                             fit_cpu=r['fit']['cpu'],child_cpu=entry['child_cpu'],child_wall=entry['child_wall'],peak_rss=r['peak_rss']))
        q=np.array([costs[f'qmc{k}'] for k in range(4)])
        integration=dict(cc17_minus_cc9=costs['cc17']-costs['cc9'],cc17_minus_gl9=costs['cc17']-costs['gl9'],
                         qmc_mean=float(q.mean()),qmc_se=float(q.std(ddof=1)/2),qmc_minus_cc17=float(q.mean()-costs['cc17']))
        for k,v in integration.items():require(np.isclose(v,r['integration'][k],atol=1e-14,rtol=1e-12),'integration metric mismatch')
        with torch.no_grad():
            training=float(pol.value(theta,p,s,w,spec['ridge']));cv,L,tilts,end,_=pol.tree(theta,p,ss)
        require(np.isclose(training,r['train_objective'],atol=1e-14,rtol=1e-12),'training objective mismatch')
        for key,value in [('ref_cost',cv.numpy()),('ref_errors',end['errors'].numpy()),('ref_mass',end['mass'].numpy())]:
            np.testing.assert_array_equal(raw[key],value);array_entries+=value.size
        for k,Lk in enumerate(L):
            np.testing.assert_array_equal(raw[f'ref_actions{k}'],Lk['u'].numpy());array_entries+=Lk['u'].numel()
            require(float(Lk['u'].abs().max())<=p.bound+1e-14,'infeasible action')
        # Independent action-coordinate reference reevaluates first TWO initial states, both regimes.
        for j in range(4):
            actions=np.concatenate([raw[f'ref_actions{k}'][j*2**k:(j+1)*2**k].flatten() for k in range(3)])
            val=reference.evaluate(actions,p,reference.build(p,ss[j//2],j%2),False)[0]
            error=abs(val-float(raw['ref_cost'][j]));require(error<1e-12,'independent implementation mismatch');npmax=max(npmax,error)
        diag=np.load(folder/'DIAGNOSTICS.npz',allow_pickle=False)
        for rr in ('cc5','cc9'):
            g=gradient_at(pol,theta,p,rr).numpy();np.testing.assert_allclose(diag[rr],g,atol=1e-12,rtol=1e-11)
        require(np.isclose(np.max(np.abs(diag['cc9']-diag['cc5'])),r['diagnostics']['gradient_rule_difference_inf'],atol=1e-13),'gradient metric mismatch')
        require(np.all(raw['ref_cost']>=lower-1e-10),'reference lower bound violated')
        reports[entry['name']]=dict(**spec,train=r['train_objective'],cc17=costs['cc17'],**integration,
                                   ref_subset_regret_lower=float(np.mean(raw['ref_cost']-upper)),
                                   ref_subset_regret_upper=float(np.mean(raw['ref_cost']-lower)),fit_cpu=r['fit']['cpu'],
                                   hessian_min=r['diagnostics']['training_hessian_min'],grad9=r['diagnostics']['cc9_gradient_inf'])
    pairs=[]
    for spec in specs():
        if spec['family']=='nonlinear' and spec['method']=='adjoint':
            bspec=dict(spec,method='adam');bname=name_for(bspec);cname=name_for(spec)
            br=json.loads((root/bname/'REPORT.json').read_text());cr=json.loads((root/cname/'REPORT.json').read_text())
            require(br['initial_sha256']==cr['initial_sha256'],'B/C initialization mismatch')
            b,c=reports[bname],reports[cname]
            pairs.append(dict(rule=spec['rule'],ridge=spec['ridge'],seed=spec['seed'],B=b['cc17'],C=c['cc17'],
                              C_minus_B=c['cc17']-b['cc17'],qmc_C_minus_B=c['qmc_mean']-b['qmc_mean']))
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    dump(out/'SUMMARY.json',reports);dump(out/'PAIRED.json',pairs)
    result=dict(verified_runs=43,changed_models=changed,verified_panels=panelcount,verified_scalar_entries=array_entries,
                replay_max_error=replaymax,independent_reference_checks=172,independent_cost_max_error=npmax,
                reference_cases=32,max_reference_width=float(np.max(upper-lower)),reference_cpu=refcpu,
                mean_reference_lower=float(lower.mean()),mean_reference_upper=float(upper.mean()),
                reference_is_finite_subset_not_full_population=True,bc_pairs=len(pairs),
                audit_cpu=time.process_time()-t[0],audit_wall=time.perf_counter()-t[1],source=sources(),
                certified_integration_error=False,production_authorized=False)
    dump(out/'AUDIT.json',result);return result


def main():
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--runs',type=Path,required=True)
    a.add_argument('--out',type=Path,required=True);v=a.parse_args();print(json.dumps(verify(v.source,v.runs,v.out),sort_keys=True))

if __name__=='__main__':main()
