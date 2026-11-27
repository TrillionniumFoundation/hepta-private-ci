#!/usr/bin/env python3
"""Exact original Granite97 three-seed Cell Split and NDU heterogeneity check.

Source locked to the independent #2285 original report. No claim of independent
new model inference, equal lifetime costs, or future efficacy.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import group_v2_independent_negative as original

def evaluate(report: dict) -> dict:
    independent=original.review(report)
    rows=[]
    for seed in original.SEEDS:
        run=report['runs'][seed]
        baseline=run['test']['static']
        split=run['test']['split']
        ndu=run['test']['ndu']
        original.require(all(t['n']==96 for t in (baseline,split,ndu)),
                         'changed genuine held cohort')
        original.require(run['selected_model']=='core' and
                         run['split_decision']=='reject_candidate',
                         'selection must predate independent test outcomes')
        rows.append({
            'seed':int(seed),'source_group_family_certified_independent':False,
            'held_cases':96,'split_correct_delta':split['correct']-baseline['correct'],
            'ndu_correct_delta':ndu['correct']-baseline['correct'],
            'split_cpu_ratio':round(split['cpu_ns']/baseline['cpu_ns'],9),
            'ndu_cpu_ratio':round(ndu['cpu_ns']/baseline['cpu_ns'],9),
            'split_admitted':False,'selected_model':'core',
        })
    original.require([x['split_correct_delta'] for x in rows]==[-3,3,0] and
                     [x['ndu_correct_delta'] for x in rows]==[-4,-1,0],
                     'original negative and heterogeneity profile changed')
    original.require(sum(x['split_correct_delta'] for x in rows)==
                     independent['split_test_correct_delta_vs_static'] and
                     sum(x['ndu_correct_delta'] for x in rows)==
                     independent['ndu_test_correct_delta_vs_static'],
                     'cross-implementation seed-vs-total mismatch')
    return {'schema':'hepta.group-v2-source-seedwise-negative.v1',
            'original_git_blob_sha':original.ORIGINAL_GIT_BLOB,
            'original_archive_zip_reopened':False,
            'source_family_count_certified':False,
            'true_equal_lifecycle_costs':False,
            'natural_future_gain':False,'split_winner':False,
            'ndu_winner':False,'production_accepted':False,
            'authority_posture':'DENY_ALL','rows':rows}

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-summary',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    original.require(not a.out.exists() and not a.out.is_symlink(),'create-only output')
    r=evaluate(original.read_original(a.original_summary))
    a.out.write_text(json.dumps(r,sort_keys=True,allow_nan=False)+'\n')
    print('REAL_GRANITE_V2_SEEDWISE_NEGATIVE_ONLY / DENY_ALL')

if __name__=='__main__':
    main()
