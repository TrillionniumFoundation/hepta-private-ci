"""Local strict V4 evidence ledger: rational certificates + trained negative controls.

Do not import any conclusion from the archived v3 audit as a current GitHub
status. Completed local experiments are not an upstream source certification.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from functools import reduce
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import numpy as np
from rational_fpt_certificate import certified_fpt, certified_risk_distance_gradient
from qvi_rational_certificate import known_case
from factorial_evidence import exact_two_sided_signflip

ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/'reports'
TASKS=('overwrite_reset','irregular_time','mqar','long_range','selective_copy','regeneration')
CASES=[
    ('0.8','-0.3','0.7','0.9','0.05'),
    ('1.2','0.1','0.6','1.1','0.4'),
    ('0.1','0.4','1.3','0.5','0.3'),
    ('2.0','-0.2','1.0','2.0','0.1'),
    ('0.001','-0.03','1.2','0.5','0.3'),
    ('0.8','-0.3','0.7','0.9','1e-22'),
]

def load(name):
    return json.loads((REPORTS/name).read_text())


def audit_factorial(name):
    d=load('p1_p2_'+name+'.json')
    if not d['matched_parameter_data_step_constraints'] or d['full_training_flops_equal']:
        raise AssertionError('unexpected training budget status')
    grouped=defaultdict(dict)
    for r in d['rows']:
        key=r['seed']
        if r['arm'] in grouped[key]:raise AssertionError('duplicate factorial row')
        grouped[key][r['arm']]=r
    if sorted(grouped)!=sorted(d['seeds']):raise AssertionError('missing seeds')
    arms=('control','call','risk','margin','call+risk','call+margin','risk+margin','call+risk+margin')
    if any(set(grouped[s])!=set(arms) for s in d['seeds']):
        raise AssertionError('missing factorial arm')
    c=[grouped[s]['control'] for s in sorted(grouped)]
    t=[grouped[s]['call+risk+margin'] for s in sorted(grouped)]
    acc=[r['holdout_accuracy'] for r in c]
    acc_t=[r['holdout_accuracy'] for r in t]
    effects=[b-a for a,b in zip(acc,acc_t)]
    times_c=[r['training_wall_seconds'] for r in c]
    times_t=[r['training_wall_seconds'] for r in t]
    ratio=np.mean(times_t)/np.mean(times_c)
    return {'task':name,'seed_count':len(grouped),'seed_ids':sorted(grouped),
            'train_length':d['train_length'],'unseen_holdout_length':d['holdout_length'],
            'train_steps_per_arm':d['rows'][0]['training_steps'],
            'holdout_rows_per_seed':d['rows'][0]['holdout_n'],
            'trained_rows':len(d['rows']),
            'ordinary_accuracy_mean':float(np.mean(acc)),
            'full_mechanism_accuracy_mean':float(np.mean(acc_t)),
            'paired_seed_deltas':effects,
            'paired_delta_mean':float(np.mean(effects)),
            'exact_two_sided_signflip_p':exact_two_sided_signflip(effects),
            'full_vs_ordinary_wallclock_training_ratio':float(ratio),
            'accuracy_over_95pct_full_mechanism':all(a>=.95 for a in acc_t),
            'matched_same_seed_weights_data_params_steps':True,
            'matched_total_training_compute':False,
            'synthetic_surrogate_only':True,
            'P1_mechanism_advantage_confirmed':False,
            'P2_real_world_memory_gate_passed':False}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    certs=[certified_fpt(*c,places=65) for c in CASES]
    if any(r['decision']!='CERTIFIED_POSITIVE_F_MINUS_G' for r in certs):
        raise AssertionError('P0 rational certification failed')
    gradients=[certified_risk_distance_gradient(x,mu,sig,t,65)
               for x,mu,sig,t in [('0','-0.3','0.7','0.9'),('0','0','0.6','1'),
                                  ('0','0.4','1.1','0.75'),('0.8','-0.3','0.7','0.9')]]
    if not all(g['strictly_negative_certified'] for g in gradients):
        raise AssertionError('P0 boundary derivative certificate failed')
    qvi=known_case()
    if qvi['bellman_residual_exact']!='0':raise AssertionError('QVI exact solver failed')
    reports=[audit_factorial(x) for x in TASKS]
    p1_attribution=load('p1_v4_42_exploratory_factorial_effects.json')
    if p1_attribution['n_rows']!=128 or p1_attribution['factorial_effect_count']!=42 or p1_attribution['any_holm_significant']:
        raise AssertionError('missing actual factorial attribution or unexpected significance')
    full=next(r for r in reports if r['task']=='regeneration')
    if full['paired_delta_mean']>=0:
        print('Attention: regeneration did not reproduce negative pilot; recheck')
    tests=(REPORTS/'v4_tests.log').read_text()
    m=re.search(r'Ran (\d+) tests in',tests)
    if not m or not tests.rstrip().endswith('OK'):
        raise AssertionError('V4 complete test transcript missing or failing')
    p0={'scope':'exact rational input semantics, compact Brownian fixed-barrier FPT',
        'certified_fpt_cases':certs,'certified_risk_gradient_cases':gradients,
        'finite_regenerative_mdp_exact_policy_certificate':qvi,
        'strictly_outward_rational_enclosures':True,
        'full_financial_HX_equity_bond_coupling':False,
        'original_HX_free_boundary_verification':False,
        'machine_FP32_BF16_libm_certified':False}
    (REPORTS/'p0_v4_rational_certificates.json').write_text(json.dumps(p0,ensure_ascii=False,indent=2))
    hw={'rustc_path':None,'cargo_path':None,'gpu_detected':False,'gpu_energy_meter':False}
    for name in ('rustc','cargo'):
        from shutil import which
        hw[name+'_path']=which(name)
    hw['gpu_detected']=any(Path(n).exists() for n in ('/dev/nvidia0','/dev/kfd'))
    audit={'created_utc':datetime.now(timezone.utc).isoformat(),
        'environment':{'python':platform.python_version(),'machine':platform.machine(),
                       'hardware_tools':hw},
        'repository':{'name':'TrillionniumFoundation/hepta-private-ci',
                      'live_latest_main_confirmed':False,'write_access_confirmed':False,
                      'latest_attempt':'Connected GitHub API HTTP403 suspended',
                      'branch_created_this_iteration':False,'commit_created_this_iteration':False,
                      'pr_created_this_iteration':False},
        'P0':{'new_proven_scalar_enclosures':len(certs),
              'new_negative_right_boundary_gradients':len(gradients),
              'exact_regenerative_policy_enumeration':qvi['enumerated_policies'],
              'certificate_details':'reports/p0_v4_rational_certificates.json',
              'full_HX_and_neural_kernel_closed':False},
        'P1_P2':{'existing_4_tasks_plus_new_2_trained_pilots':reports,
                 'total_trained_arm_seed_rows':sum(r['trained_rows'] for r in reports),
                 'actual_factorial_contrast_count':p1_attribution['factorial_effect_count'],
                 'Holm_significant_main_or_interaction':p1_attribution['any_holm_significant'],
                 'real_training_attribution_report':'reports/p1_v4_42_exploratory_factorial_effects.json',
                 'tasks_train_successful':len(reports),
                 'same_feature_flops_and_joules_control':False,
                 'unseen_original_HCSN_test_and_real_renewal':False},
        'P3':{'v3_procedural_media_study_available':(REPORTS/'p3_toy_media_encoder.json').is_file(),
              'new_instance_level_12_directed_pair_evaluator_in_tests':True,
              'rejects_class_collapsed_embedding_and_cross_split_clones':True,
              'natural_four_modality_paired_holdout_validated':False},
        'P4':{'v3_numpy_cpu_toy_study_available':(REPORTS/'p4_cpu_oracle.json').is_file(),
              'native_rust_compiled_and_tested_this_turn':False,
              'hardware_gpu_64_256_1024_4096_accepted':False,
              'physical_energy_joules_measured':False},
        'P5':{'actual_equal_compute_transformer_ssm_hybrid_compared':False,
              'scaleup_allowed':False},
        'tests':{'count':int(m.group(1)),'status':'OK',
                 'log_sha256':sha(REPORTS/'v4_tests.log')},
        'stage':{k:'OPEN' for k in ('P0','P1','P2','P3','P4','P5')},
        'all_blockers_closed':False,'production_activation_allowed':False,
        'research_admission':'DENY_ALL',
        'notes':['Theoretical rational enclosures certify only restricted scalar FPT and finite MDP',
                 'Independent numerical tests cannot prove full He-Xiong equity/bond model',
                 '3-seed CPU synthetic pilot is too small for inferential conclusions',
                 'Compute FPT interval in rational arithmetic, not actual device math',
                 'No original HCSN model source revalidated due GitHub 403',
                 'No natural multimodal dataset or native/GPU benchmarks',
                 'All six original production gates are OPEN']}
    (REPORTS/'v4_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    manifest={}
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
        if p.name in ('MANIFEST_SHA256_v4.json','MANIFEST_SHA256_v3.json','MANIFEST_SHA256.json'):
            continue
        rel=p.relative_to(ROOT).as_posix()
        manifest[rel]=sha(p)
    (ROOT/'MANIFEST_SHA256_v4.json').write_text(json.dumps(manifest,indent=2))
    print(f'V4: {int(m.group(1))} tests OK, {sum(r["trained_rows"] for r in reports)} actual trained arm-seed-task rows')
    print('CERTIFIED restricted scalar FPT:',len(certs),'certified derivative cases:',len(gradients),'rational QVI policies:',qvi['enumerated_policies'])
    for r in reports: print(r['task'],round(r['ordinary_accuracy_mean'],5),round(r['full_mechanism_accuracy_mean'],5),
                            round(r['paired_delta_mean'],5),'ratio',round(r['full_vs_ordinary_wallclock_training_ratio'],3))
    print('Original Hepta six production gates: all OPEN / DENY_ALL')


if __name__=='__main__':main()
