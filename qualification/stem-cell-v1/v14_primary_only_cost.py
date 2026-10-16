"""V14 research-only CPU cost isolation: fixed V13 primary vs BM25 on original source.

Uses V13's actual source-only/canonical plan. It never reads publisher labels,
trains Heads, loads model weights, or authorizes selection. The fixed V13 six-arm
ranker is only used for an OUT-OF-BAND replay parity test, not timing claims.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import resource
import time

from stem_v13_cheap_retrieval import (
    CONFIG, HELD, OLD, PRIMARY, QUESTION_COUNTS, CORPUS_SHA,
    Index, assert_source, digest, grams, plan_for, read_json, words, write_once,
)
from v13_retrieval_cost import BM25Only

SCHEMA = 'hepta.stem.v14.original-primary-single-arm-cost.shadow.v1'
V13_SOURCE_SHA = '9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c'
V13_PLAN_SHA = '8f6efdb78a173d64123209753ebf2dac06b03367637084a4098866cdbfe4df53'
PROFILES = ('bm25_only', 'primary_only')


class OriginalPrimaryOnly(Index):
    """No training, no other four unused V13 arms, exactly V13 primary formula."""

    def rank(self, question):
        q = words(question)
        if not q:
            raise ValueError('empty question')
        qset = set(q)
        qbig = list(zip(q,q[1:]))
        widf = self.word_idf
        phrase_total = sum(min(widf.get(x,0.), widf.get(y,0.)) for x,y in qbig)
        qchar = grams(q)
        qc = {term: freq*self.char_idf.get(term,0.) for term,freq in qchar.items()}
        qnorm = math.sqrt(sum(v*v for v in qc.values()))
        bm, phr, char = [], [], []
        for i,tf in enumerate(self.tfs):
            length = len(self.tokens[i]); scale=1.2*(0.25+0.75*length/self.avglen)
            b = sum(widf.get(t,0.)*(f*2.2)/(f+scale) for t in qset if (f:=tf.get(t,0))>0)
            bm.append(b)
            phr.append(sum(min(widf.get(x,0.), widf.get(y,0.)) for x,y in qbig if self.bigrams[i].get((x,y),0)) /(phrase_total or 1.))
            norm = self.char_norm[i]
            cp = sum(v*self.char_tf[i].get(k,0)*self.char_idf.get(k,0) for k,v in qc.items())
            char.append(cp/(qnorm*norm) if qnorm>0 and norm>0 else 0.)
        high = max(bm)
        bn = [v/high if high>0 else 0. for v in bm]
        scores=[0.7*b+0.1*p+0.2*c for b,p,c in zip(bn,phr,char)]
        if len(scores)!=len(self.passages) or any(not math.isfinite(s) for s in scores):
            raise ValueError('nonfinite primary score')
        return [self.passages[i]['id'] for i in sorted(range(len(self.passages)),key=lambda j:(-scores[j],self.passages[j]['id']))[:32]]


def validate_packet(src, plan):
    assert_source(src)
    if digest(src)!=V13_SOURCE_SHA or plan!=plan_for(src) or digest(plan)!=V13_PLAN_SHA:
        raise ValueError('original source or frozen pre-registration changed')
    if plan['precommitted_primary']!=PRIMARY or PRIMARY!='phrase_char' or CONFIG['phrase_char_weights']!=[0.7,0.1,0.2]:
        raise ValueError('posthoc arm or weights substitution prohibited')
    if src['original_dataset_sha256']!=CORPUS_SHA or set(src['families'])!=set(OLD+HELD):
        raise ValueError('original source-family lineage mismatch')


def run(src,plan,profile):
    """Measure one entire 1986-query profile, starting after source JSON decode.

    Per-family indexing and ranking work included. The separate stdout/parity
    reviewer compares raw route hashes but never counts as a timed phase.
    """
    validate_packet(src,plan)
    if profile not in PROFILES:
        raise ValueError('unknown pre-registered profile')
    process0=time.process_time_ns(); wall0=time.perf_counter_ns()
    rows=[]; index_ns=0; query_ns=0; docs_total=0
    for fam in src['family_order']:
        group=src['families'][fam]
        docs_total+=len(group['passages'])
        t0=time.process_time_ns()
        index=BM25Only(group['passages']) if profile=='bm25_only' else OriginalPrimaryOnly(group['passages'])
        index_ns+=time.process_time_ns()-t0
        for q in group['questions']:
            t0=time.process_time_ns()
            ranked=index.rank(q['text'])
            query_ns+=time.process_time_ns()-t0
            if len(ranked)!=32 or len(set(ranked))!=32:
                raise ValueError('complete Top32 missing')
            rows.append({'id':q['id'],'family':fam,'top32':ranked})
    process_cpu_ns=time.process_time_ns()-process0
    wall_ns=time.perf_counter_ns()-wall0
    if len(rows)!=1986 or docs_total!=5882:
        raise ValueError('truncated original source inventory')
    return dict(schema=SCHEMA,profile=profile,source_sha256=digest(src),plan_sha256=digest(plan),
                original_dataset_sha256=CORPUS_SHA,original_questions=len(rows),source_passages=docs_total,
                original_held_family_count=4,original_future_windows=0,original_gold_used_during_rank=False,
                rank_sha256=digest(rows),ranked_top_k=32,
                process_cpu_ns=process_cpu_ns,wall_ns=wall_ns,index_cpu_ns=index_ns,
                query_cpu_ns=query_ns,peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                encoder_forward_calls=0,reader_forward_calls=0,train_steps=0,
                complete_lifecycle_cost_vs_head_matched=False,
                semantic_reader_correctness=None,production_authorized=False,stem_winner_verified=False), rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',required=True)
    ap.add_argument('--plan',required=True)
    ap.add_argument('--profile',required=True,choices=PROFILES)
    ap.add_argument('--output',required=True)
    ap.add_argument('--private-route',required=True)
    a=ap.parse_args()
    src=read_json(a.source);plan=read_json(a.plan)
    public,rows=run(src,plan,a.profile)
    # Private original question and source IDs may be retained locally for
    # independent scoring, but never uploaded as a public research receipt.
    private={'schema':SCHEMA+'.private-routes','profile':a.profile,'source_sha256':public['source_sha256'],
             'rank_sha256':public['rank_sha256'],'rows':rows,'gold_present':False}
    write_once(a.private_route,private)
    write_once(a.output,public)
    print(json.dumps({k:public[k] for k in ('profile','original_questions','rank_sha256','process_cpu_ns','production_authorized')},sort_keys=True))

if __name__=='__main__': main()
