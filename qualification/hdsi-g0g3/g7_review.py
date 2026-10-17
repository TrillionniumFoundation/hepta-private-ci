"""Independent, model-free review of actual on-policy G7 paid CPU outcomes.

No G7 producer, trainer, policy, Torch, or model dependencies imported.
The utility is a *registered finite retrieval-evidence proxy*, not answer quality.
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

from g6_independent_review import independent_rebuild, independent_bm25

MODEL='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
SOURCE='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
TRAIN=('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')
HELD=('conv-47','conv-48','conv-49','conv-50')
BANDS=('weak','medium','strong')
ACTIONS=('STOP','BM25','RERANK')
DOM=b'hepta.hdsi.g7.train-only-episode-policy.v1\0'
WORD=re.compile(r'(?u)\b\w+\b')


def require(ok,msg):
    if ok is not True:raise ValueError(msg)


def json_bytes(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def hash_object(v):return hashlib.sha256(DOM+json_bytes(v)).hexdigest()


def clean_json(path:Path):
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=8_000_000,'oversized/symlinked evidence')
    def pairs(x):
        d={}
        for k,v in x:
            require(k not in d,'duplicate JSON key')
            d[k]=v
        return d
    return json.loads(path.read_bytes(),object_pairs_hook=pairs)


def band(q,doc):
    tokens=set(WORD.findall(q.casefold()));other=set(WORD.findall(doc.casefold()))
    require(bool(tokens) and bool(other),'empty source query/doc')
    coverage=Fraction(len(tokens&other),len(tokens))
    return 'weak' if coverage<Fraction(1,5) else ('medium' if coverage<Fraction(1,2) else 'strong')


def reward(prof,cat,action):
    if action=='STOP':return Fraction(0)
    data=prof['categories'][cat]
    hit=data['bm25_hits'] if action=='BM25' else data['rrf_hits']
    prob=Fraction(hit+1,data['n']+2)
    return prob*10000-(1-prob)*3000-(900 if action=='RERANK' else 0)


def independent_dp(prof,items,cap):
    """Independent iterative forward program; no original backwards recursion."""
    dp={0:(Fraction(0),())}
    for bandvalue in items:
        new={}
        for n,(value,seq) in dp.items():
            for a in ACTIONS:
                paid=int(a=='RERANK');k=n+paid
                if k>cap:continue
                cand=(value+reward(prof,bandvalue,a),seq+(ACTIONS.index(a),))
                if k not in new or cand[0]>new[k][0] or (cand[0]==new[k][0] and cand[1]<new[k][1]):new[k]=cand
        dp=new
    return tuple(ACTIONS[i] for i in sorted(dp.values(),key=lambda x:(-x[0],x[1]))[0][1])


def independently_score(original:bytes,public:dict,training:dict,paid:dict)->dict:
    expected, gold=independent_rebuild(original)
    require(public['roots']==expected and public['original_sha']==SOURCE
            and public['model_sha']==MODEL and public['research_only'] is True
            and public['production_authorized'] is False and public['disposition']=='HOLD_NO_GO',
            'original publisher/source packet mismatch')
    require(type(training) is dict and training.get('schema')=='hepta.hdsi.g7.train-and-prelabel.v1'
            and training.get('source_digest')==public['digest'] and training.get('material_sha')==MODEL
            and training.get('real_pretrained_train_model') is True
            and training.get('held_gold_accessed') is False
            and training.get('future_performance_verified') is False
            and training.get('production_authorized') is False
            and training.get('disposition')=='HOLD_NO_GO'
            and training.get('digest')==hash_object({k:v for k,v in training.items() if k!='digest'}),
            'TRAIN physical receipt invalid')
    require(type(training.get('train_observations')) is list and len(training['train_observations'])==144
            and training.get('actual_train_encoder_sequences')==1680
            and training.get('actual_train_encoder_batches')==108
            and type(training.get('actual_train_tokens')) is int
            and training['actual_train_tokens']>=1680
            and type(training.get('train_source_cost')) is dict
            and set(training['train_source_cost'])==set(TRAIN)
            and training.get('original_held_bm25_pair_scores')==58728,
            'incomplete original TRAIN source/model/lexical census')
    for r in TRAIN:
        require(training['train_source_cost'][r]=={'sequences':280,'batches':18,
                'train_questions':24,'train_bm25_scores':6144},'false physical TRAIN cost')
    by_train={r['root']:r for r in expected if r['root'] in TRAIN}
    accum={k:{'n':0,'bm25_hits':0,'rrf_hits':0,'roots':set()} for k in BANDS}
    seen=set()
    cached_train_rank={n:independent_bm25(v['docs'],v['questions']) for n,v in by_train.items()}
    for row in training['train_observations']:
        require(type(row) is dict and set(row)=={'root','qid','source_sha','band','bm25_hit','rrf_hit'},
                'unexpected training label fields')
        name,qid=row['root'],row['qid'];key=name,qid
        require(name in by_train and key not in seen and type(row['bm25_hit']) is bool
                and type(row['rrf_hit']) is bool,'bad TRAIN original source')
        ref=by_train[name]; question=next((q for q in ref['questions'] if q['id']==qid),None)
        require(question is not None and row['source_sha']==question['text_sha'],'TRAIN question changed')
        records=cached_train_rank[name]
        idx=next(i for i,q in enumerate(ref['questions']) if q['id']==qid)
        ids=set(question['train_support'])
        require(row['bm25_hit']==bool(ids & set(records[idx][:5]))
                and row['band']==band(question['text'],next(d['text'] for d in ref['docs'] if d['id']==records[idx][0])),
                'TRAIN cheap human source outcome changed')
        seen.add(key); x=accum[row['band']];x['n']+=1;x['bm25_hits']+=int(row['bm25_hit']);x['rrf_hits']+=int(row['rrf_hit']);x['roots'].add(name)
    require(len(seen)==144,'TRAIN cohort omission')
    profile=training['profile']
    require(type(profile) is dict and profile.get('digest')==hash_object({k:v for k,v in profile.items() if k!='digest'})
            and profile.get('source_digest')==public['digest']
            and profile.get('model_sha')==MODEL and profile.get('max_paid_questions_per_root')==8
            and profile.get('utility')=={'hit':10000,'miss':-3000,'stop':0,'rerank_incremental_fee':900,
                     'bm25_common_scan_fee_excluded_from_action_difference':True}
            and profile.get('research_only') is True and profile.get('production_authorized') is False,
            'objective/profile mismatch')
    require(profile.get('categories')=={k:{'n':v['n'],'bm25_hits':v['bm25_hits'],
               'rrf_hits':v['rrf_hits'],'roots':len(v['roots'])} for k,v in accum.items()},
            'TRAIN learned preference profile lacks original data support')
    need_profile=profile['digest']
    seal=training['sealed_plan']
    require(seal['source_digest']==public['digest'] and seal['profile_digest']==need_profile
            and seal['digest']==hash_object({k:v for k,v in seal.items() if k!='digest'})
            and seal['cap_per_root']==8 and seal['held_labels_accessed'] is False
            and seal['production_authorized'] is False and seal['precommitted_original_future'] is False,
            'wrong planned inference identity')
    require(type(paid) is dict and paid.get('schema')=='hepta.hdsi.g7.on-policy-paid-rerank.v1'
            and paid.get('digest')==hash_object({k:v for k,v in paid.items() if k!='digest'})
            and paid.get('source_digest')==public['digest']
            and paid.get('train_record_digest')==training['digest']
            and paid.get('profile_digest')==profile['digest']
            and paid.get('sealed_plan_digest')==seal['digest']
            and paid.get('material_sha')==MODEL
            and paid.get('real_selected_original_pretrained_forward') is True
            and paid.get('mathematical_Bellman_NDU_parity') is True
            and paid.get('true_future_cohort_verified') is False
            and paid.get('natural_answer_quality_verified') is False
            and paid.get('ndu_incremental_net_gain_verified') is False
            and paid.get('production_authorized') is False and paid.get('disposition')=='HOLD_NO_GO',
            'selected model output falsely claims authority or source')
    planrows={(r['root'],r['qid']):r for r in seal['decisions']}
    predicted={(r['root'],r['qid']):r for r in paid['decisions']}
    require(len(planrows)==len(predicted)==96 and set(planrows)==set(predicted),
            'incomplete selected on-policy evidence')
    original_roots={r['root']:r for r in expected if r['root'] in HELD}
    cheap_ranks={name:independent_bm25(v['docs'],v['questions']) for name,v in original_roots.items()}
    outcomes={k:{'evidence_hit5':0,'evidence_hit10':0,'submitted':0,'stopped':0,
                 'paid_question_count':0,'observed_net_preference_units':0} for k in ('bm25','ndu','bellman','fixed')}
    disagreements={k:{'rescues':0,'harms':0,'ties':0} for k in ('ndu','fixed')}
    source_groups={}
    for name in HELD:
        record=original_roots[name];docs=record['docs'];docset=set(x['id'] for x in docs)
        refs=cheap_ranks[name];ask=record['questions']
        rows=[planrows[(name,q['id'])] for q in sorted(ask,key=lambda v:v['id'])]
        order=independent_dp(profile,[r['band'] for r in rows],seal['cap_per_root'])
        require(tuple(r['ndu'] for r in rows)==tuple(r['bellman'] for r in rows)==order,
                'separate ordinary Bellman disagrees with reported NDU decisions')
        require(tuple(r['fixed'] for r in rows)==tuple('RERANK' if i<8 else 'BM25' for i in range(24)),
                'fixed paid comparator allocation switched after gold')
        source_groups[name]={k:0 for k in outcomes}
        for i,q in enumerate(ask):
            k=name,q['id'];p=planrows[k];v=predicted[k]
            require(p['root']==name and p['qid']==q['id'] and p['source_sha']==q['text_sha']
                    and p['band']==band(q['text'], next(d['text'] for d in docs if d['id']==refs[i][0]))
                    and p['bm25_top5_ids']==refs[i][:5],
                    'the frozen plan has original label-dependent input')
            require(v['source_sha']==q['text_sha'] and v['bm25_top10']==refs[i][:10],
                    'cached first-stage evidence substituted')
            truth=gold[k]
            baseline=bool(set(refs[i][:5])&truth)
            for mode in ('ndu','bellman','fixed'):
                selected=v[mode]
                require(type(selected) is dict and set(selected)=={'action','top10'}
                        and selected['action']==p[mode], 'route differs from prelabel selection')
                if selected['action']=='STOP':require(selected['top10']==[], 'STOP fabricated evidence')
                elif selected['action']=='BM25':require(selected['top10']==refs[i][:10], 'unpaid neural operation')
                else:
                    require(type(selected['top10']) is list and len(selected['top10'])==10
                            and len(set(selected['top10']))==10
                            and set(selected['top10']).issubset(set(refs[i][:64]))
                            and set(selected['top10']).issubset(docset),
                            'paid action manufactured unsupported document')
                hit=bool(truth&set(selected['top10'][:5]));hit10=bool(truth&set(selected['top10'][:10]))
                dest=outcomes[mode];dest['evidence_hit5']+=int(hit);dest['evidence_hit10']+=int(hit10)
                dest['submitted']+=int(selected['action']!='STOP');dest['stopped']+=int(selected['action']=='STOP')
                dest['paid_question_count']+=int(selected['action']=='RERANK')
                dest['observed_net_preference_units']+=(10000 if hit else -3000) if selected['action']!='STOP' else 0
                dest['observed_net_preference_units']-=900*int(selected['action']=='RERANK')
                source_groups[name][mode]+=int(hit)
                if mode in disagreements:
                    d=disagreements[mode];d['rescues']+=int(hit and not baseline);d['harms']+=int(baseline and not hit);d['ties']+=int(baseline==hit)
            b=outcomes['bm25'];b['evidence_hit5']+=int(baseline);b['evidence_hit10']+=int(bool(set(refs[i][:10])&truth))
            b['submitted']+=1;b['observed_net_preference_units']+=(10000 if baseline else -3000)
            source_groups[name]['bm25']+=int(baseline)
            require(v['ndu']==v['bellman'],'NDU and same-profile ordinary Bellman differ')
    resource=paid['by_root_and_policy_cost']
    require(type(resource) is dict and set(resource)=={name+':'+mode for name in HELD for mode in ('ndu','fixed')},
            'unreported model costs')
    total_seq=total_batches=total_paid=0
    for name in HELD:
        for mode in ('ndu','fixed'):
            c=resource[name+':'+mode]
            require(type(c) is dict and set(c)=={'paid_questions','encoder_sequences','encoder_batches',
                   'original_tokens','distinct_documents_encoded'} and
                    all(type(c[z]) is int and c[z]>=0 for z in c), 'missing model cost field')
            expected_paid=sum(planrows[name,q['id']][mode]=='RERANK' for q in original_roots[name]['questions'])
            require(c['paid_questions']==expected_paid and c['encoder_sequences']==expected_paid+c['distinct_documents_encoded']
                    and c['encoder_batches']==math.ceil(c['encoder_sequences']/16)
                    and c['original_tokens']>=c['encoder_sequences'], 'false paid original model census')
            total_seq+=c['encoder_sequences'];total_batches+=c['encoder_batches'];total_paid+=expected_paid
    require(total_seq==paid['actual_forward_sequences'] and total_batches==paid['actual_model_batches']
            and paid['shared_lexical_comparisons']==sum(len(original_roots[name]['docs'])*24 for name in HELD),
            'missing common lexical or paid Model work')
    require(outcomes['ndu']==outcomes['bellman'], 'NDU uplift untrue under same frozen objective')
    require(sum(x['evidence_hit5'] for x in (outcomes['ndu'],))<=96,'aggregate impossible')
    return {'schema':'hepta.hdsi.g7.independent-original-human-action-review.v1',
            'source_publisher_sha_verified':True,'model_free_independent_review':True,
            'historical_held_questions':96,'held_conversation_roots':4,
            'train_roots':6,'paid_original_model_selected_sequences':total_seq,
            'paid_original_model_selected_batches':total_batches,
            'paid_rerank_question_operations':total_paid,
            'train_encoder_sequences':training['actual_train_encoder_sequences'],
            'common_full_document_bm25_pair_checks':paid['shared_lexical_comparisons'],
            'actions':outcomes,'paired_with_bm25':disagreements,
            'source_root_results':source_groups,
            'target_host_energy_joules':None,'verified_dollar_cost':None,
            'future_task_quality_verified':False,'new_publisher_family_verified':False,
            'ndu_specific_task_gain_verified':False,'natural_answer_quality_verified':False,
            'production_authorized':False,'cell_split_authorized':False,
            'disposition':'HOLD_NO_GO'}


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('--paid',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=independently_score(a.original.read_bytes(),clean_json(a.source),clean_json(a.training),clean_json(a.paid))
    require(not a.output.exists() and not a.output.is_symlink(),'create-only receipt')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(json_bytes(result)+b'\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({'HOLD_NO_GO':True,'source_sha':SOURCE,'held_questions':96,
                      'conclusion':'no_NDU_advantage_against_matched_Bellman'},sort_keys=True))

if __name__=='__main__':main()
