"""Independent read-only checks of root's deadline reference."""
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
from pathlib import Path
import hashlib,importlib,json,sys,time
import numpy as np
from scipy.optimize import linprog

ROOT=Path('/workspace/scratch/e5ecafe4ccc8/hepta-research')
sys.path.insert(0,str(ROOT))
NAME='experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_deadline_frontier_20261106'
fm=importlib.import_module(NAME+'.frontier')
bm=importlib.import_module(NAME+'.binary_deadline')
model=importlib.import_module('experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_identification.model')
source=ROOT.joinpath(*NAME.split('.'))
source_before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')}
checks=[]

def check(name,condition,details=None):
    if not condition:
        raise AssertionError((name,details))
    checks.append({'name':name,'passed':True,**({'details':details} if details is not None else {})})

def pure_vectors(contract):
    # Each vector has conditional error/cost for BOTH h under ONE common policy.
    # Independent enumeration of action-contingent continuation vectors; no
    # sequence-form variables, LP coefficients, tree masses or lower_bound calls.
    @lru_cache(None)
    def rec(elapsed,launches,state):
        options={(F(0),F(1),F(0),F(0)),(F(1),F(0),F(0),F(0))}
        if elapsed>=contract.deadline or launches>=contract.max_probes:
            return tuple(options)
        for action in contract.actions(state,contract.deadline-elapsed):
            responses=contract.responses(state,action)
            future=[rec(elapsed+event[1],launches+1,event[2]) for event,law in responses]
            for children in product(*future):
                vals=[F(0)]*4
                for (event,law),v in zip(responses,children):
                    for h in (0,1):
                        vals[h]+=law[h]*v[h]
                        vals[2+h]+=law[h]*(contract.fee+contract.time_price*event[1]+v[2+h])
                options.add(tuple(vals))
        return tuple(options)
    return rec(0,0,0)

configs=[fm.Contract(0),fm.Contract(1,family='bernoulli'),fm.Contract(2,max_probes=2,family='bernoulli'),
    fm.Contract(1,family='gated'),fm.Contract(2,family='gated'),fm.Contract(3,max_probes=2,family='gated'),
    fm.Contract(1,max_probes=1),fm.Contract(2,max_probes=1),
    fm.Contract(3,max_probes=1,family='catalog',fee=F(27,100)),
    fm.Contract(6,max_probes=2,family='catalog',fee=F(27,100))]
comparison_summary=[]
for config in configs:
    points=pure_vectors(config)
    tree=fm.Tree(config)
    maxdiff=0.
    for budget in [F(0),F(7,400),F(1,30),F(3,40),F(3,10)]:
        r=tree.solve(budget)
        # Solve independently over the convex hull of enumerated pure policies.
        # This float check supplements exact Lagrangian equality below.
        num=len(points)
        objective=np.zeros(num+1);objective[-1]=1
        au=np.zeros((4,num+1))
        for i,v in enumerate(points):
            au[:,i]=list(map(float,v))
        au[:2,-1]=-1
        eq=np.ones((1,num+1));eq[0,-1]=0
        pure=linprog(objective,A_ub=au,b_ub=[0,0,float(budget),float(budget)],
            A_eq=eq,b_eq=[1.],bounds=(0,None),method='highs')
        check('pure_mixture_solver_succeeded',pure.success)
        diff=abs(float(r['upper'])-pure.fun)
        maxdiff=max(maxdiff,diff)
        check('sequence_upper_matches_independent_pure_hull',diff<1e-8,
            {'family':config.family,'deadline':config.deadline,'budget':str(budget),'error':diff})
        ev=tree.evaluate(r['policy'])
        check('returned_behavioral_policy_matches_reported_exact_fields',ev==(r['errors'],r['resources'],(F(1),F(1))))
        check('exact_budget_satisfied',max(ev[1])<=budget)
        # Neither sample-size dual, solver flag nor rounded LP optimum is used.
        for prior in [F(0),F(1,7),F(1,2),F(6,7),F(1)]:
            for mu0,mu1 in [(F(0),F(0)),(F(1,3),F(0)),(F(0),F(2,5)),(F(3,2),F(7,3))]:
                brute=max(F(0),min(prior*v[0]+(1-prior)*v[1]+mu0*v[2]+mu1*v[3]
                    for v in points)-(mu0+mu1)*budget)
                dynamic=tree.lower_bound((prior,1-prior),(mu0,mu1),budget)
                check('exact_Lagrangian_equals_independent_pure_enumeration',brute==dynamic)
                check('every_tested_exact_lower_is_below_attainable_upper',dynamic<=r['upper'])
    comparison_summary.append({'family':config.family,'deadline':config.deadline,
        'max_probes':config.max_probes,'pure_payoff_vectors':len(points),'max_lp_vs_pure_hull_gap':maxdiff})

# Force a real upward budget-recovery correction and evaluate the actual returned policy.
tree=fm.Tree(fm.Contract(2,max_probes=2,family='gated'))
r=tree.solve(F(1,100000007))
check('budget_recovery_case_exercises_nontrivial_mixture',r['mix']<1,str(r['mix']))
check('mixture_is_embedded_in_actual_returned_policy',tree.evaluate(r['policy'])==(r['errors'],r['resources'],(F(1),F(1))))

# Independent censoring from raw kernels: late labels and actual late durations
# collapse to the sole timeout event; paid launch and consumed cap remain.
for probe,cap in product(('fast','slow','joint'),range(1,5)):
    grouped={}
    for h in (0,1):
        for label,duration,mass in model.kernel(probe,h):
            event=(label,duration,0) if duration<=cap else ('timeout',cap,0)
            grouped.setdefault(event,[F(0),F(0)])[h]+=mass
    observed=dict(fm.Contract(cap).responses(0,(probe,cap)))
    check('censoring_aggregates_independently_rebuilt_raw_joint_law',observed=={k:tuple(v) for k,v in grouped.items()})

tree=fm.Tree(fm.Contract(1,max_probes=1))
policy=[]
for i,node in enumerate(tree.nodes):
    ps=[F(1,2),F(1,2)]+[F(0)]*(len(node['actions'])-2)
    if i==0:
        ps=[F(0)]*len(ps)
        index=next(j for j,a in enumerate(node['actions']) if tree.actions[a]['action']==('slow',1))
        ps[index]=F(1)
    policy.append(ps)
ev=tree.evaluate(policy)
check('uninformative_forced_timeout_costs_exactly_launch_plus_cap',ev==((F(1,2),F(1,2)),(F(7,200),F(7,200)),(F(1),F(1))))

# Independent exhaustive full binary strings. Early outputs share the final
# random tie coin; expected sample count calculated from prefix decisiveness.
binary_summary=[]
for n in range(9):
    r=bm.minimax(n)
    k=r['threshold'];coin=r['randomize_one']
    errors=[F(0),F(0)];counts=[F(0),F(0)]
    for bits in product((0,1),repeat=n):
        final=F(sum(bits)>k) if sum(bits)!=k else coin
        used=n;early_output=coin
        for i in range(n+1):
            ss=sum(bits[:i])
            if ss>k:
                used=i;early_output=F(1);break
            if ss+n-i<k:
                used=i;early_output=F(0);break
            if i==n:
                used=i;early_output=coin;break
        check('early_rule_pathwise_equals_fixed_n_randomized_rule',early_output==final)
        for h,p in enumerate((F(57,100),F(87,100))):
            mass=p**sum(bits)*(1-p)**(n-sum(bits))
            errors[h]+=mass*(final if h==0 else 1-final)
            counts[h]+=mass*used
    check('binary_full_string_error_and_cost_match_analytic_recursion',tuple(errors)==(r['risk'],r['risk']) and tuple(counts)==r['early_expected_samples'])
    # Enumerate the two-sided loss tradeoff envelope on the sufficient count statistic.
    # The given lambda witnesses an exact minimax lower; n=0 must equal .5.
    check('risk_never_exceeds_uninformative_half',r['risk']<=F(1,2))
    if n==0: check('zero_data_minimax_is_half',r['risk']==F(1,2))
    binary_summary.append({'n':n,'risk':str(r['risk']),'samples':list(map(str,counts))})

# Input contract audit, recorded as findings rather than exceptions masking science.
findings=[]
for n in [0,1,2]:
    try:
        v=bm.minimax(n,p0=.57,p1=.87)
        findings.append({'finding':'non-Fraction probabilities accepted by exact API','n':n,
            'risk_type':type(v['risk']).__name__,'risk':str(v['risk'])})
    except Exception as e:
        findings.append({'finding':'float-probability call raises after loose validation','n':n,
            'exception':type(e).__name__,'message':str(e)})
r=fm.Tree(fm.Contract(3,max_probes=1,family='catalog')).solve()
findings.append({'finding':'catalog default tariff differs from existing .30 macro',
    'reported_expected_resource':list(map(str,r['resources'])),'existing_macro_resource':'3/10',
    'requires':'Use fee=27/100,time_price=1/100 (or explicitly declare a different tariff). Default Contract is generic, not the full paid catalog macro.'})
source_after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')}
out={'schema':'ndu.deadline-independent-internal-review.v1','source_before':source_before,'source_after':source_after,
    'source_stable':source_before==source_after,'checks':checks,'check_count':len(checks),
    'pure_policy_summary':comparison_summary,'binary_summary':binary_summary,'findings':findings,
    'scope':'Independent internal enumeration and mathematical source review, not external review or LLM experiment.'}
Path(__file__).with_name('review_result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(json.dumps({'checks':len(checks),'source_stable':out['source_stable'],'summary':comparison_summary,'findings':findings},indent=2))
