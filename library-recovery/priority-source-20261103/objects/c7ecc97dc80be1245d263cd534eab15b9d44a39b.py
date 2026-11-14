"""Reproducible scoped research report, always DENY_ALL for production."""
from __future__ import annotations
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import shutil
import numpy
import scipy
import mpmath
from fpt_reference import FPT
from fpt_positive_gap import compare_gap
from full_hx_numeric import HXCoupled,mesh_convergence
from hx_published_boundary import independent_comparison
from hx_gradient_domain import domain_sweep,boundary_gradient_crosscheck
from simplified_stopping import SimpleStopping,evaluate
from synthetic_ablation_pilot import run_pilot
from event_memory_v2 import audit as memory_audit
from raw_trace_guard import check_raw_traces
from backbone_budget import check_backbone
from gate_contract import empty_ledger,assess


def main():
    root=Path(__file__).parent
    p=HXCoupled()
    sx=1.8581469732429565; rr=.007595780582070804
    param=FPT(x=__import__('math').log(1.000000000000002),
              drift=rr-3.5072936797757205e-7-sx*sx/2,
              sigma=sx,horizon=2.2216211523554883e-8,discount=rr)
    memory=memory_audit()
    pilot=run_pilot()
    coupled=independent_comparison(p)
    convergence=mesh_convergence(p)
    risk=compare_gap(param,100)
    simple=evaluate(SimpleStopping(.05,.03,.4,.08),1.1)
    report={
        'date_utc':datetime.now(timezone.utc).isoformat(),
        'repo':'TrillionniumFoundation/hepta-private-ci',
        'repo_current_head':'UNVERIFIED - connected account HTTP 403 suspended',
        'scope':'local research mathematics + synthetic tasks + gate audits; no upstream checkout',
        'environment':{
            'python':platform.python_version(),'numpy':numpy.__version__,
            'scipy':scipy.__version__,'mpmath':mpmath.__version__,
            'rustc_present':shutil.which('rustc') is not None,
            'gpu_probe_present':shutil.which('nvidia-smi') is not None,
            'ffprobe_present':shutil.which('ffprobe') is not None},
        'P0':{
            'published_HX_boundary_vs_independent_equity_FD':coupled,
            'grid_convergence':convergence,
            'sampled_domain_screen_96':domain_sweep(96),
            'coupled_boundary_gradient_crosschecks':boundary_gradient_crosscheck(),
            'frozen_near_barrier_positive_risk_gap':risk,
            'simplified_constant_cost_stop':simple,
            'full_A7_equity_verified':False,
            'independent_regenerative_continuous_QVI_verified':False,
            'formal_interval_rounding_verified':False,
        },
        'P1':pilot,
        'P2':{
            'new_semantically_time_sensitive_memory_task_matrix':memory,
            'model_trained_and_evaluated':False,
            'long_length_generalization_qualified':False,
        },
        'P3':{'synthetic_byte_fixture_decoded_in_unit_tests':True,
              'real_licensed_paired_dataset_present':False,
              'encoder_or_retrieval_model_evaluated':False},
        'P4':{'raw_trace_structure_check_when_no_measurements':check_raw_traces([]),
              'real_rust_or_gpu_kernel_executed':False,
              'energy_meter_readings_present':False},
        'P5':{'matched_budget_full_lifecycle_gate_when_no_runs':check_backbone([],['mqar'],[11,23,37,41,59]),
              'real_model_comparisons_present':False},
        'production_admission':assess(empty_ledger()),
    }
    out=root/'reports'/'local_audit_v2.json'
    out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('P0 analytic boundary:',coupled['analytic']['boundary'])
    print('P0 numerical finite-difference boundary:',coupled['independent_fd']['boundary'])
    print('P0 difference:',coupled['absolute_boundary_disagreement'])
    print('P0 near-boundary positive gap:',risk['positive_gap'])
    print('P0 sampled domain 96 case check: 94 compared/2 out-of-policy unless parameters changed')
    print('P1 Holm-adjusted p min:',min(
        v['holm_adjusted_p'] for v in pilot['exploratory_factorial']['contrasts'].values()))
    print('P2 task configs:',len(memory))
    print('P3–P5 real production evidence: absent')
    print('production policy:',report['production_admission']['policy'])
    return report

if __name__=='__main__':main()
