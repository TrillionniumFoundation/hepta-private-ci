"""Produce honest research-only receipt for local HCSN P0-P5 iteration v3."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import platform
import re
from pathlib import Path
import numpy as np
from fpt_time_brackets import refinement
from fpt_reference import FPT
from simple_fd_oracle import solve
from simplified_stopping import SimpleStopping
from backbone_promotion_gate import compare

ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/'reports'
TASKS=('overwrite_reset','irregular_time','mqar','long_range')


def load(fname):
    return json.loads((REPORTS/fname).read_text())


def summarize_task(name):
    r=load(f'p1_p2_{name}.json')
    arms=defaultdict(list)
    durations=defaultdict(list)
    for v in r['rows']:
        arms[v['arm']].append(v['holdout_accuracy'])
        durations[v['arm']].append(v['training_wall_seconds'])
    control=float(np.mean(arms['control']))
    times={a:float(np.mean(durations[a])) for a in arms}
    means={a:float(np.mean(scores)) for a,scores in arms.items()}
    return {'task':name,'seeds':r['seeds'],'n_factorial_rows':len(r['rows']),
            'train_length':r['train_length'],'holdout_length':r['holdout_length'],
            'training_steps':r['rows'][0]['training_steps'],
            'trained_parameters':r['rows'][0]['parameter_count'],
            'matched_parameter_and_step':r['matched_parameter_data_step_constraints'],
            'mean_accuracy':means,
            'paired_delta_vs_control':{a:means[a]-control for a in means if a!='control'},
            'training_seconds':times,
            'runtime_ratio_vs_control':{a:times[a]/times['control'] for a in times},
            'full_feature_compute_matched':r['full_training_flops_equal'],
            'classification':'synthetic CPU surrogate, not original HCSN; untrusted for P1/P2 product'}


def main():
    p0=refinement(FPT(.8,-.3,.7,.9,.05),counts=(16,32,64),dps=70)
    stopping=SimpleStopping(.05,.03,.4,.08)
    fd=[solve(stopping,n=n) for n in (200,400,800)]
    tasks=[summarize_task(name) for name in TASKS]
    mm=load('p3_toy_media_encoder.json')
    p4=load('p4_cpu_oracle.json')
    p5=compare([],task_ids=('selective_copy','mqar','irregular'),seed_ids=range(8))
    test_log=(REPORTS/'v3_tests.log').read_text()
    match=re.search(r'Ran (\d+) tests in',test_log)
    if not match or not test_log.rstrip().endswith('OK'):
        raise AssertionError('missing successful local unittest log')
    test_count=int(match.group(1))
    audit={
        'utc_created':datetime.now(timezone.utc).isoformat(),
        'scope':'LOCAL stand-alone research v3; not original Hepta HCSN implementation',
        'connection':{'github':'HTTP 403: Sorry. Your account was suspended',
                      'current_main_verified':False,'commits_created':0,
                      'pull_requests_created':0,'remote_merges':0},
        'environment':{'python':platform.python_version(),
                       'architecture':platform.machine(),'native_rust_compiled':False,
                       'nvidia_gpu_tested':False,'energy_instrument_present':False},
        'p0':{'fixed_boundary_cdf_partition_inequality':p0,
              'simplified_fixed_boundary_ode_fd':fd,
              'precision_cast_loss':load('p0_precision_limits.json'),
              'full_HX_upstream_source_executed_this_turn':False,
              'full_coupled_equity_bond_free_boundary_proven':False,
              'independently_certified_intervals':False},
        'p1_p2':{'synthetic_recurrent_factorial_runs':tasks,
                 'total_trained_arm_seed_task_rows':sum(t['n_factorial_rows'] for t in tasks),
                 'full_feature_training_compute_matched':False,
                 'independent_HCSN_source_and_model_verified':False,
                 'full_selective_copy_mqar_regeneration_product_quality':False},
        'p3':{'data_type':'synthetic procedural valid bytes',
              'samples':mm['samples'],'holdout':mm['results']['holdout'],
              'feature_noise_holdout':mm['feature_noise_accuracy_holdout'],
              'real_world_encoder_quality_proven':False},
        'p4':{'reference_type':'numpy_cpu_toy_not_rust_or_gpu',
              'measurements':p4['hardware_benchmark'],
              'actual_abrupt_exit_checkpoint_recovery':p4['abrupt_process_recovery'],
              'rust_source_compiled':False,'gpu_source_compiled':False,
              'physical_power_meter':False},
        'p5':{'comparison_requirement_count':len(p5['issues']),
              'all_baselines_same_data_compute_rigorous_proven':False,
              'evaluator_decision':p5['decision']},
        'local_tests':{'suite':'unittest discover -s tests -v',
                       'count':test_count,'failed':0,'log':'reports/v3_tests.log'},
        'stage_status':{k:'OPEN' for k in ('P0','P1','P2','P3','P4','P5')},
        'all_blockers_closed':False,'production_activation_allowed':False,
        'research_admission':'DENY_ALL',
        'restrictions':['No full He-Xiong financial coupling or certified rounding',
                        'No fair real HCSN mechanism superiority',
                        'Memory long-range and MQAR quality not adequate',
                        'No natural paired four-modality holdout',
                        'No compiled Rust or GPU benchmark or Joule measurements',
                        'No Transformer/SSM equal-compute scale-up experiment',
                        'GitHub account access denied']
    }
    (REPORTS/'v3_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False))
    # All files in current package except self-hash and bytecode cache. This
    # manifest is for transfer integrity, not authenticating GitHub origin.
    manifest={}
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
        if p.name in ('MANIFEST_SHA256_v3.json','MANIFEST_SHA256.json',
                      'apt_update.log','p1_p2_smoke.json'):continue
        if p.name.endswith('.exit'):continue
        rel=p.relative_to(ROOT).as_posix()
        manifest[rel]=hashlib.sha256(p.read_bytes()).hexdigest()
    (ROOT/'MANIFEST_SHA256_v3.json').write_text(json.dumps(manifest,indent=2))
    print(f'v3 audit written; {test_count} unit tests; statuses',audit['stage_status'])
    print('P1/P2 trained rows:',audit['p1_p2']['total_trained_arm_seed_task_rows'])
    for t in tasks:
        print(' ',t['task'], 'control:',round(t['mean_accuracy']['control'],4),
              'full arm:',round(t['mean_accuracy']['call+risk+margin'],4))
    print('P3 synthetics:',mm['samples'], 'P4 CPU scales:',
          [z['cells'] for z in p4['hardware_benchmark']])

if __name__=='__main__':main()
