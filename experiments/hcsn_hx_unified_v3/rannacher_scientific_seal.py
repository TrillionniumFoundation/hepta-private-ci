"""Independent integrity audit of the exploratory Rannacher comparison JSON.

Separate reproducible scientific quantities from single-process CPU timing:
source/state/decision/interval numbers are stable on a fixed IEEE754 stack,
while elapsed process CPU is observational and must not enter a cross-machine
science seal. SHA256 is content-integrity, not origin authentication, proof
that a first-hit oracle is sound, or permission to activate anything.
"""
from fractions import Fraction as F
import hashlib
import json
import math

class InvalidRannacherEvidence(ValueError):
    pass


def audit_panel(panel):
    if type(panel) is not dict or type(panel.get('observations')) is not list:
        raise InvalidRannacherEvidence('missing complete panel')
    expected={(s,n,t) for s in (.015,.2) for n,t in ((101,250),(201,500),(401,1000))}
    seen=set();scientific=[]
    for row in panel['observations']:
        if type(row) is not dict or not isinstance(row.get('pointwise_certificate'),dict):
            raise InvalidRannacherEvidence('missing certified row')
        sf,n,t=row.get('sale_fraction'),row.get('nodes'),row.get('time_steps')
        key=(sf,n,t)
        if key not in expected or key in seen:
            raise InvalidRannacherEvidence('unregistered or duplicated physical case')
        seen.add(key)
        proof=row['pointwise_certificate']
        if (type(proof.get('physical_identity_sha256')) is not str or
                len(proof['physical_identity_sha256'])!=64 or
                proof.get('nodes')!=n or proof.get('time_steps')!=t or
                proof.get('index')!=row.get('probe_index') or
                proof.get('guaranteed_pointwise_improvement') is not True or
                proof.get('all_node_financial_error_certified') is not False or
                proof.get('global_financial_obstacle_certified') is not False or
                proof.get('production_activation') is not False):
            raise InvalidRannacherEvidence('invalid or promoted scientific witness')
        try:
            old=F(proof['be_error_lower'])
            new=F(proof['rannacher_error_upper'])
            lower=F(proof['true_price_lower'])
            upper=F(proof['true_price_upper'])
        except (TypeError,ValueError,ZeroDivisionError) as err:
            raise InvalidRannacherEvidence('invalid rational interval') from err
        if not(0<=lower<=upper and 0<=new<old and row['max_error_cn_vs_eq8']>0
                and row['max_error_be_vs_eq8']>row['max_error_cn_vs_eq8']
                and all(type(row.get(k)) in (int,float) and
                        math.isfinite(row[k]) and row[k]>=0 for k in
                        ('cpu_be_s_single_sample','cpu_cn_s_single_sample'))):
            raise InvalidRannacherEvidence('unverified strict-error or cost field')
        # Exclude ONLY CPU data. Preserve all raw f64 scientific quantities
        # and exact rational endpoints without stringifying/rounding them.
        scientific.append({k:v for k,v in row.items() if not k.startswith('cpu_')})
    if seen!=expected or any(panel.get(flag) is not False for flag in (
            'roundoff_certified','all_node_certified',
            'coupled_financial_equilibrium_certified',
            'all_scientific_blockers_closed','production_activation')):
        raise InvalidRannacherEvidence('incomplete panel or improper admission')
    scientific.sort(key=lambda r:(r['sale_fraction'],r['nodes'],r['time_steps']))
    payload={k:v for k,v in panel.items() if k not in
             ('observations','sha256_canonical_payload')}
    payload['observations']=scientific
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=False)
    return dict(sha256_scientific_payload=hashlib.sha256(raw.encode()).hexdigest(),
        independent_cases=len(scientific),strict_selected_nodes=len(scientific),
        cpu_timing_excluded=True,production_activation=False,
        all_scientific_blockers_closed=False)
