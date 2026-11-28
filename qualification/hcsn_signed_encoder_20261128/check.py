"""Independent quadrature, finite differences and the first six-layer gradient at matched initialization."""
import argparse
from pathlib import Path
import sys
import json
import math
import numpy as np
import torch
from force_kernel import table,transport,DT,SIGMA,signed_term,NODES

GL_NODES,GL_WEIGHTS=np.polynomial.legendre.leggauss(96)
def integrate(fn,lo,hi):
    mid=(hi+lo)/2; half=(hi-lo)/2
    return half*sum(w*fn(mid+half*n) for w,n in zip(GL_WEIGHTS,GL_NODES))
def normal_cdf(z):return .5*math.erfc(-z/math.sqrt(2))
def direct(x,d,grid):
    cuts=[0.,*list(.5*(grid[1:]+grid[:-1])),max(3.,x+d*DT+15*SIGMA*math.sqrt(DT))]
    scale=SIGMA*math.sqrt(DT)
    def density(y):
        return math.exp(-.5*((y-x-d*DT)/scale)**2)/(math.sqrt(2*math.pi)*scale)*(-math.expm1(-2*x*y/(SIGMA**2*DT)))
    alive=[integrate(density,a,b) for a,b in zip(cuts,cuts[1:])]
    hit=normal_cdf((-x-d*DT)/scale)+math.exp(-2*d*x/SIGMA**2)*normal_cdf((-x+d*DT)/scale)
    return np.array([*alive,hit])

def test_kernel():
    grid=np.array([.015,.30,.585,.87],np.float32).astype(float)
    t=torch.from_numpy(table(grid))
    d=np.array([-4.21,-2.11,-.852,-.071,.034,.312,1.679,3.14,4.26])
    dt=torch.tensor(d,requires_grad=True)
    v=transport(t,dt)
    ref=np.array([[direct(x,mu,grid) for x in grid] for mu in d])
    finite=np.array([[(direct(x,mu+1e-5,grid)-direct(x,mu-1e-5,grid))/2e-5 for x in grid] for mu in d])
    dv=torch.stack([torch.autograd.grad(v[:,i,j].sum(),dt,retain_graph=True)[0] for i in range(4) for j in range(5)],-1).reshape(len(d),4,5)
    e=float(abs(v.detach().numpy()-ref).max());de=float(abs(dv.numpy()-finite).max())
    normal=float(abs(t.sum(-1)-1).max());grad_normal=float(abs(dv.sum(-1)).max())
    assert e<2e-6 and de<.005 and normal<5e-12 and grad_normal<2e-10
    return dict(max_row_probability_error=e,max_drift_derivative_error=de,maximum_row_mass_error=normal,
                maximum_row_derivative_sum=grad_normal,independent_values=ref.size,nodes=NODES)
def six_layers(data):
    sys.path.insert(1,str(data/'src'))
    from network import make_model
    torch.set_num_threads(1);torch.manual_seed(95)
    h=torch.randn(2,12,96);probe=torch.randn(2,256)
    scores=[];grads=[]
    for arm in ("signed","free","nonfinancial","noforce"):
        net=make_model(data,arm,137,80).eval()
        net.zero_grad();o=net.encode(h);v=(o*probe).sum();v.backward()
        grads.append(torch.stack([m.feedback.grad.reshape(-1) for m in net.mixer]))
        scores.append(o.detach().clone())
    err=float((scores[0]-scores[1]).abs().max());ge=float((grads[0]-grads[1]).abs().max())
    assert err<5e-7 and ge<2e-6 and float(grads[-1].abs().max())==0 and all(float(z.norm())>0 for z in grads[0])
    return dict(signed_free_initial_max_output_error=err,signed_free_initial_max_gain_gradient_error=ge,
                signed_gain_gradient_norm_by_layer=[float(x.norm()) for x in grads[0]],noforce_gradient=float(grads[-1].abs().max()))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument("out",type=Path);a=p.parse_args()
    d={"kernel":test_kernel(),"network":six_layers(a.data)};a.out.write_text(json.dumps(d,indent=2)+"\n");print(json.dumps(d),flush=True)
