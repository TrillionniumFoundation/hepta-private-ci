"""Finite-horizon risk-neutral LQ reference under the existing NDU research owner.

Riccati and a dense Hamiltonian forward/backward boundary solve implement the
SAME deterministic problem. Additive independent unit-covariance noise changes
expected value, not the gains in this declared LQ profile. This is not a general
nonlinear/recursive-utility FBSDE solver, a task critic, or a production API.
"""
from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch


@dataclass(frozen=True)
class Problem:
    A: torch.Tensor  # [T,n,n]
    B: torch.Tensor  # [T,n,m]
    Q: torch.Tensor  # [T,n,n]
    R: torch.Tensor  # [T,m,m]
    G: torch.Tensor  # [n,n]
    S: torch.Tensor  # [T,n,d], covariance factor

    def validate(self):
        fields = (self.A, self.B, self.Q, self.R, self.G, self.S)
        if any(not isinstance(v, torch.Tensor) or v.dtype != torch.float64
               or v.device.type != 'cpu' or v.requires_grad
               or not torch.isfinite(v).all() for v in fields):
            raise ValueError('finite detached CPU float64 coefficients required')
        if self.A.ndim != 3 or self.B.ndim != 3 or self.S.ndim != 3:
            raise ValueError('coefficient rank')
        t, n, n2 = self.A.shape
        m, d = self.B.shape[-1], self.S.shape[-1]
        if (not 1 <= t <= 32 or not 1 <= n == n2 <= 16 or not 1 <= m <= 8
                or not 1 <= d <= 8 or self.B.shape != (t,n,m)
                or self.Q.shape != (t,n,n) or self.R.shape != (t,m,m)
                or self.G.shape != (n,n) or self.S.shape != (t,n,d)):
            raise ValueError('bounded matching coefficient shapes required')
        for values, floor in ((self.Q,-1e-12),(self.G,-1e-12),(self.R,1e-8)):
            if (not torch.allclose(values, values.transpose(-1,-2), atol=1e-12, rtol=0)
                    or float(torch.linalg.eigvalsh(values).min()) < floor):
                raise ValueError('Q,G must be PSD and R uniformly positive definite')
        return t, n, m


def riccati(problem):
    """Backward value matrices P, scalar noise offsets c, and feedback gains K."""
    t, n, m = problem.validate()
    started = time.perf_counter()
    p = [None]*t + [problem.G.clone()]
    c, gains = [0.0]*(t+1), [None]*t
    residual = 0.0
    for k in range(t-1,-1,-1):
        a,b,q,r,s = (v[k] for v in (problem.A,problem.B,problem.Q,problem.R,problem.S))
        h = r + b.T@p[k+1]@b
        if float(torch.linalg.cond(h)) > 1e10:
            raise ValueError('ill-conditioned control Hessian')
        rhs = b.T@p[k+1]@a
        gains[k] = torch.linalg.solve(h,rhs)
        residual = max(residual, float((h@gains[k]-rhs).abs().max()))
        raw = q + a.T@p[k+1]@a - rhs.T@gains[k]
        p[k] = (raw+raw.T)/2
        c[k] = c[k+1] + .5*float(torch.trace(p[k+1]@s@s.T))
        if not torch.isfinite(p[k]).all() or float(torch.linalg.eigvalsh(p[k]).min()) < -1e-9:
            raise ValueError('invalid Riccati value matrix')
    return p,gains,c,dict(seconds=time.perf_counter()-started, solves=t,
        largest_solve_dimension=m, gain_equation_residual=residual, backend='finite-riccati')


def trajectory(problem, initial, gains):
    t,n,m = problem.validate()
    if (initial.shape != (n,) or initial.dtype != torch.float64
            or not torch.isfinite(initial).all() or initial.requires_grad
            or initial.device.type != 'cpu' or len(gains) != t
            or any(k.shape != (m,n) or not torch.isfinite(k).all() for k in gains)):
        raise ValueError('invalid initial state or gain sequence')
    states, actions = [initial.clone()], []
    for k in range(t):
        actions.append(-gains[k]@states[k])
        states.append(problem.A[k]@states[k]+problem.B[k]@actions[k])
    return torch.stack(states),torch.stack(actions)


def deterministic_cost(problem, states, actions):
    return .5*float(states[-1]@problem.G@states[-1] + sum(
        states[k]@problem.Q[k]@states[k]+actions[k]@problem.R[k]@actions[k]
        for k in range(len(actions))))


def hamiltonian(problem, initial):
    """Dense independent reference for the zero-noise Hamiltonian FBSDE special case.

    Unknowns are X[1:T], u[0:T-1], lambda[1:T]; lambda is a costate, NOT utility.
    Initial states may be a vector [n] or up to 256 columns [n,batch]. Matrix RHS
    reuses ONE factorization; identity columns construct a reusable linear map.
    This does not pretend open-loop plans solve realized stochastic feedback.
    """
    t,n,m = problem.validate()
    if (not isinstance(initial, torch.Tensor) or initial.ndim not in (1,2)
            or initial.shape[0] != n or (initial.ndim == 2 and not 1 <= initial.shape[1] <= 256)
            or initial.dtype != torch.float64 or initial.requires_grad
            or initial.device.type != 'cpu' or not torch.isfinite(initial).all()):
        raise ValueError('invalid initial state or column batch')
    if torch.count_nonzero(problem.S):
        raise ValueError('dense boundary reference is zero-noise only')
    width = t*(2*n+m)
    if width > 1024:
        raise ValueError('dense reference dimension budget')
    started = time.perf_counter()
    matrix = torch.zeros(width,width,dtype=torch.float64)
    tail = tuple(initial.shape[1:])
    rhs = torch.zeros((width,)+tail,dtype=torch.float64)
    eye = torch.eye(n,dtype=torch.float64)
    xs = [None]+[slice(k*n,(k+1)*n) for k in range(t)]
    us = [slice(t*n+k*m,t*n+(k+1)*m) for k in range(t)]
    ls = [None]+[slice(t*(n+m)+k*n,t*(n+m)+(k+1)*n) for k in range(t)]
    for k in range(t):
        row = slice(k*n,(k+1)*n)
        matrix[row,xs[k+1]],matrix[row,us[k]] = eye,-problem.B[k]
        if k:
            matrix[row,xs[k]] = -problem.A[k]
        else:
            rhs[row] = problem.A[k]@initial
        row = slice(t*n+k*m,t*n+(k+1)*m)
        matrix[row,us[k]],matrix[row,ls[k+1]] = problem.R[k],problem.B[k].T
    for k in range(1,t):
        row = slice(t*(n+m)+(k-1)*n,t*(n+m)+k*n)
        matrix[row,ls[k]],matrix[row,xs[k]],matrix[row,ls[k+1]] = eye,-problem.Q[k],-problem.A[k].T
    row = slice(width-n,width)
    matrix[row,ls[t]],matrix[row,xs[t]] = eye,-problem.G
    solution = torch.linalg.solve(matrix,rhs)
    residual = float((matrix@solution-rhs).abs().max())
    if not torch.isfinite(solution).all() or residual > 1e-8*(1+float(rhs.abs().max())):
        raise ValueError('Hamiltonian boundary residual failed')
    states = torch.cat((initial[None],solution[:t*n].reshape((t,n)+tail)))
    actions = solution[t*n:t*(n+m)].reshape((t,m)+tail)
    return states,actions,dict(seconds=time.perf_counter()-started,solves=1,
        largest_solve_dimension=width, boundary_residual=residual,
        backend='dense-zero-noise-hamiltonian')


def benchmark(output):
    """Nine fixed numerical problems; input tensors saved, not language tasks."""
    output.mkdir(exist_ok=False,parents=True)
    plan = dict(schema='hepta.ndu.riccati-parity.v1', seeds=[7,19,31], horizons=[4,8,16],
        state_dimension=4,control_dimension=2,tolerance=1e-8,independent_task_evidence=False)
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    records=[]
    for seed in plan['seeds']:
        for horizon in plan['horizons']:
            row=dict(seed=seed,horizon=horizon,status='started')
            try:
                rng=torch.Generator().manual_seed(seed)
                a=.9*torch.eye(4,dtype=torch.float64)+.1*torch.randn(4,4,generator=rng,dtype=torch.float64)
                b=.3*torch.randn(4,2,generator=rng,dtype=torch.float64)
                initial=torch.randn(4,generator=rng,dtype=torch.float64)
                problem=Problem(a.repeat(horizon,1,1),b.repeat(horizon,1,1),
                    torch.eye(4,dtype=torch.float64).repeat(horizon,1,1),
                    torch.eye(2,dtype=torch.float64).repeat(horizon,1,1),
                    2*torch.eye(4,dtype=torch.float64),torch.zeros(horizon,4,1,dtype=torch.float64))
                data={name:getattr(problem,name).tolist() for name in ('A','B','Q','R','G','S')}
                data['initial']=initial.tolist()
                row['problem']=data
                row['problem_sha256']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
                p,k,c,fast=riccati(problem)
                xf,uf=trajectory(problem,initial,k)
                xd,ud,dense=hamiltonian(problem,initial)
                error=max(float((xf-xd).abs().max()),float((uf-ud).abs().max()))
                cost=deterministic_cost(problem,xf,uf)
                value=.5*float(initial@p[0]@initial)+c[0]
                if max(error,abs(cost-value))>plan['tolerance']:
                    raise ValueError('solver replacement changes solution')
                row.update(status='succeeded',riccati=fast,hamiltonian=dense,
                    maximum_trajectory_difference=error,cost=cost,value=value)
            except Exception as exc:
                row.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:512])
            records.append(row)
            with (output/'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(row,allow_nan=False)+'\n')
    summary=plan|dict(planned=9,recorded=len(records),failed=sum(r['status']=='failed' for r in records),
        maximum_difference=max((r['maximum_trajectory_difference'] for r in records if r['status']=='succeeded'),default=None),
        total_seconds={key:sum(r[key]['seconds'] for r in records if key in r) for key in ('riccati','hamiltonian')},
        timing_includes_backend_different_work=True,production_accepted=False,new_encoder_reader_calls=0)
    (output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    if summary['failed']:
        raise RuntimeError('failed numerical cases retained')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    print(json.dumps(benchmark(parser.parse_args().output)))
