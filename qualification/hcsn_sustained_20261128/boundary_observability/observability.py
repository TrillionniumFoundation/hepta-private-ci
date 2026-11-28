"""Prospective minimax observability study for the HCSN first-passage port.

Run with --device cpu for an independent replay or --device cuda on a T4.
Outputs JSON containing independently verified extremal probability pairs.
"""
import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import linprog
from scipy.special import ndtr
import torch

SIGMA = 0.23
MU = 0.08 - 0.02 - 0.5 * SIGMA**2
DT = 0.25
SHOCKS = (-0.175, -0.075, 0.075, 0.175)
FOUR = ((0.08, 0.0), (0.125, 0.0), (0.5, 0.0), (3.0, 0.0))
PORTS = {
    "fixed_boundary": (),
    "one_hit": ((DT, 0.0),),
    "stock_four_horizons": FOUR,
    "eight_horizons": tuple((float(t), 0.0) for t in np.geomspace(0.04, 6, 8)),
    "four_horizons_plus_four_shocks": FOUR + tuple((DT, s) for s in (-0.20,-0.10,0.10,0.20))
}


def hit_numpy(x, t):
    xplus = np.maximum(x, 0)
    scale = SIGMA * np.sqrt(t)
    return np.where(x <= 0, 1.0, ndtr((-xplus - MU*t)/scale) +
                    np.exp(-2*MU*xplus/SIGMA**2) * ndtr((-xplus + MU*t)/scale))


def hit_torch(x, t):
    xplus = torch.clamp_min(x, 0)
    scale = SIGMA * np.sqrt(t)
    # erfc keeps the negative tails on the same numerical scale as scipy.ndtr.
    phi = lambda v: torch.special.erfc(-v / np.sqrt(2)) / 2
    return torch.where(x <= 0, torch.ones_like(x), phi((-xplus-MU*t)/scale)
                       + torch.exp(-2*MU*xplus/SIGMA**2) * phi((-xplus+MU*t)/scale))


def minimax(q, target, noise):
    """Primal affine decoder and dual pair of indistinguishable mixtures."""
    n, k = q.shape
    # Decoder: intercept c; coefficients a = a+ - a-; residual radius r.
    ones = np.ones((k, 1))
    approx = np.hstack([ones, q.T, -q.T])
    aug = np.vstack([np.hstack([approx, -ones]), np.hstack([-approx, -ones])])
    bounds = [(None, None)] + [(0, None)] * (2*n+1)
    opt = {"primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9}
    primal = linprog(np.r_[0, np.full(2*n, noise), 1], A_ub=aug,
                     b_ub=np.r_[target, -target], bounds=bounds, method="highs", options=opt)
    constraints = np.hstack([q, -q])
    eq = np.vstack([np.r_[ones[:,0], np.zeros(k)], np.r_[np.zeros(k), ones[:,0]]])
    dual = linprog(np.r_[-target, target]/2,
                   A_ub=np.vstack([constraints,-constraints]) if n else None,
                   b_ub=np.full(2*n,2*noise) if n else None, A_eq=eq,b_eq=[1,1],
                   bounds=(0,None), method="highs",options=opt)
    if not primal.success or not dual.success:
        raise ArithmeticError((primal.message, dual.message))
    weight = primal.x[1:1+n] - primal.x[1+n:1+2*n]
    intercept = primal.x[0]
    hi, lo = np.split(dual.x,2)
    upper = float(np.max(np.abs(intercept+weight@q-target))+noise*np.sum(np.abs(weight)))
    lower = float((hi-lo) @ target/2)
    discrepancy = float(np.max(np.abs(q@(hi-lo)),initial=0.0))
    if min(hi.min(),lo.min()) < -2e-8 or abs(hi.sum()-1)>2e-8 or abs(lo.sum()-1)>2e-8:
        raise ValueError("invalid probability vector")
    if discrepancy > 2*noise+5e-8 or abs(upper-lower)>5e-7:
        raise ValueError(("uncertified gap",upper,lower,discrepancy))
    return dict(upper=upper, lower=lower, discrepancy=discrepancy, c=intercept,
                a=weight.tolist(), p_plus=hi.tolist(), p_minus=lo.tolist())


def run(device):
    start = time.perf_counter()
    if device == "cuda":
        if not torch.cuda.is_available() or "T4" not in torch.cuda.get_device_name(0):
            raise RuntimeError("T4 requested but unavailable")
    torch.set_num_threads(1)
    result = dict(schema="hcsn-first-passage-minimax-v1", torch=str(torch.__version__),
                  scipy=scipy.__version__, numpy=np.__version__, platform=platform.platform(),
                  device=torch.cuda.get_device_name(0) if device=="cuda" else "cpu",
                  cuda=torch.version.cuda, rows=[])
    reference_difference = replay_difference = max_gap = 0.
    for k in (12, 32, 64):
        grid = np.linspace(.015,1.30,k)
        gx = torch.tensor(grid,device=device,dtype=torch.float64)
        rng = np.random.default_rng(916243+k)
        # Preserve sparse, concentrated, and spread simplex states in the replay.
        populations = rng.gamma(0.3,1,size=(8192,k))
        populations /= populations.sum(1,keepdims=True)
        masses = torch.tensor(populations,device=device,dtype=torch.float64)
        for name,queries in PORTS.items():
            q = np.asarray([hit_numpy(grid+s,t) for t,s in queries]).reshape(-1,k)
            qdev = torch.stack([hit_torch(gx+s,t) for t,s in queries]) if queries else gx.new_empty((0,k))
            if queries:
                reference_difference = max(reference_difference,float(np.max(np.abs(qdev.cpu().numpy()-q))))
            obs = masses@qdev.T
            for shift in SHOCKS:
                target = hit_numpy(grid+shift,DT)
                tgtdev = hit_torch(gx+shift,DT)
                actual = masses@tgtdev
                for eps in (0.0,1e-4,1e-3):
                    bound = minimax(q,target,eps)
                    weight = gx.new_tensor(bound["a"])
                    predicted = bound["c"] + obs@weight
                    # Worst-direction input error, independently for every population.
                    deviation = (predicted-actual).abs()+eps*weight.abs().sum()
                    largest = float(deviation.max().cpu())
                    a = gx.new_tensor(bound["p_plus"])
                    b = gx.new_tensor(bound["p_minus"])
                    gap = float((a-b)@tgtdev/2)
                    replay_difference = max(replay_difference,abs(gap-bound["lower"]))
                    max_gap = max(max_gap,abs(bound["lower"]-bound["upper"]))
                    if largest>bound["upper"]+5e-7 or abs(gap-bound["lower"])>1e-7:
                        raise AssertionError("replay outside bound")
                    result["rows"].append(dict(atoms=k,port=name,query_count=len(queries),
                          shift=shift,noise=eps,replay_states=len(populations),
                          replay_max=largest,replay_mean=float(deviation.mean().cpu()),
                          reconstructed_lower=gap,**bound))
    result.update(max_primal_dual_gap=max_gap,max_torch_numpy_kernel_error=reference_difference,
                  max_tensor_witness_error=replay_difference,elapsed_s=time.perf_counter()-start)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--device",choices=["cpu","cuda"],default="cuda")
    parser.add_argument("--out",default="result.json")
    a=parser.parse_args()
    Path(a.out).write_text(json.dumps(run(a.device),sort_keys=True,allow_nan=False)+"\n")
