"""Real-frequency transfer of the instantaneous, infinite-dimensional feedback."""
import json
from pathlib import Path

from halfline import Stationary


class Transfer:
    def __init__(self,p,u):
        self.p,self.u=p,u
        _,self.rate,e,l,self.mean=p.stationary(u)
        self.mass=p.reset/(p.reset+p.lag*u)
        a=p.op.tanh(e)
        b=p.op.tanh(l)
        self.weights=[-p.ke*a*self.mean/self.mass,p.ke*a/self.mass,
                      -p.ke*(1-a*a)*(p.reset-self.mean)/20,p.kl*(1-b*b)/20]

    def moment(self,k,lo,hi):
        o,p=self.p.op,self.p
        def elementary(k,l,h):
            return p._exp_integral(k,l,h)
        one=elementary(k,lo,hi)
        if o.is_zero(k):
            x=(hi*hi-lo*lo)/2
        else:
            def first(t):return o.exp(-k*t)*(t+1/k)/k
            x=first(lo) if hi is None else first(lo)-first(hi)
        loss=p.A*p._hit_moment(False,k,lo,hi)-p.rec*p._hit_moment(True,k,lo,hi)
        w=p.r-p.mu*k-p.D*k*k
        # lo,hi are only 0, the real reset point or positive infinity.
        # The sole finite nontrivial boundary term is at the reset.
        term=o.exp(-k*p.reset)*((p.mu+p.D*k)*p.Ea+p.D*p.Epa)
        sign=(int(hi is not None)-int(not o.is_zero(lo)))
        eq=(p.cash(k,lo,hi)+sign*term)/w
        return sum(z*v for z,v in zip(self.weights,[one,x,eq,loss]))

    def response(self,s):
        """Laplace resolvent with deterministic resting time and scalar drift input."""
        p,u=self.p,self.u
        o=p.op
        a=p.reset
        norm=a+p.lag*u
        lam=u/p.D
        speed=o.sqrt(u*u+4*p.D*s)
        k=2*s/(u+speed)
        t=(u+speed)/(2*p.D)
        t_all=self.moment(t,0,None)
        lower=self.moment(-k,0,a)
        upper=self.moment(t,a,None)
        img=o.exp(-k*a)
        adv=o.exp(t*a)*upper
        killed_at_reset=(img*(lower-t_all)+adv)/speed
        delayed=o.exp(-s*p.lag)
        va=killed_at_reset/(1-img*delayed)
        diff=(-k*img*(lower-t_all)+t*adv)/speed-t_all/p.D
        diff+=k*(1-img)*delayed*va
        direct=self.moment(lam,0,None)-o.exp(lam*a)*self.moment(lam,a,None)
        return lam*(direct+p.D*diff)/(norm*s)


def simulate():
    from scipy.optimize import brentq
    p=Stationary()
    roots=json.loads(Path(__file__).with_name("enclosures.json").read_text())["roots"]
    for row in roots:
        u=sum(float(z) for z in row["inward_drift"])/2
        tr=Transfer(p,u)
        s=[.001,.01,.03,.1,.15,.2,.3,.6,1.,2.,5.]
        print(u,[round(tr.response(z),5) for z in s])
        for lo,hi in zip(s[:-1],s[1:]):
            if (tr.response(lo)-1)*(tr.response(hi)-1)<0:
                print("positive growth",brentq(lambda z:tr.response(z)-1,lo,hi))


if __name__=="__main__":
    simulate()
