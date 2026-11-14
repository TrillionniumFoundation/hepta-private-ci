"""R11: frozen R10 incumbent validation, no fitting, no selection, no gate rewrite."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import zipfile
import numpy as np
import torch
from scipy.stats import qmc

from certify import (ROOT, SCALE, WidePolicy, make_problem, global_majorants,
                     one_dimensional_rule, transport_certificate,
                     certified_midpoint_radius, manufactured_polynomial)

sys.path.insert(0,str(ROOT/'continuous'))
from domain import evaluate, rule

torch.set_num_threads(1)
REPO='TrillionniumFoundation/hepta-private-ci'
R10_SHA='f8cb099a79fa2bd7e3b40ad49113cf7c8b6185e3'
R10_ZIP_SHA='98d6e9b2cf2ba6f6c651d6a86bb42ebafd04631f811bd109ed00044607e9c04c'
R11_PROTOCOL_SHA='9a2f0091d56faa38071f899f074092c72b9d2671'
TARGET=.04850
QMC_SEEDS=list(range(2026101611,2026101619))


def digest(data):return hashlib.sha256(data).hexdigest()


def write_new(path,obj):
    b=(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:f.write(b)
    return digest(b)


def independent_rules():
    laws={}
    for n in (7,11):
        x,w=one_dimensional_rule(f'gl{n}')
        states=np.stack(np.meshgrid(*([x]*4),indexing='ij'),-1).reshape(-1,4)*SCALE
        weights=np.prod(np.stack(np.meshgrid(*([w]*4),indexing='ij'),-1),-1).reshape(-1)
        assert weights.min()>0 and np.isclose(weights.sum(),1.,atol=2e-14)
        laws[f'gl{n}']=(states,weights/weights.sum())
    for i,seed in enumerate(QMC_SEEDS):
        states=(2*qmc.Sobol(4,scramble=True,seed=seed).random_base2(10)-1)*SCALE
        laws[f'qmc_new_{i}']=(states,np.full(len(states),1/len(states)))
    return laws


def verify_R10_archive(packet:Path,archive:Path):
    expected_archive=digest(archive.read_bytes())
    if expected_archive!=R10_ZIP_SHA:
        raise ValueError('R10 archive sha changed')
    manifest=json.loads((packet/'MANIFEST_SHA256.json').read_text())
    if manifest['content_members']!=1328 or len(manifest['files'])!=1328:
        raise ValueError('R10 manifest count changed')
    with zipfile.ZipFile(archive) as z:
        for item in manifest['files']:
            rel=item['path']
            content=z.read(rel)
            if len(content)!=item['bytes'] or digest(content)!=item['sha256']:
                raise ValueError(f'R10 archived content mutated: {rel}')
            unpacked=packet/rel
            if not unpacked.is_file() or digest(unpacked.read_bytes())!=item['sha256']:
                raise ValueError(f'R10 unpacked content mutated: {rel}')
    return dict(zip_sha256=expected_archive,verified_members=1328,
                manifest_sha256=digest((packet/'MANIFEST_SHA256.json').read_bytes()))


def evaluate_at(pol,theta,problem,states,weights):
    v=evaluate(pol,torch.tensor(theta,dtype=torch.float64),problem,states,chunk=256)
    if not np.isfinite(v).all():
        raise FloatingPointError('nonfinite frozen output')
    return float(weights@v.mean(1))


def numerical_derivative_probe(pol,theta,s):
    # Finite-difference regression check; NEVER shrinks the global majorant.
    base=np.asarray(s,dtype=float).copy(); p=make_problem()
    probes=[]
    for j in range(4):
        h=1e-5*SCALE[j]
        plus,minus=base.copy(),base.copy();plus[j]+=h;minus[j]-=h
        # Both points stay within the compact support for the chosen probe.
        vp=evaluate_at(pol,theta,p,plus[None,:],np.ones(1))
        vm=evaluate_at(pol,theta,p,minus[None,:],np.ones(1))
        probes.append((vp-vm)/(2*h))
    return probes


def manufactured_controls():
    output={}
    for name in ('constant','affine','quadratic','degree8'):
        expected=.0484
        entry=dict(exact_mean=expected)
        for n in ('cc5','cc9','cc17'):
            s,w=rule(n)
            entry[n]=float(w@manufactured_polynomial(name,s))
        for n in ('gl5','gl7','gl9','gl11'):
            x,w=one_dimensional_rule(n)
            s=np.stack(np.meshgrid(*([x]*4),indexing='ij'),-1).reshape(-1,4)*SCALE
            ww=np.prod(np.stack(np.meshgrid(*([w]*4),indexing='ij'),-1),-1).reshape(-1)
            entry[n]=float(ww@manufactured_polynomial(name,s))
        entry['legacy_pass']=(max(entry['cc5'],entry['cc9'])<=TARGET and
                              abs(entry['cc5']-entry['cc9'])<=1e-6)
        output[name]=entry
    if abs(output['degree8']['cc9']-output['degree8']['exact_mean'])>5e-14:
        raise AssertionError('polynomial exact reference is wrong')
    if output['degree8']['legacy_pass']:
        raise AssertionError('expected exact-polynomial coarse-rule counterexample')
    return output


def execute(packet:Path,archive:Path,out:Path):
    begun=time.perf_counter(),time.process_time()
    out.mkdir(parents=True,exist_ok=False)
    sourcehash={p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}
    plan=dict(schema='hepta.ndu.population-certificates.r11',r10_commit=R10_SHA,
              r10_archive_sha256=R10_ZIP_SHA,protocol_commit=R11_PROTOCOL_SHA,
              independent_rules=['gl7','gl11'],qmc_seeds=QMC_SEEDS,
              source_sha256=sourcehash,selection='all96 frozen R10 finals; zero refitting',
              real_arithmetic_error_bound='sum_j L_j W1(Unif_j,discrete_rule_j)',
              machine_certification='not attempted: FP neural-evaluation rounding not interval verified',
              terminal_threshold=TARGET)
    ph=write_new(out/'PLAN.json',plan)
    audit_start=time.process_time()
    receipt=verify_R10_archive(packet,archive)
    write_new(out/'INPUT_AUDIT.json',receipt)
    receipt['input_audit_cpu_seconds']=time.process_time()-audit_start
    cases_root=packet/'execution'/'runs'
    complete=json.loads((cases_root/'COMPLETE.json').read_text())
    if complete['completed']!=96 or complete['failed']!=0 or len(complete['census'])!=96:
        raise ValueError('R10 census inconsistent')
    from pathlib import Path as _Path
    source_root=packet/'source'/'native_stem_abcd'
    sys.path.insert(0,str(source_root/'refinement'))
    import importlib.util
    origin=source_root/'refinement'/'run.py'
    spec=importlib.util.spec_from_file_location('r10_refinement_run_frozen',origin)
    old_run=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(origin.parent))
    spec.loader.exec_module(old_run)
    if [e['name'] for e in complete['census']] != [old_run.name_for(q) for q in old_run.specs()]:
        raise ValueError('R10 case enumeration drift')
    laws=independent_rules()
    write_new(out/'MANUFACTURED.json',manufactured_controls())
    model=make_problem()
    rows=[]
    for i,entry in enumerate(complete['census']):
        key=entry['name'];path=cases_root/key
        report_raw=(path/'REPORT.json').read_bytes()
        if digest(report_raw)!=entry['report_sha256']:
            raise ValueError(f'R10 report altered: {key}')
        report=json.loads(report_raw)
        if report['case']!=entry['case'] or report['parameters']!=50+7*entry['case']['width']:
            raise ValueError(f'R10 parameter identity failed: {key}')
        with np.load(path/'WEIGHTS.npz',allow_pickle=False) as z:
            theta=z['theta'].copy()
        if digest(theta.astype('<f8',copy=False).tobytes())!=report['weights_sha256']:
            raise ValueError(f'R10 weight changed: {key}')
        old=report['costs']
        historical=(max(old['cc5'],old['cc9'])<=TARGET and abs(old['cc9']-old['cc5'])<=1e-6)
        if historical!=report['fit']['final_qualification']:
            raise ValueError('R10 historical gate changed')
        policy=WidePolicy(entry['case']['width'],entry['case']['seed'])
        deriv_start=time.process_time()
        majorant=global_majorants(theta,entry['case']['width'])
        radii={name:transport_certificate(majorant,name) for name in ('cc5','gl5','cc9','gl9','cc17','gl7','gl11')}
        midpoint16=certified_midpoint_radius(majorant,16)
        derivative_cpu=time.process_time()-deriv_start
        eval_start=time.process_time()
        independent={name:evaluate_at(policy,theta,model,*laws[name]) for name in laws}
        evaluation_cpu=time.process_time()-eval_start
        gl11=independent['gl11'];gl7=independent['gl7']
        qmc_values=[independent[f'qmc_new_{k}'] for k in range(8)]
        # This is explicitly an ideal-real bound with an unquantified floating-oracle error.
        ideal_lo=gl11-radii['gl11']['radius_upper']
        ideal_hi=gl11+radii['gl11']['radius_upper']
        ideal_label=('enclosed_below' if ideal_hi<=TARGET else
                     'enclosed_above' if ideal_lo>TARGET else 'inconclusive')
        if i in (0,5,24,35,48,56,72,95):
            numeric_grad=numerical_derivative_probe(policy,theta,[0.02,-0.03,0.11,-0.16])
            if any(abs(g)>L*1.000001 for g,L in zip(numeric_grad,majorant['first'])):
                raise AssertionError('sampled derivative exceeds majorant')
        else:numeric_grad=None
        case_output=dict(schema='hepta.ndu.population-certificates.case.r11',name=key,
                         r10_weight_sha256=report['weights_sha256'],
                         r10_report_sha256=entry['report_sha256'],
                         parameters=len(theta),case=entry['case'],legacy_pass=historical,
                         frozen_cc5=old['cc5'],frozen_cc9=old['cc9'],frozen_cc17=old['cc17'],
                         frozen_gl9=old['gl9'],
                         new_evaluations=independent,
                         qmc_mean=float(np.mean(qmc_values)),
                         qmc_sd=float(np.std(qmc_values,ddof=1)),
                         gl11_minus_cc17=gl11-old['cc17'],
                         gl11_minus_gl9=gl11-old['gl9'],
                         gl11_minus_gl7=gl11-gl7,
                         global_majorant=majorant,quad_radii=radii,
                         midpoint16_bound=midpoint16,
                         ideal_real_gl11_interval=[ideal_lo,ideal_hi],
                         ideal_real_status=ideal_label,
                         machine_certified=False,
                         numerical_gradient_probe=numeric_grad,
                         derivative_cpu=derivative_cpu,evaluation_cpu=evaluation_cpu)
        write_new(out/(key+'.json'),case_output)
        rows.append(dict(name=key,**entry['case'],params=len(theta),legacy=historical,
                         cc17=old['cc17'],cc5=old['cc5'],cc9=old['cc9'],
                         gl7=gl7,gl11=gl11,gl9=old['gl9'],qmc_mean=case_output['qmc_mean'],
                         qmc_sd=case_output['qmc_sd'],
                         gl11_cc17=case_output['gl11_minus_cc17'],
                         gl11_gl9=case_output['gl11_minus_gl9'],
                         w1_gl11_bound=radii['gl11']['radius_upper'],
                         analytic_midpoint_n16=midpoint16,
                         ideal_real_status=ideal_label,machine_certified=False,
                         derivative_cpu=derivative_cpu,evaluation_cpu=evaluation_cpu))
        if (i+1)%12==0:
            print(f'R11 independently validated {i+1}/96 frozen models',flush=True)
    with open(out/'SCORES.csv','x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    low=sum(x['cc17']<=TARGET for x in rows)
    oldpass=sum(x['legacy'] for x in rows)
    idealpass=sum(x['ideal_real_status']=='enclosed_below' for x in rows)
    radius=[x['w1_gl11_bound'] for x in rows]
    deltas=[abs(x['gl11_cc17']) for x in rows]
    result=dict(schema='hepta.ndu.population-certificates.complete.r11',
                run_count=len(rows),r10_candidates_unmodified=True,
                low_cc17=low,legacy_pass=oldpass,
                enclosed_below_in_ideal_real_arithmetic=idealpass,
                ideal_real_inconclusive=sum(x['ideal_real_status']=='inconclusive' for x in rows),
                machine_certified=0,
                w1_gl11_bound_range=[min(radius),max(radius)],
                max_abs_gl11_cc17=max(deltas),
                mean_abs_gl11_cc17=float(np.mean(deltas)),
                max_abs_gl11_gl9=max(abs(x['gl11_gl9']) for x in rows),
                qmc_mean_sd=float(np.mean([x['qmc_sd'] for x in rows])),
                bound_honesty='ideal-real global majorants conservative; no roundoff interval certificate',
                input_sha256=receipt['zip_sha256'],
                total_wall=time.perf_counter()-begun[0],
                total_cpu=time.process_time()-begun[1],
                input_audit_cpu=receipt['input_audit_cpu_seconds'],
                evaluations_cpu=sum(x['evaluation_cpu'] for x in rows),
                bound_cpu=sum(x['derivative_cpu'] for x in rows),
                process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                not_model_training=True,production_authorized=False)
    if len(rows)!=96 or oldpass!=35 or low!=68:
        raise AssertionError('R10 frozen census or historical results have changed')
    if plan['source_sha256']!={p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}:
        raise ValueError('R11 source mutation during evaluation')
    write_new(out/'COMPLETE.json',result)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--packet',type=Path,required=True)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    execute(args.packet,args.archive,args.out)
