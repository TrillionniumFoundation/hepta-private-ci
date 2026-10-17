"""G8 coverage-matched cautious Episode value controller.

Only original six TRAIN roots determine which actions are *admitted*.
STOP requires 20 independently supported source roots and is unavailable in this
historical 6-root study; the bound is a declared conservative engineering gate,
not an FBSDE or confidence theorem. RERANK requires a strictly positive net
advantage on every leave-one-root-out TRAIN fold. Independent ordinary Bellman
must choose the identical actions on the same frozen objective.
"""
from __future__ import annotations
from fractions import Fraction
import hashlib
import json

from g8_source import validate, canonical, TRAIN, HELD
from g7_policy import feature_band

DOM = b'hepta.hdsi.g8.coverage-aligned-guarded-utility.v1\0'
SCHEMA = 'hepta.hdsi.g8.full-corpus-episode-value.v1'
ACTIONS = ('STOP', 'BM25', 'RERANK')
BANDS = ('weak', 'medium', 'strong')
FEE = 900
WIN = 10000
LOSS = -3000
CAP = 8


def need(ok, why):
    if ok is not True:
        raise ValueError(why)


def digest(value):
    return hashlib.sha256(DOM + canonical(value)).hexdigest()


def freeze(public, observations):
    validate(public)
    expected = {(r['root'], q['id']): q for r in public['roots'] if r['root'] in TRAIN for q in r['questions']}
    need(len(expected) == 144 and type(observations) is list and len(observations) == 144,
         'TRAIN source groups are not complete')
    counts = {band: {root: {'n': 0, 'bm25': 0, 'rrf': 0, 'rescues': 0, 'harms': 0}
                     for root in TRAIN} for band in BANDS}
    seen = set()
    for x in observations:
        need(type(x) is dict and set(x) == {'root', 'qid', 'source_sha', 'band', 'bm25_hit', 'rrf_hit', 'bm25_top10', 'rrf_top10'},
             'unknown train observation or oracle field')
        key = (x['root'], x['qid'])
        need(key in expected and key not in seen and x['source_sha'] == expected[key]['text_sha']
             and x['band'] in BANDS and type(x['bm25_hit']) is bool and type(x['rrf_hit']) is bool,
             'leaked or substituted train outcome')
        original = next(r for r in public['roots'] if r['root'] == x['root'])
        truth = set(expected[key]['train_support'])
        bank = {d['id'] for d in original['docs']}
        for field in ('bm25_top10','rrf_top10'):
            ids=x[field]
            need(type(ids) is list and len(ids)==10 and len(set(ids))==10
                 and set(ids)<=bank, 'unbound train ranked source addresses')
        need(x['bm25_hit'] is bool(truth & set(x['bm25_top10'][:5]))
             and x['rrf_hit'] is bool(truth & set(x['rrf_top10'][:5])),
             'train outcome does not match original evidence addresses')
        seen.add(key)
        v = counts[x['band']][x['root']]
        v['n'] += 1
        v['bm25'] += int(x['bm25_hit'])
        v['rrf'] += int(x['rrf_hit'])
        v['rescues'] += int(x['rrf_hit'] and not x['bm25_hit'])
        v['harms'] += int(x['bm25_hit'] and not x['rrf_hit'])
    need(seen == set(expected), 'missing original training outcomes')
    policies = {}
    for band in BANDS:
        d = counts[band]
        n = sum(r['n'] for r in d.values())
        b = sum(r['bm25'] for r in d.values())
        root_support = sum(v['n'] >= 3 for v in d.values())
        # Prevent exploit of absent source support by a spurious '0 probability'.
        adv = []
        if root_support >= 4:
            for hold in TRAIN:
                rem = [v for name, v in d.items() if name != hold]
                den = sum(v['n'] for v in rem)
                adv.append(Fraction(13000 * sum(v['rescues'] - v['harms'] for v in rem), max(den,1)) - FEE)
        # This is adversarial leave-one-root-out empirical advantage, not a CI.
        permitted = (root_support >= 4 and bool(adv) and min(adv) > 0)
        policies[band] = {'observations': n, 'root_support': root_support,
                          'bm25_hits': b, 'per_root': d,
                          'rerank_admitted': bool(permitted),
                          'loo_worst_advantage_units': str(min(adv)) if adv else None,
                          'stop_admitted': False}
    p = {'schema': SCHEMA, 'source_digest': public['digest'],
         'material_sha': public['model_sha'], 'train_roots': list(TRAIN), 'held_roots': list(HELD),
         'sample': 'historical_original_evidence_hit_at_5_not_answer_quality',
         'utility': {'hit': WIN, 'miss': LOSS, 'stop': 0, 'rerank_marginal': FEE,
                     'common_bm25_already_paid': True},
         'stop_support_requirement': 'at_least_20_independent_source_roots',
         'rerank_support_requirement': 'positive_every_leave_one_root_out_fold_min_4_roots',
         'max_rerank_per_root': CAP, 'bands': policies,
         'full_corpus_training': True, 'labels_used': 'TRAIN_only',
         'future_verified': False, 'research_only': True,
         'production_authorized': False, 'disposition': 'HOLD_NO_GO'}
    p['digest'] = digest(p)
    validate_profile(p, public)
    return p


def validate_profile(p, public):
    validate(public)
    need(type(p) is dict and set(p) == {'schema', 'source_digest', 'material_sha',
         'train_roots', 'held_roots', 'sample', 'utility', 'stop_support_requirement',
         'rerank_support_requirement', 'max_rerank_per_root', 'bands', 'full_corpus_training',
         'labels_used', 'future_verified', 'research_only', 'production_authorized', 'disposition', 'digest'},
         'profile shape')
    need(p['schema'] == SCHEMA and p['source_digest'] == public['digest']
         and p['material_sha'] == public['model_sha']
         and p['train_roots'] == list(TRAIN) and p['held_roots'] == list(HELD)
         and p['sample'] == 'historical_original_evidence_hit_at_5_not_answer_quality'
         and p['utility'] == {'hit': WIN, 'miss': LOSS, 'stop': 0,
                             'rerank_marginal': FEE, 'common_bm25_already_paid': True}
         and p['stop_support_requirement'] == 'at_least_20_independent_source_roots'
         and p['rerank_support_requirement'] == 'positive_every_leave_one_root_out_fold_min_4_roots'
         and p['max_rerank_per_root'] == CAP and p['full_corpus_training'] is True
         and p['labels_used'] == 'TRAIN_only' and p['future_verified'] is False
         and p['research_only'] is True and p['production_authorized'] is False
         and p['disposition'] == 'HOLD_NO_GO', 'unregistered preference/safety scope')
    need(type(p['bands']) is dict and set(p['bands']) == set(BANDS), 'missing bands')
    need(sum(b['observations'] for b in p['bands'].values()) == 144, 'TRAIN cardinality')
    for band in BANDS:
        b = p['bands'][band]
        need(type(b) is dict and set(b) == {'observations', 'root_support', 'bm25_hits',
             'per_root', 'rerank_admitted', 'loo_worst_advantage_units', 'stop_admitted'},
             'unexpected band field')
        need(type(b['per_root']) is dict and set(b['per_root']) == set(TRAIN), 'source families swapped')
        need(b['root_support'] == sum(v['n'] >= 3 for v in b['per_root'].values())
             and b['observations'] == sum(v['n'] for v in b['per_root'].values())
             and b['bm25_hits'] == sum(v['bm25'] for v in b['per_root'].values())
             and b['stop_admitted'] is False, 'unsound stop/census')
        for v in b['per_root'].values():
            need(type(v) is dict and set(v) == {'n', 'bm25', 'rrf', 'rescues', 'harms'}
                 and all(type(v[k]) is int for k in v)
                 and 0 <= v['bm25'] <= v['n'] <= 24 and 0 <= v['rrf'] <= v['n']
                 and 0 <= v['rescues'] <= v['n'] and 0 <= v['harms'] <= v['n']
                 and v['rrf'] - v['bm25'] == v['rescues'] - v['harms'],
                 'training paired counts inconsistent')
        val = []
        if b['root_support'] >= 4:
            for hold in TRAIN:
                rem = [v for root, v in b['per_root'].items() if root != hold]
                den = sum(v['n'] for v in rem)
                val.append(Fraction(13000 * sum(v['rescues']-v['harms'] for v in rem), max(den,1)) - FEE)
        admission = bool(val) and min(val) > 0
        need(b['rerank_admitted'] is admission
             and b['loo_worst_advantage_units'] == (str(min(val)) if val else None),
             'false leave-one-root-out action admission')
    need(p['digest'] == digest({k: v for k, v in p.items() if k != 'digest'}), 'profile digest mismatch')


def expected_utility(profile, band, action):
    need(band in BANDS and action in ACTIONS, 'not a registered control')
    data = profile['bands'][band]
    if action == 'STOP':
        need(data['stop_admitted'] is True, 'unsafe stop is inadmissible')
        return Fraction(0)
    n = data['observations']
    bm = Fraction(data['bm25_hits']+1, n+2)
    base = bm*WIN+(1-bm)*LOSS
    if action == 'BM25':return base
    need(data['rerank_admitted'] is True, 'unqualified paid rerank')
    # The only permitted learned rerank value is a conservative LOO advantage.
    return base + Fraction(data['loo_worst_advantage_units'])


def available(profile, band):
    need(band in BANDS, 'unknown supported preference band')
    data = profile['bands'][band]
    return tuple(a for a in ACTIONS if a == 'BM25'
                 or (a == 'RERANK' and data['rerank_admitted'])
                 or (a == 'STOP' and data['stop_admitted']))


def ndu_backward(profile, bands, cap=CAP):
    need(type(bands) is list and 1 <= len(bands) <= 24 and all(x in BANDS for x in bands)
         and type(cap) is int and 0 <= cap <= CAP, 'bounded Episode horizon and budget')
    tail = [(Fraction(0), ()) for _ in range(cap+1)]
    for b in reversed(bands):
        next_tail = []
        for free in range(cap+1):
            opts = []
            for action in available(profile,b):
                price = int(action == 'RERANK')
                if price > free:continue
                reward, suffix = tail[free-price]
                opts.append((reward+expected_utility(profile,b,action), (action,)+suffix))
            next_tail.append(sorted(opts,key=lambda x:(-x[0],x[1]))[0])
        tail = next_tail
    return tail[cap][1]


def bellman_forward(profile, bands, cap=CAP):
    need(type(bands) is list and 1 <= len(bands) <= 24 and all(x in BANDS for x in bands)
         and type(cap) is int and 0 <= cap <= CAP, 'bounded ordinary Bellman')
    dp = {0: (Fraction(0), ())}
    for b in bands:
        new = {}
        for paid, (value, actions) in dp.items():
            for a in available(profile,b):
                next_paid = paid + int(a == 'RERANK')
                if next_paid > cap: continue
                candidate = (value+expected_utility(profile,b,a),actions+(a,))
                if next_paid not in new or candidate[0] > new[next_paid][0] or (candidate[0] == new[next_paid][0] and candidate[1] < new[next_paid][1]):
                    new[next_paid] = candidate
        dp = new
    return sorted(dp.values(),key=lambda x:(-x[0],x[1]))[0][1]


def plan(public, profile, features):
    validate_profile(profile,public)
    expected = {(r['root'],q['id']):q for r in public['roots'] if r['root'] in HELD for q in r['questions']}
    need(type(features) is list and len(features) == 96,'missing HELD label-blind cases')
    seen=set();out=[]
    for x in features:
        need(type(x) is dict and set(x) == {'root','qid','source_sha','band','bm25_top10'},
             'leaked score/label in plan input')
        k = x['root'],x['qid']
        need(k in expected and k not in seen and x['source_sha']==expected[k]['text_sha']
             and x['band'] in BANDS and type(x['bm25_top10']) is list and len(x['bm25_top10'])==10
             and len(set(x['bm25_top10']))==10, 'held identity/source change')
        seen.add(k);out.append(x)
    need(seen==set(expected) and out==sorted(out,key=lambda x:(x['root'],x['qid'])),
         'wrong held roster or ordering')
    result=[]
    for name in HELD:
        root=[x for x in out if x['root']==name]
        need(len(root)==24, 'incomplete test episode')
        seq=[x['band'] for x in root]
        ndu=ndu_backward(profile,seq,CAP)
        bell=bellman_forward(profile,seq,CAP)
        need(ndu==bell,'NDU/Bellman same-objective parity regression')
        for i,x in enumerate(root):
            result.append({**x,'ndu':ndu[i], 'bellman':bell[i],
                           'fixed':'RERANK' if i<CAP else 'BM25'})
    answer = {'schema':'hepta.hdsi.g8.prelabel-action-plan.v1',
              'source_digest':public['digest'],'profile_digest':profile['digest'],
              'cap_per_root': CAP, 'choices':result,
              'original_held_gold_accessed':False,'matched_Bellman_NDU_parity':True,
              'prospective_validation':False,'production_authorized':False,
              'disposition':'HOLD_NO_GO'}
    answer['digest']=digest(answer)
    return answer


def verify_plan(public,profile,receipt):
    need(type(receipt) is dict and set(receipt)=={'schema','source_digest','profile_digest','cap_per_root',
         'choices','original_held_gold_accessed','matched_Bellman_NDU_parity','prospective_validation',
         'production_authorized','disposition','digest'},'plan shape')
    need(receipt == plan(public,profile,[{k:v[k] for k in ('root','qid','source_sha','band','bm25_top10')}
                                             for v in receipt['choices']]),'plan was rewritten')
    # The plan is not authority merely because it rehashes its own input. Check
    # source-bound cheap retrieval and band against actual public text as well.
    from g6_coverage_model import bm25_all
    for record in public['roots']:
        if record['root'] not in HELD:continue
        rankings,_=bm25_all(record['docs'],record['questions'])
        choices={(x['root'],x['qid']):x for x in receipt['choices']}
        for q,ranking in zip(record['questions'],rankings):
            x=choices[(record['root'],q['id'])]
            need(x['bm25_top10']==[record['docs'][j]['id'] for j in ranking[:10]]
                 and x['band']==feature_band(q['text'],record['docs'][ranking[0]]['text']),
                 'lexical/feature prelabel source substitution')
