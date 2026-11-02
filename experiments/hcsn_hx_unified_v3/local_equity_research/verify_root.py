"""One exact-rational HX case: validated root bracket and guard, not all-domain certification."""
import sys,json,time,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
def audit(e,a):
 if e.startswith(('socket.','subprocess.')) or e in ('os.system','os.exec','os.posix_spawn'): raise RuntimeError('No external effects in interval proof')
sys.addaudithook(audit)
import flint
from flint import arb,acb,fmpq,ctx
ctx.prec=160
start=time.time()
R=Path(__file__).resolve().parent
params={'rate':'1/20','payout':'3/100','volatility':'1/4','maturity':'2','principal':'60','coupon':'4','tax_shield':'1/4','recovery':'3/5','shock_intensity':'1','sale_fraction':'3/200'}
p={k:arb(fmpq(v)) for k,v in params.items()}
r,delta,s,m,P,C,pi,alpha,xi,k=[p[n] for n in params]
q=r+xi*k;ss=s*s;a=(r-delta-ss/2)/ss;z=(a*a+2*r/ss).sqrt();zh=(a*a+2*q/ss).sqrt();eta=z-a;u=s*m.sqrt();principal=P/m;c=C/m;cq=c/q
assert r>0 and delta>0 and q>0 and eta>1
# API capability checks use exact rational identities with enclosure containment.
api={}
tenth=arb(fmpq(1,10));api['rational_tenth_contains_exact']=tenth.contains(fmpq(1,10));api['sqrt_square_contains_two']=(arb(2).sqrt()**2).contains(2)
poly=acb.integral(lambda x,analytic:x*x,0,1,abs_tol=arb('1e-35'))
api['integral_polynomial_contains_third']=poly.real.contains(fmpq(1,3)) and poly.imag.contains(0)
api['erfc_symmetry_contains_two']=(arb(fmpq(3,7)).erfc()+(-arb(fmpq(3,7))).erfc()).contains(2)
assert all(api.values())
N=lambda x:(-x/arb(2).sqrt()).erfc()/2
bf=lambda t:(-q*m).exp()*(N(t*u)-(r*m).exp()*N(-z*u))/(z+t)
Bf=lambda t:(N(t*u)-((z*z-t*t)*u*u/2).exp()*N(-z*u))/(z+t)
Bs=Bf(-zh)+Bf(zh);off=principal-cq
numerator=((1-pi)*C+(1-(-q*m).exp())*off)/eta+off*(bf(-a)+bf(a))+cq*Bs
denominator=delta/(eta-1)+alpha/m*Bs
assert denominator>0
closed_B=numerator/denominator
lo=arb(fmpq('6462517667/100000000'));hi=arb(fmpq('6462517668/100000000'))
assert lo>0 and closed_B>lo and closed_B<hi
assert alpha*hi<P and alpha*hi<C/q
# Entire integrand: exp and erfc composed with affine y; no branch-cut operations on y.
def debt(y,B):
 F=N((-y-a*u*u)/u)+(-2*a*y).exp()*N((-y+a*u*u)/u)
 G=((-a+zh)*y).exp()*N((-y-zh*u*u)/u)+((-a-zh)*y).exp()*N((-y+zh*u*u)/u)
 return cq+(-q*m).exp()*(principal-cq)*(1-F)+(alpha*B/m-cq)*G
# For all B in bracket, pathwise coupon <= c/q and terminal <=max(p,alpha*hi/m).
# Both c/q<31 and terminal<31, so 0<=d<=62, |d-(1-pi)C-p|<=95.
assert cq<31 and principal<31 and alpha*hi/m<31
assert (1-pi)*C+principal<34
constant_bound=arb(96) # conservative strict bound covering all the above
U=40
tail=constant_bound/eta*(-eta*U).exp()
assert tail>0
segments=(0,1,4,12,40)
results=[]
for label,B in [('lower',lo),('upper',hi)]:
 parts=[];total=acb(0)
 for left,right in zip(segments,segments[1:]):
  part=acb.integral(lambda y,analytic:(-eta*y).exp()*(debt(y,B)-(1-pi)*C-principal),left,right,abs_tol=arb('1e-28'),rel_tol=arb('1e-28'),eval_limit=200000,depth_limit=25)
  assert part.is_finite() and part.imag.contains(0)
  parts.append({'segment':[left,right],'value':part.real.str(65),'radius':part.real.rad().str(65)})
  total+=part
 finite=delta*B/(eta-1)+total.real
 enclosed=finite+arb(0,tail.upper())
 success=(enclosed<0) if label=='lower' else (enclosed>0)
 assert success
 results.append({'endpoint':label,'B':B.str(65),'segments':parts,'finite_integral_plus_exact_payout':finite.str(65),'finite_radius':finite.rad().str(65),'tail_abs_bound':tail.str(65),'total_infinite_I_enclosure':enclosed.str(65),'required_sign_verified':bool(success)})
# I(B) affine; I'(B)=delta/(eta-1)+(alpha/m)int exp(-eta*y)G(y)dy >=delta/(eta-1)>0.
slope_lower=delta/(eta-1);assert slope_lower>0
output={'status':'FIXED_CASE_ROOT_AND_GUARD_ENCLOSED','global_status':'NOT_CERTIFIED','numerical_scope':'one exact-rational HX case, exact root exists uniquely in bracket; theorem hypotheses enclosed','python_flint':flint.__version__,'precision_bits':ctx.prec,'exact_rational_inputs':params,'api_checks':api,'closed_form_B_ball':closed_B.str(65),'denominator_ball':denominator.str(65),'root_bracket_exact':['6462517667/100000000','6462517668/100000000'],'principal_guard_margin':(P-alpha*hi).str(65),'coupon_guard_margin':(C/q-alpha*hi).str(65),'slope_positive_lower_bound':slope_lower.str(65),'tail_method':'payout integral exact to infinity; debt cashflow absolute bound96; exponential tail enclosed outward','endpoints':results,'elapsed_seconds':time.time()-start}
(R/'ROOT_PROOF.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output,indent=2))
