"""P0.8 physical shared mmBERT Encoder and resource-matched Head training.

Actual CLI has NO synthetic/model-bypass mode: it downloads one revision-pinned
safetensors file, checks its bytes, performs real CPU forwards, and then fits
Head candidates. Local unit tests exercise the pure numerical subroutines only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path

import numpy as np
from p08_cohort import (SCHEMA,MODEL_REPO,MODEL_REV,MODEL_SAFETENSORS_SHA,
                        MODEL_TOKENIZER_SHA,Denied,require,strict,dump,sha,
                        put_private,read_regular,route,verify_panel)

SEEDS=(101,211,307)
STEPS=512
LR=0.05
WEIGHT_DECAY=0.0001
FEATURE_WIDTH=384
CLASSES=4
PARAMS_PER_SLOT=CLASSES*(FEATURE_WIDTH+1)
TEMPERATURES=(0.125,0.25,0.5,1.,2.,4.,8.,16.)
TRAINED=('shared','split','random_route')
ARMS=('shared','split','random_route','frozen','type_prior','global_prior',
      'centroid','centroid_loo','split_zero','split_swap')


def softmax(x: np.ndarray) -> np.ndarray:
    x=np.asarray(x,dtype=np.float64)
    require(x.shape==(4,) and np.isfinite(x).all(),'invalid scores')
    v=np.exp(x-np.max(x));return v/v.sum()


def normalize(v: np.ndarray) -> np.ndarray:
    v=np.asarray(v,dtype=np.float64)
    require(v.ndim==2 and v.shape[1]==FEATURE_WIDTH and np.isfinite(v).all(),'invalid numeric Encoder features')
    norms=np.linalg.norm(v,axis=1)
    require(np.all(norms>1e-12),'degenerate pretrained Encoder vectors')
    return v/norms[:,None]


def route_two_cluster(train: np.ndarray, all_rows: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    """Unsupervised routing trained on FIT-only features; never reads labels or tests."""
    require(train.shape==(64,FEATURE_WIDTH) and all_rows.ndim==2 and
            all_rows.shape[1]==FEATURE_WIDTH,'clustering geometry mismatch')
    first=train[0].copy()
    distances=np.square(train-first).sum(axis=1)
    second=train[int(np.argmax(distances))].copy()
    require(float(np.max(distances))>1e-12,'no distinct train features for Cell routing')
    means=np.stack((first,second))
    for _ in range(8):
        assignment=np.argmin(np.square(train[:,None,:]-means[None,:,:]).sum(axis=2),axis=1)
        counts=np.bincount(assignment,minlength=2)
        require(np.all(counts>=2),'degenerate unsupervised Cell partition')
        means=np.stack([train[assignment==j].mean(axis=0) for j in range(2)])
    result=np.argmin(np.square(all_rows[:,None,:]-means[None,:,:]).sum(axis=2),axis=1)
    require(set(result[:64].tolist())=={0,1},'both Cell types not trained')
    return result.astype(np.int8),means


def route_random_control(identifier: str) -> int:
    return hashlib.sha256(b'hepta.p08.independent-random-route.v1\0'+identifier.encode()).digest()[0]&1


def centroid_fit(train: np.ndarray,labels: np.ndarray):
    means=[]
    for class_id in range(CLASSES):
        rows=train[labels==class_id]
        require(len(rows)>=2,'too few examples per category')
        means.append(rows.mean(axis=0))
    return np.stack(means)


def train_loo_temperature(train: np.ndarray,labels: np.ndarray) -> tuple[float,int]:
    require(len(train)==64 and labels.shape==(64,),'LOO census mismatch')
    losses=[]
    for t in TEMPERATURES:
        total=0.0
        for k in range(len(train)):
            others=np.delete(train,k,axis=0)
            other_labels=np.delete(labels,k)
            c=centroid_fit(others,other_labels)
            p=softmax(c@train[k]*t)
            total-=math.log(max(1e-300,float(p[int(labels[k])])) )
        losses.append(total/len(train))
    j=min(range(len(losses)),key=lambda i:(losses[i],TEMPERATURES[i]))
    return TEMPERATURES[j],len(TEMPERATURES)*len(train)


def learn_and_predict(source: dict,features: np.ndarray) -> dict:
    """No held/transfer targets are accepted. Every train arm spends 512 SGD touches."""
    verify_panel(source)
    require(features.shape==(128,FEATURE_WIDTH),'real full-population feature shape')
    x=normalize(features)
    trainx=x[:64];ret=x[64:96];transfer=x[96:]
    require(len(ret)==len(transfer)==32,'test population drift')
    y=np.array([r['target'] for r in source['train']],dtype=np.int64)
    require(set(y)==set(range(4)),'original classes not supported')
    train_ids=[r['id'] for r in source['train']]
    all_routes,route_centroids=route_two_cluster(trainx,x)
    train_routes=all_routes[:64]
    counts=np.bincount(y,minlength=CLASSES)
    global_prior=(counts+1)/(len(y)+CLASSES)
    type_counts=np.zeros((2,CLASSES),dtype=np.float64)
    for r,label in zip(train_routes,y,strict=True):type_counts[r,label]+=1
    type_prior=(type_counts+1)/(type_counts.sum(axis=1)[:,None]+CLASSES)
    cent=centroid_fit(trainx,y)
    loo_temp,loo_paid=train_loo_temperature(trainx,y)
    inputs=np.concatenate([np.ones((len(x),1)),x],axis=1)
    predictions=[];seeds=[]
    for seed in SEEDS:
        rng=random.Random(seed)
        init=np.array([[(rng.random()-0.5)*0.02 for _ in range(FEATURE_WIDTH+1)]
                       for _ in range(2*CLASSES)],dtype=np.float64).reshape(2,CLASSES,FEATURE_WIDTH+1)
        weights={}
        arm_receipts={}
        schedule=[];order_rng=random.Random(seed+77)
        while len(schedule)<STEPS:
            ix=list(range(64));order_rng.shuffle(ix);schedule.extend(ix)
        for name in TRAINED:
            w=init[:1].copy() if name=='shared' else init.copy()
            for step,row in enumerate(schedule[:STEPS]):
                r=int(train_routes[row]);xx=inputs[row];label=int(y[row])
                slot=0 if name=='shared' else route_random_control(train_ids[row]) if name=='random_route' else r
                p=softmax(w[slot]@xx)
                g=p.copy();g[label]-=1
                w[slot]-=LR*np.outer(g,xx)+WEIGHT_DECAY*w[slot]
            weights[name]=w
            arm_receipts[name]={'actual_sgd_updates':STEPS,
                'actual_parameter_touches':STEPS*PARAMS_PER_SLOT,
                'allocated_head_scalars':int(w.size),'allocated_head_bytes':int(w.nbytes),
                'weight_sha256':sha(b'hepta.p08.head.fp64.v1\0'+w.tobytes()),
                'per_query_head_forwards':1}
        seeds.append({'seed':seed,'arms':arm_receipts})
        for part,start in [('retention',64),('transfer',96)]:
            for offset,row in enumerate(source[part]):
                i=start+offset
                r=int(all_routes[i]);rr=route_random_control(row['id']);xx=inputs[i]
                lookup={
                    'shared':softmax(weights['shared'][0]@xx),
                    'split':softmax(weights['split'][r]@xx),
                    'random_route':softmax(weights['random_route'][rr]@xx),
                    'frozen':softmax(init[r]@xx),
                    'type_prior':type_prior[r], 'global_prior':global_prior,
                    'centroid':softmax(cent@x[i]*0.25),
                    'centroid_loo':softmax(cent@x[i]*loo_temp),
                    'split_zero':softmax(weights['split'][r]@np.r_[1.,np.zeros(FEATURE_WIDTH)]),
                    'split_swap':softmax(weights['split'][1-r]@xx),
                }
                require(set(lookup)==set(ARMS),'missing candidate')
                predictions.append({'id':row['id'],'source':part,'seed':seed,
                    'p':{k:[float(v) for v in lookup[k]] for k in ARMS}})
    return {'schema':SCHEMA+'.prelabel.v1','source_sha256':sha(dump(source)),
            'head_schedule':{'seeds':list(SEEDS),'sgd_updates':STEPS,'lr':LR,'weight_decay':WEIGHT_DECAY,
                  'per_active_head_scalars':PARAMS_PER_SLOT,'class_count':CLASSES,'feature_width':FEATURE_WIDTH},
            'baseline_work':{'train_only_loo_fits':loo_paid,'centroid_temperature':loo_temp,
                 'zero_sgd_but_nonzero_math_work':True},
            'routing_sha256':sha(b'hepta.p08.train-only-clustering.v1\0'+route_centroids.tobytes()),
            'train_only_cluster_iterations':8,
            'seeds':seeds,'predictions':predictions,
            'flags':{'authentic_publisher_gold_in_predictor':False,'future_window_verified':False,
              'independent_human_gold_issuer':False,'live_model_promotion':False,
              'native_effect_authorized':False,'production_authorized':False,'authority':'DENY_ALL'}}


def _file_sha(path: Path) -> str:
    dig=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1_048_576),b''):dig.update(chunk)
    return dig.hexdigest()


def real_encode(rows: list[dict], model_directory: Path) -> tuple[np.ndarray,dict]:
    """Loads only reviewed pinned safetensors, performs actual 128 CPU forwards."""
    import torch
    from transformers import AutoTokenizer,AutoModel
    from huggingface_hub import snapshot_download
    t0=time.monotonic_ns()
    model_path=Path(snapshot_download(repo_id=MODEL_REPO,revision=MODEL_REV,
        allow_patterns=['model.safetensors','config.json','tokenizer.json',
                        'tokenizer_config.json','special_tokens_map.json'],
        local_dir=str(model_directory)))
    weights=model_path/'model.safetensors';tokfile=model_path/'tokenizer.json'
    require(weights.is_file() and _file_sha(weights)==MODEL_SAFETENSORS_SHA,'unverified actual pretrained safetensors')
    require(tokfile.is_file() and _file_sha(tokfile)==MODEL_TOKENIZER_SHA,'unverified pretrained tokenizer')
    tokenizer=AutoTokenizer.from_pretrained(str(model_path),trust_remote_code=False,use_fast=True)
    model=AutoModel.from_pretrained(str(model_path),trust_remote_code=False,use_safetensors=True,
                                   torch_dtype=torch.float32,attn_implementation='eager')
    require(model.config.model_type=='modernbert' and model.config.hidden_size==FEATURE_WIDTH,
            'unrecognized encoder network')
    model.eval();model.to('cpu');torch.set_num_threads(2)
    all_features=[];physical_calls=0;total_tokens=0
    with torch.inference_mode():
        for off in range(0,len(rows),4):
            batch=rows[off:off+4]
            tokens=tokenizer([r['text'] for r in batch],return_tensors='pt',
                             padding=True,truncation=True,max_length=128)
            output=model(**tokens)
            hidden=output.last_hidden_state
            mask=tokens['attention_mask'].unsqueeze(-1).to(hidden.dtype)
            val=(hidden*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1)
            require(tuple(val.shape)==(len(batch),FEATURE_WIDTH),'actual model output mismatch')
            all_features.append(val.float().cpu().numpy())
            physical_calls+=1;total_tokens+=int(tokens['attention_mask'].sum().item())
    features=np.concatenate(all_features,axis=0)
    require(len(features)==128 and np.isfinite(features).all(),'invalid real model observations')
    return features,{'model_repo':MODEL_REPO,'revision':MODEL_REV,
        'weight_sha256':MODEL_SAFETENSORS_SHA,'tokenizer_sha256':MODEL_TOKENIZER_SHA,
        'model_type':'modernbert','actual_cpu_model_forward_invocations':physical_calls,
        'original_pretrained_feature_rows':len(features),
        'actual_forward_input_tokens':total_tokens,
        'model_load_and_pretrained_forward_wall_ns_self_reported':time.monotonic_ns()-t0,
        'original_historical_checkpoint_reused':False,'gpu_backend_used':False,
        'original_weight_signature_issuer_attested':False}


def produce(panel_path: Path,output: Path,cache_dir: Path) -> dict:
    source=strict(read_regular(panel_path,150_000));verify_panel(source)
    rows=source['train']+source['retention']+source['transfer']
    feature,physical=real_encode(rows,cache_dir)
    predictions=learn_and_predict(source,feature)
    predictions['physical']=physical
    raw=dump(predictions);require(len(raw)<=300_000,'oversize original prediction packet')
    put_private(output,raw)
    return {'prelabel_sha256':sha(raw),'actual_pretrained_cpu_forward_calls':physical['actual_cpu_model_forward_invocations'],
            'physical_rows':physical['original_pretrained_feature_rows'],
            'producer_labels_seen':'AGNews training only', 'production_authorized':False}


def main() -> None:
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--model-cache',type=Path,required=True)
    a=ap.parse_args();print(json.dumps(produce(a.panel,a.out,a.model_cache),sort_keys=True))
if __name__=='__main__':main()
