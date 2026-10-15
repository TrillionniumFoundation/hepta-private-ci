"""Measured original-source retrieval CPU cost; no labels or pretrained model.
Run each profile in its own process. Two repeats are descriptive, not p95.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import resource
import re
import time
from stem_v13_cheap_retrieval import read_json,assert_source,plan_for,rank_source,jbytes,digest,write_once,words

class BM25Only:
    def __init__(self,docs):
        self.docs=docs
        self.rows=[tuple(words(d['text'])) for d in docs]
        self.tf=[Counter(row) for row in self.rows]
        self.df=Counter(w for row in self.rows for w in set(row))
        self.avg=sum(map(len,self.rows))/len(self.rows)
        n=len(self.rows)
        self.idf={t:math.log1p((n-d+0.5)/(d+0.5)) for t,d in self.df.items()}
    def rank(self,text):
        q=set(words(text))
        if not q:raise ValueError('blank question')
        vals=[]
        for i,c in enumerate(self.tf):
            length_scale=1.2*(0.25+0.75*len(self.rows[i])/self.avg)
            vals.append(sum(self.idf.get(t,0.)*(f*2.2)/(f+length_scale) for t in q if (f:=c.get(t,0))>0))
        return [self.docs[i]['id'] for i in sorted(range(len(self.docs)),key=lambda i:(-vals[i],self.docs[i]['id']))[:32]]

def profile(source,profile_name,reference=None):
    t0=time.process_time();w0=time.perf_counter()
    src=read_json(source)
    assert_source(src)
    plan=plan_for(src)
    output=[]
    if profile_name=='bm25_only':
        for fam in src['family_order']:
            x=src['families'][fam];idx=BM25Only(x['passages'])
            for q in x['questions']:
                output.append({'id':q['id'],'bm25_top32':idx.rank(q['text'])})
    elif profile_name=='six_arm':
        route=rank_source(src,plan)
        output=[{'id':row['id'],'bm25_top32':row['top32']['bm25']} for row in route['cases']]
    else:raise ValueError('only registered profiles')
    cpu=time.process_time()-t0;wall=time.perf_counter()-w0
    if len(output)!=1986:raise ValueError('incomplete source cost study')
    if reference is not None:
        ref=read_json(reference)
        want=[{'id':row['id'],'bm25_top32':row['top32']['bm25']} for row in ref['cases']]
        if output!=want:raise ValueError('same-source original BM25 route mismatch')
    return dict(schema='hepta.stem.v13.cheap-original-measured-retrieval-cost.v1',
        profile=profile_name,source_sha256=digest(src),question_count=1986,
        original_corpus_sha256=src['original_dataset_sha256'],
        bm25_rank_sha256=digest(output),cpu_seconds=cpu,wall_seconds=wall,
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        model_forwards=0,train_steps=0,production_authorized=False,
        equal_lifecycle_vs_model_heads=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--reference',required=True)
    p.add_argument('--profile',choices=['bm25_only','six_arm'],required=True);p.add_argument('--output',required=True)
    a=p.parse_args();result=profile(a.source,a.profile,a.reference)
    write_once(a.output,result)
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
