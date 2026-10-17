"""Real frozen MiniLM + bounded 64-candidate rerank; only TRAIN human gold.

A source owner has already stripped *all* HELD gold. This model-worker refuses
original publisher QA files and is research-only; no model selection or tool use.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import re
import resource
import time

from g6_coverage_source import SCORES, SCHEMA, canonical, deny, sha, validate, write_new
from g5_original_evidence import train_rank8
from g5_batched_encoder import BatchedMiniLM, verified_encoder_only
from real_minilm_reference import CHECKSUMS
from feature_bus import Scope, Borrow, SharedFeatureBus

RUN_SCHEMA = 'hepta.hdsi.g6.real-original-two-stage.v1'
RUN_DOMAIN = b'hepta.hdsi.g6.original-prelabel.v1\0'
TOKEN = re.compile(r'(?u)\b\w+\b')
K = 64


def bm25_all(docs: list[dict], queries: list[dict]) -> tuple[list[list[int]], int]:
    """No labels, fixed k1=1.2 b=.75. Tie sort is source ID, not truth."""
    terms = [TOKEN.findall(d['text'].casefold()) for d in docs]
    bags = [Counter(row) for row in terms]
    df = Counter(word for row in terms for word in set(row))
    avg = sum(map(len, terms)) / len(terms)
    n = len(docs)
    rankings = []
    for q in queries:
        qt = sorted(set(TOKEN.findall(q['text'].casefold())))
        scores = []
        for i, (row, bag) in enumerate(zip(terms, bags)):
            value = 0.0
            norm = .25 + .75 * len(row)/max(avg,1)
            for word in qt:
                t = bag.get(word, 0)
                if t:
                    idf = math.log1p((n - df[word] + .5)/(df[word] + .5))
                    value += idf*t*2.2/(t+1.2*norm)
            scores.append((value, docs[i]['id'], i))
        rankings.append([i for _, _, i in sorted(scores, key=lambda v:(-v[0],v[1]))])
    return rankings, n * len(queries)


def _rrf(lex_pos: int, sem_pos: int) -> float:
    return 1.0/(20 + lex_pos + 1) + 1.0/(20 + sem_pos + 1)


def merge_ranks(base: list[int], shortlist: list[int], sim: list[float],
                learned: list[float], sham: list[float]) -> dict[str,list[int]]:
    """Same 64 candidates, identical feature compute for every model arm."""
    deny(len(base) == len(set(base)) and len(shortlist) == K and base[:K] == shortlist,
         'invalid frozen shortlist')
    deny(all(len(z) == K and all(math.isfinite(x) for x in z) for z in (sim,learned,sham)),
         'incomplete scored shortlist')
    def reorder(scores):
        return [shortlist[j] for j in sorted(range(K), key=lambda j:(-scores[j],j))] + base[K:]
    positions = sorted(range(K), key=lambda j:(-sim[j],j))
    inv = {idx: order for order, idx in enumerate(positions)}
    fused = [_rrf(i, inv[i]) for i in range(K)]
    return {'bm25_full': list(base), 'bm25_64': list(base),
            'cosine_64': reorder(sim), 'rank8_64': reorder(learned),
            'sham_64': reorder(sham), 'rrf_64': reorder(fused)}


def run(root: Path, public: dict) -> dict:
    # Admission checks run without Torch, including source-only CI / -S mode.
    validate(public)
    deny(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'held publisher/QA cannot enter model worker')
    verified_encoder_only(root)
    import torch
    torch.set_num_threads(1)
    started = time.perf_counter()
    cpu_start = time.process_time()
    enc = BatchedMiniLM(root, batch_size=16)
    model_features = {}
    total_borrows = 0
    source_accounting = {}
    scopes = {}
    # One Encoder instance; use separate scope for each root, preserving source isolation.
    def encode_root(name: str, items: list[dict]):
        nonlocal total_borrows
        preproc = sha(b'hepta.hdsi.g6.original-minilm-mean-unit-token128.v1')
        scope = Scope('g6-'+name, 'g6-evidence-rerank', 1, 0,
                      sha(('g6-current-root:'+name).encode()),
                      CHECKSUMS['encoder/model.safetensors'], preproc)
        scopes[name] = scope
        bus = SharedFeatureBus(384,lambda payload,mod:enc.encode_batch([(payload,mod)])[0],
            lambda v: v.scope == scope and v.approved_use == 'g6-source-bound',
            batch_encode=enc.encode_batch)
        borrows = [Borrow(scope,'text',d['text'].encode(),'borrow-'+str(i),'g6-source-bound')
                   for i,d in enumerate(items)]
        calls, batches = enc.calls, enc.actual_batches
        receipts = bus.fanout(borrows)
        new_calls = enc.calls - calls
        deny(new_calls == bus.physical_calls and len(receipts) == len(items), 'wrong actual physical forward census')
        total_borrows += len(items)
        source_accounting[name] = {
            'model_sequences': new_calls,
            'model_batches': enc.actual_batches-batches,
            'logical_borrows': len(items),
            'identity_count': len({v.key for v in receipts}),
            'source_scope': scope.principal,
        }
        return torch.tensor([v.values for v in receipts],dtype=torch.float32)
    
    # Reuse the exact G5 256 TRAIN documents and questions, so Head training
    # budgets and initializations match original source-isolated G5 controls.
    train_features={}
    for r in public['roots']:
        if r['split'] != 'TRAIN':
            continue
        tensor = encode_root(r['root'],r['docs']+r['questions'])
        train_features[r['root']]=(tensor[256:],tensor[:256])
    learned, learned_stats = train_rank8(public['roots'],train_features,shuffled=False)
    sham, sham_stats = train_rank8(public['roots'],train_features,shuffled=True)
    deny(learned_stats['parameters']==sham_stats['parameters']==6144
         and learned_stats['steps']==sham_stats['steps']==100,
         'G6 controls require equal physical Head budget')
    predicts=[]
    comparisons=0
    for r in public['roots']:
        if r['split']!='HELD':continue
        docs=r['docs'];qs=r['questions'];name=r['root']
        rankings,work=bm25_all(docs,qs)
        comparisons += work
        union=sorted({j for seq in rankings for j in seq[:K]})
        # If a real source cannot be tokenized inside the fixed native original
        # 128-token window, mark the experiment unavailable rather than truncate.
        tensor=encode_root(name,qs + [docs[j] for j in union])
        qvec=tensor[:24];dmat=tensor[24:]
        by_doc={idx:i for i,idx in enumerate(union)}
        with torch.inference_mode():
            c=qvec@dmat.T
            l=c+8.0*(qvec@learned['a'])@(dmat@learned['b']).T
            s=c+8.0*(qvec@sham['a'])@(dmat@sham['b']).T
        c=c.tolist();l=l.tolist();s=s.tolist()
        for i,q in enumerate(qs):
            shortlist=rankings[i][:K]
            pos=[by_doc[j] for j in shortlist]
            arms=merge_ranks(rankings[i],shortlist,[c[i][j] for j in pos],
                             [l[i][j] for j in pos],[s[i][j] for j in pos])
            preds={key:[docs[idx]['id'] for idx in seq] for key,seq in arms.items()}
            predicts.append({'root':name,'qid':q['id'],'question_sha':q['text_sha'],
                             'rankings':preds,'shortlist_size':K})
    wall = time.perf_counter()-started
    cpu = time.process_time()-cpu_start
    summary = {'schema':RUN_SCHEMA,'source_digest':public['digest'],
            'model_sha':CHECKSUMS['encoder/model.safetensors'],
            'original_sha':CHECKSUMS['locomo.json'],
            'supervised_head':learned_stats,'wrong_supervision_head':sham_stats,
            'source_counters':source_accounting,
            'actual_encoder_sequences':enc.calls,'actual_encoder_batches':enc.actual_batches,
            'actual_encoder_token_positions':enc.tokens,'logical_borrows':total_borrows,
            'original_bm25_pair_scores':comparisons,
            'held_rankings':predicts,
            'cost':{'process_cpu_seconds_unattested':cpu,'process_wall_seconds_unattested':wall,
                    'process_peakrss_bytes_unattested':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                    'energy_joules':None,'host_p99_ms':None},
            'real_pretrained_forward':True,'true_future_cohort_verified':False,
            'natural_answer_quality_verified':False,'ndu_incremental_net_utility_verified':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}
    summary['digest']=sha(RUN_DOMAIN+canonical(summary))
    return summary


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    packet=json.loads(args.source.read_bytes(),object_pairs_hook=__import__('g6_coverage_source').strict_pairs)
    result=run(args.root,packet)
    write_new(args.output,result)
    print(json.dumps({'prelabel_sha256':sha(args.output.read_bytes()),
                      'physical_encoder_sequences':result['actual_encoder_sequences'],
                      'held_cases':len(result['held_rankings']),'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':
    main()
