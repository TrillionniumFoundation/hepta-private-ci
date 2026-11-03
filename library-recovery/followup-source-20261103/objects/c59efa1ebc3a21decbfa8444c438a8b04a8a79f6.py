#!/usr/bin/env python3
"""Research only: exact rational proof stress from 20 physical *synthetic* weight files.

This script never runs Rust, never reads production A0 and never approves NDU.
"""
from __future__ import annotations
import json, random, hashlib
from fractions import Fraction
from pathlib import Path
import sys
from safetensors.torch import load_file
from candidate_inventory import verify_artifact
from head_q24_oracle import Q, q24_from_f32, q24_head, independent_same_activation_head_margin
ROOT=Path('/mnt/data/neuron_five_arm_next/fixture-trained2')
OUT=Path('/mnt/data/hepta_pr1884_exact_rational_margin_qualification.json')
rnd=random.Random(20261014)
receipt=json.loads((ROOT/'training-receipt.json').read_bytes())
H=8*Q
stats={'tested':0,'targeted':0,'random':0,'wrong_accepted_signs':0,'violated_uniform_bound':0,
       'raw_head_sign_differences_before_abstention':0,'abstain':0,'accepted_pos':0,
       'accepted_neg':0,'models_checked':0,'maximum_normalized_gap_to_bound':0.0}
per_model=[]
for m in receipt['models']:
    path=ROOT / m['weight_file']
    inv=verify_artifact(path,m['weight_sha256'],arm=m['arm'],width=m['width'],
                       rank=m['rank'],expected_count=m['parameter_count'])
    tensors=load_file(str(path),device='cpu')
    w=[float(x) for x in tensors['head.weight'].reshape(-1).tolist()]
    b=float(tensors['head.bias'].item())
    qw=[q24_from_f32(v) for v in w];qb=q24_from_f32(b)
    n=len(w)
    exact_weights=[Fraction(x) for x in w]; exact_bias=Fraction(b)
    bound=Fraction(9*n+1,2*Q)
    test=[]
    # Deliberately solve for feature values near the ideal exact sign boundary.
    for j in range(n):
        if abs(w[j])<=1e-13: continue
        target=round(-b/w[j]*Q)
        if not -H<=target<=H:continue
        for delta in (-60,-16,-8,-4,-3,-2,-1,0,1,2,3,4,8,16,60):
            val=target+delta
            if -H<=val<=H:
                a=[0]*n;a[j]=val;test.append(('targeted',a))
    for _ in range(400):
        j,k=rnd.sample(range(n),2)
        if abs(w[k])<=1e-13:continue
        x=rnd.randint(-H,H)
        target=round((-b-w[j]*(x/Q))/w[k]*Q)
        delta=rnd.choice([-16,-8,-4,-2,-1,0,1,2,4,8,16])
        if -H<=target+delta<=H:
            a=[0]*n;a[j]=x;a[k]=target+delta;test.append(('targeted',a))
    for _ in range(128):
        a=[rnd.randint(-H,H) for _ in range(n)]
        test.append(('random',a))
    local={'arm':m['arm'],'tier_cap':m['cap'],'private_weight_sha256':m['weight_sha256'],
           'tested':0,'accepted':0,'abstained':0,'wrong_accepted':0,'bound_failures':0}
    for typ,a in test:
        qlogit=q24_head(qw,qb,a)
        qreal=Fraction(qlogit,Q)
        real=exact_bias+sum((wi*Fraction(ai,Q) for wi,ai in zip(exact_weights,a) if ai),Fraction())
        gap=abs(real-qreal)
        stats['tested']+=1;stats[typ]+=1;local['tested']+=1
        if gap>bound:
            stats['violated_uniform_bound']+=1;local['bound_failures']+=1
        stats['maximum_normalized_gap_to_bound']=max(stats['maximum_normalized_gap_to_bound'],float(gap/bound))
        status,twice=independent_same_activation_head_margin(qlogit,a)
        if (qlogit>0 and real<=0) or (qlogit<0 and real>=0) or (qlogit==0 and real!=0):
            stats['raw_head_sign_differences_before_abstention']+=1
        if status=='QUANTIZATION_AMBIGUOUS_ABSTAIN':
            stats['abstain']+=1;local['abstained']+=1
        else:
            stats['accepted_pos' if qlogit>0 else 'accepted_neg']+=1
            local['accepted']+=1
            if (qlogit>0 and real<=0) or (qlogit<0 and real>=0):
                stats['wrong_accepted_signs']+=1;local['wrong_accepted']+=1
    stats['models_checked']+=1
    per_model.append(local)
assert stats['models_checked']==20 and stats['violated_uniform_bound']==0 and stats['wrong_accepted_signs']==0
output={'schema':'hepta.neuron.exact-rational-research-q24-head-sign-margin.v1',
        'scope':'20 physically serialized synthetic research candidates, NOT selected Owner models',
        'frozen_weight_receipt_sha256':hashlib.sha256((ROOT/'training-receipt.json').read_bytes()).hexdigest(),
        'exact_original_F32_head_comparison':'Fraction.from_float (exact source binary F32 values)',
        'same_q24_activation_only':True,'rust_native_executed':False,'no_f32_kernel_bitwise_claim':True,
        'strict_uniform_margin_formula_twice_lsb':'9*width+1',
        'stats':stats,'per_model':per_model,
        'decision':'NO_PROMOTION','ndu_eligible':False,'production_qualification':False}
OUT.write_text(json.dumps(output,sort_keys=True,indent=2)+'\n')
print(json.dumps({'output':str(OUT),'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'stats':stats},indent=2))
