"""Uniform mathematical + IEEE-model error bound before emitting a fast path."""
import sys,json,math,time,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent
from oracle import Model,EXACT,float_exact,arb,ctx
from flint import arb_series
ctx.prec=256
start=time.perf_counter();p=Model(EXACT);B=p.B
# Round domain limits inward using whole-ball comparisons, never float root substitution.
lo=float(B.mid())
while not float_exact(lo)>B:lo=math.nextafter(lo,math.inf)
assert float_exact(math.nextafter(lo,-math.inf))<B
upper=B*(arb(2)**(-19)).exp();hi=float(upper.mid())
while not float_exact(hi)<=upper:hi=math.nextafter(hi,-math.inf)
assert float_exact(math.nextafter(hi,math.inf))>upper
wmin=float_exact(lo)-B;D=float_exact(hi)-B
assert wmin>0 and D>0
# Formal derivative coefficients are used with Taylor's real Lagrange theorem,
# not treating the truncated series O term as an automatic remainder estimate.
series=p.literal(arb_series([B,1],prec=6),B)
coeff=[series[i] for i in (2,3,4)]
# Every centre in [B,B+D] is enclosed by this single real ball.
centre=B+arb(D/2,(D/2).upper())
wide=p.literal(arb_series([centre,1],prec=6),B)
M5=wide[5].abs_upper()
assert all(c.is_finite() for c in coeff) and M5.is_finite()
cfloat=[float(c.mid()) for c in coeff];cf=[float_exact(v) for v in cfloat]
cerr=[(a-b).abs_upper() for a,b in zip(cf,coeff)]
root_hi=float(B.mid());root_lo=float((B-float_exact(root_hi)).mid())
rho=(B-float_exact(root_hi)-float_exact(root_lo)).abs_upper()
u=arb(2)**(-53);beta=u+(1+u)*rho/wmin.lower()
H=(1+beta)*D
# P(w)=sum c_i*w^(i+2), E(w)=P(w)+R5.
abs_c=[c.abs_upper() for c in coeff]
truth_lower=coeff[0].lower()-abs_c[1]*D-abs_c[2]*D*D-M5*D**3
assert truth_lower>0
remainder=M5*D**3
argument=beta*(2*abs_c[0]*(1+beta)+3*abs_c[1]*(1+beta)**2*D+4*abs_c[2]*(1+beta)**3*D*D)
coefficient=(1+beta)**2*sum(cerr[i]*H**i for i in range(3))
gamma6=6*u/(1-6*u)
rounding=gamma6*(1+beta)**2*sum(cf[i].abs_upper()*H**i for i in range(3))
relative=(remainder+argument+coefficient+rounding)/truth_lower
assert relative<arb(2)**(-40)
# Sterbenz: both float assets and root_hi within factor2. First subtraction exact.
assert float_exact(lo)>float_exact(root_hi)/2 and float_exact(hi)<2*float_exact(root_hi)
# Uniform magnitude proof for every floating intermediate: nonzero normal and finite.
# Horner products/sums (before/after RN perturbations) are bounded by interval boxes.
wbox=arb(((1-beta)*wmin+(1+beta)*D)/2,(((1+beta)*D-(1-beta)*wmin)/2).upper())
# wbox may overhang due 30-bit radius rounding near zero; use explicit endpoint bounds
# for products, and interval only for sums dominated by nonzero coefficients.
h1=cf[2]*arb(H/2,(H/2).upper())+cf[1]
h2=h1*arb(H/2,(H/2).upper())+cf[0]
normal_min=arb(2)**(-1022)
assert (1-beta)*wmin>normal_min and ((1-beta)*wmin)**2>normal_min
assert cf[2].abs_lower()*((1-beta)*wmin)>normal_min
assert h1.abs_lower()*((1-beta)*wmin)>normal_min
assert h1.abs_lower()>normal_min and h2.abs_lower()>normal_min
assert truth_lower*((1-beta)*wmin)**2>normal_min
assert all(v.abs_upper()<arb(2)**100 for v in cf+[h1,h2,H])
# Margins are orders away from normal thresholds; small RN perturbations cannot cross.
assert min(h1.abs_lower(),h2.abs_lower())>arb('1e-20')
# Explicit induction through each rounded intermediate; endpoint intervals avoid
# midpoint-radius overhang that could erase the tiny positive lower gap.
def interval_mul(A,B):
 vals=[a*b for a in A for b in B]
 return min(v.lower() for v in vals),max(v.upper() for v in vals)
def interval_add(A,B):return (A[0]+B[0]).lower(),(A[1]+B[1]).upper()
def rounded_interval(A):
 l,h=A
 assert (l>0 and h>0) or (l<0 and h<0)
 assert min(l.abs_lower(),h.abs_lower())>normal_min
 assert max(l.abs_upper(),h.abs_upper())<arb(2)**100
 return (l*(1-u if l>0 else 1+u)).lower(),(h*(1+u if h>0 else 1-u)).upper()
y=((1-beta)*wmin.lower(),(1+beta)*D.upper())
steps={}
steps['c4_times_y']=rounded_interval(interval_mul((cf[2],cf[2]),y))
steps['plus_c3']=rounded_interval(interval_add(steps['c4_times_y'],(cf[1],cf[1])))
steps['times_y']=rounded_interval(interval_mul(steps['plus_c3'],y))
steps['plus_c2']=rounded_interval(interval_add(steps['times_y'],(cf[0],cf[0])))
steps['y_squared']=rounded_interval(interval_mul(y,y))
steps['final']=rounded_interval(interval_mul(steps['y_squared'],steps['plus_c2']))
assert steps['final'][0]>0
output={'status':'UNIFORM_BOUND_ESTABLISHED_UNDER_IEEE_RN_PREMISES','exact_params':EXACT,'precision_bits':ctx.prec,'asset_lower_hex':lo.hex(),'asset_upper_hex':hi.hex(),'root_hi_hex':root_hi.hex(),'root_lo_hex':root_lo.hex(),'root_split_error_upper':rho.str(85),'min_exact_asset_root_gap':wmin.str(85),'max_exact_asset_root_gap':D.str(85),'coefficients_balls':[c.str(85) for c in coeff],'coefficients_hex':[v.hex() for v in cfloat],'coefficient_error_bounds':[v.str(85) for v in cerr],'fifth_derivative_over_factorial_bound':M5.str(85),'truth_over_w_squared_lower':truth_lower.str(85),'root_and_subtraction_relative_bound':beta.str(85),'scaled_error_bounds':{k:v.str(85) for k,v in [('remainder',remainder),('argument',argument),('coefficient',coefficient),('arithmetic',rounding)]},'relative_error_upper':relative.str(85),'relative_acceptance_budget':'2^-40','rounded_intermediate_enclosures':{k:[v.str(85) for v in pair] for k,pair in steps.items()},'precompute_seconds':time.perf_counter()-start,'global_status':'NOT_CERTIFIED','runtime_premises':'CPython IEEE binary64 RN ties-even basic +-*, no rounding-mode change, no fast-math; intermediate normals/finite proved; not arbitrary runtime certification'}
if '--no-artifact' not in sys.argv:
 (R/'COEFFICIENTS.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output,indent=2))
