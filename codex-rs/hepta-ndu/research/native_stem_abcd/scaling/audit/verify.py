"""R8 read-only verification of every stopping checkpoint and sealed prediction."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
import numpy as np


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def verify(source, root, out):
    sys.path.insert(0, str(source.resolve()))
    import torch
    from run_scaling import sources, specs, name_for, panels, digest, dump
    from engine import qualifies, TARGET, TOLERANCE, CADENCE, CAP
    from wide import WidePolicy, rule, make_problem, evaluate
    import reference
    independent_error, independent_checks = 0., 0
    t, wall = time.process_time(), time.perf_counter()
    out.mkdir(parents=True, exist_ok=False)
    plan = json.loads((root/'PLAN.json').read_text()); done = json.loads((root/'COMPLETE.json').read_text())
    require(plan['source']==sources(), 'source mismatch')
    require(done['plan_sha256']==digest((root/'PLAN.json').read_bytes()), 'plan hash mismatch')
    require(plan['specs']==specs(), 'specification mismatch')
    require([e['name'] for e in done['census']]==[name_for(s) for s in specs()], 'incomplete census')
    require(done['completed']==48 and done['failed']==0, 'execution failures')
    require((plan['target'],plan['tolerance'],plan['cadence'],plan['cap'])==(TARGET,TOLERANCE,CADENCE,CAP), 'gate substituted')
    require(plan['law_hash']==digest((root/'TRAIN_LAWS.npz').read_bytes()), 'law hash mismatch')
    laws = np.load(root/'TRAIN_LAWS.npz', allow_pickle=False)
    for name in ('cc5','cc9'):
        s,w = rule(name)
        np.testing.assert_array_equal(laws[name+'_states'],s)
        np.testing.assert_array_equal(laws[name+'_weights'],w)
    rows, reports, checkpoint_count, panels_count, scalar_count, max_error = [], {}, 0, 0, 0, 0.
    for e in done['census']:
        folder = root/e['name']; require(e['status']=='completed', 'failed case')
        require(e['report_sha256']==digest((folder/'REPORT.json').read_bytes()), 'report hash mismatch')
        r = json.loads((folder/'REPORT.json').read_text()); cpplan=json.loads((folder/'PLAN.json').read_text())
        require(r['spec']==e['spec']==cpplan['spec'], 'case identity mismatch')
        require(r['source']==plan['source']==cpplan['source'], 'case source mismatch')
        require(r['plan_sha256']==digest((folder/'PLAN.json').read_bytes()), 'case plan mismatch')
        require((cpplan['target'],cpplan['integration_tolerance'],cpplan['wall_cap'])==(TARGET,TOLERANCE,CAP), 'case gate mismatch')
        info=json.loads((folder/'FIT.json').read_text()); seal=json.loads((folder/'FIT_SEAL.json').read_text())
        require(r['fit']==info, 'fit report mismatch')
        require(seal['fit_sha256']==digest((folder/'FIT.json').read_bytes()), 'fit hash mismatch')
        require(seal['checkpoints']==digest((folder/'CHECKPOINTS.npz').read_bytes()), 'checkpoint hash mismatch')
        theta=np.load(folder/'WEIGHTS.npz',allow_pickle=False)['theta']
        initial=np.load(folder/'INITIAL.npz',allow_pickle=False)['theta']
        pol=WidePolicy(e['spec']['width'],e['spec']['seed']); np.testing.assert_array_equal(initial,pol.initial)
        require(r['initial_sha256']==digest(initial.tobytes()), 'initial mismatch')
        require(seal['weights']==r['weights_sha256']==digest(theta.tobytes()), 'weight mismatch')
        require(r['parameters']==len(theta)==50+7*pol.width, 'parameter count mismatch')
        cps=np.load(folder/'CHECKPOINTS.npz',allow_pickle=False)['theta']
        require(len(cps)==len(info['checks']) and len(cps)>0, 'checkpoint census mismatch')
        eligible=[]; previous_end=-1.
        for index,(cp,ck) in enumerate(zip(cps,info['checks'])):
            require(ck['index']==index and ck['wall_start']>=previous_end and ck['wall_end']>=ck['wall_start'], 'invalid monitor timing')
            require(ck['within_cap']==(ck['wall_end']<=CAP), 'false within-cap time')
            previous_end=ck['wall_end']; costs=[]
            for name in ('cc5','cc9'):
                s,w=rule(name)
                v=evaluate(pol,torch.tensor(cp),make_problem(),s,chunk=256)
                cost=float(w@v.mean(1));costs.append(cost)
                require(np.isclose(cost,ck[name],atol=1e-13,rtol=1e-12),'monitor cost mismatch')
            good=qualifies(*costs)
            require(ck['predicate']==good,'false monitor predicate')
            if good and ck['within_cap']:eligible.append(index)
            checkpoint_count+=1
        require(info['success']==bool(eligible),'false success claim')
        if eligible:
            require(eligible[0]==len(cps)-1,'continued after success')
            require(info['observed_wall']==info['checks'][eligible[0]]['wall_end'],'false observed time')
        else:
            require(info['observed_wall'] is None,'censoring converted to success')
        np.testing.assert_array_equal(theta,cps[-1])
        require(info['wall']>=info['checks'][-1]['wall_end'],'unmetered monitoring')
        require(info['counts']['full_hessians']==0,'dense matrix-free fit')
        require(r['prediction_sha256']==digest((folder/'PREDICTIONS.npz').read_bytes()), 'prediction hash mismatch')
        raw=np.load(folder/'PREDICTIONS.npz',allow_pickle=False)
        for name,s,w,p in panels():
            value=evaluate(pol,torch.tensor(theta),p,s,chunk=256)
            err=float(np.max(np.abs(value-raw[name]))); max_error=max(max_error,err)
            require(err<=1e-13, 'replay mismatch')
            require(np.isclose(float(w@value.mean(1)),r['metrics'][name],atol=1e-13,rtol=1e-12),'metric mismatch')
            scalar_count+=value.size;panels_count+=1
        check_states = next(s for name,s,w,p in panels() if name=='qmc0')[:2]
        with torch.no_grad():
            values, levels, _, _, _ = pol.tree(torch.tensor(theta),make_problem(),check_states)
        for root_index in range(4):
            actions = np.concatenate([L['u'][root_index*2**k:(root_index+1)*2**k].numpy().reshape(-1)
                                      for k,L in enumerate(levels)])
            tree = reference.build(make_problem(), check_states[root_index//2],root_index%2)
            independent = reference.evaluate(actions,make_problem(),tree,False)[0]
            error = abs(independent-float(values[root_index]))
            require(error<=1e-12,'independent action-coordinate mismatch')
            independent_error=max(independent_error,error);independent_checks+=1
        reports[e['name']]=r
        rows.append(dict(name=e['name'],width=pol.width,parameters=len(theta),method=e['spec']['method'],seed=e['spec']['seed'],
            success=info['success'],observed_wall=info['observed_wall'],fit_wall=info['wall'],fit_cpu=info['cpu'],
            monitor_wall=info['monitor_wall'],fit_peak_rss=info['fit_peak_rss'],hvp=info['counts']['hvp'],
            updates=info['counts']['updates'],cc17=r['metrics']['cc17'],gl9=r['metrics']['gl9'],
            qmc_mean=float(np.mean([r['metrics'][f'qmc{k}'] for k in range(4)])),
            scale=r['metrics']['scale'],dynamics=r['metrics']['dynamics'],horizon4=r['metrics']['horizon4'],
            child_wall=e['child_wall'],child_cpu=e['child_cpu']))
    for width in (4,16,64,256):
        for seed in (11,23,47):
            ids=[reports[f'w{width}-{m}-s{seed}']['initial_sha256'] for m in ('adam','lbfgs','adjoint_ncg','ad_ncg')]
            require(len(set(ids))==1,'paired initial weights mismatch')
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    result=dict(runs=48,panels=panels_count,checkpoints=checkpoint_count,scalar_predictions=scalar_count,
                replay_max_error=max_error,independent_action_checks=independent_checks,
                independent_action_max_error=independent_error,paired_four_method_groups=12,cpu=time.process_time()-t,
                wall=time.perf_counter()-wall,production_authorized=False)
    dump(out/'AUDIT.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();verify(a.source,a.runs,a.out)
