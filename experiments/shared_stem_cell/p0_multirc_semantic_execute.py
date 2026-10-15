#!/usr/bin/env python3
"""Physical frozen Stem and genuine-label Head training; no held-label access.

Uses preexisting E1 CPU full-weight loaders; unsupported weights abort with
no fallback. One process/one model, no production authorization.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import resource
import time

from p0_multirc_semantic_material import (read, save, sha, canonical, validate,
                                           Invalid, SCHEMA)
from p0_real_reader_cpu import (COMPACT_REVISIONS, LAYA_SHA, MODELS,
                                 tensor_sha, do_laya)

SEED = 20261015
STEPS = 40
LR = 0.1
TEMPS = (0.5,0.75,1.,1.5,2.,3.)


def fit_head(fit, blind, features, width):
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(1)
    if type(features) is not dict or set(features)!={r['case_id'] for r in fit+blind}:
        raise Invalid('missing actual Encoder features')
    if any(len(features[r['case_id']])!=width or
           any(not math.isfinite(float(x)) for x in features[r['case_id']])
           for r in fit+blind):
        raise Invalid('wrong feature width or nonfinite actual observation')
    training=[r for r in fit if r['split']=='train' and r['condition']=='original']
    calibration=[r for r in fit if r['split']=='calibration' and r['condition']=='original']
    if len(training)<24 or len(calibration)<8 or {r['label'] for r in training}!={0,1} or {r['label'] for r in calibration}!={0,1}:
        raise Invalid('incomplete authentic positive/negative training and calibration')
    def X(rows):return torch.tensor([features[r['case_id']] for r in rows],dtype=torch.float32)
    tx,cx=X(training),X(calibration)
    ty=torch.tensor([r['label'] for r in training],dtype=torch.long)
    cy=torch.tensor([r['label'] for r in calibration],dtype=torch.long)
    torch.manual_seed(SEED)
    model=torch.nn.Linear(width,2)
    frozen=copy.deepcopy(model).eval()
    old_digest=tensor_sha(frozen)
    count=sum(p.numel() for p in model.parameters())
    if count!=2*width+2 or count>2048:
        raise Invalid('unexpected trained Head geometry')
    begin=time.perf_counter_ns()
    optimizer=torch.optim.SGD(model.parameters(),lr=LR)
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        loss=F.cross_entropy(model(tx),ty)
        if not torch.isfinite(loss).item():
            raise Invalid('nonfinite training loss')
        loss.backward()
        optimizer.step()
    train_ms=(time.perf_counter_ns()-begin)/1e6
    if tensor_sha(frozen)!=old_digest or tensor_sha(model)==old_digest:
        raise Invalid('frozen control modified or zero actual updates')
    out={}
    for name,head in (('frozen_head',frozen),('trained_head',model.eval())):
        with torch.inference_mode():
            temp=min(TEMPS,key=lambda t:float(F.cross_entropy(head(cx)/t,cy)))
            predictions=[]
            for row in blind:
                t0=time.perf_counter_ns()
                prob=float(F.softmax(head(X([row]))/temp,dim=-1)[0,1])
                if not math.isfinite(prob) or not 0<=prob<=1:
                    raise Invalid('nonfinite Head probability')
                predictions.append({'case_id':row['case_id'], 'view_sha256':row['view_sha256'],
                                    'positive_probability':prob,
                                    'head_request_ms':(time.perf_counter_ns()-t0)/1e6})
        out[name]={'head_sha256':tensor_sha(head),'temperature':temp,
                   'predictions':predictions}
    return {'parameter_count':count,'initial_frozen_head_sha256':old_digest,
            'optimizer':'torch.optim.SGD','steps':STEPS,'seed':SEED,'learning_rate':LR,
            'head_training_ms':train_ms,'fit_train_case_ids_sha256':sha(canonical([r['case_id'] for r in training])),
            'calibration_case_ids_sha256':sha(canonical([r['case_id'] for r in calibration])),
            'train_labels_only_in_gradient':True, 'controls':out}


def run(fit_doc,blind_doc,model,args):
    fit,blind=validate(fit_doc,blind_doc)
    if model not in MODELS:
        raise Invalid('unknown original research model')
    if model!='laya421_nochange' and args.compact_checkout is None:
        raise Invalid('missing original vetted compact source')
    if model=='embeddinggemma_2_text' and (args.gemma_checkout is None or args.gemma_manifest is None):
        raise Invalid('missing pinned Gemma complete model manifest')
    start=time.perf_counter_ns();cpu=time.process_time_ns()
    if model=='laya421_nochange':
        observed=do_laya(blind)
        head=None
        checked=None
    else:
        from e1_public_triplet_real_cpu import encode_pretrained
        revision,width=COMPACT_REVISIONS[model]
        vectors,tokens,feature_digests,physical=encode_pretrained(fit+blind,model,
                         args.compact_checkout,args.gemma_checkout,args.gemma_manifest)
        if set(tokens)!={r['case_id'] for r in fit+blind} or any(type(v) is not int or not 1<=v<=512 for v in tokens.values()):
            raise Invalid('missing or silently truncated original pretrained tokens')
        trained=fit_head(fit,blind,vectors,width)
        head=trained
        checked={'source_feature_sha256':sha(canonical(feature_digests)),
                 'source_token_counts_sha256':sha(canonical(tokens)),
                 'physical_encoder_api_requests':physical.get('local_model_api_requests'),
                 'model_load_ms':physical.get('load_ms'),
                 'encoder_ms_by_case':physical.get('encode_ms_by_case'),
                 'complete_mmbert_weight_bytes_checked':(
                  physical.get('mmbert_all_serialized_weights_byte_verified') if model=='mmbert_small' else None),
                 'source_checkpoint_sha256':physical.get('mmbert_whole_pretrained_checkpoint_sha256')}
        observed={'model':model,'model_revision':revision,'feature_width':width,
                  'head_mode':'same-initialization-frozen-vs-genuine-human-supervised-sgd',
                  'training':trained,'control':trained['controls']}
    observed.update({'schema':'hepta.p0.multirc-original-semantic-physical.v1',
                     'dataset_schema':SCHEMA,'panel_id':fit_doc['metadata']['panel_id'],
                     'fit_material_sha256':sha(canonical(fit_doc)),
                     'blind_material_sha256':sha(canonical(blind_doc)),
                     'eval_blind_rows':len(blind),'complete_source_profiles':checked,
                     'actual_pretrained_local_weights_claimed':True,
                     'physical_model_origin_independently_signed':False,
                     'independent_human_adjudication_of_generated_counterfactual':False,
                     'three_future_windows_verified':False,
                     'local_process_wall_ms':(time.perf_counter_ns()-start)/1e6,
                     'local_process_cpu_ms':(time.process_time_ns()-cpu)/1e6,
                     'local_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                     'model_selection_permitted':False,'production_promotion_permitted':False,
                     'authority':'DENY_ALL'})
    return observed


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--fit',type=Path,required=True)
    p.add_argument('--blind',type=Path,required=True)
    p.add_argument('--model',choices=MODELS,required=True)
    p.add_argument('--compact-checkout',type=Path)
    p.add_argument('--gemma-checkout',type=Path)
    p.add_argument('--gemma-manifest',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():
        raise FileExistsError('prediction receipt must be create-only')
    receipt=run(read(a.fit),read(a.blind),a.model,a)
    save(a.output,receipt)
    print(json.dumps({'model':a.model,'prediction_sha256':sha(canonical(receipt)),
                      'no_release':True,'human_future_semantics_not_qualified':True}))

if __name__=='__main__':main()
