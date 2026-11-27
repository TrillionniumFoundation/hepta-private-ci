"""R18 independent read-only audit of 64 cases, all checkpoints and finite leaves."""
import argparse,csv,hashlib,json,sys,time,math,resource
from pathlib import Path
import numpy as np

def must(condition,message):
    if not condition:raise ValueError(message)
def sha(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text())
def dump(p,obj):p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def verify(source,runs,out):
    source=source.resolve();runs=runs.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(source))
    import run,solver,problem,reference
    from certificate import certificate,ablation_certificate,A,B,ABLATION_A
    from fractions import Fraction as F
    begun=time.process_time();wall=time.perf_counter()
    core=run.sources()
    census=read(runs/'PLAN.json');done=read(runs/'COMPLETE.json')
    must(core==census['source_sha'],'source hashes changed')
    must(census['protocol_commit']==run.PROTOCOL_COMMIT,'protocol mismatch')
    must(done['plan_sha']==sha((runs/'PLAN.json').read_bytes()),'plan hash mismatch')
    must(done['completed']==64 and done['failed']==0,'incomplete census')
    must(census['specs']==run.specs(),'source plan differs')
    must([(e['name'],e['spec']) for e in done['entries']]==
         [(run.name(s),s) for s in run.specs()],'missing/reordered cases')
    cert=certificate();ab=ablation_certificate()
    a,b=float(A),float(B);s=float(ABLATION_A)
    err_as=float(F(cert['rigorous_weight_component_error_upper']))
    err_ab=float(F(ab['scalar_t_distance_upper']))
    cost_err_as=float(F(cert['rigorous_true_population_regret_upper']))
    cost_err_ab=float(F(ab['rigorous_cost_regret_upper']))
    choices={1.:[(a,b),(b,a),(-a,-b),(-b,-a)],
             0.:[(s,s),(-s,-s)]}
    reference_cost={sh:problem.objective(values[0],sh)[0] for sh,values in choices.items()}
    rows=[];checks=0;max_diff=0.;max_ref_diff=0.;max_leaf_diff=0.
    for entry in done['entries']:
        if entry['status']!='completed':raise ValueError('unsuccessful execution')
        path=runs/entry['name'];plan=read(path/'PLAN.json');seal=read(path/'FIT_SEAL.json')
        rep=read(path/'REPORT.json')
        must(entry['report_sha']==sha((path/'REPORT.json').read_bytes()),'report hash mismatch')
        must(seal['plan']==rep['plan_sha']==sha((path/'PLAN.json').read_bytes()),'case plan mismatch')
        must(plan['spec']==entry['spec']==rep['spec'],'case identity mismatch')
        must(plan['source_sha']==core and rep['source_sha']==core,'source identity mismatch')
        must(plan['protocol_commit']==census['protocol_commit'],'wrong protocol')
        must(rep['reference_in_fitting'] is False and rep['qualification'] is None,'post-fit reference leaked')
        start=np.load(path/'INITIAL.npz',allow_pickle=False)['theta']
        theta=np.load(path/'WEIGHTS.npz',allow_pickle=False)['theta']
        with np.load(path/'CHECKPOINTS.npz',allow_pickle=False) as c:
            wgt=c['theta'].copy();cpu=c['cpu'].copy();cost=c['cost'].copy()
        must(start.shape==theta.shape==(2,),'bad weight shape')
        must(np.array_equal(start,np.asarray(entry['spec']['initial'])),'not paired original start')
        must(sha(start.tobytes())==seal['initial']==rep['initial_sha'],'initial hash mismatch')
        must(sha(theta.tobytes())==seal['weights']==rep['weights_sha'],'weight hash mismatch')
        must(sha((path/'CHECKPOINTS.npz').read_bytes())==seal['checkpoints'],'checkpoint hash mismatch')
        must(len(wgt)==len(cpu)==len(cost)==rep['checkpoint_count']>0,'checkpoint count altered')
        must(np.array_equal(wgt[0],start) and np.array_equal(wgt[-1],theta),'checkpoint endpoints altered')
        must(np.isfinite(wgt).all() and np.isfinite(cpu).all() and np.isfinite(cost).all(),'nonfinite checkpoint')
        must((np.diff(cpu)>=0).all() and cpu[-1]<=rep['fit_cpu']+1e-7,'falsified fit CPU')
        must(rep['fit_status']==seal['status'],'false solver status')
        must(abs(rep['fit_cpu']-seal['fit_cpu'])<1e-13,'time seal mismatch')
        sh=1. if entry['spec']['variant']=='asymmetric' else 0.
        restored=np.array([problem.objective(q,sh)[0] for q in wgt])
        d=float(np.max(np.abs(restored-cost)));max_diff=max(max_diff,d)
        must(d<=1e-12,'checkpoint cost mismatch')
        final,g,H=problem.objective(theta,sh)
        must(abs(final-rep['final_cost'])<=1e-13,'final cost mismatch')
        ref=reference.direct(theta,sh)
        max_ref_diff=max(max_ref_diff,abs(final-ref))
        must(abs(final-ref)<=2e-12,'independent full-tree discrepancy')
        must(np.allclose(g,rep['final_gradient'],atol=1e-12,rtol=1e-12),'gradient changed')
        must(np.allclose(H,rep['final_hessian'],atol=1e-12,rtol=1e-12),'Hessian changed')
        with np.load(path/'LEAVES.npz',allow_pickle=False) as arr:leaf_values=arr['values']
        must(sha((path/'LEAVES.npz').read_bytes())==rep['leaves_sha'],'leaf hash mismatch')
        must(leaf_values.shape==(16,10),'leaf table shape mismatch')
        new=[]
        for x in (-1,1):
            for p0 in (0,1):
                for e1 in (-1,1):
                    for e2 in (-1,1):
                        new.append([x,p0,e1,e2,*reference.leaf(theta,x,p0,e1,e2,sh)])
        expected=np.asarray(new,dtype='<f8')
        max_leaf_diff=max(max_leaf_diff,float(np.max(np.abs(expected-leaf_values))))
        must(np.array_equal(expected,leaf_values),'independent leaf table mismatch')
        # Numerical classification, with rigorous reference uncertainty included.
        qual_err=err_as if sh==1. else err_ab
        ref_err=cost_err_as if sh==1. else cost_err_ab
        distance=min(float(np.linalg.norm(theta-np.asarray(q))) for q in choices[sh])
        upper_dist=distance+2*math.sqrt(2)*qual_err
        upper_gap=max(0.,final-reference_cost[sh])+ref_err+1e-12 # fp64 guard
        good=upper_dist<1e-6 and upper_gap<1e-9
        checks+=len(wgt)
        rows.append(dict(name=entry['name'],seed=entry['spec']['seed'],variant=entry['spec']['variant'],method=entry['spec']['method'],
            global_quality=good,reference_set_distance=distance,upper_distance_with_ref_error=upper_dist,
            certified_reference_cost=reference_cost[sh],final_cost=final,upper_cost_gap_with_fp64_guard=upper_gap,
            gradient_inf=float(np.max(np.abs(g))),min_hessian_eig=float(np.linalg.eigvalsh(H)[0]),
            accepted=rep['counters']['accepted'],callbacks=rep['counters']['callbacks'],fit_cpu=rep['fit_cpu'],
            fit_wall=rep['fit_wall'],child_cpu=entry['child_cpu'],child_wall=entry['child_wall'],
            fit_peak_rss=rep['fit_peak_rss'],n_checkpoints=len(wgt)))
    for seed in range(8):
        initial=[]
        for variant in ('asymmetric','zero_shift'):
            for method in solver.METHODS:
                e=next(r for r in done['entries'] if r['spec']['seed']==seed and r['spec']['variant']==variant and r['spec']['method']==method)
                initial.append(np.load(runs/e['name']/'INITIAL.npz',allow_pickle=False)['theta'].tobytes())
        must(len(set(initial))==1,'paired initial bytes differ')
    groups=[]
    for var in ('asymmetric','zero_shift'):
        for method in solver.METHODS:
            sub=[r for r in rows if r['variant']==var and r['method']==method]
            groups.append(dict(variant=var,method=method,n=len(sub),global_quality=sum(r['global_quality'] for r in sub),
                mean_final_cost=float(np.mean([r['final_cost'] for r in sub])),
                median_fit_cpu=float(np.median([r['fit_cpu'] for r in sub])),
                mean_fit_peak_rss=float(np.mean([r['fit_peak_rss'] for r in sub]))))
    for name,tab in [('SCORES.csv',rows),('GROUPS.csv',groups)]:
        with (out/name).open('x',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(tab[0]));w.writeheader();w.writerows(tab)
    receipt=dict(runs=len(rows),math_tests_not_recounted=True,total_checkpoints=checks,
        max_checkpoint_cost_error=max_diff,max_reference_cost_error=max_ref_diff,
        max_independent_leaf_error=max_leaf_diff,initial_groups=8,
        total_scalar_leaf_entries=len(rows)*16*10,global_quality_successes=sum(r['global_quality'] for r in rows),
        all_python_core_source_hashes=core,
        audit_cpu=time.process_time()-begun,audit_wall=time.perf_counter()-wall,
        host_timing_attested=False,production_authorized=False,
        evidence_does_not_certify_arbitrary_deep_FBSDE=True)
    dump(out/'AUDIT.json',receipt)
    print(json.dumps(receipt,indent=2,sort_keys=True),flush=True)
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();verify(args.source,args.runs,args.out)
