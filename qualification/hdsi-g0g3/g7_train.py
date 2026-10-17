"""Original pretrained TRAIN-only value profiling; seal plan before HELD forward.

Imports pinned G6/G5 components but never sees publisher HELD evidence labels.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import resource
import time

from g6_coverage_source import TRAIN,HELD, validate, write_new, canonical
from g6_coverage_model import bm25_all
from g5_batched_encoder import BatchedMiniLM, verified_encoder_only
from g7_policy import freeze_train, feature_band, plan, hash_object, need
from real_minilm_reference import CHECKSUMS

SCHEMA='hepta.hdsi.g7.train-and-prelabel.v1'


def rrf_ranking(rank_indices:list[int],vecs:list[float],shortlist:int=64)->list[int]:
    need(len(rank_indices)==len(set(rank_indices)) and len(rank_indices)>=shortlist
         and len(vecs)==shortlist and all(math.isfinite(a) for a in vecs),
         'bounded real-feature reciprocal rank')
    sem=sorted(range(shortlist),key=lambda j:(-vecs[j],j))
    pos={j:i for i,j in enumerate(sem)}
    order=sorted(range(shortlist),key=lambda j:(-(1/(21+j)+1/(21+pos[j])),j))
    return [rank_indices[k] for k in order]+rank_indices[shortlist:]


def run_training(root:Path,public:dict)->dict:
    validate(public)
    need(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'original HELD gold must be absent before model init')
    verified_encoder_only(root)
    import torch
    torch.set_num_threads(1)
    started=time.perf_counter();cpu0=time.process_time()
    enc=BatchedMiniLM(root,batch_size=16)
    observations=[]
    source_counts={}
    for group in public['roots']:
        if group['split']!='TRAIN':continue
        name=group['root'];docs=group['docs'];qs=group['questions']
        need(name in TRAIN and len(docs)==256 and len(qs)==24,'TRAIN-only model material')
        rankings,charge=bm25_all(docs,qs)
        before_seq=enc.calls;before_batches=enc.actual_batches
        features=enc.encode_batch([(row['text'].encode(),'text') for row in docs+qs])
        need(len(features)==280 and enc.calls-before_seq==280,'real train Encoder forward census')
        dvec=torch.tensor(features[:256],dtype=torch.float32)
        qvec=torch.tensor(features[256:],dtype=torch.float32)
        with torch.inference_mode():sim=(qvec@dvec.T).tolist()
        for i,q in enumerate(qs):
            lex=rankings[i]
            sem=rrf_ranking(lex,[sim[i][j] for j in lex[:64]])
            allowed=set(q['train_support'])
            band=feature_band(q['text'],docs[lex[0]]['text'])
            observations.append({'root':name,'qid':q['id'],'source_sha':q['text_sha'],
                    'band':band,'bm25_hit':bool(allowed&{docs[j]['id'] for j in lex[:5]}),
                    'rrf_hit':bool(allowed&{docs[j]['id'] for j in sem[:5]})})
        source_counts[name]={'sequences':enc.calls-before_seq,
                             'batches':enc.actual_batches-before_batches,
                             'train_questions':len(qs),'train_bm25_scores':charge}
    need(set(source_counts)==set(TRAIN) and enc.calls==1680,'wrong TRAIN real model cost')
    profile=freeze_train(public,observations)
    held=[]
    lexical_scores=0
    for group in public['roots']:
        if group['split']!='HELD':continue
        docs=group['docs'];qs=group['questions'];name=group['root']
        ranks,paid=bm25_all(docs,qs);lexical_scores+=paid
        for q,idx in zip(qs,ranks):
            held.append({'root':name,'qid':q['id'],'source_sha':q['text_sha'],
                         'band':feature_band(q['text'],docs[idx[0]]['text']),
                         'bm25_top5_ids':[docs[j]['id'] for j in idx[:5]]})
    held.sort(key=lambda x:(x['root'],x['qid']))
    sealed=plan(public,profile,held)
    out={'schema':SCHEMA,'source_digest':public['digest'],
         'material_sha':CHECKSUMS['encoder/model.safetensors'],
         'train_observations':observations,'observations_digest':hash_object(observations),
         'profile':profile,'sealed_plan':sealed,'train_source_cost':source_counts,
         'real_pretrained_train_model':True,'actual_train_encoder_sequences':enc.calls,
         'actual_train_encoder_batches':enc.actual_batches,
         'actual_train_tokens':enc.tokens,'original_held_bm25_pair_scores':lexical_scores,
         'training_cost':{'cpu_seconds_unattested':time.process_time()-cpu0,
                          'wall_seconds_unattested':time.perf_counter()-started,
                          'resident_peak_bytes_unattested':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024},
         'held_gold_accessed':False,'future_performance_verified':False,
         'production_authorized':False,'disposition':'HOLD_NO_GO'}
    out['digest']=hash_object(out)
    return out


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--model-only',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    public=json.loads(a.source.read_bytes())
    result=run_training(a.model_only,public)
    write_new(a.output,result)
    print(json.dumps({'real_train_encoder_sequences':result['actual_train_encoder_sequences'],
                      'cost_accounting':'unattested','plan_digest':result['sealed_plan']['digest'],
                      'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
