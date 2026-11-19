"""Deterministic P0 six-node-set exploration with independent rational witnesses.

Sample nodes were chosen AFTER inspecting a numerical-error development panel;
this is NOT public timestamped preregistration and must never be reported as
whole-grid pointwise certification. Scientific and production gates stay false.
"""
from dataclasses import asdict
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

from .hx import HX,boundary,bond_value
from .hx_bond_pde_independent import solve_bond_pde
from .hx_bond_pde_rannacher import solve_bond_rannacher
from .rannacher_debt_point_certificate import certify_debt_node


def run():
    models=[(.015,(19,37,75)),(.2,(9,17,35))]
    rows=[]
    for sf,probes in models:
        p=HX(sale_fraction=sf);b=boundary(p)
        for (n,t),i in zip(((101,250),(201,500),(401,1000)),probes):
            start=time.process_time_ns()
            old=solve_bond_pde(p,b,nodes=n,time_steps=t,log_upper=3.6)
            cpu_be=(time.process_time_ns()-start)/1e9
            start=time.process_time_ns()
            new=solve_bond_rannacher(p,b,nodes=n,time_steps=t,log_upper=3.6)
            cpu_cn=(time.process_time_ns()-start)/1e9
            targets=[bond_value(p,b*math.exp(j*new.grid_step),p.maturity,b)
                     for j in range(n)]
            old_err=[abs(x-y) for x,y in zip(old.values,targets)]
            new_err=[abs(x-y) for x,y in zip(new.values,targets)]
            certificate=certify_debt_node(p,b,nodes=n,time_steps=t,index=i)
            rows.append({
                'sale_fraction':sf, 'barrier':b, 'nodes':n,'time_steps':t,
                'log_upper':3.6,'probe_index':i,'max_error_be_vs_eq8':max(old_err),
                'max_error_cn_vs_eq8':max(new_err),
                'max_error_reduction_factor':max(old_err)/max(new_err),
                'max_error_be_index':old_err.index(max(old_err)),
                'max_error_cn_index':new_err.index(max(new_err)),
                'cpu_be_s_single_sample':cpu_be,
                'cpu_cn_s_single_sample':cpu_cn,
                'cn_step_residual_max':new.max_step_residual,
                'pointwise_certificate':asdict(certificate),
            })
    result={
        'contract':'HX research-only independent fixed-barrier bond PDE test',
        'date':'2026-10-31',
        'oracle':'exact-rational Brownian first-hit, finite maturity at selected nodes',
        'analytic_eq8':'used for exploratory all-node empirical comparison only, not solver or rational certificate',
        'sample_selection':'POSTHOC max error probes (development chosen), not pre-registered',
        'units':'physical HX financial bond price; no neuronal claim',
        'runtime':'Python 3.13 / NumPy SciPy mpmath CPU',
        'numeric_scope':'selected six nodes strict error ordering; six grids empirical max error, NOT continuum accuracy theorem',
        'roundoff_certified':False,
        'all_node_certified':False,
        'coupled_financial_equilibrium_certified':False,
        'all_scientific_blockers_closed':False,
        'production_activation':False,
        'observations':rows,
    }
    raw=json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    result['sha256_canonical_payload']=hashlib.sha256(raw.encode()).hexdigest()
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=run()
    Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf8')
    print('rows',len(result['observations']),'sha256',result['sha256_canonical_payload'])
    for r in result['observations']:
        print('sale',r['sale_fraction'],'n',r['nodes'],
              'BE',f"{r['max_error_be_vs_eq8']:.9g}",
              'CN',f"{r['max_error_cn_vs_eq8']:.9g}",
              'ratio',f"{r['max_error_reduction_factor']:.4g}",
              'proof',r['pointwise_certificate']['guaranteed_pointwise_improvement'],
              'oracleCells',r['pointwise_certificate']['first_hit_cells'],
              'cpuBE',f"{r['cpu_be_s_single_sample']:.4f}",
              'cpuCN',f"{r['cpu_cn_s_single_sample']:.4f}")
