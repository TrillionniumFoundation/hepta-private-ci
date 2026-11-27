"""R15 independent read-only complete-census audit; no changes to original runs."""
import argparse
import csv
from fractions import Fraction as Q
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
from problem import population,population_direct,stage_values,branch,XS,PS,EPS,BOX
from solver import initial,observed_quality,kkt_violation,SEEDS,METHODS,ARMS,CAP_CPU
from certificate import proof
from sweep import cases,name_for,source_hashes,sha,dump,oracle_arrays


def require(ok,message):
    if not ok:raise ValueError(message)


def audit(root,out):
    out.mkdir(parents=True,exist_ok=False)
    start=time.process_time(),time.perf_counter()
    plan=json.loads((root/'PLAN.json').read_text())
    done=json.loads((root/'COMPLETE.json').read_text())
    require(plan['source']==source_hashes(),'source mismatch')
    require(plan['protocol_sha256']==sha((Path(__file__).parent/'PROTOCOL.md').read_bytes()),'protocol mismatch')
    require(plan['cases']==cases(),'case census plan mismatch')
    require(done['plan_sha256']==sha((root/'PLAN.json').read_bytes()),'plan hash mismatch')
    require([r['name'] for r in done['census']]==[name_for(s) for s in cases()],'incomplete census')
    require(done['completed']==48 and done['failed']==0,'failed or missing run')
    cert=proof()
    require(cert==plan['main_certification']==json.loads((root/'CERTIFICATE.json').read_text()),'certificate mismatch')
    radius=Q(cert['true_global_optimum_distance_upper'])
    rows=[];histories=0;max_replay=0.;max_history=0.;pairgroups={};costs_by_arm={}
    for item in done['census']:
        folder=root/item['name']
        report_bytes=(folder/'REPORT.json').read_bytes()
        require(item['status']=='completed' and sha(report_bytes)==item['report_sha256'],'report tamper')
        r=json.loads(report_bytes)
        child=json.loads((folder/'PLAN.json').read_text())
        require(r['case']==item['case']==child['case'],'case identity mismatch')
        require(r['source']==child['source']==plan['source'],'child source mismatch')
        require(r['plan_sha256']==sha((folder/'PLAN.json').read_bytes()),'child plan mismatch')
        require(child['main_certificate_distance']==cert['true_global_optimum_distance_upper'],'quality gate changed')
        fit=json.loads((folder/'FIT.json').read_text())
        require(r['fit']==fit,'fit history altered')
        seal=json.loads((folder/'FIT_SEAL.json').read_text())
        require(seal['fit_sha256']==sha((folder/'FIT.json').read_bytes()),'fit checksum mismatch')
        with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as z:theta=z['theta'].copy()
        with np.load(folder/'INITIAL.npz',allow_pickle=False) as z:theta0=z['theta'].copy()
        require(theta.shape==(2,),'weights wrong shape')
        np.testing.assert_array_equal(theta0,initial(item['case']['seed']))
        require(sha(theta0.tobytes())==seal['initial_sha256']==r['initial_sha256'],'initial weights altered')
        require(sha(theta.tobytes())==seal['selected_sha256']==r['selected_sha256'],'selected weights altered')
        np.testing.assert_array_equal(theta,fit['selected'])
        require(fit['seed']==item['case']['seed'] and fit['method']==item['case']['method'] and fit['arm']==item['case']['arm'],'fit identity altered')
        pairgroups.setdefault((fit['arm'],fit['seed']),[]).append(r['initial_sha256'])
        osc=fit['arm']=='oscillatory'
        prev=-1.;observed=[]
        for idx,cp in enumerate(fit['history']):
            x=np.asarray(cp['theta'])
            require(np.isfinite(x).all() and np.all(x>=float(BOX[0])) and np.all(x<=float(BOX[1])),'checkpoint outside parameter box')
            require(cp['cpu']>=prev,'time history reversed')
            prev=cp['cpu']; f,g,H=population(x,oscillatory=osc)
            delta=abs(f-cp['objective']);max_history=max(max_history,delta)
            require(delta<3e-12,'checkpoint score corrupted')
            require(abs(np.max(np.abs(g))-cp['gradient_inf'])<1e-10,'checkpoint gradient corrupted')
            require(abs(np.linalg.eigvalsh(H)[0]-cp['hessian_min'])<1e-8,'checkpoint Hessian corrupted')
            require(abs(kkt_violation(x,g)-cp['kkt_violation'])<1e-10,'checkpoint KKT corrupted')
            if not osc:
                good=observed_quality(x,radius)
                require(cp['quality']==good,'certificate gate result altered')
                if good and cp['cpu']<=CAP_CPU:observed.append(cp['cpu'])
            else:
                require(cp['quality'] is None,'stress cannot use global certificate')
            histories+=1
        require(fit['history'] and np.array_equal(theta,fit['history'][-1]['theta']),'final checkpoint missing')
        if not osc:
            require(fit['certified_gate_success']==bool(observed),'false certified qualification')
            require(fit['quality_first_cpu']==(observed[0] if observed else None),'falsified first time')
            require(fit['stress_global_certificate']==True,'missing main global certificate')
        else:
            require(fit['certified_gate_success'] is None and fit['quality_first_cpu'] is None,'false nonconvex global qualification')
            require(fit['stress_global_certificate'] is False,'stress global certificate forged')
            f,g,H=population(theta,oscillatory=True)
            status=bool(kkt_violation(theta,g)<1e-6 and np.linalg.eigvalsh(H)[0]>1e-5)
            require(fit['stress_numerical_local_candidate']==status,'local stationarity metric altered')
        require(fit['fit_cpu']>=fit['history'][-1]['cpu'],'unmetered checkpoint')
        require(r['prediction_sha256']==sha((folder/'PREDICTIONS.npz').read_bytes()),'prediction archive altered')
        values,branches=oracle_arrays(theta,fit['arm'])
        with np.load(folder/'PREDICTIONS.npz',allow_pickle=False) as z:
            np.testing.assert_array_equal(values,z['roots']);np.testing.assert_array_equal(branches,z['branch_costs'])
        f,g,H=population(theta,oscillatory=osc)
        scalar=population_direct(theta,oscillatory=osc)
        max_replay=max(max_replay,abs(f-scalar),abs(f-float(values.mean())))
        require(abs(f-r['final_direct_cost'])<2e-13 and abs(scalar-r['final_independent_cost'])<2e-13,'false independent cost')
        require(np.allclose(g,r['final_direct_gradient'],atol=1e-12,rtol=1e-12),'false independent gradient')
        key=(fit['arm'],fit['method'])
        costs_by_arm.setdefault(key,[]).append((float(f),theta.copy(),fit['seed'],fit['stress_numerical_local_candidate']))
        rows.append(dict(name=item['name'],arm=fit['arm'],seed=fit['seed'],method=fit['method'],
                         cost=float(f),certified_success=fit['certified_gate_success'],
                         quality_cpu=fit['quality_first_cpu'],numerical_local=fit['stress_numerical_local_candidate'],
                         kkt=fit['final_kkt_violation'],hessian_min=fit['final_hessian_eigenvalues'][0],
                         fit_cpu=fit['fit_cpu'],overall_cpu=r['overall_cpu'],child_cpu=item['child_cpu'],
                         child_wall=item['child_wall'],update_count=fit['counts']['updates'],
                         history_count=len(fit['history']),peak_rss=fit['process_peak_rss']))
    for (arm,seed),hashes in pairgroups.items():
        require(len(hashes)==3 and len(set(hashes))==1,'matched initial weights violated')
    stress=[r for r in rows if r['arm']=='oscillatory' and r['numerical_local']]
    groups=[]
    for row in stress:
        theta=next(x[1] for x in costs_by_arm[(row['arm'],row['method'])] if x[2]==row['seed'])
        match=next((g for g in groups if np.linalg.norm(theta-g['theta'])<1e-3),None)
        if match is None:groups.append(dict(theta=theta.copy(),cost=row['cost'],count=1))
        else:match['count']+=1
    with (out/'SCORES.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    cluster=[dict(theta=[float(x) for x in g['theta']],cost=g['cost'],count=g['count']) for g in sorted(groups,key=lambda g:g['cost'])]
    dump(out/'STRESS_BASINS.json',cluster)
    receipt=dict(completed=48,certified_runs=24,stress_runs=24,history_replayed=histories,
        matched_start_groups=len(pairgroups),maximum_history_error=max_history,
        maximum_final_prediction_error=max_replay,certified_passes=sum(r['certified_success'] is True for r in rows),
        numeric_local_candidates=len(stress),different_numerical_stress_basins=len(groups),
        all_stress_basins_globally_certified=False,source_sha256=source_hashes(),
        audit_cpu=time.process_time()-start[0],audit_wall=time.perf_counter()-start[1],
        production_authorized=False)
    dump(out/'AUDIT.json',receipt)
    print(json.dumps(receipt,sort_keys=True))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    s=p.parse_args();audit(s.runs,s.out)
