"""Full-corpus original MiniLM training observation, one sealed original root.

Do not call this a model learning outcome: encoder weights are frozen and the
result is a TRAIN-only task utility observation. No HELD gold is accessible.
"""
from __future__ import annotations
import json
from pathlib import Path
import resource
import time

from g5_batched_encoder import BatchedMiniLM, verified_encoder_only
from g6_coverage_model import bm25_all
from g6_coverage_source import TRAIN, write_new
from g7_policy import feature_band
from g7_train import rrf_ranking
from g8_source import validate
from g8_policy import digest, need
from real_minilm_reference import CHECKSUMS, wordpiece

SCHEMA='hepta.hdsi.g8.one-original-train-root.v1'


def execute(root:Path,source:dict,root_name:str)->dict:
    validate(source)
    need(root_name in TRAIN,'cannot execute test-side label owner')
    need(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'producer has access to human HELD gold')
    verified_encoder_only(root)
    import torch
    torch.set_num_threads(1)
    started=time.perf_counter();cpu=time.process_time()
    group=next(x for x in source['roots'] if x['root']==root_name)
    docs=group['docs'];questions=group['questions']
    ranks,n_pairs=bm25_all(docs,questions)
    universe=sorted({i for ranking in ranks for i in ranking[:64]})
    payloads=[q['text'].encode() for q in questions]+[docs[j]['text'].encode() for j in universe]
    enc=BatchedMiniLM(root,batch_size=16)
    # Token-length bucketing reduces padding and is a frozen, label-blind
    # permutation; output features are returned to the original input ordering.
    lengths=[len(wordpiece(x.decode('utf-8'),enc.vocab)) for x in payloads]
    permutation=sorted(range(len(payloads)),key=lambda i:(lengths[i],i))
    feats=enc.encode_batch([(payloads[i],'text') for i in permutation])
    inversed=[None]*len(payloads)
    for i,v in zip(permutation,feats):inversed[i]=v
    need(all(x is not None for x in inversed),'missing physical feature')
    t=torch.tensor(inversed,dtype=torch.float32)
    with torch.inference_mode():similarities=(t[:24]@t[24:].T).tolist()
    where={idx:i for i,idx in enumerate(universe)}
    rows=[];cover={'all':0,'top64':0,'top5':0,'rrf5':0}
    for qi,q in enumerate(questions):
        ranked=ranks[qi]
        score=[similarities[qi][where[j]] for j in ranked[:64]]
        rr=rrf_ranking(ranked,score)
        evidence=set(q['train_support'])
        hit=bool(evidence & {docs[k]['id'] for k in ranked[:5]})
        rr_hit=bool(evidence & {docs[k]['id'] for k in rr[:5]})
        cover['all']+=bool(evidence & {d['id'] for d in docs})
        cover['top64']+=bool(evidence & {docs[k]['id'] for k in ranked[:64]})
        cover['top5']+=int(hit);cover['rrf5']+=int(rr_hit)
        rows.append({'root':root_name,'qid':q['id'],'source_sha':q['text_sha'],
                     'band':feature_band(q['text'],docs[ranked[0]]['text']),
                     'bm25_hit':hit,'rrf_hit':rr_hit,
                     'bm25_top10':[docs[k]['id'] for k in ranked[:10]],
                     'rrf_top10':[docs[k]['id'] for k in rr[:10]]})
    need(cover['all']==24,'original TRAIN truth missing from full corpus')
    need(enc.calls==len(payloads) and enc.actual_batches==(len(payloads)+15)//16,
         'physical model work not counted')
    result={'schema':SCHEMA,'source_digest':source['digest'],'root':root_name,
            'original_model_sha':CHECKSUMS['encoder/model.safetensors'],
            'frozen_pretrained_encoder':True,'source_census':{'full_docs':len(docs),
               'full_questions':24,'encoded_unique_documents':len(universe),
               'bm25_pair_scores':n_pairs,'support':cover},
            'train_observations':rows,'encoder_sequences':enc.calls,
            'encoder_batches':enc.actual_batches,'encoder_tokens':enc.tokens,
            'run_profile': 'fp32_cpu_wordpiece128_length_buckets_batch16',
            'cost':{'cpu_seconds_self_reported':time.process_time()-cpu,
                    'wall_seconds_self_reported':time.perf_counter()-started,
                    'peak_rss_bytes_self_reported':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                    'energy_joules':None},
            'held_gold_accessed':False,'future_quality_verified':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}
    result['digest']=digest(result)
    return result


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--model-only',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--root',choices=TRAIN,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source=json.loads(a.source.read_bytes())
    value=execute(a.model_only,source,a.root)
    write_new(a.output,value)
    print(json.dumps({'root':a.root,'original_seqs':value['encoder_sequences'],
                      'batches':value['encoder_batches'], 'support':value['source_census']['support'],
                      'cpu':value['cost']['cpu_seconds_self_reported'],
                      'disposition':'HOLD_NO_GO'}),flush=True)

if __name__=='__main__':main()
