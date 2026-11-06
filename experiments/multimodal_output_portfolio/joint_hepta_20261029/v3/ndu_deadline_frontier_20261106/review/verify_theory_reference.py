"""Independent rational identities; no reuse of the frontier LP implementation."""
from fractions import Fraction as Q
from itertools import product
import json
import math
from pathlib import Path

p0=(Q(89,100),Q(1,10),Q(1,100))
p1=(Q(1,100),Q(1,10),Q(89,100))
checks=[]
def check(name,condition):
    assert condition, name
    checks.append(name)

def risk(laws,policy):
    return tuple(sum((laws[h][o]*(policy[o] if h==0 else 1-policy[o])
                      for o in range(len(policy))),Q(0)) for h in (0,1))

pure=[]
for pi in product((Q(0),Q(1)),repeat=3):
    e=risk((p0,p1),pi)
    pure.append({'policy':pi,'risk':e})
    check('supporting_error_sum_'+str(pi),sum(e)>=Q(3,25))
check('deterministic_minimax',min(max(row['risk']) for row in pure)==Q(11,100))
e=risk((p0,p1),(Q(0),Q(1,2),Q(1)))
check('randomized_minimax',e==(Q(3,50),Q(3,50)))
rows=[]
for n in range(21):
    b=Q(n,20)
    err=tuple(b*v+(1-b)*Q(1,2) for v in e)
    lower=Q(1,2)-Q(11,25)*b
    check('frontier_'+str(b),max(err)==lower)
    rows.append({'budget':b,'errors':err,'lower':lower,'upper':max(err)})
kl=.88*math.log(89); target=.9*math.log(19)
check('KL_feasible_but_risk_infeasible',kl>target and Q(3,50)>Q(1,20))
raw=((Q(2,5),Q(1,10),Q(1,10),Q(2,5)),
     (Q(1,10),Q(2,5),Q(2,5),Q(1,10)))
for h in (0,1):
    check('label_marginal_'+str(h),raw[h][0]+raw[h][2]==Q(1,2))
    check('duration_marginal_'+str(h),raw[h][0]+raw[h][1]==Q(1,2))
full=risk(raw,(Q(0),Q(1),Q(1),Q(0)))
cap=tuple((law[0],law[1],law[2]+law[3]) for law in raw)
censored=risk(cap,(Q(0),Q(1),Q(1,2)))
check('full_joint_risk',full==(Q(1,5),Q(1,5)))
check('censored_risk',censored==(Q(7,20),Q(7,20)))
check('correct_coarsening',all(sum(law)==1 for law in cap))
# Constructed counts only: no random calibration trial is claimed.
n=2000; counts={'correct':1780,'ambiguous':200,'wrong':20}
e_hat=(counts['wrong']+.5*counts['ambiguous'])/n
alpha=.05
radius=math.sqrt(math.log(2/alpha)/(2*n))
e_upper=e_hat+radius
delta=.1
query_probability=(.5-delta)/(.5-e_upper)
check('illustrative_learned_gate_nonvacuous',e_upper<delta and 0<query_probability<=1)
check('illustrative_learned_risk_arithmetic',abs(.5*(1-query_probability)+query_probability*e_upper-delta)<1e-12)
result={'status':'PASS','checks':len(checks),'check_names':checks,
        'scope':'Independent exact finite-model identities and confidence arithmetic; no LP-source reuse, random samples, actual tools, or external review.',
        'ambiguous_query':{'laws':[p0,p1],'minimax':e,'deterministic_minimax':Q(11,100),'frontier':rows,
                           'per_query_kl':kl,'target_delta':Q(1,20),'kl_required':target,'actual_feasible':False},
        'censoring':{'full_risk':full,'censored_risk':censored,'full_expected_duration':Q(3,2),'cap1_duration':Q(1)},
        'constructed_calibration_arithmetic':{'n':n,'counts':counts,'empirical_error':e_hat,'alpha':alpha,
           'two_sided_hoeffding_radius':radius,'error_upper':e_upper,'target_delta':delta,
           'certified_query_probability':query_probability,'cost_per_deployment_in_query_units':query_probability,
           'calibration_trials_cost':n,'warning':'Constructed counts, not collected observations; lifecycle bill not amortized here.'}}
out=Path(__file__).with_name('THEORY_REFERENCE_VERIFICATION.json')
out.write_text(json.dumps(result,default=str,indent=2)+'\n')
print(json.dumps({'output':str(out),'checks':len(checks),'status':'PASS',
                  'minimax':str(e[0]),'kl':kl,'required':target,
                  'illustrative_query_probability':query_probability}))
