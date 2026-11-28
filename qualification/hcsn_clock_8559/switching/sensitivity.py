"""Implicit layer for the continuous finite-maturity regime-switching equilibrium."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from smooth import fit,residual

SEG=(140,24,160)
TIMES=96

def derivatives(at,law,segments=SEG,steps=TIMES):
    z=np.asarray([*at,*law],dtype=np.complex128)
    def f(p):
        return residual(p[:2],p[2:4],p[4:6],segments,steps)
    scale=1e-17
    columns=[]
    for i in range(6):
        p=z.copy();p[i]+=scale*1j
        columns.append(np.asarray(f(p)).imag/scale)
    full=np.stack(columns,axis=1)
    return full[:,:2],full[:,2:]

def solve(law,segments=SEG,steps=TIMES):
    lam,q=np.asarray(law)[:2],np.asarray(law)[2:]
    if not (0<=lam[0]<lam[1] and min(q)>0):
        raise ValueError('This operator requires ordered, distinct frictions and positive switching rates.')
    out,_=fit(lam,q,segments,steps,initial=(69.5,72.5))
    if not out['success']:raise ArithmeticError(out)
    return np.array(out['walls'])

class EquilibriumWalls(torch.autograd.Function):
    @staticmethod
    def forward(ctx,theta):
        if tuple(theta.shape)!=(4,) or theta.dtype!=torch.float64 or theta.device.type!='cpu':
            raise ValueError('Use four CPU float64 coordinates for this reference equilibrium layer.')
        law=theta.detach().numpy()
        wall=solve(law)
        J,K=derivatives(wall,law)
        if np.linalg.cond(J)>1e5:raise ValueError('Ill-conditioned wall Jacobian.')
        ctx.save_for_backward(torch.from_numpy(-np.linalg.solve(J,K)))
        return torch.from_numpy(wall)
    @staticmethod
    def backward(ctx,grad):
        jac,=ctx.saved_tensors
        return grad@jac

def verify(path):
    theta=np.array([.01,.04,.12,.16])
    rows=[]
    for scale in [1,2,4]:
        seg=(70*scale,12*scale,80*scale);M=48*scale
        wall=solve(theta,seg,M);J,K=derivatives(wall,theta,seg,M)
        jac=-np.linalg.solve(J,K)
        dirs=np.r_[np.eye(4),[[.01,-.02,.03,.04],[-.02,.03,.01,.04]]]
        checks=[]
        for d in dirs:
            h=1.e-5/(np.max(abs(d)))
            plus=solve(theta+h*d,seg,M);minus=solve(theta-h*d,seg,M)
            measured=(plus-minus)/(2*h);pred=jac@d
            checks.append(dict(direction=d.tolist(),resolved=measured.tolist(),predicted=pred.tolist(),
                               max_abs_error=float(np.max(abs(measured-pred))),
                               relative_error=float(np.max(abs(measured-pred))/max(1.,np.max(abs(pred))))))
        rows.append(dict(spatial_segments=seg,bond_time_steps=M,wall=wall.tolist(),root_jacobian=J.tolist(),
                         root_condition=float(np.linalg.cond(J)),gradient=jac.tolist(),checks=checks))
        print(scale,wall,jac.tolist(),max(x['relative_error'] for x in checks),flush=True)
    t=torch.tensor(theta,requires_grad=True);w=EquilibriumWalls.apply(t)
    scalar=torch.log(w[1]/w[0]);grad,=torch.autograd.grad(scalar,t)
    a=dict(resolved_panels=rows,value=float(scalar.detach()),backprop_gradient=grad.tolist(),
           interpretation='Derivative of this discretized fitted-wall root, local to distinct ordered regimes.')
    path.write_text(json.dumps(a,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);args=p.parse_args();verify(args.out)
