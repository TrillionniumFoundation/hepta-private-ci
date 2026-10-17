"""Independent late-label review of two genuinely paid CPU original-model arms.

No import of V9 producer, no model weights/train inference. Checks identities,
selection, original v3 parity, and source-test gold after sealed predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
for folder in ('stem-optimal-v3','stem-optimal-v5','stem-optimal-v4'):
    sys.path.insert(0,str(ROOT/folder))
import stem_hard_charge_review_v3 as publisher
import paired_review_v5 as historical
import cheap_lexical_review_v4 as lexical

SCHEMA='hepta.stem.physical-selective.v9'
REVIEW='hepta.stem.physical-selective-original-review.v9'
SOURCE_SHA=historical.SOURCE_PLAN_SHA
CANDIDATE='granite47'
CHEAP='char_345_tfidf_centroid'
ROUTE_K=8
MODES={'selective':8,'full':32}


def need(ok, reason):
    if not ok: raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,allow_nan=False,
                      separators=(',',':')).encode('utf-8')


def probability(values):
    need(type(values) is list and len(values)==4 and
         all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in values) and
         abs(sum(values)-1) <= 1e-5, 'invalid original V9 probability')
    return values


def rerank(cheap, original_source):
    valid={x['case_id']:x['source_sha256'] for x in original_source['heldout']}
    need(len(valid)==32 and len(cheap['rows'])==32,'original cheap cohort missing')
    rows={}
    for x in cheap['rows']:
        need(type(x) is dict and set(x)=={'case_id','source_sha256','scores'} and
             x['case_id'] in valid and x['case_id'] not in rows and
             x['source_sha256']==valid[x['case_id']] and
             type(x['scores']) is dict and set(x['scores'])=={'word_12_tfidf_centroid',CHEAP},
             'original cheap source/cardinality mismatch')
        rows[x['case_id']]=probability(x['scores'][CHEAP])
    need(set(rows)==set(valid),'original cheap source missing')
    scored=[]
    for cid,p in rows.items():
        top=sorted(p,reverse=True)
        scored.append((top[0]-top[1],cid))
    scored.sort()
    return [cid for _,cid in scored[:ROUTE_K]],rows


def checked_run(run, mode, source, cheap, original, materials, selected):
    need(type(run) is dict and run.get('schema')==SCHEMA and run.get('mode')==mode and
         run.get('candidate')==CANDIDATE and run.get('source_plan_sha256')==SOURCE_SHA and
         run.get('authority')=='DENY_ALL' and run.get('disposition')=='HOLD_NO_GO' and
         run.get('production_authorized') is False and
         run.get('stem_winner_verified') is False and run.get('cell_split_authorized') is False and
         run.get('future_windows')==0 and run.get('source_independent_families')==1 and
         run.get('full_lifecycle_savings_qualified') is False and
         run.get('hardware_meter_independently_attested') is False and
         run.get('original_v3_label_exposure_prior_to_design') is True and
         run.get('trial_separate_fresh_process') is True,
         'original V9 physical result identity/authority invalid')
    model=materials['candidates'][CANDIDATE]
    need((run['model_repo'],run['model_revision'],run['actual_weight_sha256'])==
         (model['repo'],model['revision'],model['weight_sha256']) and
         run['material_sha256']==sha(canonical(materials)) and
         run['source_sha256']==sha(canonical(source)) and
         run['cheap_receipt_sha256']==sha(canonical(cheap)) and
         run['original_receipt_sha256']==sha(canonical(original)),
         'V9 physical original data/model fingerprint mismatch')
    need(run['selected_case_ids']==selected and
         run['head_parameters']==27656 and run['optimizer_steps']==100 and
         run['initial_head_sha256']==original['initial_head_sha256'] and
         type(run['trained_head_byte_identical_to_original']) is bool and
         (run['trained_head_sha256']==original['trained_head_sha256']) ==
             run['trained_head_byte_identical_to_original'],
         'V9 original training identity or replay mismatch')
    cost=run['cost']; n=MODES[mode]; batches=1 if mode=='selective' else 2
    need(type(cost) is dict and set(cost)=={
        'model_load_wall_seconds','cheap_wall_seconds','full_encoder_frozen_train_rows',
        'physically_encoded_heldout_rows','physically_executed_encoder_sequences',
        'actual_model_forward_hook_calls','frozen_train_forward_batches',
        'heldout_forward_batches','feature_encode_wall_seconds',
        'head_training_wall_seconds','elapsed_cpu_seconds','elapsed_wall_seconds',
        'process_peak_rss_bytes','energy_joules','p99_latency_ms'},
        'incomplete original V9 physical meter')
    need(cost['full_encoder_frozen_train_rows']==64 and
         cost['physically_encoded_heldout_rows']==n and
         cost['physically_executed_encoder_sequences']==64+n and
         cost['frozen_train_forward_batches']==4 and cost['heldout_forward_batches']==batches and
         cost['actual_model_forward_hook_calls']==4+batches and
         cost['energy_joules'] is None and cost['p99_latency_ms'] is None and
         type(cost['process_peak_rss_bytes']) is int and cost['process_peak_rss_bytes']>0 and
         all(type(cost[k]) in (int,float) and math.isfinite(cost[k]) and cost[k]>=0
             for k in ('model_load_wall_seconds','cheap_wall_seconds','feature_encode_wall_seconds',
                       'head_training_wall_seconds','elapsed_cpu_seconds','elapsed_wall_seconds')),
         'unqualified forward hook, count, performance or claimed energy')
    wanted={r['case_id']:r['source_sha256'] for r in source['heldout']
            if mode=='full' or r['case_id'] in selected}
    need(len(wanted)==n and run['active_case_ids']==[r['case_id'] for r in source['heldout']
             if mode=='full' or r['case_id'] in selected] and
         type(run['rows']) is list and len(run['rows'])==n,
         'V9 physically encoded only wrong case count')
    by_id={};old={r['case_id']:r['scores']['learned'] for r in original['rows']}
    for row in run['rows']:
        need(type(row) is dict and set(row)=={'case_id','source_sha256','probabilities'} and
             row['case_id'] in wanted and row['case_id'] not in by_id and
             row['source_sha256']==wanted[row['case_id']],
             'V9 extra or swapped physically encoded case')
        p=probability(row['probabilities']);comparison=probability(old[row['case_id']])
        need(all(abs(a-b)<=5e-4 for a,b in zip(p,comparison)),
             'repaid pretrained execution failed original V3 prediction parity')
        by_id[row['case_id']]=p
    need(set(by_id)==set(wanted),'missing new physical inference')
    return by_id


def score(scores,gold):
    need(set(scores)==set(gold) and len(scores)==32,'not same original human gold')
    correct=0;brier=0.0
    for cid,label in gold.items():
        p=probability(scores[cid]);correct+=int(max(range(4),key=lambda x:p[x])==label)
        brier+=sum((v-float(i==label))**2 for i,v in enumerate(p))/32
    return {'correct':correct,'n':32,'brier':brier}


def review(train_raw,test_raw,source,cheap,original,material,selected_run,full_run):
    need(source['source_plan_sha256']==SOURCE_SHA and
         source['heldout_labels_excluded'] is True and
         cheap['source_plan_sha256']==SOURCE_SHA and
         original['candidate']==CANDIDATE and
         original['source_plan_sha256']==SOURCE_SHA, 'unaligned original source')
    # Authenticate original task labels through independent publisher-owned source bytes.
    frozen, gold=publisher.reconstruct(train_raw,test_raw,publisher.original.FIXED_SHA)
    need(source['train']==frozen['train'] and source['heldout']==frozen['heldout'],
         'publisher original source roster drift')
    # Existing independent V4 reviewer checks the model-free cheap algorithm numerically.
    cheap_report=lexical.review_original(train_raw,test_raw,source,cheap)
    need(cheap_report['independent_algorithm_replay'] is True and
         cheap_report['publisher_original_sha_verified'] is True,
         'historical cheap source cannot independently replay')
    selected,cheap_scores=rerank(cheap,source)
    a=checked_run(selected_run,'selective',source,cheap,original,material,selected)
    b=checked_run(full_run,'full',source,cheap,original,material,selected)
    need(all(all(abs(x-y)<=5e-4 for x,y in zip(a[cid],b[cid])) for cid in selected),
         'same task selected/full physical executions disagree')
    routed={cid: a[cid] if cid in a else cheap_scores[cid] for cid in gold}
    reference={cid:r['scores']['learned'] for cid,r in
               [(r['case_id'],r) for r in original['rows']]}
    # Compute descriptor from actual original archived predictions too.
    report={'schema':REVIEW,'case_count':32,'physical_model':CANDIDATE,
            'selected_case_ids':selected,'prelabel_selection_count':ROUTE_K,
            'physical_selective':score(routed,gold),
            'physical_full':score(b,gold),
            'original_previously_paid_full':score(reference,gold),
            'cheap_char':score(cheap_scores,gold),
            'observed_selective':selected_run['cost'],
            'observed_full':full_run['cost'],
            'actual_selective_forward_hook_calls':5,
            'actual_full_forward_hook_calls':6,
            'true_new_selective_heldout_sequences':8,
            'true_new_full_heldout_sequences':32,
            'model_train_and_loading_paid_in_both_arms':True,
            'same_runner_two_distinct_processes':True,
            'training_and_load_cost_eliminated':False,
            'independently_attested_host_meter':False,
            'source_independent_families':1,'future_windows':0,
            'prior_heldout_labels_seen':True,
            'full_lifecycle_savings_qualified':False,
            'production_authorized':False,'stem_winner_verified':False,
            'cell_split_authorized':False,'disposition':'HOLD_NO_GO','authority':'DENY_ALL'}
    return report


def main():
    p=argparse.ArgumentParser()
    for name in ('source','cheap','original','materials','selective','full','train','test','output'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args();read=lambda path:json.loads(Path(path).read_text(encoding='utf-8'),
                            parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    report=review(Path(a.train).read_bytes(),Path(a.test).read_bytes(),read(a.source),
                  read(a.cheap),read(a.original),read(a.materials),read(a.selective),read(a.full))
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as f:f.write(canonical(report)+b'\n');f.flush()
    print(json.dumps({'review_sha256':sha(out.read_bytes()),'disposition':'HOLD_NO_GO',
                      'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':main()
