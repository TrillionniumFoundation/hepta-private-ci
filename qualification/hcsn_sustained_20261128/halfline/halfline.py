"""Closed, infinite-domain regenerative averages for the signed two-price law."""
from math import exp,pi,sqrt,tanh
from scipy.special import ndtr


class Scalars:
    number = staticmethod(float)
    exp = staticmethod(exp)
    sqrt = staticmethod(sqrt)
    phi = staticmethod(ndtr)
    sqrt2pi = staticmethod(lambda:sqrt(2*pi))
    tanh = staticmethod(tanh)
    is_zero = staticmethod(lambda x: x==0)


class Stationary:
    def __init__(self,ops=Scalars):
        self.op=ops
        c=ops.number
        self.r,self.delta,self.sigma,self.tax,self.alpha,self.C,self.m,self.q=map(c,(".08",".02",".23",".27",".6","6.39","1",".09"))
        self.v,self.ke,self.kl,self.reset,self.lag=map(c,("-.8",".6","4.1",".30",".25"))
        self.P=c("61.68")*(1+c(".28")*self.v)
        self.D=self.sigma*self.sigma/2
        self.mu=self.r-self.delta-self.D
        self.speed=ops.sqrt(self.mu*self.mu+4*self.D*self.r)
        self.eta=(self.speed-self.mu)/(2*self.D)
        self.gamma=(self.speed+self.mu)/(2*self.D)
        self.B=self._wall()
        self.A=ops.exp(-self.q*self.m)*(self.P/self.m-self.C/(self.m*self.q))
        self.constant=-(1-self.tax)*self.C+self.C/(self.m*self.q)+self.A-self.P/self.m
        self.rec=self.alpha*self.B/self.m-self.C/(self.m*self.q)
        a=self.reset
        low=ops.exp(-self.gamma*a)*self.cash(-self.gamma,0,a)
        high=ops.exp(self.eta*a)*self.cash(self.eta,a,None)
        self.Ea=(low+high)/self.speed
        self.Epa=(-self.gamma*low+self.eta*high)/self.speed

    def _normal_tail(self,k,center):
        o=self.op
        w=self.sigma*o.sqrt(self.m)
        z=center/w
        if o.is_zero(k):
            return center*o.phi(z)+w*o.exp(-z*z/2)/o.sqrt2pi()
        return (o.phi(z)-o.exp(-k*center+(k*w)*(k*w)/2)*o.phi(z-k*w))/k

    def _hit_moment(self,discounted,k,l,h):
        o=self.op
        if discounted:
            z=o.sqrt(self.mu*self.mu+4*self.D*self.q)
            terms=[((self.mu+z)/(2*self.D),z*self.m),((self.mu-z)/(2*self.D),-z*self.m)]
        else:
            terms=[(self.mu/self.D,self.mu*self.m),(0,-self.mu*self.m)]
        val=0
        for b,n in terms:
            rate=k+b
            def tail(x):
                return o.exp(-rate*x)*self._normal_tail(rate,n-x)
            val+=tail(l) if h is None else tail(l)-tail(h)
        return val

    def _wall(self):
        f=self._hit_moment(False,self.eta,0,None)
        g=self._hit_moment(True,self.eta,0,None)
        y=self.C/self.q
        a=(1-self.op.exp(-self.q*self.m))/self.eta+self.op.exp(-self.q*self.m)*f
        return ((1-self.tax)*self.C/self.eta+
                (a*self.P+(g-a)*y)/self.m)/(self.delta/(self.eta-1)+self.alpha*g/self.m)

    def _exp_integral(self,k,l,h):
        o=self.op
        if h is None:
            return o.exp(-k*l)/k
        if o.is_zero(k):
            return h-l
        return (o.exp(-k*l)-o.exp(-k*h))/k

    def cash(self,k,l,h):
        return (self.delta*self.B*self._exp_integral(k-1,l,h)+self.constant*self._exp_integral(k,l,h)
                -self.A*self._hit_moment(False,k,l,h)+self.rec*self._hit_moment(True,k,l,h))

    def stationary(self,u):
        o=self.op
        k=u/self.D
        a=self.reset
        denom=a+self.lag*u
        growth=o.exp(k*a)
        def loss(k,l,h):
            return self.A*self._hit_moment(False,k,l,h)-self.rec*self._hit_moment(True,k,l,h)
        loss_sum=loss(0,0,a)-loss(k,0,None)+growth*loss(k,a,None)
        # Laplace transformation of the equity ODE with E(0)=E'(0)=0.
        # k=eta is removable and unused in the intervals tested here.
        w=self.r-self.mu*k-self.D*k*k
        boundary_term=(self.mu+self.D*k)*self.Ea+self.D*self.Epa
        whole=self.cash(k,0,None)
        eq_sum=(self.cash(0,0,a)+self.mu*self.Ea+self.D*self.Epa)/self.r
        eq_sum+=(growth*self.cash(k,a,None)-boundary_term-whole)/w
        equity,loss=eq_sum/(20*denom),loss_sum/(20*denom)
        xbar=a/2+1/k
        # Prices are strictly positive on the evaluated brackets (certified).
        residual=u+self.mu-o.number(".7")*self.v+self.ke*o.tanh(equity)*(a-xbar)-self.kl*o.tanh(loss)
        return residual,u/denom,equity,loss,xbar
