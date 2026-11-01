"""Same equity ODE Green integral near its zero-value/zero-slope boundary.

It is used where eta*x <= 1, avoiding exponentially amplified IVP roundoff.
The rest of the full A7 formula remains; the smooth blend is not an accuracy
waiver. All quadrature constants have fixed offline hi/lo representations.
"""

import json
from pathlib import Path


def model_class(k, nodes):
    class GreenHX(k.FullHX):
        def increments(self,x):
            lo,hi=self.a*self.s-x/self.s,self.a*self.s+x/self.s
            survival=k.cdf_interval(x.coerce(0),lo,hi)
            survival -= k.expm1(-2*self.a*x)*k.Phi(lo)
            u,v=-self.a+self.zt,-self.a-self.zt
            gm1=k.expm1(u*x)*k.Phi(-x/self.s-self.zt*self.s)
            gm1 += k.expm1(v*x)*k.Phi(-x/self.s+self.zt*self.s)
            for sign in (-1,1):
                hi=sign*self.zt*self.s
                gm1 -= k.cdf_interval(x.coerce(0),hi-x/self.s,hi)
            return survival,gm1

        def local_equity(self,x):
            flow0=(self.delta*self.b-(1-self.theta[4])*self.theta[7]
                   +(self.alpha*self.b-self.theta[8])/self.m)
            cuts=[x.coerce(0)]
            if x.v > 8*self.s.v:
                cuts.append(8*self.s)
            cuts.append(x)
            result=x.coerce(0)
            for left,right in zip(cuts[:-1],cuts[1:]):
                part=x.coerce(0)
                for node,weight in nodes:
                    y=left+node*(right-left)
                    gap=x-y
                    survival,gm1=self.increments(y)
                    flow=flow0+self.delta*self.b*k.expm1(y)
                    flow += self.discount*self.q*survival+(self.alpha*self.b/self.m-self.c/self.R)*gm1
                    kernel=-k.exp(self.eta*gap)*k.expm1(-2*self.z*gap)
                    part -= weight*kernel*flow
                result += (right-left)*part
            return result/(self.z*self.s2)

        def equity(self,x):
            limit=min([x.coerce(.5),1/self.eta],key=lambda t:t.v)
            if x.v <= .8*limit.v:
                return self.local_equity(x)
            if x.v >= limit.v:
                return self.raw_equity(x)
            t=(x/limit-.8)/.2
            w=t**3*(10+t*(-15+6*t))
            return (1-w)*self.local_equity(x)+w*self.raw_equity(x)

    return GreenHX


NODES=json.loads(Path(__file__).with_name("GREEN_CONSTANTS.json").read_text())
