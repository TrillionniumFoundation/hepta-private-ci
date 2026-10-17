"""Frozen live Granite text route -> physically selective DINO vision research.

RESEARCH_ONLY/DENY_ALL: this is a text+vision FEATURE-only CPU study,
not final task inference, Hepta product integration or NDU evaluation.
The model process cannot access original published predictions or TEST answers;
its source-only route gate is independently reconstructed from live text scores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time

import v28_physical_lazy_vision as physical
import v29_route_only as route

SCHEMA = 'hepta.stem.v30.live-text-selective-vision-cost.v1'
GRANITE_REPO = 'ibm-granite/granite-embedding-97m-multilingual-r2'
GRANITE_REV = '835ad14087e140460703cf0fae09f97d469d65c2'
TEXT_BATCH = 16
TEXT_ITEMS_PER_CASE = 5
TEXT_WIDTH = 384
TEXT_FORWARDS = 20
PREDICTION_SCALE = 8.0
MAX_TEXT_PARITY = 0.0001


def softmax(logits):
    physical.require(type(logits) in (tuple, list) and len(logits)==4 and
                     all(type(x) in (float,int) and math.isfinite(x) for x in logits),
                     'nonfinite or incomplete original text choice scores')
    scaled=[PREDICTION_SCALE*float(x) for x in logits]
    pivot=max(scaled)
    exp=[math.exp(x-pivot) for x in scaled]
    total=math.fsum(exp)
    physical.require(math.isfinite(total) and total>0, 'nonfinite probability normalization')
    out=tuple(x/total for x in exp)
    physical.require(abs(math.fsum(out)-1.)<=1e-10, 'invalid text probability vector')
    return out


def route_from_live_text(cases, probabilities, sealed_rows):
    """Source-case ordering and selection ONLY from new text inference.

    Frozen V29 truth-free trigger flags serve as a strict *conformance gate*,
    not as input features, trained targets, or candidate labels.
    """
    physical.require(type(cases) is list and len(cases)==physical.N_CASES
                     and type(sealed_rows) is list and len(sealed_rows)==physical.N_CASES
                     and type(probabilities) is dict and len(probabilities)==physical.N_CASES,
                     'incorrect source or physical text cohort')
    source_ids, route_ids = set(), set()
    selected=[]
    for source,expected in zip(cases,sealed_rows):
        physical.require(type(source) is dict and physical.h64(source.get('id'))
                         and physical.h64(source.get('group'))
                         and type(expected) is dict and set(expected)==route.ROUTE_COLUMNS
                         and source['id']==expected['id'] and source['group']==expected['group']
                         and source['id'] not in source_ids and expected['id'] not in route_ids,
                         'misordered, reused or substituted route/source identity')
        source_ids.add(source['id']);route_ids.add(expected['id'])
        p=probabilities.get(source['id'])
        physical.require(type(p) in (tuple,list) and len(p)==4
                         and all(type(x) is float and math.isfinite(x) and 0<=x<=1 for x in p)
                         and abs(math.fsum(p)-1.)<1e-6,
                         'unobserved or malformed real text score')
        a,b=sorted(p,reverse=True)[:2]
        chosen=(a-b)<0.005
        physical.require(type(expected['trigger_vision']) is bool
                         and expected['trigger_vision'] is chosen,
                         'actual text inference contradicts frozen label-blind route')
        if chosen:selected.append(source)
    physical.require(set(probabilities)==source_ids and len(selected)==physical.N_TRIGGER,
                     'live text route is not exactly the original 21/64 policy')
    return selected


def encode_text_scores(backend, cases, *, clock=time.perf_counter_ns, cpu=time.process_time_ns):
    """Run original question plus four choices through the *existing* pinned
    LocalEncoder. Exact native CLS/L2 semantics, never approximate a cached text
    vector with an image Encoder output. No TEST labels/cached predictions.
    """
    import torch
    import torch.nn.functional as F
    from e3_granite_dino_real import input_prompts
    physical.require(type(cases) is list and len(cases)==physical.N_CASES,
                     'exact original test sources needed')
    prompts=[]
    for source in cases:
        physical.require(type(source) is dict and source.get('split')=='test'
                         and physical.h64(source.get('id')) and type(source.get('choices')) is list
                         and len(source['choices'])==4 and 'label' not in source
                         and 'answer' not in source,
                         'model input changed or TEST answer exposed')
        group=input_prompts(source)
        physical.require(len(group)==TEXT_ITEMS_PER_CASE and
                         all(type(p) is str and 0 < len(p.encode('utf-8'))<=12000 for p in group),
                         'unbounded or incomplete live text prompt')
        prompts.extend(group)
    physical.require(len(prompts)==physical.N_CASES*TEXT_ITEMS_PER_CASE,
                     'incomplete live input vectorization')
    first=getattr(backend,'forward_calls',None)
    physical.require(type(first) is int and first>=0, 'backend text forward counter unavailable')
    wall0,cpu0=clock(),cpu()
    features=[]
    for k in range(0,len(prompts),TEXT_BATCH):
        batch=backend.encode(prompts[k:k+TEXT_BATCH],pooling='cls-first-token')
        physical.require(isinstance(batch,torch.Tensor) and batch.device.type=='cpu'
                         and batch.dtype==torch.float32 and
                         tuple(batch.shape)==(len(prompts[k:k+TEXT_BATCH]),TEXT_WIDTH)
                         and bool(torch.isfinite(batch).all()),
                         'text backend yielded false/invalid materialization')
        features.append(batch)
    physical.require(backend.forward_calls-first==TEXT_FORWARDS,
                     'unverified real Granite batch call count')
    embeddings=F.normalize(torch.cat(features).view(physical.N_CASES,5,TEXT_WIDTH),dim=-1)
    similarity=torch.einsum('nd,ncd->nc',embeddings[:,0],embeddings[:,1:])
    values=similarity.detach().cpu().tolist()
    physical.require(len(values)==physical.N_CASES and
                     all(len(row)==4 for row in values),'incorrect original choice projection')
    scores={r['id']:softmax(v) for r,v in zip(cases,values)}
    wall,used=clock()-wall0,cpu()-cpu0
    physical.require(type(wall) is int and wall>0 and type(used) is int and used>=0,
                     'missing real text execution time')
    return {'text_items':len(prompts),'text_batches':backend.forward_calls-first,
            'text_cpu_ns':used,'text_wall_ns':wall},scores


def study_arms(source_rows,sealed_rows,process_text,process_vision):
    """ABBA same-host, same-loaded-pair measurement; repeat the complete text
    route in *every* arm. No reused cached text/output or historic image class.
    """
    physical.require(len(source_rows)==physical.N_CASES and
                     len(sealed_rows)==physical.N_CASES,'incomplete original sources')
    ids={x['id'] for x in source_rows}
    selected_ids={p['id'] for p in sealed_rows if p['trigger_vision']}
    physical.require(len(ids)==physical.N_CASES and len(selected_ids)==physical.N_TRIGGER,
                     'malformed original source schedule')
    observations=[];text_outputs=[]; full=[];selective=[]
    for name in ('all64','conditional21','conditional21','all64'):
        start_wall=time.perf_counter_ns(); start_cpu=time.process_time_ns()
        text_obs,probs=process_text(source_rows)
        chosen=route_from_live_text(source_rows,probs,sealed_rows)
        request=source_rows if name=='all64' else chosen
        image_obs,images=process_vision(request)
        wall=time.perf_counter_ns()-start_wall
        cpu=time.process_time_ns()-start_cpu
        physical.require(set(probs)==ids and set(images)==(ids if name=='all64' else selected_ids),
                         'wrong full vs selective feature inventory')
        physical.require(text_obs['text_items']==320 and text_obs['text_batches']==20
                         and image_obs['items']==len(request)
                         and image_obs['batches']==(8 if name=='all64' else 3),
                         'missing physical text or DINO forward receipt')
        physical.require(type(wall) is int and wall>0 and type(cpu) is int and cpu>=0
                         and wall>=text_obs['text_wall_ns']
                         and cpu>=text_obs['text_cpu_ns']
                         and wall>=image_obs['wall_ns']
                         and cpu>=image_obs['cpu_ns'],
                         'unobserved sequence timing')
        # The two phase observations contain their own timing fields.  Do NOT
        # unpack image_obs over the end-to-end feature-time clock: that silently
        # overwrites total cpu_ns/wall_ns with DINO-only measurements.  Treat
        # total, text and vision as three independently named observed clocks.
        physical.require(cpu>=text_obs['text_cpu_ns']+image_obs['cpu_ns']
                         and wall>=text_obs['text_wall_ns']+image_obs['wall_ns'],
                         'total feature clocks do not include both model phases')
        observations.append({'arm':name, 'cpu_ns':cpu, 'wall_ns':wall,
                             'text_items':text_obs['text_items'],
                             'text_batches':text_obs['text_batches'],
                             'text_cpu_ns':text_obs['text_cpu_ns'],
                             'text_wall_ns':text_obs['text_wall_ns'],
                             'items':image_obs['items'],
                             'batches':image_obs['batches'],
                             'media_bytes_read':image_obs['media_bytes_read'],
                             'vision_cpu_ns':image_obs['cpu_ns'],
                             'vision_wall_ns':image_obs['wall_ns']})
        text_outputs.append(probs)
        (full if name=='all64' else selective).append(images)
    max_text=max(abs(a[k][j]-b[k][j])
                 for a in text_outputs for b in text_outputs
                 for k in ids for j in range(4))
    max_image=max(abs(a[k][j]-b[k][j])
                  for a in full for b in selective
                  for k in selected_ids for j in range(TEXT_WIDTH))
    physical.require(max_text<=MAX_TEXT_PARITY and max_image<=MAX_TEXT_PARITY,
                     'repeated physical feature output drift')
    return observations,max_text,max_image


def run(args):
    for bad in ('HELD_SHA','HEPTA_V24_ORIGINAL_ZIP','HEPTA_V25_ORIGINAL_LABELS'):
        physical.require(bad not in os.environ,'source-target leak in model process')
    physical.require(not (args.source_dir/'private_labels').exists(),
                     'TEST-label folder present in physical model runner')
    physical.require(not (args.source_dir/'inputs'/'fit_labels.jsonl').exists(),
                     'TRAIN label file must be physically removed before model run')
    from e3_scienceqa_contract import DINO,GRANITE,validate_source,read_pinned
    from e3_granite_dino_real import FrozenVision, verified_acquisition
    from execution import LocalEncoder
    physical.require(DINO==(physical.DINO_REPO,physical.DINO_REVISION)
                     and GRANITE==(GRANITE_REPO,GRANITE_REV),
                     'frozen model owner identity mismatch')
    raw=physical.protected_read(args.plan)
    sealed_rows=route.validate_model_plan(raw)
    src=physical.protected_read(args.source_dir/'inputs'/'sources.jsonl')
    physical.require(physical.sha(src)==physical.STEM_SOURCE,
                     'original source material missing/mismatch')
    sources=[physical.strict_json(row) for row in src.splitlines()]
    validate_source(sources)
    seals=physical.strict_json(physical.protected_read(args.source_dir/'source-seals.json'))
    all_rows,_=physical.align_source(sealed_rows,sources,seals)
    physical.require(args.weights_dir.is_absolute() and not args.weights_dir.exists(),
                     'weights stage must be absolute/create-only')
    # Acquisition and model load are observed once, before the balanced warm
    # comparisons. No alternate code path for unqualified text/vision checkpoints.
    start=time.perf_counter_ns()
    granite_manifest=verified_acquisition(*GRANITE,args.weights_dir/'granite')
    dino_manifest=verified_acquisition(*DINO,args.weights_dir/'dino')
    text_model=LocalEncoder(args.weights_dir/'granite',granite_manifest,maximum_tokens=512)
    vision=FrozenVision(args.weights_dir/'dino',dino_manifest)
    load_wall_ns=time.perf_counter_ns()-start
    physical.require(text_model.forward_calls==0 and vision.calls==0,
                     'frozen models must start without hidden prefill')
    training=next(x for x in sources if x['split']=='train')
    # Warm-up is source-only, physically executes both models once. No TRAIN
    # label access or TEST image access in this preflight.
    from e3_granite_dino_real import input_prompts
    text_model.encode(input_prompts(training),pooling='cls-first-token')
    vision.encode([read_pinned(args.source_dir/'images'/training['image'],training['image'],maximum=8*1024*1024)])
    physical.require(text_model.forward_calls==1 and vision.calls==1,'warmup was not physical')
    def text_fn(rows):return encode_text_scores(text_model,rows)
    def visual_fn(rows):
        return physical.execute_arm(vision,rows,args.source_dir/'images',
               read_bytes=lambda p,d:read_pinned(p,d,maximum=8*1024*1024))
    try:
        observations,text_diff,visual_diff=study_arms(all_rows,sealed_rows,text_fn,visual_fn)
        text_model.close();vision.close()
    finally:
        del text_model,vision
    physical.require(sum(x['text_batches'] for x in observations)==80 and
                     sum(x['batches'] for x in observations)==22,
                     'missing entire paired physical model workload')
    rss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    physical.require(rss>0,'no observed resident-memory high watermark')
    result={'schema':SCHEMA,'authority':'DENY_ALL','disposition':'HOLD_NO_CELL_OR_MODEL_SELECTION',
            'production_authorized':False,'stem_winner_verified':False,
            'frozen_route_plan_sha256':route.MINIMAL_SHA256,
            'historical_archive_sha256':physical.ARCHIVE_SHA,
            'actual_live_text_route_from_model':True,
            'cached_vision_predictions_used_for_route':False,
            'real_test_labels_opened':False,'new_training_updates':0,
            'real_original_source_case_count':physical.N_CASES,
            'selected_vision_cases':physical.N_TRIGGER,
            'real_text_model_repo':GRANITE_REPO,'real_text_model_revision':GRANITE_REV,
            'real_vision_model_repo':physical.DINO_REPO,'real_vision_model_revision':physical.DINO_REVISION,
            'text_model_manifest_sha256':physical.sha(physical.canonical(granite_manifest)),
            'vision_model_manifest_sha256':physical.sha(physical.canonical(dino_manifest)),
            'actual_pretrained_text_and_vision_forwards':True,
            'warmup_text_batches':1,'warmup_vision_batches':1,
            'model_acquisition_and_load_wall_ns':load_wall_ns,
            'arm_traces':observations,'text_score_max_abs_drift':text_diff,
            'image_feature_max_abs_drift':visual_diff,
            'process_peak_rss_kib_not_incremental':rss,
            'energy_joules':None,'gpu_peak_bytes':None,
            'independent_future_windows':0,
            'full_product_end_to_end_savings_proven':False,
            'original_task_accuracy_recomputed_this_run':False,
            'physical_cpu_execution_owner':'original-frozen-granite-and-dinov2'}
    physical.safe_write(args.output,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--source-dir',type=Path,required=True)
    p.add_argument('--weights-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    d=run(p.parse_args())
    print(json.dumps({'authority':'DENY_ALL','actual_live_text_route_from_model':d['actual_live_text_route_from_model'],
                      'physical_arm_totals':[a['cpu_ns'] for a in d['arm_traces']],
                      'production_authorized':False},sort_keys=True))
