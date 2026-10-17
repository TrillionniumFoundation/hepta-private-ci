"""Source-first full-corpus BM25 ceiling diagnostic, separate cost scope.

Original publisher questions and transcript are public; human evidence labels are
opened only for retrospective scoring. No LLM/Encoder forward, no trained Cell,
no oracle-selected candidate set. This is NOT a cost-matched 256-doc experiment.
"""
from __future__ import annotations
from collections import Counter,defaultdict
import hashlib
import json
import math
import re
import time
from pathlib import Path

from g5_independent_review import expected_root, HELD, LOCOMO_SHA

TOKEN=re.compile(r'(?u)\b\w+\b')


def evaluate_full_pub(raw:bytes)->dict:
    if hashlib.sha256(raw).hexdigest()!=LOCOMO_SHA:
        raise ValueError('unfrozen original publisher human data')
    orig=json.loads(raw)
    if type(orig) is not list or {x['sample_id'] for x in orig} != set(('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')+HELD):
        raise ValueError('wrong original source-root population')
    by_root={x['sample_id']:x for x in orig}
    metrics={'any_at_1':0,'any_at_3':0,'any_at_5':0,'any_at_10':0,
             'all_at_5':0,'at_least_one_gold_in_full_corpus':0,
             'all_gold_in_full_corpus':0,'denominator':0,'original_transcript_documents':0,
             'bm25_document_question_comparisons':0}
    t=time.perf_counter()
    per_root={}
    for root in HELD:
        source=by_root[root]
        docs={}
        for label,turns in source['conversation'].items():
            if not label.startswith('session_') or type(turns) is not list:continue
            for row in turns:
                ident=row.get('dia_id')
                word=row.get('text')
                if type(ident) is not str or not re.fullmatch(r'D\d+:\d+',ident):continue
                if type(word) is not str or not word.strip() or len(word.encode())>8192:continue
                text=str(row.get('speaker',''))+': '+word
                if ident in docs:
                    raise ValueError('duplicate canonical source dialogue ID')
                docs[ident]=text
        keys=sorted(docs)
        tokens=[TOKEN.findall(docs[k].casefold()) for k in keys]
        counts=[Counter(x) for x in tokens]
        df=Counter(word for row in tokens for word in set(row))
        avg=sum(len(x) for x in tokens)/len(tokens)
        selected,gold=expected_root(source,root,'HELD')
        root_hit=0
        for q in selected['questions']:
            identifiers=set(gold[q['id']])
            doc_intersection=identifiers & set(keys)
            metrics['at_least_one_gold_in_full_corpus']+=int(bool(doc_intersection))
            metrics['all_gold_in_full_corpus']+=int(bool(identifiers) and identifiers<=set(keys))
            query=set(TOKEN.findall(q['text'].casefold()))
            scores=[]
            for ident,terms,bag in zip(keys,tokens,counts):
                denom=0.25+0.75*len(terms)/max(avg,1)
                value=0.0
                for term in query:
                    tf=bag.get(term,0)
                    if tf:
                        idf=math.log1p((len(keys)-df[term]+0.5)/(df[term]+0.5))
                        value+=idf*tf*2.2/(tf+1.2*denom)
                scores.append((value,ident))
            top=[key for _,key in sorted(scores,key=lambda r:(-r[0],r[1]))]
            for k in (1,3,5,10):
                metrics[f'any_at_{k}']+=int(bool(identifiers & set(top[:k])))
            good=bool(identifiers & set(top[:5]))
            metrics['all_at_5']+=int(bool(identifiers) and identifiers<=set(top[:5]))
            root_hit+=good
            metrics['denominator']+=1
            metrics['bm25_document_question_comparisons']+=len(keys)
        metrics['original_transcript_documents']+=len(keys)
        per_root[root]={'source_utterances':len(keys),'question_count':len(selected['questions']),
                        'bm25_any_at_5':root_hit}
    metrics['full_corpus_cheap_cpu_wall_seconds_unattested']=time.perf_counter()-t
    if metrics['denominator']!=96:
        raise ValueError('incomplete source-first original question census')
    return {'schema':'hepta.hdsi.g5.full-original-corpus-bm25-diagnostic.v1',
            'source_original_sha':LOCOMO_SHA,'source_first_fixed_questions':True,
            'applies_to_different_doc_budget':True,
            'cannot_be_counted_as_matched_256_doc_head_lift':True,
            'metrics':metrics,'roots':per_root,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}


def main():
    import argparse,os
    p=argparse.ArgumentParser()
    p.add_argument('--original',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    r=evaluate_full_pub(a.original.read_bytes())
    if a.output.exists() or a.output.is_symlink():raise ValueError('create-only independent record')
    fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()+b'\n')
        f.flush();os.fsync(f.fileno())
    print(json.dumps({'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
                      'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
