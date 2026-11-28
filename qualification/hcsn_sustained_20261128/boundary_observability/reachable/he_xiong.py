"""Published stationary He–Xiong values in differentiable, causal sender/receiver cells."""
import math
import torch
from torch import nn
from torch.nn import functional as F
from dataclasses import dataclass

def cdf(x):
    return .5*math.erfc(-x/math.sqrt(2))


def _average_slope_at_nearby_roots(derivative, left, right):
    """Two-point Gauss average of a derivative on a short spectral interval."""
    half = (right - left) / 2
    midpoint = left + half
    offset = half / math.sqrt(3)
    return (derivative(midpoint - offset) + derivative(midpoint + offset)) / 2

@dataclass(frozen=True)
class Law:
    r:float=.08
    payout:float=.02
    sigma:float=.23
    alpha:float=.6
    tax:float=.27
    C:float=6.39
    P0:float=61.68
    m:float=1.
    premium:float=.01

class Published(nn.Module):
    def __init__(self,p=None):
        super().__init__()
        p=self.p=p or Law()
        self.var=p.sigma**2
        self.a=(p.r-p.payout-.5*self.var)/self.var
        self.mu=self.a*self.var
        self.z=math.sqrt(self.a**2+2*p.r/self.var)
        self.q=p.r+p.premium
        self.zb=math.sqrt(self.a**2+2*self.q/self.var)
        self.eta=self.z-self.a
        self.gamma=self.z+self.a
        self.disc=math.exp(-self.q*p.m)
        self.c=p.C/p.m
        s=p.sigma*math.sqrt(p.m)
        def small(y):
            return self.disc*(cdf(y*s)-math.exp(p.r*p.m)*cdf(-self.z*s))/(self.z+y)
        # Eq. 12 and A7 have removable divided differences when the two
        # discount roots coincide. With fixed contract coefficients the
        # branch is independent of all trainable inputs (margin, principal).
        self._close_discount_roots = abs(self.z-self.zb) <= 1e-4 * max(1., abs(self.z))
        def big(y):
            if self._close_discount_roots and y == -self.zb:
                def derivative(v):
                    pdf = math.exp(-.5*(v*s)**2)/math.sqrt(2*math.pi)
                    factor = math.exp(.5*(self.z-v)*(self.z+v)*s*s)
                    return s*pdf + v*s*s*factor*cdf(-self.z*s)
                return _average_slope_at_nearby_roots(derivative, -self.z, y)
            return (cdf(y*s)-math.exp((self.z**2-y**2)*s*s/2)*cdf(-self.z*s))/(self.z+y)
        t=small(self.a)+small(-self.a)
        u=big(self.zb)+big(-self.zb)
        den=p.payout/(self.eta-1)+p.alpha/p.m*u
        w=(1-self.disc)/self.eta+t
        self.bc=((1-p.tax)/self.eta+(u-w)/(p.m*self.q))/den
        self.bp=w/(p.m*den)
        self.B0=self.bc*p.C+self.bp*p.P0
        self.register_buffer('basis_y',torch.tensor([self.a,-self.a,self.zb,-self.zb],dtype=torch.float64))
        with torch.enable_grad():
            margin=torch.tensor(.18,dtype=torch.float64,requires_grad=True)
            base=torch.tensor(p.P0,dtype=torch.float64)
            a,f=self.values(margin,base)
            da,=torch.autograd.grad(a,margin,retain_graph=True)
            df,=torch.autograd.grad(f,margin)
        for name,v in [('A0',a),('F0',f),('dA0',da),('dF0',df)]:
            self.register_buffer(name,v.detach())

    def boundary(self,P):
        return self.bc*self.p.C+self.bp*P

    def passage(self,x,t):
        s=self.p.sigma*math.sqrt(t)
        return torch.special.ndtr((-x-self.mu*t)/s)+torch.exp(-2*self.a*x)*torch.special.ndtr((-x+self.mu*t)/s)

    def equity(self,x,P):
        p=self.p
        B=self.boundary(P)
        s=p.sigma*math.sqrt(p.m)
        X=x[...,None]
        y=self.basis_y
        def k(y,j):
            return (torch.exp((((j-self.a)**2-y*y)*s*s*.5)-j*X)*torch.special.ndtr((-X+(j-self.a)*s*s)/s)
                    -torch.exp(-(self.a+y)*X)*torch.special.ndtr((-X+y*s*s)/s))
        j=self.gamma
        coeff=torch.special.ndtr(y*s)-torch.exp(((j-self.a)**2-y*y)*s*s*.5)*cdf((j-self.a)*s)
        full=coeff*torch.exp(-j*X)+k(y,j)
        tail=k(y,-self.eta)
        # y=[a,-a,zb,-zb]. Each pair forms the two summands in (A5).
        if self._close_discount_roots:
            # N(u) = K(x;a,u,gamma) + k(x;a,-u,-eta) vanishes at u=z.
            # N(zb)/(z-zb) = -average[N'] from z to zb. Differentiate only
            # the spectral argument; x and P keep their ordinary Torch graph.
            def k_slope(v, root):
                shifted = (-x + v*s*s)/s
                scale = torch.exp(-(self.a+v)*x)
                first = (torch.exp(.5*((root-self.a)**2-v*v)*s*s-root*x)
                         * torch.special.ndtr((-x+(root-self.a)*s*s)/s))
                return (-v*s*s*first + x*scale*torch.special.ndtr(shifted)
                        - s*scale*torch.exp(-.5*shifted.square())/math.sqrt(2*math.pi))

            def numerator_slope(v):
                factor = math.exp(.5*(self.z-v)*(self.z+v)*s*s)
                coeff_slope = (s*math.exp(-.5*(v*s)**2)/math.sqrt(2*math.pi)
                               + v*s*s*factor*cdf(self.z*s))
                return (coeff_slope*torch.exp(-j*x) + k_slope(v,j)
                        - k_slope(-v,-self.eta))

            regular = ((full[...,0]+tail[...,1])/(self.z-self.a)
                       + (full[...,1]+tail[...,0])/(self.z+self.a))
            discounted = ((full[...,3]+tail[...,2])/(self.z+self.zb)
                          - _average_slope_at_nearby_roots(numerator_slope, self.z, self.zb))
            aux = torch.stack((regular, discounted), dim=-1)
        else:
            aux=(full[...,::2]+tail[...,1::2])/(self.z-y[::2])+(full[...,1::2]+tail[...,::2])/(self.z+y[::2])
        adj=P/p.m-self.c/self.q
        equity_cost=(1-p.tax)*p.C+(1-self.disc)*adj
        decay=torch.exp(-j*x)
        payout=-p.payout*B*decay/(j+1)
        cost=-equity_cost*(1/self.eta-torch.expm1(-j*x)/j)
        gap=p.alpha*B/p.m-self.c/self.q
        bond=self.disc*adj*aux[...,0]-gap*aux[...,1]
        return B*torch.exp(x)+(payout+cost+bond)/(self.z*self.var)

    def values(self,x,P):
        # The stopped-region extension reproduces absorption at an already crossed wall.
        live=x.clamp_min(0)
        a=self.equity(live,P)
        f=self.passage(live,self.p.m)
        return torch.where(x>0,a,torch.zeros_like(a)),torch.where(x>0,f,torch.ones_like(f))

    def move_mean(self,x,dt=.25,reset=.30):
        live=x.clamp_min(0)
        s=self.p.sigma*math.sqrt(dt)
        m1=live+self.mu*dt
        m2=-live+self.mu*dt
        def positive_mean(m):
            t=m/s
            return m*torch.special.ndtr(t)+s/math.sqrt(2*math.pi)*torch.exp(-.5*t*t)
        alive=positive_mean(m1)-torch.exp(-2*self.a*live)*positive_mean(m2)
        out=alive+reset*self.passage(live,dt)
        return torch.where(x>0,out,torch.full_like(x,reset))

class LiteralCell(nn.Module):
    def __init__(self,kind='literal',input_dim=6,n=8):
        super().__init__()
        self.kind=kind
        self.n=n
        self.drive=nn.Linear(input_dim,n//2,dtype=torch.float64)
        self.rec=nn.Linear(n,n,bias=False,dtype=torch.float64)
        self.readout=nn.Linear(n,2,dtype=torch.float64)
        self.law=Published()
        mask=torch.ones(n,n,dtype=torch.float64)
        mask[:n//2,n//2:]=0.
        self.register_buffer('mask',mask)

    def forward(self,x,silence_boundary=False,diagnostics=False):
        x=x.double()
        prior=x.new_zeros(len(x[0]),self.n)
        margin=prior+.18
        aa,ff=prior+self.law.A0,prior+self.law.F0
        rows=[]
        crossings=[]
        for frame in x:
            if self.kind=='zero':
                feedback=0.
            else:
                # A weakening of continuation value lowers debt pressure; a high first-hit risk increases it.
                feedback=.4*((aa-self.law.A0)/20).tanh()+.4*(ff-self.law.F0).tanh()
            msg=torch.zeros_like(prior) if silence_boundary else prior
            principal=self.law.p.P0*(1+.28*(F.pad(self.drive(frame),(0,self.n//2))+F.linear(msg,self.rec.weight*self.mask)+feedback).tanh())
            b=torch.log(self.law.boundary(principal)/self.law.B0)
            live=margin+prior-b
            if self.kind=='tangent':
                aa=self.law.A0+self.law.dA0*(live-.18)
                ff=self.law.F0+self.law.dF0*(live-.18)
            elif self.kind=='ordinary':
                aa=self.law.A0+20*((live-.18)*self.law.dA0/20).tanh()
                ff=self.law.F0+((live-.18)*self.law.dF0).tanh()
            else:
                aa,ff=self.law.values(live,principal)
            margin=self.law.move_mean(live)
            if diagnostics:
                crossings.append((live<=0).detach())
            prior=b
            feats=torch.cat(((aa[:,self.n//2:]-self.law.A0)/20,ff[:,self.n//2:]-self.law.F0),dim=1)
            rows.append(self.readout(feats))
        results=torch.stack(rows)
        return (results,torch.stack(crossings)) if diagnostics else results
