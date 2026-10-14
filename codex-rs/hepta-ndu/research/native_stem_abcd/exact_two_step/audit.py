"""R14 independent read-only audit of 15 fresh finite-law runs and proofs."""
import argparse
import csv
import json
import hashlib
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
import numpy as np


def must(cond, message):
    if not cond:raise ValueError(message)


def audit(source,runs,out):
    sys.path.insert(0,str(source.resolve()))
    import solver,certificate,sweep,scout,stress
    begin=time.process_time(),time.perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((runs/'PLAN.json').read_text())
    completed=json.loads((runs/'COMPLETE.json').read_text())
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    must(plan['source']==sweep.sources(),'source identity mismatch')
    must(completed['plan_sha256']==sha(runs/'PLAN.json'),'sweep plan changed')
    must(plan['cases']==sweep.cases(),'case census mismatch')
    must([x['name'] for x in completed['census']]==[sweep.case_name(x) for x in sweep.cases()],'missing or reordered cases')
    must(completed['completed']==15 and completed['failed']==0,'execution failures')
    must(plan['cap']==solver.CAP,'cap changed')
    exact=certificate.certificate()
    must(json.loads((runs/'CERTIFICATE.json').read_text())==exact,'exact certificate mismatch')
    bound=Q(exact['distance_to_unique_global_optimum_upper'])
    rows=[];count=0;replaymax=0.;pairs={}
    for entry in completed['census']:
        must(entry['status']=='completed','failed run')
        name=entry['name'];folder=runs/name
        must(sha(folder/'REPORT.json')==entry['report_sha256'],'report hash mismatch')
        r=json.loads((folder/'REPORT.json').read_text())
        c=json.loads((folder/'PLAN.json').read_text())
        must(r['plan_sha256']==sha(folder/'PLAN.json'),'child plan mismatch')
        must(c['source']==plan['source']==r['source'],'child source mismatch')
        must((c['seed'],c['method'])==(entry['case']['seed'],entry['case']['method']),'identity mismatch')
        must(c['cap_cpu_seconds']==solver.CAP,'child cap mismatch')
        init=np.load(folder/'INITIAL.npy',allow_pickle=False);trained=np.load(folder/'WEIGHTS.npy',allow_pickle=False)
        must(np.array_equal(init,solver.initial(c['seed'])),'initial bytes mismatch')
        must(hashlib.sha256(init.tobytes()).hexdigest()==r['initial_sha256'],'initial SHA mismatch')
        must(hashlib.sha256(trained.tobytes()).hexdigest()==r['selected_sha256'],'trained weight SHA mismatch')
        must(np.array_equal(trained,np.asarray(r['result']['selected'])),'selected vector mismatch')
        rec=r['result']
        must(rec['method']==c['method'] and rec['seed']==c['seed'],'result identity mismatch')
        must(rec['oracle_parameters_used_in_training']==False,'oracle leakage')
        must(rec['certificate_used_for_stopping_only']==True,'quality gating mismatch')
        must(len(rec['history'])==rec['counts']['updates']+1,'missing/repeated checkpoints')
        must(rec['counts']['updates']>0,'untrained candidate')
        must(rec['cpu']<=r['overall_cpu']+1e-8,'fit CPU not fully charged')
        must(rec['wall']<=r['overall_wall']+1e-8,'fit wall not fully charged')
        must(rec['status']=='quality','unexpected reason for stop')
        # Independently compute exact parameter-quality from each binary64 checkpoint.
        qcount=0;times=[];previous=-1.;last_step=-1
        for step,ck in enumerate(rec['history']):
            v=np.asarray(ck['theta']);must(np.isfinite(v).all(),'nonfinite checkpoint')
            t=ck['cpu'];must(t>=previous,'nonmonotone checkpoint time')
            previous=t
            must(ck['step']>=last_step,'reversed update counter');last_step=ck['step']
            diff=[Q.from_float(float(v[i]))-z for i,z in enumerate((certificate.A,certificate.B))]
            passed=(sum((z*z for z in diff),Q(0)) < (solver.QUALITY-bound)**2)
            must(ck['quality']==passed,'forged checkpoint quality')
            if passed and t<=solver.CAP:qcount+=1;times.append(t)
            count+=1
        must(rec['success']==bool(times),'false success')
        must(len(times)==1 and times[0]==rec['first_quality_cpu'],'forged time / did not stop at first quality')
        must(np.array_equal(trained,np.asarray(rec['history'][-1]['theta'])),'nonterminal saved weight')
        cost,g,H=solver.population(trained)
        must(abs(cost-rec['final_cost'])<=1e-13,'forged final cost')
        must(abs(np.max(abs(g))-rec['final_grad_inf'])<=1e-13,'forged gradient')
        must(abs(np.linalg.eigvalsh(H)[0]-rec['final_hessian_min'])<=1e-13,'forged Hessian')
        must(np.linalg.eigvalsh(H)[0]>float(certificate.STRONG_CONVEXITY)-1e-12,'global Hessian bound violation')
        replaymax=max(replaymax,abs(cost-rec['final_cost']))
        pairs.setdefault(c['seed'],[]).append((c['method'],r['initial_sha256']))
        rows.append(dict(run=name,seed=c['seed'],method=c['method'],success=rec['success'],
                         first_quality_cpu=rec['first_quality_cpu'],fit_cpu=rec['cpu'],
                         whole_child_cpu=entry['child_cpu'],fit_wall=rec['wall'],
                         initial_sha256=r['initial_sha256'],selected_sha256=r['selected_sha256'],
                         population_cost=cost,grad_inf=float(np.max(abs(g))),hessian_min=float(np.linalg.eigvalsh(H)[0]),
                         steps=rec['counts']['updates'],peak_rss=r['process_peak_rss_bytes']))
    for seed,items in pairs.items():
        must(len(items)==3 and set(x[0] for x in items)==set(solver.METHODS),'missing paired method')
        must(len(set(x[1] for x in items))==1,'initialization mismatch')
    with (out/'RUNS.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # Independent high-precision two-stage calculation checks candidate gradient
    # (diagnostic separate from the exact interval certificate).
    import mpmath as mp
    mp.mp.dps=85
    c,g=scout.calc(scout.mpf(certificate.A),scout.mpf(certificate.B))
    intervals=certificate.gradient_enclosure()
    for j in (0,1):
        must(scout.mpf(intervals[j].lo)<=g[j]<=scout.mpf(intervals[j].hi),'high precision gradient not enclosed')
    numerical_out=stress.run()
    must(numerical_out['continuous_candidate_gap']>.01,'continuous transfer diagnostic unexpectedly changed')
    (out/'CONTINUOUS_STRESS.json').write_text(json.dumps(numerical_out,indent=2,sort_keys=True)+'\n')
    receipt=dict(schema='hepta.ndu.r14.independent_audit',completed_cases=len(rows),
                 checkpoints=count,paired_initialization_groups=len(pairs),
                 successful_by_method={m:sum(r['success'] and r['method']==m for r in rows) for m in solver.METHODS},
                 max_cost_replay_difference=replaymax,
                 exact_candidate_gradient_enclosed=True,
                 exact_certificate_sha256=sha(runs/'CERTIFICATE.json'),
                 audit_cpu=time.process_time()-begin[0],audit_wall=time.perf_counter()-begin[1],
                 alternative_continuous_law_is_certified=False,
                 production_authorized=False,global_ci_verified=False)
    (out/'RECEIPT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt,sort_keys=True))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();audit(a.source,a.runs,a.out)
