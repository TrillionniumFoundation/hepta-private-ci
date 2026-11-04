"""One predeclared minimum-L1 Belief edit per published joint model.

TRAIN only; all unique oracle terminal choices constrained, including signs
already correct. No budget relaxation, validation data, test data, or search.
"""
from pathlib import Path
from fractions import Fraction
import argparse,hashlib,json,time,sys
import numpy as np
import scipy
from scipy.optimize import linprog

ROOT=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def signs_for_rows(x,y,mask,theta,tolerance):
    chosen=[];signs=[];ties=0;nonterminal=0
    for i in range(len(x)):
        ids=np.flatnonzero(mask[i]);best=np.max(y[i,ids]);winners=ids[np.abs(y[i,ids]-best)<=tolerance]
        if len(winners)!=1:ties+=1;continue
        if winners[0] not in (4,5):nonterminal+=1;continue
        chosen.append(i);signs.append(1. if winners[0]==5 else -1.)
    indices=np.asarray(chosen,dtype=int);sign=np.asarray(signs)
    logit=np.sum(x[indices]*theta[3],axis=1)
    return indices,sign,logit,ties,nonterminal

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--output',required=True);args=ap.parse_args()
    root=Path(args.study_root);out=Path(args.output)
    if out.exists():raise FileExistsError('output must be new')
    protocol=json.loads((ROOT/'PROTOCOL_BEFORE_RESULTS.json').read_text())
    geometry=root/'fixtures/train_linear_geometry.npz';assert sha(geometry)==protocol['source_geometry_sha256']
    assert protocol['logit_margin']==1e-4 and protocol['budget_fraction']==.5 and protocol['no_budget_relaxation']
    data=np.load(geometry);records=[];start=time.process_time()
    for fit in protocol['source_fits']:
        x,y,mask,theta=[data[f'fit{fit}_{key}'] for key in ('x','y','mask','theta')]
        assert x.shape[1]==49 and theta.shape==(4,49)
        assert all(np.isfinite(a).all() for a in (x,y,mask,theta))
        rows,signs,old_logits,ties,nonterminal=signs_for_rows(x,y,mask,theta,1e-10)
        base=theta[3];rho=.5*float(np.linalg.norm(base));p=len(base);margin=1e-4
        # Variables delta[49], absolute-value epigraph t[49].
        constraints=np.vstack([np.c_[-signs[:,None]*x[rows],np.zeros((len(rows),p))],
                               np.c_[np.eye(p),-np.eye(p)],np.c_[-np.eye(p),-np.eye(p)],
                               np.r_[np.zeros(p),np.ones(p)][None,:]])
        rhs=np.r_[signs*old_logits-margin,np.zeros(2*p),rho]
        t0=time.process_time()
        result=linprog(np.r_[np.zeros(p),np.ones(p)],A_ub=constraints,b_ub=rhs,
                       bounds=[(None,None)]*p+[(0.,None)]*p,method='highs',
                       options={'time_limit':20.,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
        solver_cpu=time.process_time()-t0
        record={'fit':fit,'original_train_rows':len(x),'unique_oracle_terminal_rows':rows.tolist(),
                'constraint_count_terminal':len(rows),'oracle_tie_rows_excluded':ties,'unique_nonterminal_rows_excluded':nonterminal,
                'wrong_sign_rows_before':rows[signs*old_logits<=0].tolist(),
                'correct_sign_count_before':int(np.sum(signs*old_logits>0)),
                'rho':rho,'base_belief_l2':float(np.linalg.norm(base)),'base_weights':base.tolist(),
                'solver_status':int(result.status),'solver_message':result.message,'solver_cpu_seconds':solver_cpu,
                'proposal_available':False}
        delta=np.zeros(p)
        if result.success:
            candidate=result.x[:p];new=base+candidate
            logits=np.sum(x[rows]*new,axis=1)
            violation=float(max(0.,np.max(margin-signs*logits)))
            l1_exact=sum((Fraction.from_float(abs(float(v))) for v in candidate),Fraction(0))
            budget_exact=Fraction.from_float(rho)
            finite=bool(np.isfinite(candidate).all() and np.isfinite(new).all())
            admissible=finite and violation<=protocol['numerical_constraint_tolerance'] and l1_exact<=budget_exact
            record.update(lp_objective=float(result.fun),delta_l1=float(np.sum(abs(candidate))),delta_l2=float(np.linalg.norm(candidate)),
                          terminal_constraint_max_violation=violation,minimum_signed_logit_after=float(np.min(signs*logits)),
                          wrong_sign_rows_after=rows[signs*logits<=0].tolist(),
                          originally_correct_sign_regressions=int(np.sum((signs*old_logits>0)&(signs*logits<=0))),
                          exact_ieee_l1_within_budget=bool(l1_exact<=budget_exact),
                          exact_ieee_l1={'numerator':str(l1_exact.numerator),'denominator':str(l1_exact.denominator)},
                          proposal_available=admissible,numerical_admission_failure=not admissible)
            if admissible:delta=candidate
        # A single signed permutation is fixed before any validation/test use.
        random_seed=protocol['seed']+1000*fit+7331;rng=np.random.default_rng(random_seed)
        permutation=rng.permutation(p);random_signs=rng.choice(np.array([-1.,1.]),size=p)
        random_delta=delta[permutation]*random_signs
        assert np.array_equal(np.sort(abs(delta)),np.sort(abs(random_delta)))
        rand_logits=np.sum(x[rows]*(base+random_delta),axis=1)
        record.update(effective_delta=delta.tolist(),effective_weights=(base+delta).tolist(),
                      nonzero_edit=bool(np.any(delta)),random_seed=random_seed,random_delta=random_delta.tolist(),
                      random_weights=(base+random_delta).tolist(),random_l1=float(np.sum(abs(random_delta))),
                      random_l2=float(np.linalg.norm(random_delta)),random_wrong_terminal_sign_rows=rows[signs*rand_logits<=0].tolist(),
                      random_terminal_constraint_max_violation=float(max(0.,np.max(margin-signs*rand_logits))),
                      random_norm_matching='signed permutation preserves exact absolute-value multiset, hence L1/L2')
        records.append(record)
        print(json.dumps({k:record.get(k) for k in ['fit','constraint_count_terminal','proposal_available','nonzero_edit','wrong_sign_rows_before','wrong_sign_rows_after','rho','delta_l1','delta_l2','solver_cpu_seconds']}),flush=True)
    output={'schema':'hepta-exploratory-belief-lp-proposals-v1','protocol_sha256':sha(ROOT/'PROTOCOL_BEFORE_RESULTS.json'),
            'source_geometry_sha256':sha(geometry),'source_solver_sha256':sha(__file__),
            'numpy':np.__version__,'scipy':scipy.__version__,'python':sys.version,'fits':records,
            'total_cpu_seconds':time.process_time()-start,'no_validation_or_test_data_used':True}
    out.write_text(json.dumps(output,indent=2,sort_keys=True,allow_nan=False)+'\n')

if __name__=='__main__':
    with np.errstate(over='raise',invalid='raise',divide='raise'):main()
