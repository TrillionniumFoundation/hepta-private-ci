"""Post-confirmation geometry of the frozen purchase head, using exact binary-rational inputs."""
import argparse
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from . import experiment as ex, readout_edit as edit


def rational_solution(matrix, approx):
    """Recover a strictly positive exact solution on the numerical candidate support."""
    n=len(approx)
    rows=[[Fraction(float(x)) for x in col]+[Fraction(0)] for col in matrix.T]
    rows.append([Fraction(1)]*n+[Fraction(1)])
    pivots=[]
    for col in range(n):
        row=len(pivots)
        found=next((r for r in range(row,len(rows)) if rows[r][col]),None)
        if found is None:continue
        rows[row],rows[found]=rows[found],rows[row]
        pivot=rows[row][col]
        rows[row]=[x/pivot for x in rows[row]]
        for r in range(len(rows)):
            if r!=row and rows[r][col]:
                factor=rows[r][col]
                rows[r]=[a-factor*b for a,b in zip(rows[r],rows[row],strict=True)]
        pivots.append(col)
    if any(all(x==0 for x in row[:-1]) and row[-1]!=0 for row in rows):
        raise ValueError('inconsistent exact constraints')
    free=set(range(n))-set(pivots)
    weights=[Fraction(float(x)) for x in approx]
    for i,col in enumerate(pivots):
        weights[col]=rows[i][-1]-sum(rows[i][j]*weights[j] for j in free)
    if min(weights)<=0 or sum(weights)!=1:raise ValueError('invalid positive weights')
    for col in matrix.T:
        if sum(a*Fraction(float(b)) for a,b in zip(weights,col,strict=True))!=0:
            raise ValueError('exact convex intersection fails')
    return weights


def frozen_rows(raw, old, out):
    base=ex.read(out/'fit.json')['full-svd-.1']
    rows={}
    for split in ('train','dev','test'):
        data,_=ex.panel(raw,old,split)
        x=edit.matrix(data,base)
        for i,q in enumerate(data['query_id']):
            rows[str(q)]={'state_hex':[float(v).hex() for v in x[i,:-1]],'split':split,
                          'source':str(data['group'][i]),'target':int(data['target'][i]),
                          'free':int(data['scores'][i,0].argmax()),'paid':int(data['read_scores'][i,0].argmax())}
    return rows


def audit(raw, old, out):
    base=ex.read(out/'fit.json')['full-svd-.1']
    panels={}
    for split in ('train','dev','test'):
        d,_=ex.panel(raw,old,split)
        m,w,s,_=edit.variables(d,base)
        panels[split]=(m,s,d['query_id'],d['group'])
    result={}
    for k in (2,3):
        for subset in combinations(tuple(panels),k):
            m,s,query,group=map(np.concatenate,zip(*(panels[n] for n in subset),strict=True))
            z=s[:,None]*m
            A=np.vstack([z.T,np.ones(len(z))])
            # Select a basic feasible support; near-dependent input columns can
            # produce floating-point supports that fail exact reconstruction.
            # Only the rational equalities below can establish nonseparability.
            for seed in range(32):
                direction=np.random.default_rng(seed).uniform(-1,1,len(z))
                opt=linprog(direction,A_eq=A,b_eq=np.r_[np.zeros(z.shape[1]),1.],bounds=(0,None),method='highs')
                if not opt.success:break
                ids=np.flatnonzero(opt.x>1.e-8)
                try:
                    weights=rational_solution(z[ids],opt.x[ids])
                    break
                except ValueError:
                    continue
            else:
                raise ValueError('no exact positive support found')
            name='+'.join(subset)
            if opt.status==2:
                result[name]={'points':len(m),'separation':edit.capacity(m,w,s)}
                if not result[name]['separation']['feasible']:raise ValueError('both alternatives failed')
                continue
            if not opt.success:raise ValueError(opt.message)
            support=[{'query':str(query[i]),'source':str(group[i]),'rescue':bool(s[i]>0),
                      'positive_rational_weight':str(lam)} for i,lam in zip(ids,weights,strict=True)]
            result[name]={'points':len(m),'support_count':len(ids),'weighted_sum_identically_zero':True,
                          'separation':{'feasible':False},'signed_support':support}
    return {'status':'retrospective labelled expressivity audit; no fitting change to any deployed policy',
            'features':'18 frozen first-prefix reliability/acoustic features after training standardization and clipping, plus intercept',
            'proof':'For the signed feature vectors, positive rational weights sum to one and the weighted vector equals zero in all 19 coordinates exactly. An affine score positive on every rescue and nonpositive otherwise cannot give these opposite labels on this support. The intercept absorbs the fixed price.',
            'panels':result}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','old','out','report'):p.add_argument(k,type=Path)
    p.add_argument('--save-inputs',type=Path);a=p.parse_args()
    ex.write(a.report,audit(a.root,a.old,a.out))
    if a.save_inputs:ex.write(a.save_inputs,frozen_rows(a.root,a.old,a.out))
