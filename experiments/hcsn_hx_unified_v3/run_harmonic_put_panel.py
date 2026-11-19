"""Two original financial regimes; canonical research-only panel."""
import json
from hashlib import sha256
from pathlib import Path
from experiments.hcsn_hx_unified_v3.hx import HX,boundary,equity_closed
from experiments.hcsn_hx_unified_v3.hx_harmonic_put import harmonic_put_component,tightened_fixed_equity_envelope
import math

cases=[]
for fraction in (.015,.2):
    p=HX(sale_fraction=fraction)
    b=boundary(p)
    L=3.6
    held=equity_closed(p,b*math.exp(L),b)
    component=harmonic_put_component(p,candidate_barrier=b,log_upper=L)
    refined=tightened_fixed_equity_envelope(p,candidate_barrier=b,log_upper=L,
                                                nominal_upper_equity=held)
    cases.append({
        'sale_fraction':fraction,'barrier_f64':b,'held_policy_equity_f64':held,
        'r_harmonic_optional_premium_upper':component.put_premium_upper,
        'old_put_upper':refined.old_put_premium_upper,
        'new_fixed_equity_lower':refined.equity_lower,
        'new_fixed_equity_upper':refined.equity_upper,
        'old_fixed_equity_upper':refined.original_equity_upper,
        'new_abs_error_upper':refined.nominal_absolute_error_upper,
        'r_harmonic_exponent_lower':component.gamma_lower,
        'r_harmonic_exponent_upper':component.gamma_upper,
        'rational_power':component.rational_power,
    })
payload={
    'schema':'hcsn-p0-r-harmonic-optional-put-v1',
    'parent_pr':4516,
    'main_observed_sha':'732e934ba496d90fbe042b8d41d479ef901643e5',
    'parent_head_sha':'be808f2a05ad6f3761e7b8d15c1792fcb958e3e6',
    'status':'RESEARCH_ONLY_DENY_ALL_NO_GO',
    'all_scientific_blockers_closed':False,
    'global_equilibrium_certified':False,
    'complete_debt_error_budget':False,
    'production_activation':False,
    'cases':cases,
    'limits':['fixed financial barrier; only put premium tighter',
              'no independent coupled obstacle or interval interior PDE error',
              'no fully authenticated host recovery, GPU or real hardware energy'],
}
s=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
p=Path(__file__).with_name('HX_HARMONIC_PUT_PANEL_20261031.json')
p.write_text(s,encoding='utf-8')
print('sha256',sha256(s.encode()).hexdigest())
print(s)
