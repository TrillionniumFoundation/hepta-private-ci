#!/usr/bin/env python3
"""Exploratory TRAIN-only class reweighting on original P0 frozen features.

This is not an E1 preregistered Head arm. It uses CAL for temperature tuning,
never reads BLIND labels, and cannot be used to select an Encoder or Cell.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import math

import numpy as np
import torch
from safetensors.numpy import load as safetensors_load

from actual_feature_head_shadow_v1 import (
    MODELS, SOURCE_GITHUB_RUN, SOURCE_HEAD, Invalid, canonical, execute,
    load_existing_probe, parse_source, sha, source_indices, verify_archive, zip_read,
)

TEMPERATURES=(.5,.75,1.,1.5,2.,3.)
SCHEMA='hepta.p0.actual-4145-head-train-only-balanced-exploratory.v1'


def train_only_pos_weight(labels: list[int]) -> float:
    if type(labels) is not list or len(labels)<24 or any(type(x) is not int or x not in (0,1) for x in labels):
        raise Invalid('unqualified training label inventory')
    pos=sum(labels)
    if not 0<pos<len(labels):raise Invalid('training lacks both classes')
    return (len(labels)-pos)/pos


def run_balanced(root: Path, original_shadow_receipt: dict) -> dict:
    # Complete 348-prediction ORIGINAL two-model NumPy audit must run first.
    # The input report is only an optional link, not a substitute for source.
    original=execute(root)
    if (original['authority']!='DENY_ALL' or original['original_human_held_labels_accessed'] or
            original['complete_original_four_stem_gate_satisfied']):
        raise Invalid('original partial study falsely granted authority')
    if original_shadow_receipt.get('schema')!=original['schema'] or original_shadow_receipt.get('source_fit_outer_zip_sha256')!=original['source_fit_outer_zip_sha256']:
        raise Invalid('inconsistent original source identity')
    e1=load_existing_probe(root)
    fit=parse_source(zip_read(verify_archive(root,'p0_multirc_fit_38868208650.zip'),'fit.json'))
    blind=parse_source(zip_read(verify_archive(root,'p0_multirc_blind_38868208650.zip'),'blind.json'))
    train,cal,held,_=source_indices(fit,blind)
    labels=[fit['cases'][i]['label'] for i in train]
    cal_y=torch.tensor([fit['cases'][i]['label'] for i in cal],dtype=torch.float32)
    pos_weight=train_only_pos_weight(labels)
    ty=torch.tensor(labels,dtype=torch.float32)
    prev_threads=torch.get_num_threads();torch.set_num_threads(1)
    outputs={}
    try:
        for model,(filename,width) in MODELS.items():
            p=verify_archive(root,filename)
            feature_raw=zip_read(p,model+'.replay/features.safetensors')
            features=safetensors_load(feature_raw)['features_q24_fp32']
            if features.shape!=(362,width) or features.dtype!=np.float32:
                raise Invalid('unsafe original Head input')
            rng=np.random.Generator(np.random.PCG64(20261015))
            projection=(rng.standard_normal((width,128))/math.sqrt(128)).astype(np.float32)
            proj=torch.from_numpy(features)@torch.from_numpy(projection)
            observations=[]
            for seed in e1.SEEDS:
                with torch.random.fork_rng(devices=[]):
                    torch.manual_seed(seed)
                    initial=e1.MatchedHead('gated')
                for kind in ('additive','gated'):
                    module=copy.deepcopy(initial);module.kind=kind
                    if sum(p.numel() for p in module.parameters())!=4145:
                        raise Invalid('changed equal Head budget')
                    opt=torch.optim.SGD(module.parameters(),lr=e1.LR)
                    for _ in range(e1.STEPS):
                        opt.zero_grad(set_to_none=True)
                        loss=torch.nn.functional.binary_cross_entropy_with_logits(
                            module(proj[train]),ty,pos_weight=torch.tensor(pos_weight))
                        if not torch.isfinite(loss):raise Invalid('nonfinite class-weighted loss')
                        loss.backward();opt.step()
                    with torch.inference_mode():
                        logits=module(proj[cal]);
                        losses=[float(torch.nn.functional.binary_cross_entropy_with_logits(logits/t,cal_y)) for t in TEMPERATURES]
                        tau=TEMPERATURES[min(range(len(losses)),key=losses.__getitem__)]
                        probability=torch.sigmoid(logits/tau)
                        acc=float(((probability>=.5)==cal_y.bool()).float().mean())
                        brier=float(((probability-cal_y)**2).mean())
                        pcount=int((probability>=.5).sum())
                        full_sha=e1.state_digest(module.state_dict())
                    observations.append({'seed':seed,'arm':'train_only_balanced_'+kind,
                                         'parameter_count':4145,'optimizer_steps':40,
                                         'train_only_positive_class_weight':pos_weight,
                                         'calibration_temperature_optimistically_selected':tau,
                                         'calibration_predicted_positive_count':pcount,
                                         'calibration_actual_positive_count':16,
                                         'calibration_accuracy_not_independent_test':acc,
                                         'calibration_brier_not_independent_test':brier,
                                         'trained_head_state_sha256':full_sha})
            outputs[model]={'model_revision':original['models'][model]['original_model_revision'],
                            'original_real_feature_safetensors_sha256':sha(feature_raw),
                            'new_foundation_encoder_forwards':0,
                            'original_train_positive_count':sum(labels),
                            'original_train_negative_count':len(labels)-sum(labels),
                            'only_train_labels_in_gradient':True,
                            'arms':observations}
    finally:
        torch.set_num_threads(prev_threads)
    return {'schema':SCHEMA,'source_github_run_id':SOURCE_GITHUB_RUN,
            'source_commit_sha':SOURCE_HEAD,
            'source_shadow_schema':original['schema'],
            'data_used_for_class_weight_selection':'original TRAIN labels only',
            'calibration_labels_used_for_temperature_selection':True,
            'calibration_metrics_not_independent_future_test':True,
            'experimental_head_training_loss_changed_not_same_as_frozen_E1_protocol':True,
            'original_four_model_admission_passed':False,
            'original_human_held_labels_accessed':False,
            'new_original_encoder_weights_downloaded':False,
            'production_promotion_permitted':False,'model_selected':False,
            'authority':'DENY_ALL','models':outputs}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path,required=True)
    cli.add_argument('--shadow-receipt',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    if args.output.is_symlink() or args.output.exists():raise FileExistsError('source evidence create-only')
    original=json.loads(args.shadow_receipt.read_text())
    evidence=run_balanced(args.root,original)
    raw=canonical(evidence)+b'\n'
    if len(raw)>100000:raise Invalid('unbounded research evidence size')
    with args.output.open('xb') as f:f.write(raw)
    print(json.dumps({'schema':SCHEMA,'model_count':len(evidence['models']),
                      'original_held_labels_opened':False,
                      'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
