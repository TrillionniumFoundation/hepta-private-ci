"""Laplace transform in bond issue maturity; elliptic equity solve at fixed walls."""
from math import comb
import numpy as np
from scipy.optimize import root
from transform import Law


class Modes:
    def __init__(self,M,mu,D):
        val,self.vec=np.linalg.eig(M)
        self.inv=np.linalg.inv(self.vec)
        self.power=(-mu-np.sqrt(mu**2+4*D*val))/(2*D)
        self.generator=(self.vec*self.power)@self.inv
        self.val=val

    def apply(self,z,distance):
        return self.vec@(np.exp(self.power*distance)*(self.inv@z))


class EquityTransform:
    def __init__(self,law:Law,tax=.27,*,width=22.,terms=29,smooth=24):
        self.law=law;self.tax=tax;self.width=width
        self.terms=terms;self.smooth=smooth
        # The economic contract's coupon and face rates stay fixed as the PDE
        # propagation-time variable is transformed, then it is evaluated at maturity.
        self.c=law.coupon/law.maturity
        self.par=law.principal/law.maturity
        k=np.arange(terms+smooth+1)
        self.s=(width/2+1j*np.pi*k)/law.maturity
        eul=[comb(smooth,j)/2**smooth for j in range(smooth+1)]
        w=np.ones(len(k));w[0]=.5
        for j in range(1,smooth+1):w[terms+j]=sum(eul[j:])
        self.weight=w*(-1.)**k*np.exp(width/2)/law.maturity

    def grid_free(self,walls,point=None):
        w=np.asarray(walls)
        if min(w)<=0:raise ValueError("Positive walls required")
        o=np.argsort(w,kind="stable");w=w[o]
        index=np.argsort(o)
        j=np.asarray(self.law.rates)[o];lq=np.asarray(self.law.premia)[o]+self.law.r
        Q=np.array([[-j[0],j[0]],[j[1],-j[1]]])
        D=self.law.sigma**2/2;mu=self.law.r-self.law.payout-D
        r=self.law.r;I=np.eye(2)
        eq_mat=r*I-Q
        modes=Modes(eq_mat,mu,D);K=modes.generator
        h=np.log(w[1]/w[0]); a=j[0]; L=r+a
        rootE=np.sqrt(mu**2+4*D*L)
        pe=(-mu+rootE)/(2*D);ne=(-mu-rootE)/(2*D)
        el=np.exp(-pe*h);er=np.exp(ne*h)
        left=np.array([[el,1.],[pe-K[0,0],(ne-K[0,0])*er]])
        costs=(1-self.tax)*self.law.coupon+self.par
        slope=[];prices=[]
        for s in self.s:
            bmat=np.diag(s+lq)-Q
            debt=Modes(bmat,mu,D);Kb=debt.generator
            far=np.linalg.solve(bmat,np.full(2,self.par+self.c/s))
            rec=self.law.recovery/(self.law.maturity*s)
            kap=s+lq[0]+a
            rt=np.sqrt(mu**2+4*D*kap)
            pb=(-mu+rt)/(2*D);nb=(-mu-rt)/(2*D)
            bl=np.exp(-pb*h);br=np.exp(nb*h)
            bc=(self.par+self.c/s)/kap; bv=a*rec/(kap-mu-D)
            target=[rec*w[0]-(bc+bv*w[0]),
                    Kb[0,0]*(bc+bv*w[1]-far[0])+Kb[0,1]*(rec*w[1]-far[1])-bv*w[1]]
            Ab,Bb=np.linalg.solve([[bl,1],[pb-Kb[0,0],(nb-Kb[0,0])*br]],target)
            btop=np.array([bc+bv*w[1]+Ab+Bb*br,rec*w[1]])
            amplitudes=debt.inv@(btop-far)
            constant=np.linalg.solve(eq_mat,far-costs/s)
            coeff=np.column_stack([np.linalg.solve(eq_mat-v*I,u)*z
                                   for v,u,z in zip(debt.val,debt.vec.T,amplitudes)])
            outer=lambda x:w[1]*np.exp(x)/s+constant+coeff@np.exp(debt.power*x)
            po=outer(0.)
            dpo=w[1]/s+coeff@debt.power
            ec=(bc-costs/s)/L;ev=(self.law.payout/s+bv)/(L-mu-D)
            Aj=Ab/(r-lq[0]-s);Bj=Bb/(r-lq[0]-s)
            def ep(z):
                t1=Aj*np.exp(pb*(z-h));t2=Bj*np.exp(nb*z);asset=ev*w[0]*np.exp(z)
                return ec+asset+t1+t2,asset+pb*t1+nb*t2
            e0,de0=ep(0.);eh,deh=ep(h)
            Ae,Be=np.linalg.solve(left,[-e0,dpo[0]+K[0,0]*(eh-po[0])-K[0,1]*po[1]-deh])
            top=np.array([eh+Ae+Be*er,0.])
            deltas=dpo+K@(top-po)
            slope.append([de0+pe*Ae*el+ne*Be,deltas[1]])
            if point is not None:
                x=np.log(point/w[0])
                if x<=0:pv=np.zeros(2)
                elif x<h:pv=np.array([ep(x)[0]+Ae*np.exp(pe*(x-h))+Be*np.exp(ne*x),0])
                else:pv=outer(x-h)+modes.apply(top-po,x-h)
                prices.append(pv)
        fit=(self.weight@np.real(np.array(slope)))[index]
        if point is None:return fit
        return fit,(self.weight@np.real(np.array(prices)))[index]

    def barriers(self,start=None):
        logs=np.log(self.law.barriers if start is None else start)
        # Most significant error source in differencing is the inverse-Laplace sum.
        solution=root(lambda x:self.grid_free(np.exp(x)),logs,method="hybr",
                      options={"xtol":2e-9,"eps":1e-11})
        walls=np.exp(solution.x);err=np.linalg.norm(self.grid_free(walls),ord=np.inf)
        if err>2e-7:raise ArithmeticError((solution.message,err))
        return walls
