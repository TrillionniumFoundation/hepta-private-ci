"""Torch-free independent replay of genuine historical natural-label calibration.

Reads original V6 probabilities/labels and recorded trained scalar parameters;
reconstructs 827 source-heldout predictions for all 3 seeds/4 controls.
Neither an independent model issuer nor prospective quality certification.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import stat
import zipfile

V6_SHA='197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a'
SCHEMA='hepta.bridge.v78.original-natural-exposed-source-folds.shadow.v1'
ARMS=('frozen','always_positive','fit_threshold','two_scalar_calibrator')
SEEDS=(41,47,53)


def check(ok,why):
    if not ok:raise ValueError(why)


def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def digest(obj):
    return hashlib.sha256(canon(obj).encode()).hexdigest()


def _pairs(pairs):
    data={}
    for k,v in pairs:
        check(k not in data,'duplicate JSON keys denied')
        data[k]=v
    return data


def read_json(path):
    p=Path(path)
    check(not p.is_symlink() and p.is_file() and p.stat().st_size<=2_000_000,
          'bounded normal report required')
    return json.loads(p.read_bytes(),parse_constant=lambda n: (_ for _ in ()).throw(ValueError(n)),
                      object_pairs_hook=_pairs)


def originals(original):
    path=Path(original)
    check(not path.is_symlink(),'no symlink original allowed')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        check(stat.S_ISREG(st.st_mode) and st.st_size==20_928_479,'exact historical V6 archive size required')
        blob=f.read(st.st_size+1)
        en=os.fstat(f.fileno())
    check(len(blob)==st.st_size and (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==
          (en.st_dev,en.st_ino,en.st_size,en.st_mtime_ns) and
          hashlib.sha256(blob).hexdigest()==V6_SHA,'original V6 bytes changed')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        cases=json.loads(z.read('reader-v5-independent-audit/natural-cases.json'),object_pairs_hook=_pairs)
        rows=cases['tune']
        check(len(rows)==827 and len({r['source_hash'] for r in rows})==16,
              'complete old exposed MultiRC internal panel required')
        ids=[canon([r[k] for k in ('source_split','paragraph_id','question_id','answer_id')]) for r in rows]
        check(len(set(ids))==827,'unique row source IDs required')
        scores={}
        for s in SEEDS:
            d=json.loads(z.read(f'reader-v6-bridge/seed-{s}/bridge/warmup-natural-internal.json'),
                         object_pairs_hook=_pairs)
            check(d['case_ids']==ids and d['threshold_selected'] is False and
                  len(d['probabilities'])==827,'original one-to-one source panel required')
            scores[s]=d['probabilities']
    return rows,scores


def fold_assign(rows):
    g=sorted({r['source_hash'] for r in rows})
    rng=random.Random('hepta-v78-natural-internal-exposed-source-groups-20261015')
    rng.shuffle(g)
    return {source:i%4 for i,source in enumerate(g)}


def score(rows,pred):
    gold=[r['label'] for r in rows]
    check(len(gold)==len(pred)>0 and all(type(v) is int and v in (0,1) for v in pred),
          'every binary original prediction required')
    tp=sum(y==p==1 for y,p in zip(gold,pred))
    denom=sum(gold)+sum(pred)
    questions={}
    for r,y,p in zip(rows,gold,pred):
        key=(r['source_split'],r['paragraph_id'],r['question_id'])
        questions.setdefault(key,[]).append(y==p)
    return dict(candidates=len(rows),questions=len(questions),
      source_groups=len({r['source_hash'] for r in rows}),
      f1_a=2*tp/denom if denom else 0.,
      exact_match=sum(all(v) for v in questions.values())/len(questions),
      accuracy=sum(y==p for y,p in zip(gold,pred))/len(gold))


def training_threshold(original, labels):
    candidates=[]
    for i in range(1,20):
        t=i/20
        pred=[int(p>t) for p in original]
        tp=sum(y==p==1 for y,p in zip(labels,pred))
        div=sum(labels)+sum(pred)
        candidates.append((2*tp/div if div else 0.,-abs(t-.5),-t,t))
    return max(candidates)[-1]


def independent_calibrated_probability(prob,params):
    # Torch clip(logit(x),1e-6,1-1e-6) was FP32; no near-threshold case
    # may be silently repaired; accept only exact predicted class parity.
    p=min(max(float(prob),1e-6),1-1e-6)
    z=math.exp(params['log_scale'])*math.log(p/(1-p))+params['bias']
    return 1/(1+math.exp(-max(-50,min(50,z))))


def verify(original,report):
    rows,p=originals(original)
    assignment=fold_assign(rows)
    check(report['schema']==SCHEMA and report['status']=='EXPOSED_SOURCE_CALIBRATION_ONLY'
        and report['original_V6_zip_sha256']==V6_SHA
        and report['source_group_fold_assignment_sha256']==digest(assignment)
        and report['seeds']==list(SEEDS) and report['arms']==list(ARMS)
        and report['folds']==4 and report['actual_calibration_fits']==12
        and report['trainable_scalars_per_model']==2 and report['steps_per_calibrator']==240
        and report['old_binding_original_weight_update_count']==0
        and report['historical_pretrained_logits_used'] is True
        and report['future_independent_multirc_verified'] is False
        and report['learned_new_1700_head_real_token_task_verified'] is False
        and report['production_authorized'] is False
        and report['cell_split_production_authorized'] is False
        and report['native_ndu_admitted'] is False
        and report['model_selected'] is False,'original narrow analysis scope/authority required')
    check(set(report['measures'])=={'41','47','53'},'complete seeds required')
    for seed in SEEDS:
        x=report['measures'][str(seed)]
        expected=p[seed]
        check(x['original_probabilities_sha256']==digest(expected)
              and len(x['folds'])==4,'complete original archived probability ancestry required')
        predictions={arm:[None]*len(rows) for arm in ARMS}
        for f,record in enumerate(x['folds']):
            train=[i for i,r in enumerate(rows) if assignment[r['source_hash']]!=f]
            held=[i for i,r in enumerate(rows) if assignment[r['source_hash']]==f]
            groups_train={rows[i]['source_hash'] for i in train}
            groups_held={rows[i]['source_hash'] for i in held}
            check(len(groups_train)==12 and len(groups_held)==4 and not groups_train&groups_held,
                  'true physical source partition required')
            check(record['fold']==f and record['train_cases']==len(train) and
                  record['heldout_cases']==len(held) and
                  record['train_source_groups']==12 and record['heldout_source_groups']==4 and
                  record['train_source_set_sha256']==digest(sorted(groups_train)) and
                  record['heldout_source_set_sha256']==digest(sorted(groups_held)),
                  'original heldout group or case count drift')
            thr=training_threshold([expected[i] for i in train],[rows[i]['label'] for i in train])
            check(record['threshold']==thr,'threshold unexpectedly tuned on heldout group')
            params=record['calibrator']
            check(set(params)=={'log_scale','bias','train_ce','cpu_ns','optimizer_updates','trainable_parameters'}
                  and params['optimizer_updates']==240 and params['trainable_parameters']==2
                  and type(params['cpu_ns']) is int and params['cpu_ns']>=0
                  and all(type(params[k]) in (int,float) and math.isfinite(params[k]) for k in
                          ('log_scale','bias','train_ce')) and
                  abs(params['log_scale'])<=20 and abs(params['bias'])<=20 and params['train_ce']>=0,
                  'one bounded real 2-scalar calibration receipt required')
            for i in held:
                predicted=dict(frozen=int(expected[i]>.5),always_positive=1,
                    fit_threshold=int(expected[i]>thr),
                    two_scalar_calibrator=int(independent_calibrated_probability(expected[i],params)>.5))
                for arm in ARMS:
                    check(predictions[arm][i] is None,'duplicate original heldout row')
                    predictions[arm][i]=predicted[arm]
        for arm in ARMS:
            check(all(type(k) is int for k in predictions[arm])
                  and digest(predictions[arm])==x['oof_prediction_sha256'][arm],
                  'independent historical prediction recreation differs')
            recomputed=score(rows,predictions[arm]);saved=x['arm_metrics'][arm]
            for key in ('candidates','questions','source_groups'):
                check(saved[key]==recomputed[key],'model source denominator changed')
            for key in ('f1_a','exact_match','accuracy'):
                check(abs(saved[key]-recomputed[key])<=1e-12,
                      'independently computed MultiRC label metric disagrees')
    return dict(schema='hepta.bridge.v78.independent-real-label-review.v1',
       status='ARCHIVED_SOURCE_ONLY_REPLAY_PASS_NO_PRODUCTION',
       original_v6_sha256=V6_SHA,sources=16,original_cases=827,real_archived_labels_used=True,
       trained_two_parameter_calibrators=12,all_three_seed_fold_predictions_replayed=True,
       torch_imported=False,prospective_quality_verified=False,
       new_granite_forward_executed=False,model_selected=False,
       production_authorized=False,cell_split_production_authorized=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('original','result','review'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    check(not a.review.exists() and not a.review.is_symlink(),'review result must be write-once')
    result=verify(a.original,read_json(a.result))
    with a.review.open('x') as f:
        json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps(dict(status=result['status'],reviewed=True),sort_keys=True))

if __name__=='__main__':main()
