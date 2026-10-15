#!/usr/bin/env python3
"""Independent human-label E2 score on exact P0 ORIGINAL MultiRC source only.

Scoring is descriptive (8 original independent passage groups), NOT genuine
future task utility, causal gain, signed provenance or model selection.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from e2_seal_blind_predictions import (SCHEMA as SEAL_SCHEMA, P0_SOURCE, P0_RUN,
                                       ARMS, SEEDS, MODELS, source_cases, sha, canonical, seal as rebuild_prelabel_seal)

SCHEMA = 'hepta.e2.original-human-matched-gated-independent-score.v1'


def score(blind, original_labels, original_reports, numeric_reviews, sealed, probe_reports, *, original_p0_scored,
          current_candidate_sha, current_run_id):
    rows=source_cases(blind)
    originals={r['case_id']:r for r in rows if r['condition']=='original'}
    if (not original_p0_scored or type(original_labels) is not dict or
        len(originals)!=len(original_labels) or set(original_labels)!=set(originals) or
        any(type(y) is not int or y not in (0,1) for y in original_labels.values()) or
        len({r['source_group'] for r in originals.values()})!=8 or
        type(original_reports) is not dict or set(original_reports)!=set(MODELS) or
        type(sealed) is not dict or set(sealed)!=set(MODELS) or
        type(numeric_reviews) is not dict or set(numeric_reviews)!=set(MODELS) or
        type(probe_reports) is not dict or set(probe_reports)!=set(MODELS)):
        raise ValueError('missing full original human source and all real P0/E1 arms')
    baseline_sha={m:sha(original_reports[m]) for m in MODELS}
    out={}
    same_case=[{'case_id':r['case_id'],'view_sha256':r['view_sha256'],
                'source_group':r['source_group'],'condition':r['condition']} for r in rows]
    for model in MODELS:
        s=sealed[model]
        if (type(s) is not dict or s.get('schema')!=SEAL_SCHEMA or s.get('model')!=model or
            s.get('p0_source_sha')!=P0_SOURCE or s.get('p0_run_id')!=P0_RUN or
            s.get('candidate_head_sha')!=current_candidate_sha or
            s.get('candidate_run_id')!=current_run_id or
            s.get('original_report_sha256')!=baseline_sha[model] or
            s.get('blind_material_sha256')!=sha(blind) or
            s.get('blind_cases')!=same_case or
            s.get('original_human_labels_included') is not False or
            s.get('original_future_windows_verified') is not False or
            s.get('independently_signed') is not False or
            s.get('source_origin_authenticated') is not False or
            s.get('production_promotion_permitted') is not False or
            s.get('authority')!='DENY_ALL'):
            raise ValueError('wrong model, source, Run, unscored receipt or authority')
        numeric=numeric_reviews[model]
        if (type(numeric) is not dict or
            numeric.get('schema')!='hepta.e1.matched-gated-independent-replay.v1' or
            numeric.get('trial_count')!=12 or numeric.get('parameter_count_each')!=4145 or
            numeric.get('numeric_consistency_only') is not True or
            numeric.get('held_quality_scored') is not False or
            numeric.get('production_promotion_permitted') is not False or
            numeric.get('authority')!='DENY_ALL' or
            s.get('numeric_review_sha256')!=sha(numeric)):
            raise ValueError('the independent numeric-only review differs from the seal')
        for key in ('probe_report_sha256','numeric_review_sha256','probe_weights_sha256'):
            v=s.get(key)
            if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
                raise ValueError('missing originally sealed numeric identity')
        # The previous E2 only checked a self-reported probe SHA. A changed,
        # valid-length forecast could be scored even if it never appeared in
        # the E1 producer. Reconstruct the exact published seal FROM the
        # independently archived original producer report and numeric receipt.
        # This prevents detached/rehashed forecast swaps. It is NOT a signed
        # execution attestation: a compromised runner could forge all inputs.
        probe=probe_reports[model]
        if (type(probe) is not dict or sha(probe)!=s.get('probe_report_sha256') or
                probe.get('original_report_sha256')!=baseline_sha[model]):
            raise ValueError('detached original E1 producer prediction report')
        rebuilt=rebuild_prelabel_seal(blind,probe,numeric,model,
                                       current_candidate_sha,current_run_id)
        if canonical(rebuilt)!=canonical(s):
            raise ValueError('sealed forecast differs from original E1 producer output')
        forecasts=s.get('forecasts')
        if (type(forecasts) is not list or
            [(x.get('seed'),x.get('arm')) for x in forecasts] != [(seed,arm) for seed in SEEDS for arm in ARMS]):
            raise ValueError('incomplete original prelabel forecast grid')
        by_seed={}
        for seed in SEEDS:
            arms={}
            for forecast in forecasts:
                if forecast['seed']!=seed: continue
                probs=forecast.get('probabilities')
                if (type(probs) is not list or len(probs)!=len(rows) or
                    any(type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1 for p in probs)):
                    raise ValueError('missing finite blind predictions')
                pred=dict(zip([r['case_id'] for r in rows],probs))
                # Diagnostics are scored ONLY for human-labeled original condition.
                selected=[(pred[cid],original_labels[cid]) for cid in originals]
                arms[forecast['arm']]={'accuracy':sum((p>=.5)==bool(y) for p,y in selected)/len(selected),
                                       'brier':sum((p-y)**2 for p,y in selected)/len(selected),
                                       'original_rows':len(selected)}
            paired={}
            for status in ('frozen','trained'):
                add=next(f['probabilities'] for f in forecasts if (f['seed'],f['arm'])==(seed,status+'_additive'))
                gate=next(f['probabilities'] for f in forecasts if (f['seed'],f['arm'])==(seed,status+'_gated'))
                group=defaultdict(list)
                for index,r in enumerate(rows):
                    if r['condition']=='original':
                        y=original_labels[r['case_id']]
                        group[r['source_group']].append((add[index]-y)**2-(gate[index]-y)**2)
                if len(group)!=8:
                    raise ValueError('insufficient original human passage groups')
                vals=[sum(v)/len(v) for _,v in sorted(group.items())]
                paired[status]={'additive_brier_minus_gated_brier':sum(vals)/len(vals),
                                'per_original_source_group_gains':vals,
                                'source_groups_gated_better':sum(v>0 for v in vals),
                                'source_groups_gated_worse':sum(v<0 for v in vals),
                                'source_groups_tied':sum(v==0 for v in vals)}
            by_seed[str(seed)]={'arms':arms,'paired':paired}
        out[model]={'seeds':by_seed,'original_human_source_passage_groups':8,
                    'reconstructed_exact_original_prelabel_forecasts':True,
                    'head_parameter_count_each':4145,
                    'projection_information_loss_matched':True,
                    'comparison_is_with_original_deployed_nochange':False}
    return {'schema':SCHEMA, 'models':out, 'original_human_cases':len(originals),
            'original_human_source_groups':8,
            'original_p0_human_review_replayed':True,
            'model_or_head_winner_selected':False,'independent_future_windows':False,
            'external_model_origin_authenticated':False,
            'statistical_95pct_superiority_certified':False,
            'equal_full_lifecycle_cost_certified':False,
            'physical_cell_split_permitted':False,
            'production_promotion_permitted':False, 'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('fit','blind','labels','train-parquet','validation-parquet','output'):
        p.add_argument('--'+key,type=Path,required=True)
    for model in (*MODELS,'laya421_nochange'):
        p.add_argument('--p0-'+model.replace('_','-'),type=Path,required=True)
    for model in MODELS:
        p.add_argument('--seal-'+model.replace('_','-'),type=Path,required=True)
        p.add_argument('--numeric-'+model.replace('_','-'),type=Path,required=True)
        p.add_argument('--probe-'+model.replace('_','-'),type=Path,required=True)
    p.add_argument('--candidate-head-sha',required=True)
    p.add_argument('--candidate-run-id',type=int,required=True)
    a=p.parse_args()
    from p0_multirc_semantic_material import read, original_rows
    from p0_multirc_semantic_review import review as original_review, original_label_audit
    fit,blind,owner=read(a.fit),read(a.blind),read(a.labels)
    meta=fit['metadata']
    tr=original_rows(a.train_parquet,meta['train_sha256'])
    val=original_rows(a.validation_parquet,meta['validation_sha256'])
    reports={m:read(getattr(a,'p0_'+m)) for m in (*MODELS,'laya421_nochange')}
    p0=original_review(fit,blind,owner,tr,val,reports)
    if (p0.get('production_promotion_permitted') is not False or
        p0.get('model_winner_selected') is not False or
        p0.get('authority')!='DENY_ALL'):
        raise ValueError('original P0 human scorer does not hold authorization boundary')
    labels=original_label_audit(fit,blind,owner,tr,val)
    result=score(blind,labels,{m:reports[m] for m in MODELS},
                 {m:read(getattr(a,'numeric_'+m)) for m in MODELS},
                 {m:read(getattr(a,'seal_'+m)) for m in MODELS},
                 {m:read(getattr(a,'probe_'+m)) for m in MODELS},
                 original_p0_scored=True, current_candidate_sha=a.candidate_head_sha,
                 current_run_id=a.candidate_run_id)
    with a.output.open('xb') as f:
        f.write(canonical(result)+b'\n')


if __name__=='__main__':main()
