"""Independent ORIGINAL ZIP-based recomputation of E9 four-fold held-out score.

Read-only reviewer: does not import E9 fit/evaluator/proposer or E7 first scorer.
Reviews only the one AG News historical panel, never authenticates label signer.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path

from e7_second_opinion import (HIST_SHA, REAL_SHA, archive, group_labels,
                               model_predictions)

ARMS = ('granite_only','mmbert_only','gate_conf_075','gate_conf_090','gate_conf_098')
THRESHOLD = {'gate_conf_075':.75, 'gate_conf_090':.9,'gate_conf_098':.98}


def must(ok, why):
    if not ok:
        raise ValueError(why)


def strict_json(path):
    raw=Path(path).read_bytes()
    must(0<len(raw)<=2_000_000,'invalid bounded reviewer input')
    def pairs(ordered):
        out={}
        for k,v in ordered:
            must(k not in out,'duplicate JSON key')
            out[k]=v
        return out
    parsed=json.loads(raw,object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    return parsed,sha256(raw).hexdigest()


def review(historical, physical, prelabel_file, scored_file, fits, output):
    """Recompute each outcome from two ORIGINAL real model archived reports."""
    must(type(fits) in (list,tuple) and len(fits)==4,'exactly four folds required')
    old=archive(historical,HIST_SHA)
    new=archive(physical,REAL_SHA)
    truth=group_labels(old)
    probabilities=model_predictions(new,truth)
    pre,pre_sha=strict_json(prelabel_file)
    result,result_sha=strict_json(scored_file)
    must(type(pre) is dict and pre.get('schema')=='hepta.e9.prelabel-4fold-physical-v1'
         and pre.get('labels_seen_during_prelabel') is False
         and pre.get('physical_archive_sha256')==REAL_SHA
         and pre.get('production_accepted') is False,
         'wrong purported label-blind source')
    precases=pre.get('rows')
    must(type(precases) is list and len(precases)==128,'incomplete original source-only panel')
    lookup={}
    for r in precases:
        must(type(r) is dict and type(r.get('case_id')) is str and r['case_id'] not in lookup,
             'invalid or duplicated source-only case')
        lookup[r['case_id']]=r
    must(set(lookup)==set(truth),'case source changed')
    groups=[truth[cid][0] for cid in truth]
    must(len(set(groups))==128,'duplicate original source group')
    ordered=sorted(groups,key=lambda g:sha256(('hepta-e9-folds-20261015-v1:'+g).encode()).digest())
    fold={gid:index//32 for index,gid in enumerate(ordered)}
    chosen={}
    frozen={}
    for path in fits:
        f,_=strict_json(path)
        must(type(f) is dict and f.get('schema')=='hepta.e9.train-only-selected-fold-v1'
             and f.get('prelabel_sha256')==pre_sha and f.get('authority')=='DENY_ALL'
             and f.get('holdout_labels_seen') is False
             and f.get('production_accepted') is False,'invalid frozen selection')
        k,a=f.get('fold'),f.get('selected_arm')
        must(type(k) is int and 0<=k<4 and k not in chosen and a in ARMS,
             'duplicated/missing/unknown frozen arm')
        chosen[k]=a
        frozen[k]=f
    must(set(chosen)==set(range(4)),'incomplete model fold roster')
    # Completely independent rebuild of the 96 original training outcomes
    # (only after the four training decisions are sealed).
    for k in range(4):
        tlabels={cid:row[2] for cid,row in truth.items() if fold[row[0]] != k}
        must(len(tlabels)==96,'train-fold source leak')
        sealed_train={'schema':'hepta.e9.train-only-fold-v1','authority':'DENY_ALL',
                      'fold':k,'prelabel_sha256':pre_sha,
                      'historical_archive_sha256':HIST_SHA,'holdout_labels_included':False,
                      'rows':[{'case_id':cid,'group_id':truth[cid][0],'label':tlabels[cid]}
                              for cid in sorted(tlabels)]}
        digest_train=sha256(json.dumps(sealed_train,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
        must(frozen[k].get('train_source_sha256')==digest_train,
             'forged training source evidence')
        training={}
        for arm in ARMS:
            wins=0;cost=0;extra_calls=0;brier=Fraction(0)
            for cid,y in tlabels.items():
                p,gt=probabilities['granite97'][cid]
                q,mt=probabilities['mmbert_small'][cid]
                if arm=='granite_only':prob,spent,paid=p,gt,0
                elif arm=='mmbert_only':prob,spent,paid=q,mt,0
                else:
                    paid=int(max(p,1-p)<THRESHOLD[arm]);prob=q if paid else p
                    spent=gt+(mt if paid else 0)
                wins+=int((prob>=.5)==bool(y))
                brier+=(Fraction(str(prob))-y)**2
                cost+=spent;extra_calls+=paid if arm!='mmbert_only' else 0
            training[arm]={'correct':wins,'n':96,'brier':float(brier/96),
                           'time_proxy_ns':cost,
                           'hypothetical_secondary_calls':extra_calls}
        winner=min(ARMS,key=lambda a:(-training[a]['correct'],
                   training[a]['brier'],training[a]['time_proxy_ns'],ARMS.index(a)))
        must(frozen[k].get('train_scores')==training and chosen[k]==winner,
             'frozen fold not independently justified by original training data')
    test_correct=test_cost=extra=base_correct=base_cost=win=loss=0
    test_brier=base_brier=Fraction(0)
    for cid, (gid,input_sha,label) in truth.items():
        row=lookup[cid]
        k=fold[gid]
        must((row.get('group_id'),row.get('joint_input_digest'))==(gid,input_sha)
             and type(row.get('fold')) is int and row['fold']==k,
             'mutated original source group or assignment')
        p,tg=probabilities['granite97'][cid]
        q,tm=probabilities['mmbert_small'][cid]
        must(row.get('granite_prob')==p and row.get('mmbert_prob')==q,
             'prelabel does not match original pretrained predictions')
        arm=chosen[k]
        if arm=='granite_only':a,cc,step=p,tg,0
        elif arm=='mmbert_only':a,cc,step=q,tm,0
        else:
            step=int(max(p,1-p)<THRESHOLD[arm]);a=q if step else p
            cc=tg+(tm if step else 0)
        routes=row.get('routing')
        must(type(routes) is dict and type(routes.get(arm)) is dict
             and routes[arm].get('probability')==a
             and routes[arm].get('secondary_used') is bool(step if arm!='mmbert_only' else 1),
             'route seal changed after original model execution')
        selected=(a>=.5)==bool(label)
        baseline=(p>=.5)==bool(label)
        test_correct+=int(selected);base_correct+=int(baseline)
        win+=int(selected and not baseline);loss+=int(baseline and not selected)
        test_brier+=(Fraction(str(a))-label)**2
        base_brier+=(Fraction(str(p))-label)**2
        test_cost+=cc;base_cost+=tg
        extra+=step if arm!='mmbert_only' else 0
    must(type(result) is dict and result.get('schema')=='hepta.e9.fourfold-source-group-crossfit-retrospective.v1'
         and result.get('authority')=='DENY_ALL'
         and result.get('prelabel_sha256')==pre_sha
         and result.get('production_accepted') is False
         and result.get('prospective_utility_accepted') is False
         and result.get('source_origin_independently_signed') is False,
         'improper primary score or authority')
    must(result.get('selected_per_fold')=={str(k):chosen[k] for k in sorted(chosen)},
         'primary fold choices changed')
    r=result.get('trained_route');b=result.get('granite_baseline')
    must(type(r) is dict and type(b) is dict,'missing primary full-score rows')
    integers={
        'correct':test_correct,'archived_per_case_wall_proxy_ns_sum':test_cost,
        'hypothetical_extra_mmbert_calls':extra,
        'paired_improvements_from_granite':win,
        'paired_regressions_from_granite':loss,
    }
    for field,value in integers.items():
        must(type(r.get(field)) is int and r[field]==value,'primary score counts differ')
    must(type(b.get('correct')) is int and b['correct']==base_correct and
         type(b.get('archived_per_case_wall_proxy_ns_sum')) is int and
         b['archived_per_case_wall_proxy_ns_sum']==base_cost,
         'baseline count/proxy cost drift')
    for row,field,value in ((r,'accuracy',test_correct/128),
                            (r,'brier',float(test_brier/128)),
                            (b,'accuracy',base_correct/128),
                            (b,'brier',float(base_brier/128))):
        must(type(row.get(field)) is float and math.isclose(row[field],value,abs_tol=1e-14,rel_tol=0),
             'primary aggregate metric drift')
    statement={
        'schema':'hepta.e9.independent-original-two-ZIP-crossfit-audit.v1',
        'authority':'DENY_ALL', 'prelabel_sha256':pre_sha,
        'primary_report_sha256':result_sha, 'source_archive_sha256':HIST_SHA,
        'physical_archive_sha256':REAL_SHA,
        'original_128_case_predictions_and_labels_recomputed':True,
        'train_only_source_group_fold_choices_frozen':True,
        'selected_per_fold':{str(k):chosen[k] for k in sorted(chosen)},
        'crossfit_correct':test_correct,'granite_correct':base_correct,
        'crossfit_secondary_model_calls_hypothetical':extra,
        'crossfit_proxy_time_ns':test_cost,'granite_proxy_time_ns':base_cost,
        'paired_improved':win,'paired_worsened':loss,
        'crossfit_Brier':float(test_brier/128),'granite_Brier':float(base_brier/128),
        'actual_new_pretrained_forwards':0,
        'independently_observed_future_time_success':False,
        'online_system2_gain_certified':False,
        'production_accepted':False,
    }
    raw=json.dumps(statement,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    with Path(output).open('xb') as f:f.write(raw)
    return statement


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('historical','physical','prelabel','scored','output'):
        ap.add_argument('--'+arg,required=True)
    ap.add_argument('--fits',required=True,nargs=4)
    c=ap.parse_args()
    result=review(c.historical,c.physical,c.prelabel,c.scored,c.fits,c.output)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
