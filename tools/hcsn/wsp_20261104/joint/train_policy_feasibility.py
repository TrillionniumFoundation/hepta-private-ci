"""Finite TRAIN-state expressivity diagnostic, not an efficacy search.

Freeze features and belief; vary exactly the 147 continuation coefficients.
Test whether every uniquely oracle-optimal TRAIN action can dominate every
other legal action. Ties in the oracle are excluded (no arbitrary tie target).
L-infinity bounds contain the prior L2 trust ball; infeasibility under these
looser bounds is evidence of infeasibility in that L2 ball. Feasibility does
not by itself certify a globally optimal NDU policy or holdout benefit.
"""
from pathlib import Path
import argparse, hashlib, json, time
import numpy as np
from scipy.optimize import linprog
import scipy

FITS=(11,23,37,53,71)
ACTIONS=('STOP','WAIT','READ','REPAIR','SUBMIT0','SUBMIT1')

def construct(x,y,mask,theta,margin):
    # Explicit reductions avoid BLAS exception-flag issues encountered upstream.
    out=np.einsum('ij,kj->ik',x,theta,optimize=False)
    p=1/(1+np.exp(-out[:,3]))
    scores=np.c_[np.zeros(len(x)),out[:,:3],1-2*p,2*p-1]
    A=[]; b=[]; identity=[]; skipped=[]; witnesses=[]
    for i in range(len(x)):
        ids=np.flatnonzero(mask[i]); target=np.max(y[i,ids])
        winners=ids[np.abs(y[i,ids]-target)<=1e-10]
        if len(winners)!=1:
            skipped.append(i); continue
        a=int(winners[0])
        for other in ids:
            other=int(other)
            if other==a:continue
            v=np.zeros(147)
            if 1<=a<=3:v[(a-1)*49:a*49]-=x[i]
            if 1<=other<=3:v[(other-1)*49:other*49]+=x[i]
            rhs=float(scores[i,a]-scores[i,other]-margin)
            meta={'row':i,'oracle_action':ACTIONS[a],'other_action':ACTIONS[other],
                  'oracle_gap':float(y[i,a]-y[i,other]),
                  'frozen_or_base_score_gap':float(scores[i,a]-scores[i,other]),
                  'rhs':rhs}
            if not np.any(v) and rhs<0:
                # y=e_i is a direct Farkas witness: A^T y=0, b^T y=rhs<0.
                witnesses.append({**meta,'constraint':len(A),'type':'immutable_terminal_contradiction',
                                  'certificate_A_transpose_y_max_abs':0.,'certificate_b_dot_y':rhs,
                                  'certificate_y':{'index':len(A),'value':1.}})
            A.append(v);b.append(rhs);identity.append(meta)
    return np.asarray(A),np.asarray(b),identity,skipped,witnesses

def solve_case(A,b,bounds):
    start=time.process_time()
    res=linprog(np.zeros(147),A_ub=A,b_ub=b,bounds=bounds,method='highs',
                options={'time_limit':15.,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
    answer={'solver_status':int(res.status),'solver_message':res.message,'cpu_seconds':time.process_time()-start}
    if res.success:
        residual=A@res.x-b
        answer.update(max_constraint_violation=float(max(0.,residual.max())),
                      delta_l2=float(np.linalg.norm(res.x)),delta_linf=float(np.max(abs(res.x))))
        answer['numerically_feasible']=answer['max_constraint_violation']<=1e-7
    return answer

def main():
    ap=argparse.ArgumentParser();ap.add_argument('geometry');ap.add_argument('output');args=ap.parse_args()
    path=Path(args.geometry);data=np.load(path)
    report={'schema':'hepta-train-head-policy-feasibility-v1','source_geometry_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'numpy':np.__version__,'scipy':scipy.__version__,'margins':[0.,.001],'oracle_tie_tolerance':1e-10,
            'scope':'original TRAIN only; 147 frozen-feature continuation coefficients; belief and fixed STOP/SUBMIT untouched; no candidate is deployed or tested on holdout',
            'trust_box':'componentwise +/- rho where rho=.5*||base continuation||_2; this contains the L2 trust ball, so only infeasibility transfers',
            'fits':[]}
    for fit in FITS:
        x,y,mask,theta=[data[f'fit{fit}_{key}'] for key in ('x','y','mask','theta')]
        rho=.5*float(np.linalg.norm(theta[:3])); entry={'fit':fit,'train_rows':len(x),'rho_l2':rho,'cases':[]}
        for margin in report['margins']:
            A,b,ids,skipped,witnesses=construct(x,y,mask,theta,margin)
            case={'margin':margin,'constraints':len(b),'oracle_tie_rows_skipped':skipped,
                  'immutable_contradictions':witnesses,'immutable_contradiction_rows':sorted(set(w['row'] for w in witnesses)),
                  'unrestricted':solve_case(A,b,[(None,None)]*147),
                  'trust_box_outer_bound':solve_case(A,b,[(-rho,rho)]*147)}
            if not witnesses and case['trust_box_outer_bound']['solver_status']==2:
                # Numeric Farkas certificate for A_box delta <= b_box.
                Ab=np.vstack([A,np.eye(147),-np.eye(147)])
                bb=np.r_[b,np.full(294,rho)]
                cert=linprog(bb,A_eq=np.vstack([Ab.T,np.ones(len(bb))]),
                             b_eq=np.r_[np.zeros(147),1.],bounds=[(0.,None)]*len(bb),
                             method='highs',options={'time_limit':15.,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9})
                case['trust_box_outer_bound']['certificate_status']=int(cert.status)
                if cert.success:
                    support=np.flatnonzero(cert.x>1e-12)
                    case['trust_box_outer_bound']['numeric_farkas_certificate']={
                        'A_transpose_y_max_abs':float(np.max(abs(Ab.T@cert.x))),
                        'b_dot_y':float(bb@cert.x),'y_sum':float(cert.x.sum()),
                        'min_y':float(cert.x.min()),
                        'support':[{'constraint':int(k),'weight':float(cert.x[k])} for k in support],
                        'ordering':'oracle inequalities, +I box upper bounds, -I box lower bounds',
                        'scope':'floating-point certificate, not an exact rational proof'}
            entry['cases'].append(case)
        report['fits'].append(entry)
        print(json.dumps({'fit':fit,'cases':[{'margin':c['margin'],'constraints':c['constraints'],'ties':len(c['oracle_tie_rows_skipped']),'fixed_conflict_rows':c['immutable_contradiction_rows'],'free_status':c['unrestricted']['solver_status'],'box_status':c['trust_box_outer_bound']['solver_status']} for c in entry['cases']]}),flush=True)
    Path(args.output).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':
    with np.errstate(over='raise',invalid='raise',divide='raise'):main()
