#!/usr/bin/env python3
"""Post-prelabel original-human study of nested TRAIN source budgets only.

No E1/E3 Torch import; labels enter only after the original P0 source owner is
replayed and every separately reviewed E3 budget forecast is sealed. No model
selection, future utility or production authority is inferred.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from e2_seal_blind_predictions import MODELS, P0_SOURCE, P0_RUN, SEEDS, sha as e2_sha

SCHEMA='hepta.e3.original-human-source-budget-descriptive-score.v1'
BUDGETS=(4,8,12)
KINDS=('additive','gated')


def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def sha(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def metric(rows):
    if not rows:
        raise ValueError('missing original human label observations')
    return {'original_rows':len(rows),
            'accuracy':sum((p>=.5)==bool(y) for p,y in rows)/len(rows),
            'brier':sum((p-y)**2 for p,y in rows)/len(rows),
            'positive_support':sum(y for _,y in rows)}


def group_brier_gain(original,labels,add,gate):
    bygroup=defaultdict(list)
    for i,r in original:
        y=labels[r['case_id']]
        bygroup[r['source_group']].append((add[i]-y)**2-(gate[i]-y)**2)
    if len(bygroup)!=8:
        raise ValueError('not eight original independent test source passages')
    gains=[sum(v)/len(v) for _,v in sorted(bygroup.items())]
    return {'additive_minus_gated_brier_positive_means_gated_better':sum(gains)/len(gains),
            'original_source_passages':8,
            'gated_better_source_passages':sum(x>0 for x in gains),
            'gated_worse_source_passages':sum(x<0 for x in gains),
            'tied_source_passages':sum(x==0 for x in gains),
            'per_original_source_passage_gains':gains}


def review_human(fit,blind,labels,e2_score,e2_seals,e3_reports,e3_reviews,*,candidate_sha,run_id):
    if (type(fit) is not dict or type(blind) is not dict or type(labels) is not dict or
        type(e2_score) is not dict or
        e2_score.get('schema')!='hepta.e2.original-human-matched-gated-independent-score.v1' or
        e2_score.get('original_p0_human_review_replayed') is not True or
        e2_score.get('production_promotion_permitted') is not False or
        e2_score.get('authority')!='DENY_ALL' or
        type(e2_seals) is not dict or set(e2_seals)!=set(MODELS) or
        type(e3_reports) is not dict or set(e3_reports)!=set(MODELS) or
        type(e3_reviews) is not dict or set(e3_reviews)!=set(MODELS) or
        type(candidate_sha) is not str or len(candidate_sha)!=40 or
        type(run_id) is not int or run_id<=0):
        raise ValueError('original source owner and complete E2/E3 conditions required')
    rows=blind.get('cases')
    if type(rows) is not list or not rows:
        raise ValueError('missing original blind source cases')
    original=[(i,r) for i,r in enumerate(rows) if r.get('condition')=='original']
    if (set(labels)!={r['case_id'] for _,r in original} or
        any(type(y) is not int or y not in (0,1) for y in labels.values()) or
        len({r['source_group'] for _,r in original})!=8 or
        e2_score.get('original_human_cases')!=len(original)):
        raise ValueError('not source-bound original human labels')
    e2_parent_blind=e2_sha(blind)
    out={}
    for model in MODELS:
        e2=e2_seals[model];r=e3_reports[model];v=e3_reviews[model]
        if (type(e2) is not dict or type(r) is not dict or type(v) is not dict or
            e2.get('model')!=model or e2.get('candidate_head_sha')!=candidate_sha or
            e2.get('candidate_run_id')!=run_id or e2.get('p0_source_sha')!=P0_SOURCE or
            e2.get('p0_run_id')!=P0_RUN or e2.get('blind_material_sha256')!=e2_parent_blind or
            e2.get('authority')!='DENY_ALL' or
            r.get('schema')!='hepta.e3.source-group-learning-curve.v1' or
            r.get('model')!=model or r.get('panel_id')!=fit.get('metadata',{}).get('panel_id') or
            r.get('original_fit_sha256')!=sha(fit) or r.get('original_blind_sha256')!=sha(blind) or
            r.get('original_e1_probe_sha256')!=e2.get('probe_report_sha256') or
            r.get('original_e1_numeric_sha256')!=e2.get('numeric_review_sha256') or
            r.get('candidate_head_sha')!=candidate_sha or r.get('candidate_run_id')!=run_id or
            r.get('production_promotion_permitted') is not False or
            r.get('statistical_winner_selected') is not False or r.get('authority')!='DENY_ALL' or
            v.get('schema')!='hepta.e3.independent-source-group-train-replay.v1' or
            v.get('reviewed_e3_report_sha256')!=sha(r) or
            v.get('reviewed_e3_weights_sha256')!=r.get('e3_trained_weights_sha256') or
            v.get('reviewed_original_fit_sha256')!=sha(fit) or
            v.get('reviewed_original_blind_sha256')!=sha(blind) or
            v.get('reviewed_e1_report_sha256')!=r.get('original_e1_probe_sha256') or
            v.get('reviewed_model')!=model or
            v.get('original_full_budget_e1_parity') is not True or
            v.get('validated_records')!=18 or
            v.get('production_promotion_permitted') is not False or v.get('authority')!='DENY_ALL'):
            raise ValueError('E3 report does not match independent numeric E1/E3 source custody')
        records=r.get('records'); forecasts=e2.get('forecasts')
        expected=[(b,s,k) for b in BUDGETS for s in SEEDS for k in KINDS]
        if type(records) is not list or [(a.get('budget_source_groups'),a.get('seed'),a.get('architecture')) for a in records]!=expected:
            raise ValueError('incomplete E3 source-group/seed/architecture budget grid')
        if (type(forecasts) is not list or
            {(f.get('seed'),f.get('arm')) for f in forecasts} !=
             {(s,a) for s in SEEDS for a in ('frozen_additive','trained_additive','frozen_gated','trained_gated')}):
            raise ValueError('missing original E1 full-budget match')
        baseline={(f['seed'],f['arm']):f['probabilities'] for f in forecasts}
        budget_scores={}
        for budget in BUDGETS:
            by_seed={};status=None
            for seed in SEEDS:
                pairs={}
                for kind in KINDS:
                    rec=next(x for x in records if
                             (x['budget_source_groups'],x['seed'],x['architecture'])==(budget,seed,kind))
                    if rec.get('status')=='missing_both_labels':
                        if rec.get('optimizer_updates')!=0 or rec.get('blind_predictions') is not None:
                            raise ValueError('infeasible budget cannot produce a scored Head')
                        pairs[kind]=None
                        continue
                    if (rec.get('status')!='trained' or rec.get('optimizer_updates')!=40 or
                        rec.get('head_parameter_count')!=4145):
                        raise ValueError('false Head budget optimizer')
                    p=rec.get('blind_predictions')
                    if (type(p) is not list or len(p)!=len(rows) or
                        any(type(x) not in (int,float) or not math.isfinite(x) or x<0 or x>1 for x in p)):
                        raise ValueError('invalid sealed original blind E3 predictions')
                    if budget==12:
                        old=baseline[seed,'trained_'+kind]
                        if len(old)!=len(p) or max(abs(x-y) for x,y in zip(old,p))>3e-5:
                            raise ValueError('original full E1 predictions fail E3 budget parity')
                    pairs[kind]=p
                if (pairs['additive'] is None)!=(pairs['gated'] is None):
                    raise ValueError('unfair Head budget feasibility mismatch')
                if pairs['additive'] is None:
                    status='infeasible_missing_two_train_labels'
                    by_seed[str(seed)]={'status':status,'scored_original_rows':0}
                    continue
                selected=lambda p:[(p[i],labels[row['case_id']]) for i,row in original]
                by_seed[str(seed)]={'status':'scored_original_human_only',
                                   'additive':metric(selected(pairs['additive'])),
                                   'gated':metric(selected(pairs['gated'])),
                                   'paired':group_brier_gain(original,labels,pairs['additive'],pairs['gated'])}
            budget_scores[str(budget)]={'seeds':by_seed,'status':status or 'descriptive_source_scored'}
        out[model]={'budgets':budget_scores,'same_initial_weights_as_original_E1':True,
                    'complete_group_budget_reproduces_E1':True,
                    'head_parameter_count_each':4145}
    return {'schema':SCHEMA,'models':out,'original_human_label_rows':len(original),
            'independent_original_source_groups':8,'train_source_group_budgets':[4,8,12],
            'descriptive_only':True,'temporal_future_utility_certified':False,
            '95pct_superiority_certified':False,'full_training_plus_serving_cost_matched':False,
            'old_task_retention_verified':False,'stem_or_head_winner_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for f in ('fit','blind','labels','train-parquet','validation-parquet','e2-scored','output'):
        p.add_argument('--'+f,type=Path,required=True)
    for model in MODELS:
        for kind in ('e2-seal','e3-report','e3-numeric'):
            p.add_argument('--'+kind+'-'+model.replace('_','-'),type=Path,required=True)
    p.add_argument('--candidate-head-sha',required=True)
    p.add_argument('--candidate-run-id',type=int,required=True)
    a=p.parse_args()
    from p0_multirc_semantic_material import read,original_rows
    from p0_multirc_semantic_review import original_label_audit
    fit,blind,owner=read(a.fit),read(a.blind),read(a.labels)
    meta=fit['metadata']
    tr=original_rows(a.train_parquet,meta['train_sha256'])
    val=original_rows(a.validation_parquet,meta['validation_sha256'])
    labels=original_label_audit(fit,blind,owner,tr,val)
    result=review_human(fit,blind,labels,read(a.e2_scored),
                        {m:read(getattr(a,'e2_seal_'+m)) for m in MODELS},
                        {m:read(getattr(a,'e3_report_'+m)) for m in MODELS},
                        {m:read(getattr(a,'e3_numeric_'+m)) for m in MODELS},
                        candidate_sha=a.candidate_head_sha,run_id=a.candidate_run_id)
    with a.output.open('xb') as fd:fd.write(canonical(result)+b'\n')


if __name__=='__main__':main()
