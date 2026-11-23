"""Replay TRAIN geometry and compare three realizable readout extensions."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.special import expit

GEOMETRY_SHA = "2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5"


def solve(x, y, mask, weights, editable, margin=1e-3):
    raw = x @ weights.T
    p = expit(raw[:, 3])
    base = np.column_stack((np.zeros(len(x)),raw[:,:3],1-2*p,2*p-1))
    # Action-specific additive heads have zero displacement at the incumbent.
    # STOP is fixed at zero. Old belief and the original Q scores stay present.
    d = x.shape[1]
    rows,limits,witnesses=[],[],[]
    for i in range(len(x)):
        legal=np.flatnonzero(mask[i])
        winners=legal[np.isclose(y[i,legal],y[i,legal].max(),atol=1e-10,rtol=0)]
        if len(winners)!=1:
            continue
        a=int(winners[0])
        for b in legal[legal!=a]:
            coefficients=np.zeros((len(editable),d))
            if a in editable: coefficients[editable.index(a)]-=x[i]
            if b in editable: coefficients[editable.index(b)]+=x[i]
            cap=float(base[i,a]-base[i,b]-margin)
            if not coefficients.any() and cap<0:
                witnesses.append(dict(row=i,preferred=a,other=int(b),base_gap=float(base[i,a]-base[i,b])))
            rows.append(coefficients.ravel()); limits.append(cap)
    A,b=np.asarray(rows),np.asarray(limits)
    t0=time.monotonic()
    result=dict(dimensions=A.shape[1],constraints=len(b),unchangeable_violations=len(witnesses),
                first_witness=witnesses[0] if witnesses else None)
    if witnesses:
        return {**result,"status":"infeasible_by_identity","seconds":time.monotonic()-t0}
    # Minimize max absolute coordinate subject to every legal action ranking.
    n=A.shape[1]
    Aub=np.concatenate((np.c_[A,np.zeros(len(A))],np.c_[np.eye(n),-np.ones(n)],np.c_[-np.eye(n),-np.ones(n)]))
    res=linprog(np.r_[np.zeros(n),1.0],A_ub=Aub,b_ub=np.r_[b,np.zeros(2*n)],
                bounds=[(None,None)]*n+[(0,None)],method="highs",options={"time_limit":60.0})
    result.update(status={0:"feasible",1:"unresolved_limit",2:"infeasible_lp"}.get(res.status,"unresolved"),
                  seconds=time.monotonic()-t0,status_detail=res.message)
    if res.success:
        v=res.x[:-1]
        violation=float(np.maximum(A@v-b,0).max())
        if violation>5e-7: raise ArithmeticError("independent ranking residual too large")
        result.update(min_linf=float(res.x[-1]),l2=float(np.linalg.norm(v)),worst_constraint_residual=violation,
                      displacement=v.tolist())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    if hashlib.sha256(args.geometry.read_bytes()).hexdigest()!=GEOMETRY_SHA: raise ValueError("wrong geometry")
    dest={"input_sha256":GEOMETRY_SHA,"margin":0.001,"scope":"original TRAIN only, additive affine heads, no behavioral holdout","fits":{}}
    with np.load(args.geometry,allow_pickle=False) as inp:
        for fit in [11,23,37,53,71]:
            parts=[inp[f"fit{fit}_{k}"] for k in ("x","y","mask","theta")]
            dest["fits"][fit]={k:solve(*parts,actions) for k,actions in {
                "continuation":[1,2,3],"terminal":[4,5],"joint":[1,2,3,4,5]}.items()}
    with args.output.open("x") as f:
        json.dump(dest,f,separators=(",",":"),allow_nan=False)


if __name__=="__main__":
    main()
