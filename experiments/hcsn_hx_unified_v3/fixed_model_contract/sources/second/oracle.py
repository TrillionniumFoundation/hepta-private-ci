"""Independent Arb literal A7 and local Green expression; one frozen parameter tuple."""
from flint import arb,acb,fmpq,ctx
ctx.prec=256
EXACT=dict(zip(('rate','payout','volatility','maturity','principal','coupon','tax_shield','recovery','shock_intensity','sale_fraction'),('1/20','2/25','1/4','3','60','4','1/4','3/20','1','2/25')))
def ar(v): return arb(fmpq(v))
def float_exact(v):
 n,d=v.as_integer_ratio();return arb(fmpq(n,d))
class Model:
 def __init__(self,params):
  self.params=params
  r,d,s,m,P,C,pi,alpha,xi,k=[ar(params[n]) for n in EXACT]
  self.r,self.d,self.s,self.m,self.P,self.C,self.pi,self.alpha=r,d,s,m,P,C,pi,alpha
  self.ss=s*s;self.q=r+xi*k;self.a=(r-d-self.ss/2)/self.ss
  self.z=(self.a*self.a+2*r/self.ss).sqrt();self.zh=(self.a*self.a+2*self.q/self.ss).sqrt()
  self.eta=self.z-self.a;self.gamma=self.z+self.a;self.u=s*m.sqrt();self.p=P/m;self.cq=C/m/self.q
  N=self.N;z=self.z;u=self.u;q=self.q;a=self.a
  bf=lambda t:(-q*m).exp()*(N(t*u)-(r*m).exp()*N(-z*u))/(z+t)
  Bf=lambda t:(N(t*u)-((z*z-t*t)*u*u/2).exp()*N(-z*u))/(z+t)
  Bs=Bf(-self.zh)+Bf(self.zh);off=self.p-self.cq
  top=((1-pi)*C+(1-(-q*m).exp())*off)/self.eta+off*(bf(-a)+bf(a))+self.cq*Bs
  self.slope=d/(self.eta-1)+alpha/m*Bs
  self.B=top/self.slope
  assert self.slope>0 and self.B>0 and alpha*self.B<P and alpha*self.B<C/q
 def N(self,x):return (-x/arb(2).sqrt()).erfc()/2
 def cashflow(self,y,B):
  a,u,zh=self.a,self.u,self.zh;N=self.N
  F=N((-y-a*u*u)/u)+(-2*a*y).exp()*N((-y+a*u*u)/u)
  G=((-a+zh)*y).exp()*N((-y-zh*u*u)/u)+((-a-zh)*y).exp()*N((-y+zh*u*u)/u)
  debt=self.cq+(-self.q*self.m).exp()*(self.p-self.cq)*(1-F)+(self.alpha*B/self.m-self.cq)*G
  return self.d*B*y.exp()+debt-(1-self.pi)*self.C-self.p
 def local(self,V,B=None):
  B=self.B if B is None else B;x=(V/B).log()
  assert x>0
  term=acb.integral(lambda t,analytic:(-self.a*x*(1-t)).exp()*(self.z*x*(1-t)).sinh()*self.cashflow(x*t,B),0,1,abs_tol=arb('1e-65'),rel_tol=arb('1e-60'),eval_limit=20000,depth_limit=20)
  assert term.is_finite() and term.imag.contains(0)
  ivp=-2*x/(self.ss*self.z)*term.real
  I=self.slope*(B-self.B)
  correction=(2*I/self.ss)*(-self.a*x).exp()*(self.z*x).sinh()/self.z
  return ivp+correction
 def literal(self,V,B):
  x=(V/B).log();a,u,z=self.a,self.u,self.z;N=self.N
  def K(y,beta):
   w=((beta-a)**2-y*y)*u*u/2
   return (-beta*x).exp()*N(y*u)-(w-beta*x).exp()*N((beta-a)*u)+(w-beta*x).exp()*N((-x+(beta-a)*u*u)/u)-(-(a+y)*x).exp()*N((-x+y*u*u)/u)
  def little(y):
   beta=-self.eta;w=((beta-a)**2-y*y)*u*u/2
   return (w-beta*x).exp()*N((-x+(beta-a)*u*u)/u)-(-(a+y)*x).exp()*N((-x+y*u*u)/u)
  def A(y):return (K(y,self.gamma)+little(-y))/(z-y)+(K(-y,self.gamma)+little(y))/(z+y)
  off=self.p-self.cq;cash=(1-self.pi)*self.C+(1-(-self.q*self.m).exp())*off
  return V-self.d*B/(z*self.ss)*(-self.gamma*x).exp()/(self.gamma+1)-cash/(z*self.ss)*(1/self.eta+(1-(-self.gamma*x).exp())/self.gamma)+((-self.q*self.m).exp()*off*A(a)-(self.alpha*B/self.m-self.cq)*A(self.zh))/(z*self.ss)
