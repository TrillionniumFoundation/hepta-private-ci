#!/usr/bin/env python3
"""Optional local numerical crosscheck, NOT the publisher label rejudge.

Use the exact original E3 sealed predictions and eight archived arm aggregate
correctness/matched-pair counts to derive optimal joint feasibility bounds for
V24's fixed lazy-vision route. The variables are *invented feasible label
assignments* constrained by aggregates; they are NOT the original labels.
SciPy MILP is optional to the GitHub V25 source-only and publisher workflows.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import hashlib

import numpy as np
import scipy
from scipy.optimize import milp, LinearConstraint, Bounds

import v24_multimodal_causal_bounds as v24


def sharp_bounds(archive: Path) -> dict:
    pred,review,seals=v24.verify_archive(archive)
    v24.analyze(pred,review,seals)
    original=pred['predictions']
    n=len(original)
    assert n==64  # Only after full source/material validation
    arms={name:np.array([v24.top(tuple(row['arms'][name])) for row in original],dtype=np.int32)
          for name in sorted(v24.ARMS)}
    def correct_mask(name):
        return (arms[name][:,None] == np.arange(4)[None,:]).astype(np.int32)
    rows=[];rhs=[]
    for i in range(n):
        m=np.zeros((n,4),dtype=np.int32);m[i]=1
        rows.append(m.ravel());rhs.append(1)
    for name in sorted(v24.ARMS):
        rows.append(correct_mask(name).ravel());rhs.append(int(review['arms'][name]['correct']))
    for name in sorted(v24.PAIR_ARMS):
        cm=correct_mask(name);baseline=correct_mask('text_only')
        pair=review['paired_vs_text_only'][name]
        rows.append((cm*(1-baseline)).ravel());rhs.append(int(pair['rescued_errors_vs_text']))
        rows.append((baseline*(1-cm)).ravel());rhs.append(int(pair['new_errors_vs_text']))
    A=np.asarray(rows,dtype=np.float64);b=np.asarray(rhs,dtype=np.float64)
    assert A.shape==(84,256)
    use_image=[]
    for row in original:
        p=sorted(row['arms']['text_only'],reverse=True)
        use_image.append(p[0]-p[1]<v24.PRIMARY_THRESHOLD)
    lazy=np.where(np.asarray(use_image,dtype=bool),arms['bridge_image_only'],arms['text_only'])
    lazy_mask=(lazy[:,None] == np.arange(4)[None,:]).astype(np.float64).ravel()
    constraints=LinearConstraint(A,b,b)
    bounds=Bounds(np.zeros(256),np.ones(256))
    sols=[]
    for sign in (+1,-1):
        r=milp(sign*lazy_mask,integrality=np.ones(256),bounds=bounds,
               constraints=constraints,options={'mip_rel_gap':0.0,'time_limit':30.0})
        if r.status!=0 or r.x is None or float(r.mip_gap)>1e-9:
            raise ValueError('joint historical aggregate bound NOT certified by MILP')
        x=np.rint(r.x).astype(np.int32)
        if np.max(np.abs(x-r.x))>1e-7 or np.max(np.abs(A@x-b))>1e-7:
            raise ValueError('integer witness does not satisfy every exact original source constraint')
        objective=int(round(float(lazy_mask@x)))
        sols.append(objective)
    lo,hi=sols
    old=v24.analyze(pred,review,seals)['text_margin_conditional_image_route']['pairwise_only_bounds_reported_by_original_reviewer']
    if not (old['minimum_consistent_correct']<=lo<=hi<=old['maximum_consistent_correct']):
        raise ValueError('all-arm bounds violate original pairwise-only certificate')
    return {
        'schema':'hepta.stem.v25.all-arm-aggregate-feasibility.v1',
        'archived_immutable_predictions_sha256':v24.PRED_SHA256,
        'original_archive_sha256':v24.ARCHIVE_SHA256,
        'sample_count':n,'source_family_independence_verified':False,
        'binary_hypothetical_label_variables':256,
        'joint_exact_integer_equality_constraints':84,
        'all_eight_original_arm_correct_totals_and_six_matched_pair_rescue_harm_counts_used':True,
        'full_original_publisher_answer_labels_reopened':False,
        'v24_frozen_text_margin_threshold':v24.PRIMARY_THRESHOLD,
        'planned_vision_image_calls':sum(use_image),
        'pairwise_only_consistent_accuracy_lower_count':old['minimum_consistent_correct'],
        'pairwise_only_consistent_accuracy_upper_count':old['maximum_consistent_correct'],
        'joint_eight_arm_consistent_accuracy_lower_count':lo,
        'joint_eight_arm_consistent_accuracy_upper_count':hi,
        'solver':'scipy.optimize.milp HiGHS integral optimum both directions',
        'numpy_version':np.__version__,'scipy_version':scipy.__version__,
        'is_actual_task_accuracy':False,
        'is_prospective_model_win':False,
        'no_real_encoder_forward_this_run':True,
        'decision':'HOLD_JOINT_AGGREGATES_DO_NOT_IDENTIFY_ACTUAL_CASE_LABELS',
        'production_authorized':False,'authority_posture':'DENY_ALL',
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=sharp_bounds(args.archive)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:
        json.dump(result,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({'decision':result['decision'],
                      'joint_consistency_bounds':[
                          result['joint_eight_arm_consistent_accuracy_lower_count'],
                          result['joint_eight_arm_consistent_accuracy_upper_count']],
                      'production_authorized':False},sort_keys=True))

if __name__=='__main__':main()
