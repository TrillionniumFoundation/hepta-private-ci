"""Review ORIGINAL physically executed E3 image effects without leaking or using labels.

An argmax change or probability shift is not task correctness or causal image
necessity. Reconstructs no model inputs; observed effects remain descriptive.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
from scienceqa_independent_rejudge_v5 import (
    ARMS, V5Error, canonical, need, parse, read_archive, sha,
    PRED_SHA, SOURCE_SHA,
)


def review(original):
    need(sha(original['sealed-source-bound-predictions.json'])==PRED_SHA,
         'original source prediction SHA drift')
    data=parse(original['sealed-source-bound-predictions.json'])
    need(data.get('source_sha256')==SOURCE_SHA and data.get('arms')==list(ARMS)
         and data.get('held_labels_visible_to_inference') is False and
         data.get('production_accepted') is False,'unregistered source/arms')
    rows=data.get('predictions')
    need(type(rows) is list and len(rows)==64,'missing original 64 source predictions')
    seen=set(); observations={a:{'flip':0,'js':[],'tv':[],'margin':[],'entropy':[]} for a in ARMS}
    for item in rows:
        need(type(item) is dict and set(item)=={'id','group','split','source_input_sha256','arms'} and
             item['split']=='test' and item['id'] not in seen and
             type(item['arms']) is dict and set(item['arms'])==set(ARMS),
             'incomplete original per-case arm roster')
        seen.add(item['id'])
        base=item['arms']['text_only']
        need(item['arms']['image_masked']==base,'image mask does not reproduce text-only')
        for arm in ARMS:
            q=item['arms'][arm]
            need(type(q) is list and len(q)==4 and all(type(v) in (float,int)
                and math.isfinite(v) and 0<=v<=1 for v in q) and
                abs(math.fsum(q)-1)<1e-6,'noncanonical original probability')
            mid=[(p+t)/2 for p,t in zip(base,q)]
            js=.5*math.fsum(p*math.log(p/m) for p,m in zip(base,mid) if p>0)+\
               .5*math.fsum(t*math.log(t/m) for t,m in zip(q,mid) if t>0)
            tv=math.fsum(abs(p-t) for p,t in zip(base,q))/2
            sorted_q=sorted(q,reverse=True)
            obj=observations[arm]
            obj['flip']+=int(max(range(4),key=lambda k:(base[k],-k)) !=
                             max(range(4),key=lambda k:(q[k],-k)))
            obj['js'].append(js);obj['tv'].append(tv)
            obj['margin'].append(sorted_q[0]-sorted_q[1])
            obj['entropy'].append(-math.fsum(p*math.log(p) for p in q if p>0))
    need(len(seen)==64,'duplicate or missing original test case')
    result={}
    for name,record in observations.items():
        result[name]={'argmax_flips_vs_text':record['flip'],
                      'mean_jensen_shannon_nats':math.fsum(record['js'])/64,
                      'mean_total_variation':math.fsum(record['tv'])/64,
                      'mean_prediction_margin':math.fsum(record['margin'])/64,
                      'mean_entropy_nats':math.fsum(record['entropy'])/64}
    need(result['text_only']['argmax_flips_vs_text']==0 and
         result['image_masked']['argmax_flips_vs_text']==0 and
         result['calibrated_fusion']['argmax_flips_vs_text']==0,
         'masked or zero-weight calibration control changed predictions')
    return {'schema':'hepta.stem.original-e3-labelblind-vision-sensitivity.v5',
            'source_sha256':SOURCE_SHA,'original_prediction_sha256':PRED_SHA,
            'original_test_count':64,'model_prediction_arms':result,
            'original_model_forward_in_this_review':False,
            'heldout_labels_accessed':False,
            'image_effect_on_predictions_observed':True,
            'visual_necessity_or_correctness_proven':False,
            'independent_human_adjudication':False,
            'new_training_or_update':False,
            'production_authorized':False,'stem_selected':False,
            'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--archive',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    result=review(read_archive(args.archive))
    need(not args.output.exists() and not args.output.is_symlink(),'no overwrite')
    with args.output.open('xb') as fd:
        fd.write(canonical(result));fd.flush();os.fsync(fd.fileno())
    print('ORIGINAL_IMAGE_EFFECT_OBSERVED / NO-LABEL NO-GO')

if __name__=='__main__':main()
