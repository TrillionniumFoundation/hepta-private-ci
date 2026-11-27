"""R11 post-seal independent replay of ALL frozen weights and new rule calculations."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from certify import global_majorants,transport_certificate,certified_midpoint_radius,manufactured_polynomial
from run import (R10_SHA,R10_ZIP_SHA,R11_PROTOCOL_SHA,QMC_SEEDS,ROOT,TARGET,
                 verify_R10_archive,independent_rules,digest,evaluate_at,manufactured_controls,
                 WidePolicy,make_problem,write_new)

torch.set_num_threads(1)


def insist(predicate,msg):
    if not predicate:raise ValueError(msg)


def close(a,b,atol=1e-12,rtol=1e-11):
    return bool(np.isfinite([a,b]).all() and np.isclose(a,b,atol=atol,rtol=rtol))


def verify(packet:Path,archive:Path,runroot:Path,out:Path):
    wall,cpu=time.perf_counter(),time.process_time()
    out.mkdir(parents=True,exist_ok=False)
    plan=json.loads((runroot/'PLAN.json').read_text())
    complete=json.loads((runroot/'COMPLETE.json').read_text())
    insist(plan['schema']=='hepta.ndu.population-certificates.r11' and plan['r10_commit']==R10_SHA,'plan ref changed')
    insist(plan['r10_archive_sha256']==R10_ZIP_SHA and plan['protocol_commit']==R11_PROTOCOL_SHA,'plan base changed')
    insist(plan['qmc_seeds']==QMC_SEEDS and plan['independent_rules']==['gl7','gl11'],'evaluation plan changed')
    insist(complete['run_count']==96 and complete['r10_candidates_unmodified'],'incomplete run census')
    insist(complete['legacy_pass']==35 and complete['low_cc17']==68,
           'historical gate count changed')
    insist(not complete['production_authorized'] and complete['machine_certified']==0,'false certification')
    receipt=verify_R10_archive(packet,archive)
    src=Path(__file__).resolve().parent
    for name,expected in plan['source_sha256'].items():
        file=src/name
        insist(file.is_file() and digest(file.read_bytes())==expected,'source drift: '+name)
    original=json.loads((packet/'execution'/'runs'/'COMPLETE.json').read_text())
    insist(len(original['census'])==96 and original['completed']==96 and original['failed']==0,'old R10 census changed')
    # Input reference order is itself bound to frozen R10 plan.
    import importlib.util
    location=packet/'source'/'native_stem_abcd'/'refinement'/'run.py'
    spec=importlib.util.spec_from_file_location('r10_run_independent',location)
    frozen=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(location.parent));spec.loader.exec_module(frozen)
    insist([row['name'] for row in original['census']]==[frozen.name_for(s) for s in frozen.specs()],
           'changed input ordering')
    from run import manufactured_controls
    raw_poly=json.loads((runroot/'MANUFACTURED.json').read_text())
    expected_poly=manufactured_controls()
    for name in expected_poly:
        for key in expected_poly[name]:
            x,y=raw_poly[name][key],expected_poly[name][key]
            insist((x==y if isinstance(y,bool) else close(float(x),float(y),atol=1e-14)),
                   'manufactured polynomial mismatch')
    laws=independent_rules();p=make_problem();rows=[]
    details=[];full_max=0.;all_radii=[]
    for n,entry in enumerate(original['census']):
        path=runroot/(entry['name']+'.json')
        insist(path.is_file(),'missing frozen-candidate result: '+entry['name'])
        result=json.loads(path.read_text())
        prior_path=packet/'execution'/'runs'/entry['name']
        prior_bytes=(prior_path/'REPORT.json').read_bytes()
        insist(digest(prior_bytes)==entry['report_sha256'],'old R10 report tampered')
        prior=json.loads(prior_bytes)
        with np.load(prior_path/'WEIGHTS.npz',allow_pickle=False) as stored:
            theta=stored['theta'].copy()
        whash=digest(theta.astype('<f8',copy=False).tobytes())
        insist(result['name']==entry['name'] and result['case']==entry['case'],'case identity mismatch')
        insist(result['r10_report_sha256']==entry['report_sha256'],'old report binding mismatch')
        insist(result['r10_weight_sha256']==whash==prior['weights_sha256'],'weight binding mismatch')
        insist(result['parameters']==len(theta)==50+7*entry['case']['width'],'parameter mismatch')
        old=prior['costs']
        legacy=(max(old['cc5'],old['cc9'])<=TARGET and abs(old['cc9']-old['cc5'])<=1e-6)
        insist(legacy==result['legacy_pass']==prior['fit']['final_qualification'],'historical gate substituted')
        for label,key in [('frozen_cc5','cc5'),('frozen_cc9','cc9'),('frozen_cc17','cc17'),('frozen_gl9','gl9')]:
            insist(close(result[label],old[key],atol=1e-14),'frozen R10 cost changed')
        maj=global_majorants(theta,entry['case']['width'])
        for k in ('first','second'):
            insist(np.array_equal(result['global_majorant'][k],maj[k]),'majorant mismatch')
            insist(result['global_majorant'][k+'_decimal']==maj[k+'_decimal'],'decimal bound mismatch')
        for rn in ('cc5','gl5','cc9','gl9','cc17','gl7','gl11'):
            cert=transport_certificate(maj,rn)
            reported=result['quad_radii'][rn]
            insist(cert['radius_upper']==reported['radius_upper'],'W1 radius mismatch')
            insist(np.array_equal(cert['w1'],reported['w1']),'transport cost mismatch')
            insist(not reported['model_evaluation_roundoff_certified'],'false numerical certification')
        insist(close(result['midpoint16_bound'],certified_midpoint_radius(maj,16)),'midpoint radius changed')
        r_gl11=result['quad_radii']['gl11']['radius_upper']
        center=result['new_evaluations']['gl11']
        expected_label=('enclosed_below' if center+r_gl11<=TARGET else
                        'enclosed_above' if center-r_gl11>TARGET else 'inconclusive')
        insist(result['ideal_real_status']==expected_label,'false enclosure classification')
        insist(result['machine_certified'] is False,'false machine certification')
        policy=WidePolicy(entry['case']['width'],entry['case']['seed'])
        recomputed={name:evaluate_at(policy,theta,p,*laws[name]) for name in laws}
        for name,value in recomputed.items():
            insist(close(value,result['new_evaluations'][name],atol=1e-13,rtol=1e-12),
                   'independent numerical rule mismatch: '+name)
            full_max=max(full_max,abs(value-result['new_evaluations'][name]))
        vals=[recomputed[f'qmc_new_{i}'] for i in range(8)]
        insist(close(float(np.mean(vals)),result['qmc_mean']),'QMC mean mismatch')
        insist(close(float(np.std(vals,ddof=1)),result['qmc_sd']),'QMC SD mismatch')
        g11=recomputed['gl11'];r=result['quad_radii']['gl11']['radius_upper']
        insist(close(result['ideal_real_gl11_interval'][0],g11-r,atol=1e-8), 'lower enclosure changed')
        insist(close(result['ideal_real_gl11_interval'][1],g11+r,atol=1e-8), 'upper enclosure changed')
        all_radii.append(r)
        rows.append(dict(name=entry['name'],width=entry['case']['width'],legacy=legacy,
                         lower_cost_threshold=g11<=TARGET,gl11=g11,old_cc17=old['cc17'],
                         gl11_minus_old_cc17=g11-old['cc17'],radius=r,
                         bound_status=expected_label,machine_certified=False,
                         qmc_mean=np.mean(vals),qmc_sd=np.std(vals,ddof=1)))
        if (n+1)%24==0:print(f'Independent audit replayed {n+1}/96 frozen candidates',flush=True)
    insist(complete['low_cc17']==sum(row['old_cc17']<=TARGET for row in rows)==68,'historical low-cost count changed')
    insist(complete['legacy_pass']==sum(row['legacy'] for row in rows)==35,'historical gate count changed')
    insist(complete['ideal_real_inconclusive']==sum(row['bound_status']=='inconclusive' for row in rows),
           'certificate status count changed')
    insist(close(complete['max_abs_gl11_cc17'],max(abs(row['gl11_minus_old_cc17']) for row in rows)),'summary altered')
    with open(out/'AUDIT.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    receipt=dict(input_sha256=receipt['zip_sha256'],source_commit=R10_SHA,source_paths=len(plan['source_sha256']),
                 validated_candidates=len(rows),verified_poly=len(raw_poly),
                 max_numerical_replay_difference=full_max,old_legacy_pass=35,old_low_cc17=68,
                 real_arithmetic_inconclusive=96,machine_certified=0,
                 radius_range=[min(all_radii),max(all_radii)],
                 audit_cpu=time.process_time()-cpu,audit_wall=time.perf_counter()-wall,
                 not_model_training=True,production_authorized=False)
    write_new(out/'AUDIT.json',receipt)
    print(json.dumps(receipt,sort_keys=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--packet',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--runs',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    verify(args.packet,args.archive,args.runs,args.out)
