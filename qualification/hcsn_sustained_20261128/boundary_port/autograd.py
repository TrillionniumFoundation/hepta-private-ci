"""Reverse-mode derivatives for one physical boundary wire and two receiver heads."""
import json
from pathlib import Path
import numpy as np
import torch

from halfline import Stationary
from port import drive, rate, port_gain, read_first_hit

def tensor(x):
    return torch.as_tensor(float(x),dtype=torch.float64)


class Torch:
    number=staticmethod(tensor)
    exp=staticmethod(lambda x:torch.exp(torch.as_tensor(x,dtype=torch.float64)))
    sqrt=staticmethod(lambda x:torch.sqrt(torch.as_tensor(x,dtype=torch.float64)))
    tanh=staticmethod(torch.tanh)
    phi=staticmethod(torch.special.ndtr)
    sqrt2pi=staticmethod(lambda:tensor(2*np.pi).sqrt())
    is_zero=staticmethod(lambda t:bool(t==0))


def implicit(value, residual):
    """First-order implicit derivative on one already selected simple branch."""
    u=tensor(value).requires_grad_()
    f=residual(u)
    du,=torch.autograd.grad(f,u,retain_graph=True)
    if abs(du)<1e-6:
        raise ArithmeticError("branch is too close to a fold")
    return u-(f-f.detach())/du.detach()


def path(eps,kappa,branch,rec="high",cut_wire=False):
    numerical=port_gain(float(eps.detach()),float(kappa.detach()),branch,rec)
    def src_f(u):
        v=drive(eps*.25*rate(u),Torch)
        return Stationary(Torch,drive=v).stationary(u)[0]
    u=implicit(numerical["u"],src_f)
    v=drive(eps*.25*rate(u),Torch)
    wall=Stationary(Torch,drive=v).B
    y=torch.log(wall/Stationary(Torch).B)
    if cut_wire:
        y=torch.zeros_like(y)
    v2=drive(kappa*y,Torch)
    pr=Stationary(Torch,drive=v2)
    u2=implicit(numerical["receiver_u"] if not cut_wire else
                port_gain(0.,0.,branch,rec)["receiver_u"],lambda r:pr.stationary(r)[0])
    mu=-.20-kappa*y/.25
    x=tensor(.18)
    wid=tensor(.23*.5)
    hit=torch.special.ndtr((-x-mu*.25)/wid)+torch.exp(-2*mu*x/.23**2)*torch.special.ndtr((-x+mu*.25)/wid)
    return torch.stack((rate(u2),hit))


def reference(eps,kappa):
    out=[]
    for b in ("low","high"):
        p=port_gain(eps,kappa,b,"high")
        out.append(np.array([p["receiver_rate"],read_first_hit(p["reported_value"],kappa)]))
    return out[1]-out[0]


def run():
    torch.set_num_threads(1)
    rows=[]
    for e in (0.,.025,.075):
        g=torch.tensor([e,1.],dtype=torch.float64,requires_grad=True)
        def fn(t,cut=False):
            return path(t[0],t[1],"high",cut_wire=cut)-path(t[0],t[1],"low",cut_wire=cut)
        data=fn(g).detach().numpy()
        jac=torch.autograd.functional.jacobian(fn,g).detach().numpy()
        ctrl=fn(g,True).detach().numpy()
        cjac=torch.autograd.functional.jacobian(lambda t:fn(t,True),g).detach().numpy()
        ref=[]
        for i,h in enumerate((.0001,.0002)):
            def point(d):
                v=np.array([e,1.]);v[i]+=h*d
                return reference(*v)
            ref.append((point(-2)-8*point(-1)+8*point(1)-point(2))/(12*h))
        ref=np.array(ref).T
        if np.max(abs(jac-ref))>1e-7 or np.max(abs(data-reference(e,1.)))>1e-9:
            raise RuntimeError("external differences did not reproduce reverse mode")
        if np.max(abs(ctrl))!=0 or np.max(abs(cjac))!=0:
            raise RuntimeError("a receiver bypasses its disconnected boundary wire")
        rows.append(dict(epsilon=e,kappa=1.,contrast=data.tolist(),reverse_jacobian=jac.tolist(),
                         fourth_order_jacobian=ref.tolist(),max_absolute_difference=np.max(abs(jac-ref)),
                         cut_wire_contrast=ctrl.tolist(),cut_wire_jacobian=cjac.tolist()))
    return dict(torch=torch.__version__,rows=rows,observable_order=["signed_receiver_steady_flux","single_interval_hit_mass"],
                differentiable_inputs=["source_gain","receiver_wire_gain"],receiver_initialization="same high branch for the steady receiver; same 0.18 margin for the one-bin receiver")

if __name__=="__main__":
    report=run()
    Path(__file__).with_name("autograd.json").write_text(json.dumps(report,indent=2)+"\n")
    print(report)
