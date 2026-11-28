"""Check the exact bilinear price-mixture identity at this two-support operating family."""
import json
import numpy as np
import torch
from model import finance


def run():
    a=np.asarray(finance());c=a[1];s=(a[2]-a[0])/2
    q=[c[1]/c[2]-c[3]/c[3],1+s[1]/c[2]-s[3]/c[3],
       (c[2]-c[1])/c[2]-(c[4]-c[3])/c[3],(s[2]-s[1])/c[2]-(s[4]-s[3])/c[3]]
    torch.manual_seed(51);u=(2*torch.rand(20000,dtype=torch.float64)-1).requires_grad_();w=torch.rand_like(u).requires_grad_()
    eq=c[1]+s[1]*u+w*(c[2]-c[1]+(s[2]-s[1])*u)
    loss=c[3]+s[3]*u+w*(c[4]-c[3]+(s[4]-s[3])*u)
    real=u+eq/c[2]-loss/c[3]
    poly=q[0]+q[1]*u+q[2]*w+q[3]*u*w
    da=torch.autograd.grad(real.sum(),(u,w));db=torch.autograd.grad(poly.sum(),(u,w))
    return dict(coefficients=q,max_value_abs=float((real-poly).detach().abs().max()),
                gradient_max_abs=[float((v-h).abs().max()) for v,h in zip(da,db)],points=len(w),
                normalized_log_boundary_coefficient=float(s[0]/c[0]))
if __name__=='__main__':
    print(json.dumps(run(),indent=2))
