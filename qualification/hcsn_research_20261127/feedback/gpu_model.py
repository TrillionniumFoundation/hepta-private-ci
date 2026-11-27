"""Long-stream GPU constructor. Every inter-layer physical link sends only centered boundary at lag one."""
import math
import torch
from torch import nn
from torch.autograd.function import once_differentiable
from model import FeedbackBoundary
from qualification.hcsn_smallnet_20261124.model import ModelConfig
from qualification.hcsn_closure_20261124.communication import ControlSpec
from qualification.hcsn_closure_20261124.joint_run import JointHCSN
from qualification.hcsn_closure_20261124.baselines import CausalTransformer,GRUClassifier,LIFClassifier

class NativeRoot(torch.autograd.Function):
    @staticmethod
    def forward(ctx,mu,cost,absolute,sigma,rho,eta,gain,maintenance):
        kroot=(mu.square()+2*rho*sigma**2).sqrt()
        k=torch.where(mu>=0,(mu+kroot)/sigma**2,2*rho/(kroot-mu))
        s=gain/rho;d=(1-eta)*(absolute+mu/rho-maintenance/gain)+cost/s
        h=1+k*d;u=(2*(h-eta)).sqrt()
        for _ in range(4):
            q=eta*(-u).exp();v=u+q-h;t=1-q;u-=2*v*t/(2*t.square()-v*q)
        q=eta*(-u).exp();t=1-q;b=absolute-u/k
        tol=5e-6 if mu.dtype==torch.float32 else 5e-14
        if not bool((torch.isfinite(b)&(h>eta)&((u+q-h).abs()<=tol)&(b<absolute-1e-4)&(b>absolute-8)).all()):
            raise FloatingPointError("Halley domain/residual")
        ctx.save_for_backward(u/(k*kroot)-(d/kroot+(1-eta)/rho)/t,-1/(s*t),1-(1-eta)/t)
        return b
    @staticmethod
    @once_differentiable
    def backward(ctx,grad):
        return (*(grad*g for g in ctx.saved_tensors),None,None,None,None,None)

class GpuFeedback(FeedbackBoundary):
    def __init__(self,n,precision,root):
        config=ModelConfig(neurons=n,precision=precision,backend="uniformized",boundary_mode="qvi",
             message_mode="full",feature_bank="value_risk",feature_normalization="none")
        JointHCSN.__init__(self,config,"boundary_only")
        self.root_kind=root
        self.register_buffer("boundary_reference",self.fixed_boundary.detach().clone())
        for name,value in [("call_gain",.6),("panic_gain",.6),("target_margin",.7)]:
            self.register_buffer(name,self.reset_absolute.new_tensor(value))
        self.control_spec=ControlSpec("accumulate",config.slow_every);self.channel="boundary_only"
    def qvi_boundary(self,drift,cost):
        if getattr(self,"root_kind","newton")=="newton":return JointHCSN.qvi_boundary(self,drift,cost)
        c=self.config;eta=math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages))
        b=NativeRoot.apply(drift,cost,self.reset_absolute,c.sigma,c.discount,eta,c.gain,c.maintenance)
        nominal=(drift==c.base_drift)&(cost==c.cost)
        return torch.where(nominal,b+(self.fixed_boundary.expand_as(b)-b).detach(),b)

class StreamNetwork(nn.Module):
    def __init__(self,arm,n,depth,precision):
        super().__init__();physical=arm in ("newton","halley");self.physical=physical;self.n=n
        self.layers=nn.ModuleList([GpuFeedback(n,precision,arm) if physical else
             {"gru":GRUClassifier,"attention":CausalTransformer,"lif":LIFClassifier}[arm](n) for _ in range(depth)])
        learn=torch.float64 if precision=="float64" else torch.float32
        if not physical:self.layers.to(dtype=learn)
        self.links=nn.ModuleList([nn.Linear(n//2 if physical else n,6,dtype=learn) for _ in range(depth-1)])
    def forward(self,x):
        for layer,link in zip(self.layers,self.links):
            if self.physical:
                state=None;z=[]
                for frame in x:
                    _,_,state=layer(frame[None],state,return_features=True)
                    b=state.physical.boundary[:,self.n//2:]-layer.boundary_reference[self.n//2:]
                    z.append(b.to(frame))
                z=torch.stack(z)
                z=torch.cat((torch.zeros_like(z[:1]),z[:-1]),0)
            else:
                _,z,_=layer(x,return_features=True)
            x=link(z)
        return self.layers[-1](x)
