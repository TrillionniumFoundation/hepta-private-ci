"""Recompute reported errors from independent quadrature/ODE prices on a subset."""
import argparse
from pathlib import Path
import json
import sys

import numpy as np

from design import Law,Surface,TEST_SCALE,TEST_X,PILOT,OPTIONS,population,CENTER


def check(reference,root):
    sys.path.insert(0,str(reference.parent))
    from reference import solution
    result=json.loads((root/"held.json").read_text())
    runs=np.load(root/"held_measurements.npz")
    if runs["design_ids"].shape!=(128,4,12,6):
        raise ValueError("six paid calls per trajectory required")
    recovered=np.random.default_rng(84733)
    contracts=population(recovered,128)
    np.testing.assert_array_equal(contracts,runs["contracts"])
    # Check every paid recorded measurement via experiment-specific selected
    # IDs against a fresh replay of initially drawn noise, paired by order.
    worst_raw,worst_metric,worst_jac=0.,0.,0.
    for i,p in enumerate(contracts):
        law=Law(Surface(*p[4:]),PILOT+OPTIONS)
        ids=np.arange(len(PILOT)+len(OPTIONS))[None,:]
        actual,jac=law.evaluate(p[None,:4],ids,True)
        noise=recovered.normal(size=(12,6,2))
        for j in range(4):
            subset=actual[0][runs["design_ids"][i,j]]
            raw=subset+(.02+.002*abs(subset))*noise
            worst_raw=max(worst_raw,float(np.max(abs(raw-runs["raw"][i,j]))))
        if i not in (3,27,69,110):
            continue
        for k in range(4):
            h=CENTER[k]*1e-5
            up=p[:4].copy()
            down=up.copy()
            up[k]+=h
            down[k]-=h
            approx=(law.evaluate(up[None,:],ids)-law.evaluate(down[None,:],ids))/(2*h)
            worst_jac=max(worst_jac,float(np.max(abs(approx-jac[...,k])/(1+abs(approx)))))
        def direct(theta):
            c,par,alpha,tax=theta
            r,d,s,m,prem=p[4:]
            vals=[]
            for scale in TEST_SCALE:
                contract=np.array([r,d,s,tax,alpha,c,par*scale,m,prem])
                vals.append(solution(contract,TEST_X)[:,[0,2,1]])
            return np.array(vals)
        gold=direct(p[:4])
        for method in range(4):
            for rep in (0,11):
                z=runs["estimates"][i,method,rep]
                err=abs(direct(z)-gold)
                check_scores=[err[:-1].max()/p[1],err[-1].max()/p[1],np.max(abs(z/p[:4]-1))]
                worst_metric=max(worst_metric,float(np.max(abs(check_scores-runs["scores"][i,method,rep]))))
    if worst_raw>1e-10 or worst_metric>1e-8 or worst_jac>1e-7:
        raise ArithmeticError((worst_raw,worst_metric,worst_jac))
    return dict(all_scalar_readings_checked=int(runs["raw"].size),different_contracts=128,
                sample_reference_multiarm_trajectories=32,maximum_raw_difference=worst_raw,
                maximum_independent_score_difference=worst_metric,maximum_relative_jac_difference=worst_jac)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("reference",type=Path)
    ap.add_argument("directory",type=Path)
    args=ap.parse_args()
    report=check(args.reference,args.directory)
    (args.directory/"verified.json").write_text(json.dumps(report,indent=2)+"\n")
    print(report)
