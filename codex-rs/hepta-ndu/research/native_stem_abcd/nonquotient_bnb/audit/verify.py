"""R19 independent read-only numerical/identity audit; no fitting permitted."""
import argparse,csv,hashlib,json,sys,time
from pathlib import Path
import numpy as np


def need(ok,msg):
    if not ok:raise ValueError(msg)

def digest(b):return hashlib.sha256(b).hexdigest()
def load(path):return json.loads(path.read_text())

def audit(src,runs,proof,out):
    src=src.resolve();runs=runs.resolve()
    sys.path.insert(0,str(src))
    from run import sources,specs,name,sha
    from model import ETA,full,independent_direct,leaves
    import global_bound
    from problem import objective as inherited_objective
    out.mkdir(parents=True,exist_ok=False)
    begin=time.process_time()
    proof=load(proof)
    recalc=global_bound.run(limit=global_bound.LIMIT,threshold=global_bound.THRESHOLD)
    for k in ('global_cost_regret_rigorous_upper','passes_frozen_global_threshold',
              'candidate_a','candidate_b','nodes_split','frontier_count',
              'original_strong_convexity','candidate_objective_rational_upper'):
        need(proof[k]==recalc[k],f'global proof tampered: {k}')
    need(proof['frontier_complete'] and proof['passes_frozen_global_threshold'],'global proof failed')
    plan=load(runs/'PLAN.json');complete=load(runs/'COMPLETE.json')
    need(plan['source_sha']==sources(),'source mismatch')
    need(complete['plan_sha']==digest((runs/'PLAN.json').read_bytes()),'census plan mismatch')
    need(plan['specs']==specs(),'plan specification changed')
    need(len(complete['entries'])==64 and complete['completed']==64 and complete['failed']==0,
         'incomplete case census')
    need([(e['name'],e['spec']) for e in complete['entries']]==[(name(s),s) for s in specs()],
         'case identities changed')
    base_weight=np.array([float(global_bound.A),float(global_bound.B)])
    base_cost=full(base_weight,ETA)[0]
    gap=float(global_bound.F(proof['global_cost_regret_rigorous_upper']))
    # R18 exact certificate has global cost <1e-48 for its representative.
    from certificate import A as OLD_A,B as OLD_B
    oa,ob=float(OLD_A),float(OLD_B)
    ctrl_best=full((oa,ob),0)[0]
    quality=[];groups={};max_replay=0.;max_leaf=0.;ckpts=0;changed=0
    for index,e in enumerate(complete['entries']):
        need(e['status']=='completed','case failed')
        spec=e['spec'];folder=runs/e['name']
        report_bytes=(folder/'REPORT.json').read_bytes()
        need(digest(report_bytes)==e['report_sha'],'report digest mismatch')
        rep=json.loads(report_bytes);seal=load(folder/'FIT_SEAL.json')
        need(rep['spec']==spec and rep['source_sha']==plan['source_sha'],'identity/source mismatch')
        need(digest((folder/'PLAN.json').read_bytes())==seal['plan']==rep['plan_sha'],'case plan digest mismatch')
        need(load(folder/'PLAN.json')['reference_used_in_fit'] is False,'reference oracle leaked')
        need(rep['fitted_with_global_reference'] is False and rep['global_qualification'] is None,
             'reference in fitting')
        with np.load(folder/'INITIAL.npz',allow_pickle=False) as d:initial=d['theta'].copy()
        with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as d:theta=d['theta'].copy()
        with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as d:
            h=d['theta'].copy();cpu=d['cpu'].copy();cost=d['cost'].copy()
        eta=ETA if spec['arm']=='nonquotient' else 0.
        need(np.array_equal(initial,np.array(spec['initial'],dtype='<f8')),'initial mismatch')
        need(theta.shape==(2,) and np.isfinite(theta).all(),'invalid weights')
        need(digest(initial.tobytes())==seal['initial']==rep['initial_sha'],'initial digest mismatch')
        need(digest(theta.tobytes())==seal['weights']==rep['weights_sha'],'weight digest mismatch')
        need(digest((folder/'CHECKPOINTS.npz').read_bytes())==seal['checkpoints'],'checkpoint digest mismatch')
        need(len(h)==len(cpu)==len(cost)==rep['checkpoints'] and len(h)>0,'checkpoint count mismatch')
        need(np.array_equal(h[0],initial) and np.array_equal(h[-1],theta),'checkpoint terminal mismatch')
        need(np.all(np.diff(cpu)>=0) and cpu[-1]<=rep['fit_cpu']+1e-7,'checkpoint CPU order mismatch')
        values=np.array([full(x,eta)[0] for x in h])
        err=float(np.max(np.abs(values-cost)))
        need(err<=1e-13,'checkpoint cost mismatch')
        max_replay=max(max_replay,err)
        exact=np.array(leaves(theta,eta))
        need(digest((folder/'LEAVES.npz').read_bytes())==rep['leaves_sha'],'leaves digest mismatch')
        with np.load(folder/'LEAVES.npz',allow_pickle=False) as d:
            need(np.array_equal(d['values'],exact),'branch path mismatch')
        f,g,H=full(theta,eta)
        val=independent_direct(theta,eta)
        err2=abs(val-f);max_leaf=max(max_leaf,err2)
        need(err2<=1e-12,'independent leaf value mismatch')
        need(abs(rep['final_cost']-f)<=1e-13,'rehashed false cost')
        need(abs(rep['independent_full_tree_cost']-val)<=1e-13,'rehashed independent cost')
        np.testing.assert_allclose(rep['gradient'],g,rtol=1e-11,atol=1e-11)
        np.testing.assert_allclose(rep['hessian'],H,rtol=1e-11,atol=1e-11)
        need(rep['fit_cpu']==seal['fit_cpu'] and rep['fit_status']==seal['status'],'timing/status mismatch')
        need(rep['whole_child_cpu']>=rep['fit_cpu'] and rep['whole_child_wall']>=rep['fit_wall'],
             'unmetered work')
        changed+=int(not np.array_equal(initial,theta))
        groups.setdefault((spec['seed'],spec['arm']),[]).append(initial.tobytes())
        if spec['arm']=='nonquotient':
            # Candidate global bound is rigorous; final score is FP64 with a guard.
            maxregret=max(0.,f-base_cost)+gap+1e-11
            passes=maxregret<.001
        else:
            maxregret=max(0.,f-ctrl_best)+1e-11
            passes=maxregret<.001
        ckpts+=len(h)
        quality.append(dict(name=e['name'],seed=spec['seed'],arm=spec['arm'],method=spec['method'],
           a=theta[0],b=theta[1],cost=f,gradient_inf=float(np.max(abs(g))),
           hessian_min=float(np.linalg.eigvalsh(H)[0]),
           certified_global_regret_upper=maxregret,qualified=passes,
           checkpoint_count=len(h),fit_cpu=rep['fit_cpu'],fit_wall=rep['fit_wall'],
           whole_child_cpu=rep['whole_child_cpu'],child_cpu=e['child_cpu'],
           peak_rss=rep['fit_peak_rss']))
    for k,arr in groups.items():
        need(len(arr)==4 and len(set(arr))==1,'different solver initialization')
    for seed in range(8):
        need(groups[seed,'nonquotient'][0]==groups[seed,'control'][0],
             'different arm initialization')
    summary=[]
    for arm in ('nonquotient','control'):
        for method in ('adam','bfgs','lbfgs','trust-exact'):
            sub=[s for s in quality if s['arm']==arm and s['method']==method]
            need(len(sub)==8,'missing group')
            summary.append(dict(arm=arm,method=method,total=8,
                qualified=sum(s['qualified'] for s in sub),
                median_fit_cpu=float(np.median([s['fit_cpu'] for s in sub])),
                mean_final_cost=float(np.mean([s['cost'] for s in sub])),
                mean_global_regret_upper=float(np.mean([s['certified_global_regret_upper'] for s in sub]))))
    for name,table in (('SCORES.csv',quality),('GROUPS.csv',summary)):
        with (out/name).open('x',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    result=dict(schema='hepta.ndu.nonquotient.r19.audit',runs=len(quality),
        total_checkpoints=ckpts,changed_weights=changed,paired_groups=len(groups),
        max_checkpoint_replay_error=max_replay,max_independent_leaf_error=max_leaf,
        global_bound_rigorous=True,individual_final_float_cost_with_guard=True,
        actual_global_optimizer_uniqueness_proven=False,
        qualification={q['arm']+'/'+q['method']:q['qualified'] for q in summary},
        audit_cpu=time.process_time()-begin,production_authorized=False)
    (out/'AUDIT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--proof',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();audit(a.source,a.runs,a.proof,a.out)
