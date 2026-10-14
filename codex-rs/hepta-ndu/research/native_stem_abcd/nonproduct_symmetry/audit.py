"""R17 audit of all 64 actual fits, checkpoint history and both stochastic laws."""
import argparse,csv,hashlib,json,os,resource,time
from pathlib import Path
import numpy as np
from certificate import certify,S
from run import specs,name,sources,CPU_CAP,PARENT,PROTOCOL,kappa,digest
from solver import METHODS,INITIALS
from problem import objective,transfer
from reference import cert_equiv_eval

def require(ok,message):
    if not ok:raise ValueError(message)

def read(path):return json.loads(path.read_text())
def write(path,record):
    with path.open('x') as f:json.dump(record,f,indent=2,sort_keys=True)
def audit(runs,out):
    t0=time.process_time();w0=time.perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    plan=read(runs/'SWEEP_PLAN.json');receipt=read(runs/'COMPLETE.json')
    # Execution plan hashes exactly the five source modules present during fit;
    # independent audit/reference helpers were added after fitting.
    # Bind all executed code without pretending audit-only files were fit inputs.
    current=sources()
    require(plan['source']=={k:current[k] for k in plan['source']},'executed source drift')
    require(plan['parent']==PARENT and plan['protocol']==PROTOCOL,'parent/protocol mismatch')
    require(plan['cap']==CPU_CAP,'cpu cap changed')
    require(plan['specs']==specs(),'planned census mismatch')
    require(receipt['plan_sha']==digest((runs/'SWEEP_PLAN.json').read_bytes()),'plan hash mismatch')
    require(receipt['completed']==64 and receipt['failed']==0 and len(receipt['results'])==64,'incomplete census')
    assert len({x['name'] for x in receipt['results']})==64
    cert=certify();r=float(S);d=float(__import__('fractions').Fraction(cert['weight_component_error_upper']))
    excess=float(__import__('fractions').Fraction(cert['true_population_excess_upper']))
    ref=objective([r,r],0)[0]
    rows=[];total_checkpoints=0;max_error=0.;max_indep=0.
    for case,entry in zip(specs(),receipt['results']):
        require(entry['case']==case and entry['name']==name(case),'case identity mismatch')
        require(entry['status']=='completed' and entry['returncode']==0,'failed case')
        directory=runs/name(case)
        report=read(directory/'REPORT.json');child=read(directory/'PLAN.json')
        seal=read(directory/'FIT_SEAL.json')
        require(entry['report_sha']==digest((directory/'REPORT.json').read_bytes()),'reported file hash mismatch')
        require(child['source']==plan['source'] and child['protocol_commit']==PROTOCOL,'child source/protocol mismatch')
        require(child['case']==case and report['case']==case,'child case mismatch')
        require(report['plan_sha']==digest((directory/'PLAN.json').read_bytes())==seal['plan_sha'],'child plan hash mismatch')
        with np.load(directory/'WEIGHTS.npz',allow_pickle=False) as z:theta=z['theta'].copy()
        with np.load(directory/'INITIAL.npz',allow_pickle=False) as z:initial=z['theta'].copy()
        with np.load(directory/'CHECKPOINTS.npz',allow_pickle=False) as z:
            ctheta=z['theta'].copy();ctime=z['cpu'].copy();ccost=z['cost'].copy()
        require(theta.shape==(2,) and initial.shape==(2,),'wrong weight shape')
        require(np.array_equal(initial,np.array(INITIALS[case['seed']],dtype=np.float64)),'initial mismatch')
        require(report['initial_sha']==digest(initial.tobytes())==seal['initial_sha'],'initial hash mismatch')
        require(report['weight_sha']==digest(theta.tobytes())==seal['weight_sha'],'weight mismatch')
        require(seal['checkpoints_sha']==digest((directory/'CHECKPOINTS.npz').read_bytes()),'checkpoint file hash mismatch')
        require(report['fit']==seal,'fit seal inconsistent')
        require(len(ctheta)==len(ctime)==len(ccost)==report['num_checkpoints'] and len(ctheta)>0,'checkpoint count mismatch')
        require(np.array_equal(ctheta[0],initial) and np.array_equal(ctheta[-1],theta),'checkpoint endpoints mismatch')
        require(np.all(np.diff(ctime)>=0) and ctime[-1]<=seal['fit_cpu']+1e-8,'invalid checkpoint CPU chronology')
        saved=np.asarray([objective(th,kappa(case))[0] for th in ctheta])
        e=float(np.max(np.abs(saved-ccost)));max_error=max(e,max_error)
        require(e<=1e-13,'checkpoint cost mismatch')
        cost,g,H=objective(theta,kappa(case))
        indep=cert_equiv_eval(theta,kappa(case));eind=abs(indep-cost)
        max_indep=max(max_indep,eind)
        require(eind<=1e-12,'independent leaf mismatch')
        require(abs(cost-report['cost'])<=1e-12 and abs(indep-report['independent_leaf_cost'])<=1e-12,'false final cost')
        require(abs(float(np.max(np.abs(g)))-report['gradient_inf'])<=1e-10,'false gradient')
        require(abs(float(np.linalg.eigvalsh(H)[0])-report['hessian_min'])<=1e-10,'false hessian')
        measured=transfer(theta,kappa(case))
        require(all(abs(measured[k]-v)<=1e-12 for k,v in report['transfers'].items()),'false transfer panel')
        dist=min(np.linalg.norm(theta-[r,r]),np.linalg.norm(theta+[r,r]))
        dist_upper=dist+np.sqrt(2)*d
        regret_upper=max(0.,cost-ref)+excess+2e-14
        if cost<ref-1e-10:raise ValueError('certified global lower bound contradicted')
        quality=bool(dist_upper<1e-6 and regret_upper<1e-9)
        total_checkpoints+=len(ctheta)
        rows.append(dict(name=name(case),seed=case['seed'],architecture=case['arch'],method=case['method'],
            a=theta[0],b=theta[1],cost=cost,ref_candidate_cost=ref,dist_to_global_set=dist_upper,
            regret_upper_est=regret_upper,numerical_global_quality=quality,checkpoint_count=len(ctheta),
            grad_inf=np.max(np.abs(g)),hessian_min=np.linalg.eigvalsh(H)[0],fit_cpu=seal['fit_cpu'],
            child_cpu=entry['child_cpu'],peak_rss=report['peak_rss'],status=seal['status'],
            **report['transfers']))
    for seed in range(8):
        inits=[]
        for arch in ('nonproduct','product_only'):
            for method in METHODS:
                with np.load(runs/name(dict(seed=seed,arch=arch,method=method))/'INITIAL.npz') as z:
                    inits.append(z['theta'].tobytes())
        require(len(set(inits))==1,'mismatched initial tensors')
    with (out/'SCORES.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    groups=[]
    for arch in ('nonproduct','product_only'):
        for method in METHODS:
            cohort=[r for r in rows if r['architecture']==arch and r['method']==method]
            groups.append(dict(architecture=arch,method=method,denominator=len(cohort),
                  success=sum(r['numerical_global_quality'] for r in cohort),
                  mean_cost=float(np.mean([r['cost'] for r in cohort])),
                  median_fit_cpu=float(np.median([r['fit_cpu'] for r in cohort])),
                  mean_fit_cpu=float(np.mean([r['fit_cpu'] for r in cohort])),
                  mean_rss=float(np.mean([r['peak_rss'] for r in cohort]))))
    with (out/'GROUPS.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(groups[0]));w.writeheader();w.writerows(groups)
    summary=dict(cases=len(rows),total_checkpoints=total_checkpoints,source_sha=plan['source'],audit_only_source_sha={k:v for k,v in current.items() if k not in plan['source']},
         all_initial_groups=8,largest_checkpoint_error=max_error,largest_independent_leaf_error=max_indep,
         certified_global_candidate=[str(S),str(S)],strict_certificate=cert,
         success_counts={r['architecture']+'/'+r['method']:r['success'] for r in groups},
         whole_child_cpu=float(receipt['child_cpu']),sweep_wall=float(receipt['wall']),
         audit_cpu=time.process_time()-t0,audit_wall=time.perf_counter()-w0,
         full_flops=None,energy_joules=None,project_cloud=False,native_hardware=False,
         no_global_general_deep_model_claim=True)
    write(out/'AUDIT.json',summary)
    print(json.dumps({k:summary[k] for k in ('cases','total_checkpoints','largest_checkpoint_error',
          'largest_independent_leaf_error','success_counts','audit_cpu')},sort_keys=True))
    return summary
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--runs',required=True,type=Path)
    a.add_argument('--out',required=True,type=Path);v=a.parse_args();audit(v.runs,v.out)
