#!/usr/bin/env python3
"""Physical, synthetic-only F32 Head -> Q24 integer quantization experiment.

Never infers Hepta selected model, native Rust execution, calibration, NDU or
production admission. Loads saved *earlier* synthetic weights in the working
container and holds frozen activation rows equal across every model arm.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import time

import torch
import safetensors
from safetensors.torch import load_file

sys.path.insert(0, '/mnt/data/neuron_five_arm_next')
from candidate_inventory import verify_artifact
from head_q24_oracle import Q, q24_from_f32, q24_head

ROOT = Path('/mnt/data/neuron_five_arm_next/fixture-trained2')
RECEIPT_PATH = ROOT/'training-receipt.json'
DEST = Path('/mnt/data/hepta_pr1884_quantized_head_physical_study.json')
H = 8 * Q
SEED = 1884_20261014


def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def example_activations(width:int):
    prng=random.Random(SEED)
    rows=[([0]*width,'zero'),([Q]*width,'one'),([H]*width,'positive_8'),([-H]*width,'negative_8'),
          ([H if i%2==0 else -H for i in range(width)],'alternating_extremes')]
    for i in range(1024):
        count=prng.randrange(1, max(2,width//4+1))
        active=prng.sample(range(width),count)
        a=[0]*width
        for pos in active:
            a[pos]=prng.randrange(-H,H+1)
        rows.append((a,'sparse_stress'))
    for i in range(256):
        rows.append(([prng.randrange(-H,H+1) for _ in range(width)],'dense_stress'))
    return rows


def main():
    started=time.monotonic()
    frozen_receipt=json.loads(RECEIPT_PATH.read_bytes())
    assert len(frozen_receipt['models'])==20
    assert frozen_receipt.get('production_qualification') is False
    assert frozen_receipt.get('ndu_eligible') is False
    assert frozen_receipt.get('native_q24_parity_verified') is False
    all_model_info=[]
    unique_widths=sorted(set(m['width'] for m in frozen_receipt['models']))
    frozen_rows={w:example_activations(w) for w in unique_widths}
    for entry in frozen_receipt['models']:
        path=ROOT/entry['weight_file']
        verified=verify_artifact(path, entry['weight_sha256'], arm=entry['arm'],width=entry['width'],
                                 rank=entry['rank'], expected_count=entry['parameter_count'])
        saved=load_file(str(path),device='cpu')
        w=[float(v) for v in saved['head.weight'].view(-1).tolist()]
        b=float(saved['head.bias'].view(-1)[0].item())
        quant_w=[q24_from_f32(v) for v in w]
        quant_b=q24_from_f32(b)
        max_abs=0.
        max_bound=0.
        max_prob_bound=0.
        max_observed_prob=0.
        margin_flips=0
        case_count=0
        per_kind={}
        for row,kind in frozen_rows[entry['width']]:
            float_logit=math.fsum([b]+[w_i*(a_i/Q) for w_i,a_i in zip(w,row)])
            quant_logit=q24_head(quant_w,quant_b,row)/Q
            error=abs(float_logit-quant_logit)
            bound=abs(b-quant_b/Q)+math.fsum(abs(w_i-q_i/Q)*abs(a_i)/Q
                                               for w_i,q_i,a_i in zip(w,quant_w,row)) \
                     +sum(x!=0 for x in row)*(.5/Q)+2e-14
            assert math.isfinite(float_logit) and math.isfinite(quant_logit)
            if error>bound+1e-12:
                raise AssertionError(f'Q24 bound violation {entry["weight_file"]}: {error}, {bound}')
            # sigmoid is globally 1/4-Lipschitz; avoid rounding or calibration claims
            # (the original Hepta state/activation computation has NOT been run).
            if (float_logit>=0)!=(quant_logit>=0):
                margin_flips+=1
            max_abs=max(max_abs,error)
            max_bound=max(max_bound,bound)
            max_prob_bound=max(max_prob_bound,bound/4)
            p=lambda x:1/(1+math.exp(-x)) if x>=0 else math.exp(x)/(1+math.exp(x))
            max_observed_prob=max(max_observed_prob,abs(p(float_logit)-p(quant_logit)))
            case_count+=1
            pstats=per_kind.setdefault(kind,{'count':0,'max_abs_logit_gap':0.})
            pstats['count']+=1
            pstats['max_abs_logit_gap']=max(pstats['max_abs_logit_gap'],error)
        all_model_info.append({
            'arm':entry['arm'],'budget_ceiling':entry['cap'],'model_sha256':sha(path),
            'width':entry['width'],'rank':entry['rank'],'private_parameter_count':entry['parameter_count'],
            'weight_bytes':verified['physical_model_bytes'],
            'actual_physical_tensor_inventory_verified':True,
            'real_f32_head_weights_reloaded':True,
            'tested_frozen_activation_count':case_count,
            'max_abs_linear_head_logit_gap':max_abs,
            'max_conservative_per_sample_gap_bound':max_bound,
            'max_abs_sigmoid_proba_gap':max_observed_prob,
            'upper_bound_sigmoid_gap_from_lipschitz':max_prob_bound,
            'threshold_sign_disagreements_unlabelled':margin_flips,
            'by_input_class':per_kind,
        })
    result={
        'schema':'hepta.neuron.physical-f32-to-q24-head-quantization-research.v1',
        'study_evidence_class':'OLDER_UNSELECTED_SYNTHETIC_PHYSICAL_WEIGHTS_ONLY',
        'description':'Frozen saved F32 Head vs Python exact-integer Q24 Head on shared synthetic Q24 activations',
        'source_receipt_sha256':sha(RECEIPT_PATH),
        'repro_script':'hepta_pr1884_head_quantization_probe.py',
        'activation_prng':'python.Random','activation_seed':SEED,
        'process':{'python':platform.python_version(),'torch':torch.__version__,
                   'safetensors':safetensors.__version__,'machine':platform.machine(),
                   'cpu_wall_elapsed_seconds':round(time.monotonic()-started,5),
                   'target_hepta_machine_attested':False},
        'model_count':len(all_model_info),
        'total_frozen_sample_model_pairs':sum(x['tested_frozen_activation_count'] for x in all_model_info),
        'all_physical_candidate_artifacts_checked':True,
        'max_abs_logit_gap_across_all_models':max(x['max_abs_linear_head_logit_gap'] for x in all_model_info),
        'max_abs_sigmoid_gap_across_all_models':max(x['max_abs_sigmoid_proba_gap'] for x in all_model_info),
        'max_quantization_theoretical_per_sample_logit_bound':max(x['max_conservative_per_sample_gap_bound'] for x in all_model_info),
        'total_unlabelled_head_threshold_sign_disagreements':sum(x['threshold_sign_disagreements_unlabelled'] for x in all_model_info),
        'model_rows':all_model_info,
        'disclaimers':{
            'these_are_selected_v1_or_active_cell_weights':False,
            'rust_native_temporal_executed':False,
            'rust_native_head_executed':False,
            'trained_head_reproduces_full_cell_policy':False,
            'actual_future_labels_or_quality_measured':False,
            'a0_owner_identity_independently_attested':False,
            'complete_a4_resource_profile_available':False,
            'causal_ndu_benefit_demonstrated':False,
            'ndu_eligible':False,
            'production_qualification':False,
            'decision':'NO_PROMOTION',
        }
    }
    DEST.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('model_count','total_frozen_sample_model_pairs','max_abs_logit_gap_across_all_models','max_abs_sigmoid_gap_across_all_models','max_quantization_theoretical_per_sample_logit_bound','total_unlabelled_head_threshold_sign_disagreements')},indent=2))
    print('report_sha256',sha(DEST))

if __name__=='__main__':
    main()
