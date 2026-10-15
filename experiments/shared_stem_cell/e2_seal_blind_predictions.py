#!/usr/bin/env python3
"""Publish only ORIGINAL E1 label-blind forecasts after separate numeric replay.

No original human held labels or model weights enter this exporter. Hashes are
content checks, NOT signatures or independent model-origin authentication.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'hepta.e2.e1-original-blind-prelabel-seal.v1'
MODELS = ('granite_97m_r2', 'mmbert_small', 'embeddinggemma_2_text')
ARMS = ('frozen_additive', 'trained_additive', 'frozen_gated', 'trained_gated')
SEEDS = (41,47,53)
P0_SOURCE = 'b3b3712828cb5814e1a87d1e69a030ec947c43c1'
P0_RUN = 38686023757


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def sha(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def digest_hex(s):
    return type(s) is str and len(s) == 64 and all(x in '0123456789abcdef' for x in s)


def source_cases(blind):
    rows=blind.get('cases') if type(blind) is dict else None
    if (type(rows) is not list or not rows or len(rows) > 1024 or
        any(type(r) is not dict or type(r.get('case_id')) is not str or
            not digest_hex(r.get('view_sha256')) or
            r.get('condition') not in ('original','no_evidence') or
            type(r.get('source_group')) is not str for r in rows)):
        raise ValueError('unbound original source cases')
    ids=[r['case_id'] for r in rows]
    if len(set(ids))!=len(ids) or not any(r['condition']=='original' for r in rows):
        raise ValueError('duplicate or missing original human-evaluable case')
    return rows


def seal(blind, report, numeric, model, candidate_sha, candidate_run):
    if (model not in MODELS or type(candidate_sha) is not str or
            len(candidate_sha)!=40 or any(c not in '0123456789abcdef' for c in candidate_sha) or
            type(candidate_run) is not int or candidate_run <= 0):
        raise ValueError('unregistered model or source run')
    rows=source_cases(blind)
    ids=[r['case_id'] for r in rows]
    if (type(report) is not dict or report.get('schema')!='hepta.e1.matched-projected-gated-head.v1' or
            report.get('model')!=model or report.get('original_blind_sha256')!=sha(blind) or
            report.get('blind_case_ids')!=ids or report.get('authority')!='DENY_ALL' or
            report.get('quality_scored') is not False or report.get('held_labels_accessed') is not False or
            report.get('model_selection_permitted') is not False or
            report.get('production_promotion_permitted') is not False or
            report.get('native_representation_preserved') is not False or
            report.get('timing_is_counterbalanced') is not False or
            report.get('end_to_end_cost_equal') is not False or
            report.get('additional_encoder_forwards')!=0 or report.get('additional_pretrained_loads')!=0 or
            not digest_hex(report.get('original_report_sha256')) or
            not digest_hex(report.get('probe_safetensors_sha256'))):
        raise ValueError('invalid original numeric-source E1 ancestry')
    if (type(numeric) is not dict or numeric.get('schema')!='hepta.e1.matched-gated-independent-replay.v1' or
            numeric.get('trial_count')!=12 or numeric.get('parameter_count_each')!=4145 or
            numeric.get('numeric_consistency_only') is not True or
            numeric.get('held_quality_scored') is not False or
            numeric.get('physical_model_origin_authenticated') is not False or
            numeric.get('production_promotion_permitted') is not False or
            numeric.get('authority')!='DENY_ALL'):
        raise ValueError('missing actual independent numeric-only review')
    if (numeric.get('reviewed_probe_report_sha256')!=sha(report) or
            numeric.get('reviewed_probe_weights_sha256')!=report['probe_safetensors_sha256'] or
            numeric.get('reviewed_original_p0_report_sha256')!=report['original_report_sha256'] or
            numeric.get('reviewed_blind_material_sha256')!=sha(blind) or
            numeric.get('reviewed_model')!=model):
        raise ValueError('forecast not bound to independently replayed E1 producer report')
    threshold=numeric.get('tolerance')
    if (type(threshold) not in (float,int) or not 0 < threshold <= 3e-5 or
        any(type(numeric.get(k)) not in (float,int) or
            not math.isfinite(numeric[k]) or not 0 <= numeric[k] <= threshold
            for k in ('max_weight_disagreement','max_probability_disagreement'))):
        raise ValueError('incomplete or failed numeric review')
    arms=report.get('arms')
    if (type(arms) is not list or len(arms)!=12 or
        [(r.get('seed'),r.get('arm')) for r in arms] != [(s,a) for s in SEEDS for a in ARMS]):
        raise ValueError('incomplete E1 prelabel four-arm/three-seed grid')
    forecasts=[]
    for r in arms:
        p=r.get('blind_probabilities')
        if (type(p) is not list or len(p)!=len(ids) or
            any(type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1 for v in p) or
            not digest_hex(r.get('initial_sha256')) or not digest_hex(r.get('final_sha256')) or
            r.get('parameter_count')!=4145 or
            r.get('optimizer_steps')!=(40 if r['arm'].startswith('trained_') else 0)):
            raise ValueError('invalid finite original blind forecasts or Head lineage')
        forecasts.append({'seed':r['seed'],'arm':r['arm'],'probabilities':p})
    return {'schema': SCHEMA, 'model': model,
            'p0_source_sha': P0_SOURCE, 'p0_run_id': P0_RUN,
            'candidate_head_sha':candidate_sha,'candidate_run_id':candidate_run,
            'blind_material_sha256': sha(blind),
            'original_report_sha256':report['original_report_sha256'],
            'probe_report_sha256':sha(report), 'probe_weights_sha256':report['probe_safetensors_sha256'],
            'numeric_review_sha256':sha(numeric),
            'blind_cases':[{'case_id':r['case_id'], 'view_sha256':r['view_sha256'],
                            'source_group':r['source_group'],'condition':r['condition']} for r in rows],
            'forecasts':forecasts, 'original_human_labels_included':False,
            'original_future_windows_verified':False,
            'independently_signed':False, 'source_origin_authenticated':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('blind','probe-report','numeric-review','output'):
        ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--model',required=True,choices=MODELS)
    ap.add_argument('--candidate-head-sha',required=True)
    ap.add_argument('--candidate-run-id',required=True,type=int)
    a=ap.parse_args()
    from p0_multirc_semantic_material import read
    result=seal(read(a.blind),read(a.probe_report),read(a.numeric_review),
                a.model,a.candidate_head_sha,a.candidate_run_id)
    with a.output.open('xb') as f:
        f.write(canonical(result)+b'\n')


if __name__=='__main__': main()
