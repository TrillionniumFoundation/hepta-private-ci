import sys,json,hashlib
from decimal import Decimal,localcontext
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path
sys.path.insert(0,'/workspace/scratch/e5ecafe4ccc8/jac_safe_work')
from v3.ndu_jac.finite_study import build_problem
base=Path('/workspace/scratch/e5ecafe4ccc8/jac_safe_work/v3/ndu_jac_confidence')
hr_path=base/'headroom.json'; hr=json.loads(hr_path.read_text())
ev_path=Path('/workspace/scratch/e5ecafe4ccc8/hepta-research/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac/evidence/gap_study.json')
ev_bytes=ev_path.read_bytes(); banks=json.loads(ev_bytes)['rows']
checks={'historical_source_identity':hashlib.sha256(ev_bytes).hexdigest()==hr['historical_evidence_sha256'],
 'corrected_result_identity':hashlib.sha256((base/'result.corrected.json').read_bytes()).hexdigest()==hr['corrected_result_sha256'],
 '20_retained_banks':len(banks)==len(hr['rows'])==20}
source_paths={name:(base/name if name in ('headroom.py','confidence.py') else base.parent/'ndu_jac'/name) for name in hr['source_sha256']}
start={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in source_paths.items()}
checks['source_hashes_match_receipt']=start==hr['source_sha256']
nodes,root,_=build_problem()
# Independent implementation: Decimal real exp/log, exact binary input conversion.
# It imports no headroom arithmetic, optimal_policy, or source evaluator.
with localcontext() as ctx:
 ctx.prec=110
 def d(v):
  f=F(v);return Decimal(f.numerator)/Decimal(f.denominator)
 eta,rho=d(2.),d(.17)
 stats={'biggest_exp':Decimal(0),'biggest_z':Decimal(0)}
 def calculate(policy=None):
  @lru_cache(None)
  def value(s):
   qs=[]
   for action,law in nodes[s].items():
    if policy is not None and policy[s][action]!=1:continue
    total=sum((F(o.probability) for o in law),F(0))
    moment=Decimal(0)
    for o in law:
     branch=d(o.reward)-d(o.cost)-d(o.adjustment_cost)
     if o.next_state is not None:
      exponent=-rho*d(o.duration);stats['biggest_exp']=max(stats['biggest_exp'],abs(exponent))
      branch+=exponent.exp()*value(o.next_state)
     exponent=-eta*branch;stats['biggest_exp']=max(stats['biggest_exp'],abs(exponent))
     moment+=d(F(o.probability)/total)*exponent.exp()
    stats['biggest_z']=max(stats['biggest_z'],abs((moment-1)/(moment+1)))
    qs.append(-moment.ln()/eta)
   return max(qs)
  return value(root)
 optimum=calculate()
 def contained(value,enclosure):
  return d(F(enclosure['lower']))<=value<=d(F(enclosure['upper']))
 checks['independent_110_digit_optimum_enclosed']=contained(optimum,hr['known_law_optimum_interval'])
 by_seed={r['seed']:r for r in hr['rows']}
 vals=[]; details=[]
 for bank in banks:
  r=by_seed[bank['seed']]
  v=calculate(bank['policies']['vanilla_argmax']); gain=optimum-v
  vals.append(gain)
  checks['baseline_enclosed_'+str(bank['seed'])]=contained(v,r['baseline_interval'])
  checks['headroom_enclosed_'+str(bank['seed'])]=contained(gain,r['headroom_interval'])
  details.append({'seed':bank['seed'],'baseline_value_decimal':str(v),'headroom_decimal':str(gain)})
 max_gain=max(vals); mean_gain=sum(vals)/len(vals); sum_gain=sum(vals)
 maxupper=max(F(row['headroom_interval']['upper']) for row in hr['rows'])
 sumupper=sum((F(row['headroom_interval']['upper']) for row in hr['rows']),F(0))
 fee=F(hr['fee_fraction'])
 checks['each_oracle_headroom_upper_below_fee']=maxupper<fee
 checks['sum_20_one_shot_headrooms_upper_below_single_fee']=sumupper<fee
 checks['recorded_max_upper_exact']=maxupper==F(hr['max_headroom_upper'])
 checks['recorded_mean_upper_exact']=sumupper/len(vals)==F(hr['mean_headroom_upper'])
 checks['recorded_sum_upper_exact']=sumupper==F(hr['sum_headroom_upper'])
 checks['independent_actual_exp_arguments_inside_domain']=stats['biggest_exp']<8
 checks['positive_reuse_not_globally_excluded']=9*max_gain>d(fee)
 reference={'oracle_value_decimal':str(optimum),'max_headroom_decimal':str(max_gain),
   'mean_headroom_decimal':str(mean_gain),'sum_20_headrooms_decimal':str(sum_gain),
   'max_paid_gain_one_episode_decimal':str(max_gain-d(fee)),
   'sum_20_one_each_minus_one_fee_decimal':str(sum_gain-d(fee)),
   'max_exp_argument_magnitude':str(stats['biggest_exp']),'max_log_atanh_abs_z':str(stats['biggest_z']),
   'illustrative_nine_reuses_of_positive_headroom_minus_one_fee':str(9*max_gain-d(fee)),
   'reuse_note':'This only shows the one-episode/20-distinct-bank bound cannot rule out arbitrary M under a separately declared one-time-fee contract. No learned strategy, actual reuse saving, or all-cost net benefit is claimed.'}
end={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in source_paths.items()}
checks['no_target_sources_changed']=end==start
assert all(checks.values())
out={'status':'PASS','scope':'Independent proof inspection of rational series/rounding plus 110-digit Decimal Bellman evaluation of the unchanged finite artifact and 20 retained deterministic baselines. No new banks, fitting, observations or model calls.',
 'check_count':len(checks),'checks':checks,'source_sha256':start,'headroom_json_sha256':hashlib.sha256(hr_path.read_bytes()).hexdigest(),
 'reference':reference,'rows':details,
 'interval_proof_review':{'dyadic_rounding':'floor(lo*2^80), ceil(hi*2^80) is outward for both signs',
  'exp_tail':'After degree N=40 the first omitted term is x^41/41! and all later term ratios are at most x/42<1 on [0,8]; interval arithmetic preserves the partial sum and upper tail.',
  'negative_exp':'positive reciprocal with reversed endpoints preserves enclosure',
  'log_tail':'80 terms leave power z^161; the tail is bounded by 2*z^161/(161*(1-z^2)), with upper interval power and upper squared-z used conservatively.',
  'recursive_values':'Monotone exponential/log CE transformations, exact probability normalization, and maxima of action intervals enclose the real finite-model optimum and deterministic baseline values.',
  'headroom':'Intersecting optimum-minus-baseline interval with nonnegative values is valid because the baseline is feasible in the same action/information class.'},
 'accounting_review':{'one_episode_fee_conclusion':'Sound for the frozen one-scored-episode .01 audit-charge gate.',
  'twenty_episode_shared_fee':'Sound only for the explicitly stated sum of 20 separately scored CE episodes, one from each listed baseline, with one shared fee; this is not a joint entropic objective.',
  'long_reuse':'No impossibility conclusion for arbitrary deployment count M is justified. A positive-headroom fixed baseline can amortize a one-time fee; existing diagnostics do not include its additional real acquisition/deployment costs.',
  'confidence_adapter':'The rational headroom enclosure does not upgrade SciPy confidence quantiles or the floating confidence propagation to formal interval arithmetic.'},
 'new_banks':0,'new_observations':0,'new_model_calls':0,'external_review':False}
p=Path('/workspace/scratch/e5ecafe4ccc8/theory_work/REVIEW_HEADROOM.json')
p.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'status':out['status'],'check_count':len(checks),'reference':reference,'output':str(p)},indent=2))
