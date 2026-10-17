"""G7: finite, source-frozen Episode-NDU/Bellman allocation (research only).

No claims of stochastic FBSDE, independent preference discovery, true future
learning, savings for counterfactual calls, or production effect authority.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
import re

from g6_coverage_source import TRAIN, HELD, canonical, validate

DOM = b'hepta.hdsi.g7.train-only-episode-policy.v1\0'
SCHEMA = 'hepta.hdsi.g7.train-only-policy.v1'
ACTIONS = ('STOP', 'BM25', 'RERANK')
BANDS = ('weak', 'medium', 'strong')
HIT = 10_000
MISS = -3_000
# Units are *declared hypothetical preference units*, not US dollars.
# BM25 scanning is already paid before action selection in all three arms.
MARGINAL_RERANK_FEE = 900
MAX_ROOT_BUDGET = 8
TOKEN = re.compile(r'(?u)\b\w+\b')


def need(ok: bool, msg: str) -> None:
    if ok is not True:
        raise ValueError(msg)


def hash_object(value) -> str:
    return hashlib.sha256(DOM + canonical(value)).hexdigest()


def feature_band(query: str, highest_doc: str) -> str:
    q = set(TOKEN.findall(query.casefold()))
    d = set(TOKEN.findall(highest_doc.casefold()))
    need(bool(q) and bool(d), 'empty top-ranked input')
    overlap = Fraction(len(q & d), len(q))
    if overlap < Fraction(1, 5):
        return 'weak'
    if overlap < Fraction(1, 2):
        return 'medium'
    return 'strong'


def freeze_train(public: dict, observations: list[dict]) -> dict:
    """Train-only supported evidence outcomes; no held original label permitted."""
    validate(public)
    expected = {(r['root'], q['id']): (r, q) for r in public['roots'] if r['split']=='TRAIN'
                for q in r['questions']}
    need(len(expected)==144 and type(observations) is list and len(observations)==144,
         'incomplete train source')
    seen=set();out = {k:{'n':0,'bm25_hits':0,'rrf_hits':0,'roots':set()} for k in BANDS}
    for obs in observations:
        need(type(obs) is dict and set(obs)=={'root','qid','source_sha','band','bm25_hit','rrf_hit'},
             'unknown training observation field')
        key=obs['root'],obs['qid']
        need(key in expected and key not in seen,'TRAIN-only deduplicated observations required')
        r,q=expected[key]
        need(obs['source_sha']==q['text_sha'] and obs['band'] in BANDS
             and type(obs['bm25_hit']) is bool and type(obs['rrf_hit']) is bool,
             'unbound original train label/feature')
        seen.add(key)
        x=out[obs['band']];x['n']+=1;x['bm25_hits']+=int(obs['bm25_hit']);x['rrf_hits']+=int(obs['rrf_hit']);x['roots'].add(r['root'])
    need(seen==set(expected),'incomplete real source train')
    bins={k:{'n':v['n'],'bm25_hits':v['bm25_hits'],'rrf_hits':v['rrf_hits'],
             'roots':len(v['roots'])} for k,v in out.items()}
    profile={'schema':SCHEMA,'source_digest':public['digest'],'model_sha':public['model_sha'],
             'train_roots':list(TRAIN),'held_roots':list(HELD),
             'label':'original_human_evidence_hit_at_5_not_answer_quality',
             'utility':{'hit':HIT,'miss':MISS,'stop':0,'rerank_incremental_fee':MARGINAL_RERANK_FEE,
                        'bm25_common_scan_fee_excluded_from_action_difference':True},
             'smoothing':'beta_1_1','categories':bins,'max_paid_questions_per_root':MAX_ROOT_BUDGET,
             'horizon':24,'research_only':True,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    profile['digest']=hash_object(profile)
    verify_profile(profile, public)
    return profile


def verify_profile(profile,public):
    validate(public)
    need(type(profile) is dict and set(profile)=={'schema','source_digest','model_sha','train_roots',
         'held_roots','label','utility','smoothing','categories','max_paid_questions_per_root',
         'horizon','research_only','production_authorized','disposition','digest'},'profile shape')
    need(profile['schema']==SCHEMA and profile['source_digest']==public['digest']
         and profile['model_sha']==public['model_sha'] and profile['train_roots']==list(TRAIN)
         and profile['held_roots']==list(HELD) and profile['label']=='original_human_evidence_hit_at_5_not_answer_quality'
         and profile['utility']=={'hit':HIT,'miss':MISS,'stop':0,'rerank_incremental_fee':MARGINAL_RERANK_FEE,
                 'bm25_common_scan_fee_excluded_from_action_difference':True}
         and profile['smoothing']=='beta_1_1' and profile['max_paid_questions_per_root']==MAX_ROOT_BUDGET
         and profile['horizon']==24 and profile['research_only'] is True
         and profile['production_authorized'] is False and profile['disposition']=='HOLD_NO_GO',
         'wrong objective, budget, model or authority')
    need(type(profile['categories']) is dict and set(profile['categories'])==set(BANDS),'missing bands')
    need(sum(v['n'] for v in profile['categories'].values())==144,'model cannot fabricate training sample count')
    for v in profile['categories'].values():
        need(type(v) is dict and set(v)=={'n','bm25_hits','rrf_hits','roots'} and
             all(type(v[k]) is int for k in v) and 0<=v['bm25_hits']<=v['n']
             and 0<=v['rrf_hits']<=v['n']<=144 and 0<=v['roots']<=6,
             'invalid training profile')
    need(profile['digest']==hash_object({k:v for k,v in profile.items() if k!='digest'}),
         'tampered profile')


def expected_value(profile: dict, band: str, action: int) -> Fraction:
    need(band in BANDS and type(action) is int and 0<=action<3,'unsupported action')
    if action==0:return Fraction(0)
    x=profile['categories'][band];n=x['n'];h=x['bm25_hits'] if action==1 else x['rrf_hits']
    # Laplace-smoothed expectations with fixed prices, no model-selected outcome metric.
    p=Fraction(h+1,n+2)
    return p*HIT+(1-p)*MISS-(MARGINAL_RERANK_FEE if action==2 else 0)


def ndu_backward(profile: dict, bands: list[str], cap: int) -> tuple[int,...]:
    """Finite deterministic recursive utility with explicit remaining-resource state."""
    need(type(bands) is list and 1<=len(bands)<=24 and all(b in BANDS for b in bands)
         and type(cap) is int and 0<=cap<=MAX_ROOT_BUDGET,'unbounded recursive solver')
    tail=[(Fraction(0),tuple()) for _ in range(cap+1)]
    for band in reversed(bands):
        successor=[]
        for free in range(cap+1):
            options=[]
            for a in range(3):
                if a==2 and free==0:continue
                value,sub=tail[free-int(a==2)]
                options.append((expected_value(profile,band,a)+value,(a,)+sub))
            # Exact optimality for this frozen linear special case only.
            successor.append(sorted(options,key=lambda v:(-v[0],v[1]))[0])
        tail=successor
    return tail[cap][1]


def bellman_forward(profile: dict,bands: list[str],cap: int) -> tuple[int,...]:
    """Independent forward knapsack, no backwards solve or recursive reuse."""
    need(type(bands) is list and 1<=len(bands)<=24 and all(b in BANDS for b in bands)
         and type(cap) is int and 0<=cap<=MAX_ROOT_BUDGET,'unbounded Bellman budget')
    states={0:(Fraction(0),tuple())}
    for b in bands:
        new={}
        for paid,(score,seq) in states.items():
            for action in range(3):
                cost=int(action==2)
                if paid+cost>cap:continue
                cand=(score+expected_value(profile,b,action),seq+(action,))
                key=paid+cost
                if key not in new or cand[0]>new[key][0] or (cand[0]==new[key][0] and cand[1]<new[key][1]):
                    new[key]=cand
        states=new
    return sorted(states.values(),key=lambda v:(-v[0],v[1]))[0][1]


def plan(public:dict,profile:dict,held_features:list[dict],cap:int=MAX_ROOT_BUDGET)->dict:
    verify_profile(profile,public)
    need(type(held_features) is list and len(held_features)==96,'held source census')
    expected={(r['root'],q['id']):q for r in public['roots'] if r['split']=='HELD' for q in r['questions']}
    ordered=[];seen=set()
    for item in held_features:
        need(type(item) is dict and set(item)=={'root','qid','source_sha','band','bm25_top5_ids'},'unsafe held observation')
        k=item['root'],item['qid']
        need(k in expected and k not in seen and item['source_sha']==expected[k]['text_sha']
             and item['band'] in BANDS and type(item['bm25_top5_ids']) is list
             and len(item['bm25_top5_ids'])==5 and len(set(item['bm25_top5_ids']))==5,
             'held source/lexical leak')
        seen.add(k);ordered.append(item)
    need(seen==set(expected) and ordered==sorted(ordered,key=lambda x:(x['root'],x['qid'])),
         'noncanonical held roster')
    arms=[]
    for root in HELD:
        rows=[v for v in ordered if v['root']==root]
        need(len(rows)==24,'root missing')
        bands=[v['band'] for v in rows]
        ndu=ndu_backward(profile,bands,cap)
        bellman=bellman_forward(profile,bands,cap)
        need(ndu==bellman,'same-utility Bellman/NDU mismatch')
        # Fixed eight source-order priced actions: no held labels or outcomes.
        fixed=[2 if i<cap else 1 for i in range(24)]
        arms.extend([{'root':root,'qid':r['qid'],'source_sha':r['source_sha'],
                       'band':r['band'],'bm25_top5_ids':r['bm25_top5_ids'],
                       'ndu':ACTIONS[ndu[i]],'bellman':ACTIONS[bellman[i]],
                       'fixed':ACTIONS[fixed[i]]} for i,r in enumerate(rows)])
    out={'schema':'hepta.hdsi.g7.sealed-prelabel-plan.v1','profile_digest':profile['digest'],
         'source_digest':public['digest'],'cap_per_root':cap,'decisions':arms,
         'same_objective_bellman_ndu_parity':True,'held_labels_accessed':False,
         'precommitted_original_future':False,'research_only':True,
         'production_authorized':False,'disposition':'HOLD_NO_GO'}
    out['digest']=hash_object(out)
    return out


def verify_plan(public,profile,proposal):
    verify_profile(profile,public)
    need(type(proposal) is dict and proposal.get('schema')=='hepta.hdsi.g7.sealed-prelabel-plan.v1'
         and proposal.get('profile_digest')==profile['digest']
         and proposal.get('source_digest')==public['digest']
         and proposal.get('same_objective_bellman_ndu_parity') is True
         and proposal.get('held_labels_accessed') is False
         and proposal.get('precommitted_original_future') is False
         and proposal.get('production_authorized') is False and proposal.get('disposition')=='HOLD_NO_GO'
         and proposal.get('research_only') is True,
         'unsafe plan')
    need(proposal.get('digest')==hash_object({k:v for k,v in proposal.items() if k!='digest'}),
         'plan seal mismatch')
    regenerated=plan(public,profile,[{k:row[k] for k in ('root','qid','source_sha','band','bm25_top5_ids')}
                             for row in proposal['decisions']],cap=proposal['cap_per_root'])
    need(proposal==regenerated,'not a label-blind exact solver plan')
