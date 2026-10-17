"""V14 independently check ORIGINAL V13 source routes, then score in separate label process.

Private routes include original source IDs and question IDs; never upload private
routes, original LoCoMo media/dialogue/answers, or per-question publisher gold.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from stem_v13_cheap_retrieval import (
    CORPUS_SHA, HELD, OLD, PRIMARY, Index,
    digest, file_sha, read_json, write_once,
)
from v14_primary_only_cost import SCHEMA, V13_SOURCE_SHA, V13_PLAN_SHA, validate_packet

REPORT_SCHEMA='hepta.stem.v14.original-primary-independent-recount.shadow.v1'


def unpack_routes(private,receipt,src,arm):
    if type(private)!=dict or set(private)!={'schema','profile','source_sha256','rank_sha256','rows','gold_present'}:
        raise ValueError('private route schema tampering')
    if (private['schema']!=SCHEMA+'.private-routes' or private['profile']!=arm
        or private['gold_present'] is not False or private['source_sha256']!=V13_SOURCE_SHA
        or digest(private['rows'])!=private['rank_sha256']):
        raise ValueError('private rank seal changed')
    expected={q['id']:(fam,{d['id'] for d in g['passages']}) for fam,g in src['families'].items() for q in g['questions']}
    if len(private['rows'])!=1986 or not isinstance(private['rows'],list):raise ValueError('incomplete route')
    rows={}
    for row in private['rows']:
        if type(row)!=dict or set(row)!={'id','family','top32'}:raise ValueError('route injection')
        rid=row['id']
        if rid not in expected or rid in rows or row['family']!=expected[rid][0]:raise ValueError('route alias')
        ids=row['top32']
        if type(ids)!=list or len(ids)!=32 or any(type(x)!=str or x not in expected[rid][1] for x in ids) or len(set(ids))!=32:
            raise ValueError('source mismatched/outside family')
        rows[rid]=ids
    if set(rows)!=set(expected):raise ValueError('missing original cases')
    if receipt['profile']!=arm or receipt['rank_sha256']!=private['rank_sha256']:
        raise ValueError('public/private seal mismatch')
    return rows


def attest_receipts(src,plan,pairs):
    validate_packet(src,plan)
    if len(pairs)!=2:raise ValueError('two physical arms required')
    for arm,(private,public) in pairs.items():
        if arm not in ('bm25_only','primary_only') or set(public)!={'schema','profile','source_sha256','plan_sha256','original_dataset_sha256','original_questions','source_passages','original_held_family_count','original_future_windows','original_gold_used_during_rank','rank_sha256','ranked_top_k','process_cpu_ns','wall_ns','index_cpu_ns','query_cpu_ns','peak_process_rss_kib','encoder_forward_calls','reader_forward_calls','train_steps','complete_lifecycle_cost_vs_head_matched','semantic_reader_correctness','production_authorized','stem_winner_verified'}:
            raise ValueError('unknown public arm/schema')
        if (public['schema']!=SCHEMA or public['source_sha256']!=V13_SOURCE_SHA
            or public['plan_sha256']!=V13_PLAN_SHA or public['original_dataset_sha256']!=CORPUS_SHA
            or (public['original_questions'],public['source_passages'],public['ranked_top_k'])!=(1986,5882,32)
            or any(type(public[k])!=int or public[k]<0 for k in ('process_cpu_ns','wall_ns','index_cpu_ns','query_cpu_ns','peak_process_rss_kib'))
            ):
            raise ValueError('invalid physical budget/material')
        if (public['original_gold_used_during_rank'] is not False or public['production_authorized'] is not False
            or public['stem_winner_verified'] is not False or public['complete_lifecycle_cost_vs_head_matched'] is not False
            or public['semantic_reader_correctness'] is not None or public['original_future_windows']!=0
            or public['train_steps']!=0 or public['encoder_forward_calls']!=0 or public['reader_forward_calls']!=0):
            raise ValueError('model/gold/production claim falsely authorized')
        if public['index_cpu_ns']+public['query_cpu_ns']>public['process_cpu_ns']*1.02:
            raise ValueError('nested timing exceed parent')
    return {arm:unpack_routes(private,public,src,arm) for arm,(private,public) in pairs.items()}


def exact_source_recount(src,plan,pairs):
    """Recompute V13 six-arm source-first frozen ranks; NO publisher labels."""
    routes=attest_receipts(src,plan,pairs)
    differences={'bm25_only':0,'primary_only':0}
    for fam in src['family_order']:
        family=src['families'][fam]
        idx=Index(family['passages'])
        for q in family['questions']:
            truth=idx.rank(q['text'])
            for arm,name in [('bm25_only','bm25'),('primary_only',PRIMARY)]:
                if routes[arm][q['id']]!=truth[name]:
                    differences[arm]+=1
    if any(differences.values()):raise ValueError('not exact ORIGINAL V13 frozen rankings')
    return {'schema':REPORT_SCHEMA+'.source-first', 'source_sha256':V13_SOURCE_SHA,
            'plan_sha256':V13_PLAN_SHA,'cases_compared':1986,
            'direct_v13_rank_match_count':{k:1986-v for k,v in differences.items()},
            'heldout_gold_opened':False,'source_first_replay_valid':True,'production_authorized':False}


def score_held_original(original,src,plan,pairs,source_first):
    """Postseal independent publisher-weak labels, never Reader task correctness."""
    if source_first.get('source_first_replay_valid') is not True or source_first.get('cases_compared')!=1986:
        raise ValueError('must pass source-first complete parity before reading publisher labels')
    routes=attest_receipts(src,plan,pairs)
    if file_sha(original)!=CORPUS_SHA:raise ValueError('original corpus SHA mismatch')
    raw=read_json(original)
    # Independent publisher annotation parser; V13 scorer is not imported.
    gold={}
    for item in raw:
        fam=item['sample_id']
        known={d['id'] for d in src['families'][fam]['passages']}
        for i,q in enumerate(item['qa']):
            rid=fam+'/q'+str(i)
            refs=q.get('evidence')
            if (type(refs)!=list or not refs or any(type(v)!=str or v not in known for v in refs)):
                gold[rid]=None
            else:gold[rid]=set(refs)
    if len(gold)!=1986 or set(gold)!={q['id'] for fam,group in src['families'].items() for q in group['questions']}:
        raise ValueError('independent source annotation census incomplete')
    per_family={}
    overall={arm:{'any_hit3':0,'any_hit16':0,'any_hit32':0,'all_hit3':0} for arm in routes}
    for fam in HELD:
        qs=src['families'][fam]['questions']
        fam_stats={arm:{'any_hit3':0,'any_hit16':0,'any_hit32':0,'all_hit3':0} for arm in routes}
        unknown=0; valid=0; gained=0;lost=0
        for q in qs:
            ident=q['id']; evidence=gold[ident]
            if evidence is None:unknown+=1;continue
            valid+=1
            for arm in routes:
                top=routes[arm][ident]
                for k,field in [(3,'any_hit3'),(16,'any_hit16'),(32,'any_hit32')]:
                    hit=bool(evidence.intersection(top[:k]));fam_stats[arm][field]+=int(hit);overall[arm][field]+=int(hit)
                allhit=evidence.issubset(set(top[:3]));fam_stats[arm]['all_hit3']+=int(allhit);overall[arm]['all_hit3']+=int(allhit)
            cheap=bool(evidence.intersection(routes['bm25_only'][ident][:3]))
            primary=bool(evidence.intersection(routes['primary_only'][ident][:3]))
            gained+=int(primary and not cheap);lost+=int(cheap and not primary)
        per_family[fam]={'questions':len(qs),'unknown':unknown,'annotated':valid,'arms':fam_stats,
                         'gain_over_bm25':gained,'loss_to_bm25':lost,'net':gained-lost}
    if sum(per_family[f]['questions'] for f in HELD)!=829 or sum(per_family[f]['unknown'] for f in HELD)!=7:
        raise ValueError('original held denominator changed')
    if overall['bm25_only']['any_hit3']!=372 or overall['primary_only']['any_hit3']!=383:
        raise ValueError('V13 fixed BM25/primary weak-support parity failed')
    if (overall['bm25_only']['any_hit16'],overall['bm25_only']['any_hit32'],
        overall['primary_only']['any_hit16'],overall['primary_only']['any_hit32'])!=(515,575,528,587):
        raise ValueError('registered V13 source candidate ceilings changed')
    return dict(schema=REPORT_SCHEMA+'.postseal',original_dataset_sha256=CORPUS_SHA,
                source_sha256=V13_SOURCE_SHA,plan_sha256=V13_PLAN_SHA,
                independent_heldout_roots=4,heldout_questions=829,publisher_unknown=7,
                primary_fixed_before_heldout=True,baseline_original_ranking_reproduced=True,
                per_family=per_family,complete_held_aggregates=overall,
                weak_proxy_gain_not_prospective=True,full_reader_semantics_judged=False,
                lifecycle_cost_to_head_matched=False,production_authorized=False,stem_winner_verified=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--plan',required=True)
    p.add_argument('--bm25-private',required=True);p.add_argument('--bm25-receipt',required=True)
    p.add_argument('--primary-private',required=True);p.add_argument('--primary-receipt',required=True)
    p.add_argument('--source-report',required=True);p.add_argument('--score-report')
    p.add_argument('--original')
    a=p.parse_args();src=read_json(a.source);plan=read_json(a.plan)
    pairs={n:(read_json(getattr(a,n.replace('bm25_only','bm25').replace('primary_only','primary')+'_private')),
              read_json(getattr(a,n.replace('bm25_only','bm25').replace('primary_only','primary')+'_receipt')))
          for n in ('bm25_only','primary_only')}
    report=exact_source_recount(src,plan,pairs)
    write_once(a.source_report,report)
    if a.original or a.score_report:
        if not (a.original and a.score_report):raise ValueError('postseal score needs both original & destination')
        result=score_held_original(a.original,src,plan,pairs,report)
        write_once(a.score_report,result)
        print(json.dumps({k:v for k,v in result['complete_held_aggregates'].items()},sort_keys=True))
    else:print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
