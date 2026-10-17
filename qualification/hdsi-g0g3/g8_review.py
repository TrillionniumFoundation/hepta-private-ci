"""Independent model-free G8 source/utility/physics-accounting audit.

Reconstruct original human evidence and the same-utility ordinary Bellman solver
without importing any G8 model, trainer, actor, NDU solver, Torch or tokenizer.
Only matching terminal receipts may be described as reviewed. An archived public
historical holdout is NOT prospective evidence, even when this review succeeds.
"""
from __future__ import annotations
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re

from g6_independent_review import independent_rebuild,original_full_docs,independent_bm25

ORIGINAL='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
MODEL='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
TRAIN=('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')
HELD=('conv-47','conv-48','conv-49','conv-50')
BANDS=('weak','medium','strong')
DOM=b'hepta.hdsi.g8.coverage-aligned-guarded-utility.v1\0'
SOURCE_DOM=b'hepta.hdsi.g8.full-original-source.v1\0'
WORD=re.compile(r'(?u)\b\w+\b')


def require(x, why):
    if x is not True:raise ValueError(why)


def packed(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(x):return hashlib.sha256(DOM+packed(x)).hexdigest()


def independently_band(query,first_doc):
    q=set(WORD.findall(query.casefold()));d=set(WORD.findall(first_doc.casefold()))
    require(bool(q) and bool(d),'empty source terms')
    fraction=Fraction(len(q&d),len(q))
    return 'weak' if fraction<Fraction(1,5) else ('medium' if fraction<Fraction(1,2) else 'strong')


def independent_roots(raw):
    expected,gold=independent_rebuild(raw)
    # G6 preserved G5's 256-document TRAIN bank; G8 must use all original docs
    # in every root while preserving the exact historically fixed question IDs.
    originals=json.loads(raw)
    by={item['sample_id']:item for item in originals}
    for row in expected:
        row['docs']=original_full_docs(by[row['root']])
    return expected,gold


def independent_count_profile(public,assembled):
    expected={(r['root'],q['id']):q for r in public['roots'] if r['root'] in TRAIN for q in r['questions']}
    require(len(assembled['train_observations'])==len(expected)==144,
            'train observation count missing')
    counts={b:{root: {'n':0,'bm25':0,'rrf':0,'rescues':0,'harms':0} for root in TRAIN}
            for b in BANDS}
    seen=set();indexed={r['root']:r for r in public['roots']}
    actual={n:independent_bm25(indexed[n]['docs'],indexed[n]['questions']) for n in TRAIN}
    for row in assembled['train_observations']:
        require(type(row) is dict and set(row)=={'root','qid','source_sha','band',
                  'bm25_hit','rrf_hit','bm25_top10','rrf_top10'},'unreviewed train field')
        name,qid=row['root'],row['qid'];key=name,qid
        require(key in expected and key not in seen,'leaked or duplicated train row')
        seen.add(key);q=expected[key];bank=indexed[name]['docs'];ids={d['id'] for d in bank}
        pos=next(i for i,v in enumerate(indexed[name]['questions']) if v['id']==qid)
        ranked=actual[name][pos]
        require(row['source_sha']==q['text_sha']
                and row['band']==independently_band(q['text'],next(d['text'] for d in bank if d['id']==ranked[0]))
                and row['bm25_top10']==ranked[:10]
                and len(row['rrf_top10'])==len(set(row['rrf_top10']))==10
                and set(row['rrf_top10'])<=set(ranked[:64]),
                'TRAIN lexical or learned candidate substitution')
        gold=set(q['train_support']);b=bool(gold&set(row['bm25_top10'][:5]));r=bool(gold&set(row['rrf_top10'][:5]))
        require(row['bm25_hit'] is b and row['rrf_hit'] is r,'train oracle label spoofing')
        count=counts[row['band']][name]
        count['n']+=1;count['bm25']+=int(b);count['rrf']+=int(r)
        count['rescues']+=int(r and not b);count['harms']+=int(b and not r)
    require(seen==set(expected),'incomplete training source')
    profile=assembled['profile']
    require(profile['source_digest']==public['digest']
            and profile['material_sha']==MODEL and profile['train_roots']==list(TRAIN)
            and profile['held_roots']==list(HELD)
            and profile['max_rerank_per_root']==8
            and profile['utility']=={'hit':10000,'miss':-3000,'stop':0,'rerank_marginal':900,
                                    'common_bm25_already_paid':True}
            and profile['stop_support_requirement']=='at_least_20_independent_source_roots'
            and profile['rerank_support_requirement']=='positive_every_leave_one_root_out_fold_min_4_roots'
            and profile['full_corpus_training'] is True and profile['labels_used']=='TRAIN_only'
            and profile['production_authorized'] is False and profile['disposition']=='HOLD_NO_GO'
            and profile['digest']==digest({k:v for k,v in profile.items() if k!='digest'}),
            'value profile/source/objective changed')
    for b,per_root in counts.items():
        x=profile['bands'][b]
        n=sum(v['n'] for v in per_root.values());nh=sum(v['bm25'] for v in per_root.values())
        good=sum(v['n']>=3 for v in per_root.values())
        advantage=[]
        if good>=4:
            for hold in TRAIN:
                other=[v for k,v in per_root.items() if k!=hold]
                total=sum(z['n'] for z in other)
                delta=sum(z['rescues']-z['harms'] for z in other)
                advantage.append(Fraction(13000*delta,max(total,1))-900)
        admit=bool(advantage) and min(advantage)>0
        require(x=={'observations':n,'root_support':good,'bm25_hits':nh,'per_root':per_root,
                    'rerank_admitted':admit,'loo_worst_advantage_units':str(min(advantage)) if advantage else None,
                    'stop_admitted':False},'unindependent utility or STOP admission')
    return profile


def own_bellman(profile,bands,cap=8):
    """Independent iterative action knapsack, not the original NDU code."""
    dp={0:(Fraction(0),())}
    for b in bands:
        v=profile['bands'][b];n=v['observations']
        p=Fraction(v['bm25_hits']+1,n+2)
        bm=p*10000-(1-p)*3000
        opts=[('BM25',bm)]
        if v['rerank_admitted']:opts.append(('RERANK',bm+Fraction(v['loo_worst_advantage_units'])))
        new={}
        for spent,(score,old) in dp.items():
            for name,reward in opts:
                k=spent+int(name=='RERANK')
                if k>cap:continue
                alt=score+reward,old+(name,)
                if k not in new or alt[0]>new[k][0] or (alt[0]==new[k][0] and alt[1]<new[k][1]):new[k]=alt
        dp=new
    return sorted(dp.values(),key=lambda x:(-x[0],x[1]))[0][1]


def review(original:bytes, public:dict, roots:list[dict], assembled:dict, paid:dict):
    reference,gold=independent_roots(original)
    require(public['roots']==reference and public['model_sha']==MODEL and public['original_sha']==ORIGINAL
            and public['held_gold_exported'] is False and public['research_only'] is True
            and public['production_authorized'] is False and public['disposition']=='HOLD_NO_GO'
            and public['digest']==hashlib.sha256(SOURCE_DOM+packed({k:v for k,v in public.items() if k!='digest'})).hexdigest(),
            'publisher root/held label/source not independently verified')
    require(len(roots)==6 and {r['root'] for r in roots}==set(TRAIN)
            and assembled['source_root_digests']=={r['root']:r['digest'] for r in roots},
            'original training receipt missing')
    require(assembled['source_digest']==public['digest']
            and assembled['schema']=='hepta.hdsi.g8.train-assembly-prelabel.v1'
            and assembled['digest']==digest({k:v for k,v in assembled.items() if k!='digest'})
            and assembled['original_held_gold_accessed'] is False
            and assembled['production_authorized'] is False,
            'assembly sealed before held human gold')
    table={r['root']:r for r in reference}
    true_seq=true_batch=true_tok=true_pairs=0
    for row in roots:
        name=row['root'];docs=table[name]['docs'];questions=table[name]['questions']
        bm=independent_bm25(docs,questions)
        union=set(d for entries in bm for d in entries[:64])
        seq=24+len(union)
        require(row['digest']==digest({k:v for k,v in row.items() if k!='digest'})
                and row['schema']=='hepta.hdsi.g8.one-original-train-root.v1'
                and row['original_model_sha']==MODEL and row['source_digest']==public['digest']
                and row['frozen_pretrained_encoder'] is True and row['held_gold_accessed'] is False
                and row['future_quality_verified'] is False and row['production_authorized'] is False
                and row['encoder_sequences']==seq and row['encoder_batches']==math.ceil(seq/16)
                and row['encoder_tokens']>=seq
                and row['source_census']['bm25_pair_scores']==len(docs)*24
                and row['source_census']['full_docs']==len(docs)
                and row['source_census']['full_questions']==24
                and row['source_census']['encoded_unique_documents']==len(union)
                and row['source_census']['support']['all']==24,
                'actual original source or real physical model census invalid')
        true_seq+=seq;true_batch+=math.ceil(seq/16);true_tok+=row['encoder_tokens'];true_pairs+=len(docs)*24
    require((true_seq,true_batch,true_tok,true_pairs)==
            (assembled['actual_train_encoder_sequences'],assembled['actual_train_encoder_batches'],
             assembled['actual_train_encoder_tokens'],assembled['train_bm25_pairs']),
            'TRAIN source/device work overcounted')
    profile=independent_count_profile(public,assembled)
    need=assembled['sealed_held_plan']
    require(need['profile_digest']==profile['digest']
            and need['source_digest']==public['digest']
            and need['digest']==digest({k:v for k,v in need.items() if k!='digest'})
            and need['original_held_gold_accessed'] is False
            and need['matched_Bellman_NDU_parity'] is True,
            'held plan was not frozen')
    choices={(r['root'],r['qid']):r for r in need['choices']}
    require(len(choices)==96,'incomplete sealed answer set')
    for name in HELD:
        root=table[name];qs=sorted(root['questions'],key=lambda x:x['id'])
        rank=independent_bm25(root['docs'],root['questions'])
        observed=[]
        for q in qs:
            i=next(i for i,v in enumerate(root['questions']) if v['id']==q['id'])
            p=choices[name,q['id']]
            doc=next(d for d in root['docs'] if d['id']==rank[i][0])
            require(p['root']==name and p['source_sha']==q['text_sha']
                    and p['band']==independently_band(q['text'],doc['text'])
                    and p['bm25_top10']==rank[i][:10],
                    'postseal lexical/features changed')
            observed.append(p['band'])
        decision=own_bellman(profile,observed)
        for j,q in enumerate(qs):
            p=choices[name,q['id']]
            require(p['ndu']==p['bellman']==decision[j]
                    and p['fixed']==('RERANK' if j<8 else 'BM25'),
                    'same objective ordinary Bellman parity or fixed control broken')
    require(paid['schema']=='hepta.hdsi.g8.paid-original-episode-v1'
            and paid['source_digest']==public['digest']
            and paid['assembled_digest']==assembled['digest']
            and paid['plan_digest']==need['digest']
            and paid['profile_digest']==profile['digest']
            and paid['original_model_sha']==MODEL
            and paid['digest']==digest({k:v for k,v in paid.items() if k!='digest'})
            and paid['held_human_gold_accessed'] is False
            and paid['mathematical_NDU_Bellman_parity'] is True
            and paid['production_authorized'] is False
            and paid['disposition']=='HOLD_NO_GO',
            'paid model source or arithmetic forged')
    outcomes={mode:{'hit_at_5':0,'hit_at_10':0,'submitted':0,'stopped':0,'paid_rerank':0,'net_utility':0}
              for mode in ('bm25','ndu','bellman','fixed')}
    gains={mode:{'rescues':0,'harms':0,'ties':0} for mode in ('ndu','fixed')}
    seen=set(); source_hit={r:{mode:0 for mode in outcomes} for r in HELD}
    for obs in paid['decisions']:
        name,qid=obs['root'],obs['qid'];key=name,qid
        require(key in choices and key not in seen,'extra/missing paid question')
        seen.add(key);q=next(v for v in table[name]['questions'] if v['id']==qid)
        bm=independent_bm25(table[name]['docs'],[q])[0]
        # independent_bm25 accepts the same corpus and one question; same doc ordering and idf.
        require(obs['source_sha']==q['text_sha'] and obs['bm25_top10']==bm[:10],
                'model changed cheap source ranking')
        truth=gold[key];ref=bool(set(bm[:5])&truth)
        for mode in outcomes:
            action='BM25' if mode=='bm25' else obs[mode]['action']
            top=bm[:10] if mode=='bm25' else obs[mode]['top10']
            require((mode=='bm25') or (action==choices[key][mode]),'unsealed paid action')
            require(action in ('STOP','BM25','RERANK'),'illegal policy action')
            if action=='STOP':require(top==[],'STOP is not successful evidence')
            if action=='BM25':require(top==bm[:10],'unpaid model work substituted')
            if action=='RERANK':
                require(type(top) is list and len(top)==len(set(top))==10
                        and set(top)<=set(bm[:64]),'neural rerank introduced out-of-support material')
            hit=bool(truth&set(top[:5]));hit10=bool(truth&set(top[:10]))
            stat=outcomes[mode]
            stat['hit_at_5']+=int(hit);stat['hit_at_10']+=int(hit10)
            stat['submitted']+=int(action!='STOP');stat['stopped']+=int(action=='STOP')
            stat['paid_rerank']+=int(action=='RERANK')
            stat['net_utility']+=((10000 if hit else -3000) if action!='STOP' else 0)-900*int(action=='RERANK')
            source_hit[name][mode]+=int(hit)
            if mode in gains:
                gains[mode]['rescues']+=int(hit and not ref)
                gains[mode]['harms']+=int(ref and not hit)
                gains[mode]['ties']+=int(hit==ref)
        require(obs['ndu']==obs['bellman'],'NDU cannot have other model or cost')
    require(len(seen)==96 and outcomes['ndu']==outcomes['bellman'],'G8 observation parity failure')
    total_seq=total_batches=0
    for name in HELD:
        docs=table[name]['docs'];qs=table[name]['questions'];rank=independent_bm25(docs,qs)
        for mode in ('ndu','fixed'):
            selected=[i for i,q in enumerate(qs) if choices[name,q['id']][mode]=='RERANK']
            union={d for i in selected for d in rank[i][:64]}
            cost=paid['model_cost_by_source_and_policy'][name+':'+mode]
            expected=len(selected)+len(union)
            require(cost['paid_rerank_questions']==len(selected)
                    and cost['physically_encoded_queries_and_docs']==expected
                    and cost['unique_rerank_documents']==len(union)
                    and cost['pretrained_forward_batches']==math.ceil(expected/16)
                    and cost['real_original_input_token_positions']>=expected,
                    'actual on-policy resource/cost census inconsistent')
            total_seq+=expected;total_batches+=math.ceil(expected/16)
    require(total_seq==paid['actual_pretrained_sequence_forwards']
            and total_batches==paid['actual_pretrained_batches']
            and paid['shared_bm25_pair_scores']==sum(len(table[n]['docs'])*24 for n in HELD),
            'wrong resource accounting or cheap baseline')
    return {'schema':'hepta.hdsi.g8.independent-human-replay.v1',
            'original_publisher_sha_verified':True,
            'source_families_train':6,'source_families_held':4,
            'train_full_corpus_original_questions':144,
            'train_original_model_sequences':true_seq,
            'train_original_model_batches':true_batch,
            'paid_original_model_sequences':total_seq,
            'paid_original_model_batches':total_batches,
            'held_historical_original_questions':96,
            'all_train_original_gold_reachable':True,
            'training_bm25_hit5':sum(v['bm25_hits'] for v in profile['bands'].values()),
            'training_rrf_hit5':sum(sum(z['rrf'] for z in v['per_root'].values()) for v in profile['bands'].values()),
            'qualified_paid_band_count':sum(v['rerank_admitted'] for v in profile['bands'].values()),
            'qualified_stop_band_count':sum(v['stop_admitted'] for v in profile['bands'].values()),
            'arms':outcomes,'paired_vs_bm25':gains,'source_root_results':source_hit,
            'bounded_real_model_training_cost_attested':False,
            'net_NDU_over_matched_Bellman':0,
            'natural_language_answer_correctness_verified':False,
            'historically_public_not_prospective':True,
            'future_source_generalization_verified':False,
            'automatic_Cell_split_authorized':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('--paid',type=Path,required=True)
    p.add_argument('--root-receipt',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    def read(path):
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<8_000_000,
                'untrusted/symlinked oversized receipt')
        def unique(pairs):
            obj={}
            for k,v in pairs:
                require(k not in obj,'duplicate JSON evidence key')
                obj[k]=v
            return obj
        return json.loads(path.read_bytes(),object_pairs_hook=unique)
    value=review(args.original.read_bytes(),read(args.source),
           [read(x) for x in args.root_receipt],read(args.training),read(args.paid))
    require(not args.output.exists() and not args.output.is_symlink(),'create-only independent result')
    args.output.parent.mkdir(exist_ok=True,parents=True)
    fd=os.open(args.output,os.O_EXCL|os.O_CREAT|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(packed(value)+b'\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({'review':'HOLD_NO_GO','model_free':True,
         'BM25_hit5':value['arms']['bm25']['hit_at_5'],
         'ndu_hit5':value['arms']['ndu']['hit_at_5'],
         'fixed_hit5':value['arms']['fixed']['hit_at_5']},sort_keys=True))

if __name__=='__main__':main()
