"""Independent sealed-prediction scorer; no import from model/trainer implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
import zipfile
from pathlib import Path

SCHEMA="hepta.p0.compact.physical-trial.v1"
ARMS=("frozen_gate","learned_gate","trained_linear")
SPLITS=("test","new_holdout")
MODELS=("granite97","mmbert_small")

class ScoreError(ValueError):pass

def check(pred,msg):
    if not pred:raise ScoreError(msg)

def canon(o):return json.dumps(o,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(o):return hashlib.sha256(canon(o)).hexdigest()
def file_digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def percentile(v,p):
    check(len(v)>=100 and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in v),"p99 unmeasured")
    s=sorted(v)
    i=int(math.ceil(p*len(s)))-1
    return s[max(0,i)]

def exact_pair_binomial(recovered,lost):
    """Exploratory two-sided exact McNemar test conditional on discordant pairs."""
    check(type(recovered) is int and type(lost) is int and recovered>=0 and lost>=0,"paired counts")
    n=recovered+lost
    if n==0:return 1.
    k=min(recovered,lost)
    return min(1., 2*sum(math.comb(n,j) for j in range(k+1))/2**n)

def score(source, labels, reports, *, source_digest, labels_digest, report_digests, historical_path=None):
    check(type(source) is dict and source.get('schema')=='hepta.p0.compact.source-only.v1' and
          source.get('authority')=='DENY_ALL' and source.get('cross_sectional_not_future') is True,
          "source mode")
    check(digest(source)==source_digest and digest(labels)==labels_digest,"unsealed input")
    cases=source.get('future_source_only')
    check(type(cases) is list and len(cases)==192 and
          Counter(v.get('split') for v in cases)==Counter({'test':64,'new_holdout':128}),"not fixed test cohort")
    check(labels.get('schema')=='hepta.p0.compact.future-labels.v1' and
          labels.get('future_source_sha256')==digest(cases) and
          labels.get('production_accepted') is False and labels.get('independently_authenticated') is False,
          "label availability or origin")
    truth=labels.get('labels')
    check(type(truth) is list and len(truth)==len(cases),"truth coverage")
    truth_by={}
    for v,c in zip(truth,cases):
        check(type(v) is dict and all(v.get(k)==c.get(k) for k in ('case_id','group_id','source_digest','split')) and
              type(v.get('label')) is int and v['label'] in (0,1),"label/source mismatch")
        check(c['case_id'] not in truth_by,"duplicate source")
        truth_by[c['case_id']]=v['label']
    check(set(reports)==set(MODELS) and set(report_digests)==set(MODELS),"incomplete compact models")
    result={}; paired={}
    selected={}
    for model, report in reports.items():
        check(report.get('schema')==SCHEMA and report.get('model_id')==model and
              report.get('source_sha256')==source_digest and report.get('source_only_future_sha256')==digest(cases) and
              report.get('authority')=='DENY_ALL' and report.get('production_accepted') is False and
              report.get('p0_accepted') is False and report.get('p1_accepted') is False and
              report.get('model_weights_executed_locally') is True and
              report.get('authenticity_independently_verified') is False and
              report.get('chronological_future_verified') is False and
              report.get('matched_full_lifecycle_cost') is False,"overclaim or mixed run")
        check(digest(report)==report_digests[model],"prediction seal drift")
        check(report.get('actual_encoder_forward_count')==352 and report.get('q24_feature_dimension')==384,
              "real physical forward count/width")
        arr=report.get('future_predictions')
        check(type(arr) is list and len(arr)==len(cases),"prediction coverage")
        check(type(report.get('head_stats')) is dict and set(report['head_stats'])==set(ARMS),"Head arm coverage")
        this={}
        for v,c in zip(arr,cases):
            check(type(v) is dict and all(v.get(k)==c.get(k) for k in ('case_id','group_id','split','joint_input_digest')) and
                  type(v.get('probs')) is dict and set(v['probs'])==set(ARMS) and
                  type(v.get('encoder_forward_ns')) is int and v['encoder_forward_ns']>0 and
                  type(v.get('head_ns')) is dict and set(v['head_ns'])==set(ARMS) and
                  all(type(x) is int and x>0 for x in v['head_ns'].values()) and
                  all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1 for p in v['probs'].values()),
                  "source/order/probability/meter mismatch")
            this[c['case_id']]=v
        check(len(this)==len(cases),"duplicate case")
        selected[model]=this
        per_split={}
        for split in SPLITS:
            ids=[r['case_id'] for r in cases if r['split']==split]
            outcome={}
            for arm in ARMS:
                p=[this[i]['probs'][arm] for i in ids]
                y=[truth_by[i] for i in ids]
                corr=sum(int((v>=.5)==bool(t)) for v,t in zip(p,y))
                outcome[arm]={'cases':len(ids),'correct':corr,'accuracy':corr/len(ids),
                              'brier':math.fsum((v-t)**2 for v,t in zip(p,y))/len(ids)}
            per_split[split]=outcome
        durations=[v['encoder_forward_ns']/1e6 for v in this.values() if v['split']=='new_holdout']
        result[model]={'quality':per_split,'observed_val2_encoder_latency_ms_p50':percentile(durations,.5),
                       'observed_val2_encoder_latency_ms_p95':percentile(durations,.95),
                       'observed_val2_encoder_latency_ms_p99':percentile(durations,.99),
                       'encoder_latency_unit':'single-input observed source-order CPU, excludes queue/load/preprocess',
                       'encoder_forwards':report['actual_encoder_forward_count'],
                       'head_stats':report['head_stats'],
                       'model_load_wall_ns':report['model_load_wall_ns'],
                       'total_run_cpu_ns':report['entire_run_cpu_ns'],
                       'reported_process_peak_rss_kib':report['linux_process_peak_rss_kib']}
    for split in SPLITS:
        ids=[r['case_id'] for r in cases if r['split']==split]
        for arm in ARMS:
            a,b=selected['granite97'],selected['mmbert_small']
            r=l=0
            for cid in ids:
                y=bool(truth_by[cid]);ac=(a[cid]['probs'][arm]>=.5)==y;bc=(b[cid]['probs'][arm]>=.5)==y
                r+=int(ac and not bc);l+=int(bc and not ac)
            paired[f'{split}.{arm}.granite_vs_mmbert']={
                'granite_recovers':r,'granite_loses':l,'delta_accuracy':(r-l)/len(ids),
                'exploratory_exact_mcnemar_p_uncorrected':exact_pair_binomial(r,l),
                'source_groups_clustered_by_identity':False}
    historical = None
    if historical_path is not None:
        # Import only a separately authored independent archived numeric auditor,
        # never the trainer; reject if the authoritative historical artifact is
        # missing or its bytes/model-source identities do not match.
        from real_model_artifact_replay import ARCHIVE_SHA256, replay
        reviewed = replay(historical_path, expected_archive_sha256=ARCHIVE_SHA256)
        check(reviewed['source_cases']==128 and reviewed['independent_numeric_and_case_replay'] is True and
              reviewed['independent_model_or_source_authentication'] is False and
              reviewed['production_accepted'] is False, "historical authority/coverage")
        with zipfile.ZipFile(historical_path) as z:
            old_cases=json.loads(z.read('stem-agnews-new-source-panel.json'))['cases']
            old_gemma=json.loads(z.read('stem-gemma-fresh-arms.json'))
            old_laya=json.loads(z.read('stem-laya-fresh-arm.json'))
        new_cases={row['case_id']:row for row in cases if row['split']=='new_holdout'}
        check(len(old_cases)==len(new_cases)==128, 'historical source/slot mismatch')
        for case in old_cases:
            check(case['case_id'] in new_cases and
                  all(case.get(k)==new_cases[case['case_id']].get(k) for k in
                      ('group_id','joint_input_digest','source_digest','split')) and
                  truth_by[case['case_id']]==case['label'], 'historical data or ground-truth mismatch')
        history={}
        for a in old_gemma+[old_laya]:
            name=a['arm_id']
            check(name not in history and name in reviewed['metrics'],'unexpected historical arm')
            rows={}
            for row in a['rows']:
                cid=row['case_id']
                check(cid in new_cases and cid not in rows and
                      row['source_digest']==new_cases[cid]['source_digest'] and
                      row['joint_input_digest']==new_cases[cid]['joint_input_digest'] and
                      type(row['prob_sports']) in (int,float) and
                      math.isfinite(row['prob_sports']) and 0 <= row['prob_sports'] <= 1,
                      'invalid historical row')
                rows[cid]=row
            check(set(rows)==set(new_cases),'historical missing rows')
            history[name]=rows
        check(set(history)=={'gemma2_frozen_head','gemma2_trained_head',
                             'gemma2_trained_head_scaled_1024','laya421_frozen'},
              'historical arm inventory')
        cross={}
        for model, new_rows in selected.items():
            for new_arm in ARMS:
                for old_name,old_rows in history.items():
                    recovered=lost=0
                    for cid in sorted(new_cases):
                        y=bool(truth_by[cid])
                        now=(new_rows[cid]['probs'][new_arm]>=.5)==y
                        then=(old_rows[cid]['prob_sports']>=.5)==y
                        recovered+=int(now and not then)
                        lost+=int(then and not now)
                    cross[f'{model}.{new_arm}__vs__{old_name}']={
                        'new_correct_only':recovered,'historical_correct_only':lost,
                        'delta_accuracy':(recovered-lost)/128,
                        'exploratory_exact_mcnemar_p_uncorrected':exact_pair_binomial(recovered,lost)}
        historical={'workflow_run':reviewed['workflow_run'],
                    'artifact_sha256':reviewed['verified_local_artifact_sha256'],
                    'historical_arms':reviewed['metrics'],
                    'cross_model_paired_on_identical_val2_sources':cross,
                    'model_weights_and_sources_independently_authenticated':False,
                    'same_Head_structure_training_budget_and_cpu_cost':False,
                    'four_model_equal_resource_winner_eligible':False,
                    'production_accepted':False}
    return {'schema':'hepta.p0.compact.independent-source-score.v1',
            'source_digest':source_digest,'labels_digest':labels_digest,'report_sha256':report_digests,
            'cohorts':'same pinned AGNews family, original test + val2 source-disjoint but not longitudinal',
            'models':result,'paired':paired,'historical_context':historical,
            'interpretation':'descriptive only; Head/train/total compute not equal to Laya/Gemma historical controls',
            'independent_numeric_replay':True,'independent_source_authentication':False,
            'independent_model_execution_authentication':False,'pretraining_overlap_ruled_out':False,
            'lifespan_cost_equalized':False,'future_time_gain_established':False,
            'full_four_model_physical_panel_complete':False,'p0_accepted':False,'p1_accepted':False,
            'production_accepted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--labels',required=True)
    p.add_argument('--granite',required=True);p.add_argument('--mmbert',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--historical',help="exact frozen Gemma/Laya archive for descriptive cross-model replay")
    a=p.parse_args()
    paths={'granite97':a.granite,'mmbert_small':a.mmbert}
    scores=score(read(a.source),read(a.labels),{k:read(v) for k,v in paths.items()},
                 source_digest=file_digest(a.source),labels_digest=file_digest(a.labels),
                 report_digests={k:file_digest(v) for k,v in paths.items()},historical_path=a.historical)
    with Path(a.output).open('xb') as f:f.write(canon(scores))
    print(json.dumps({'score_sha256':file_digest(a.output),'production_accepted':False,'authority':'DENY_ALL'}))
if __name__=='__main__':main()
