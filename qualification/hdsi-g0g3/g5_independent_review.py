"""Independent original publisher human-evidence review for Hepta G5.

Model-free scorer. Does not import the producer, weight loader, Torch or trained
Head. Reconstructs all source-first original human question IDs from the original
LoCoMo bytes, verifies complete withheld prediction rankings and then opens gold.
No independent person, host attestation, answer correctness or future validation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re

LOCOMO_SHA = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
MODEL_SHA = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
TRAIN = ('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')
HELD = ('conv-47','conv-48','conv-49','conv-50')
ARMS = ('bm25', 'cosine', 'rank8', 'sham_rank8', 'zero_features', 'shuffled_question')
DOM = b'hepta.hdsi.g5.original-source\0'
RUN_DOM = b'hepta.hdsi.g5.physical-prelabel\0'


def fail_if_not(valid, message):
    if valid is not True:
        raise ValueError(message)


def h(raw):
    return hashlib.sha256(raw).hexdigest()


def packed(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def without_dup(pairs):
    obj={}
    for k,v in pairs:
        fail_if_not(k not in obj,'duplicate critical JSON key')
        obj[k]=v
    return obj


def read_packet(path: Path, limit: int):
    fail_if_not(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=limit,
                'unsafe/missing packet')
    return json.loads(path.read_bytes(), object_pairs_hook=without_dup)


def expected_root(orig, root: str, split: str):
    assert split in ('TRAIN','HELD')
    spoken={}
    for key, items in orig['conversation'].items():
        if not key.startswith('session_') or type(items) is not list:
            continue
        for turn in items:
            if type(turn) is not dict:
                continue
            content=turn.get('text')
            if type(content) is not str or not 12<=len(content)<=180 or len(content.encode())>240:
                continue
            ident, who = turn.get('dia_id'), turn.get('speaker')
            if (type(ident) is not str or re.fullmatch('D[0-9]+:[0-9]+', ident) is None
                    or type(who) is not str or not 1<=len(who)<=64):
                continue
            msg=who+': '+content
            fail_if_not(ident not in spoken,'duplicate transcript source')
            spoken[ident]={'id':ident,'text':msg,'text_sha':h(msg.encode())}
    chosen=sorted(spoken.values(), key=lambda a:(h(('hdsi.g5.doc.v1\0'+root+'\0'+a['id']).encode()),a['id']))[:256]
    fail_if_not(len(chosen)==256,'original transcript cap')
    all_questions=[]
    for i, qa in enumerate(orig['qa']):
        question=qa.get('question') if type(qa) is dict else None
        if type(question) is not str or not 4<=len(question.strip())<=350 or len(question.encode())>800:
            continue
        key=h(('hdsi.g5.question.v1\0'+root+'\0'+str(i)+'\0'+question).encode())
        all_questions.append((key,i,question,qa))
    all_questions.sort(key=lambda z:z[0]); selected=all_questions[:24]
    fail_if_not(len(selected)==24,'original question cap')
    qrows=[]; held_gold={}
    for _,ix,q,raw in selected:
        entry={'id':f'q{ix}','text':q,'text_sha':h(q.encode())}
        gold=raw.get('evidence')
        fail_if_not(type(gold) is list and len(gold)<30,'original publisher evidence format')
        facts=sorted({v for v in gold if type(v) is str})
        if split=='TRAIN':
            entry['train_support']=facts
        else:
            held_gold[entry['id']]=facts
        qrows.append(entry)
    return {'root':root,'split':split,'docs':chosen,'questions':qrows},held_gold


def verify_original(raw:bytes,public:dict,runs:dict):
    fail_if_not(len(raw)<4_000_000 and h(raw)==LOCOMO_SHA,'original publisher digest')
    all_orig=json.loads(raw, object_pairs_hook=without_dup)
    fail_if_not(type(all_orig) is list and len(all_orig)==10,'wrong original population')
    canonical_roots={r['sample_id']:r for r in all_orig}
    fail_if_not(set(canonical_roots)==set(TRAIN+HELD),'unexpected root')
    keys={'schema','original_sha','model_sha','doc_cap','questions_per_root',
          'train_root_count','held_root_count','roots','production_authorized','disposition','digest'}
    fail_if_not(type(public) is dict and set(public)==keys and public['schema']=='hepta.hdsi.g5.locomo-original-source.v1'
                and public['original_sha']==LOCOMO_SHA and public['model_sha']==MODEL_SHA
                and public['doc_cap']==256 and public['questions_per_root']==24
                and public['train_root_count']==6 and public['held_root_count']==4
                and public['production_authorized'] is False and public['disposition']=='HOLD_NO_GO',
                'invalid label-free source packet')
    fail_if_not(type(public['digest']) is str and public['digest']==h(DOM+packed({k:v for k,v in public.items() if k!='digest'})),
                'original source packet seal')
    fail_if_not(type(public['roots']) is list and len(public['roots'])==10,'source root count')
    expected=[]; gold={}; banks={}; source_groups={}
    for name in sorted(canonical_roots):
        split='TRAIN' if name in TRAIN else 'HELD'
        population, private=expected_root(canonical_roots[name],name,split)
        expected.append(population)
        banks[name]={d['id'] for d in population['docs']}
        source_groups[name]=split
        for qid, refs in private.items():
            gold[(name,qid)]=refs
    fail_if_not(public['roots']==expected,'original source-first roster or hidden label tampering')

    strict={'schema','source_digest','model_sha','source_sha','training',
            'shuffled_supervision_training','roots','actual_full_encoder_forward_sequences',
            'encoder_token_positions','actual_batched_model_calls',
            'original_hidden_dimension','held_predictions','cost','original_model_forward',
            'independent_human_answer_scored','future_generalization_verified',
            'ndu_incremental_utility_verified','source_family_holdout_verified',
            'production_authorized','disposition','digest'}
    fail_if_not(type(runs) is dict and set(runs)==strict,'unexpected physical receipt schema')
    fail_if_not(runs['schema']=='hepta.hdsi.g5.real-minilm-evidence-study.v1'
                and runs['source_digest']==public['digest']
                and runs['model_sha']==MODEL_SHA and runs['source_sha']==LOCOMO_SHA
                and runs['original_hidden_dimension']==384
                and runs['disposition']=='HOLD_NO_GO'
                and runs['production_authorized'] is False
                and runs['original_model_forward'] is True
                and runs['independent_human_answer_scored'] is False
                and runs['future_generalization_verified'] is False
                and runs['ndu_incremental_utility_verified'] is False
                and runs['source_family_holdout_verified'] is True,
                'false model, source or capability claim')
    fail_if_not(runs['digest']==h(RUN_DOM+packed({k:v for k,v in runs.items() if k!='digest'})),
                'prediction seal changed after gold was available')
    for k in ('training','shuffled_supervision_training'):
        tr=runs[k]
        fail_if_not(set(tr)=={'initial_sha','trained_sha','steps','train_supported','parameters','training_elapsed_wall_seconds','training_loss_final'}
                    and tr['steps']==100 and tr['parameters']==6144
                    and type(tr['train_supported']) is int and 1<=tr['train_supported']<=144
                    and tr['trained_sha']!=tr['initial_sha']
                    and all(type(tr[d]) is str and re.fullmatch('[0-9a-f]{64}',tr[d]) is not None
                            for d in ('initial_sha','trained_sha')),
                    'reported Head training unsubstantiated')
        fail_if_not(all(type(tr[d]) in (float,int) and math.isfinite(tr[d]) and tr[d]>=0
                        for d in ('training_elapsed_wall_seconds','training_loss_final')),
                    'nonfinite training resource')
    fail_if_not(runs['training']['initial_sha']==runs['shuffled_supervision_training']['initial_sha']
                and runs['training']['steps']==runs['shuffled_supervision_training']['steps']
                and runs['training']['train_supported']==runs['shuffled_supervision_training']['train_supported'],
                'not same initialization or training budget')
    fail_if_not(type(runs['roots']) is dict and set(runs['roots'])==set(TRAIN+HELD), 'missing physical source roots')
    total=0; batches=0
    for root,vals in runs['roots'].items():
        fail_if_not(set(vals)=={'actual_completed_forward_sequences','logical_fanout_borrows','unique_feature_keys','root_split'}
                    and vals['logical_fanout_borrows']==280 and 1<=vals['actual_completed_forward_sequences']<=280
                    and vals['unique_feature_keys']==vals['actual_completed_forward_sequences']
                    and vals['root_split']==source_groups[root], 'source/physical accounting mismatch')
        total+=vals['actual_completed_forward_sequences']
        batches+=math.ceil(vals['actual_completed_forward_sequences']/16)
    fail_if_not(total==runs['actual_full_encoder_forward_sequences'] and batches==runs['actual_batched_model_calls']
                and type(runs['encoder_token_positions']) is int and runs['encoder_token_positions']>=total,
                'actual Encoder forward or model batch accounting mismatch')
    cost=runs['cost']
    fail_if_not(set(cost)=={'elapsed_wall_seconds','elapsed_cpu_seconds','head_fit_wall_seconds',
                           'maxrss_bytes_unattested','energy_joules','target_host_p99_ms'}
                and cost['energy_joules'] is None and cost['target_host_p99_ms'] is None
                and type(cost['maxrss_bytes_unattested']) is int and cost['maxrss_bytes_unattested']>0
                and all(type(cost[k]) in (int,float) and math.isfinite(cost[k]) and cost[k]>=0
                        for k in ('elapsed_wall_seconds','elapsed_cpu_seconds','head_fit_wall_seconds')),
                'unsafe/missing full-service resource witness')
    fail_if_not(cost['head_fit_wall_seconds']<=cost['elapsed_wall_seconds'], 'nested training timer double-billed')
    results=runs['held_predictions']
    fail_if_not(type(results) is list and len(results)==96,'held evaluation count')
    need_keys=set(gold)
    observed={}
    for row in results:
        fail_if_not(type(row) is dict and set(row)=={'root','qid','question_sha','ranks'},'label-bearing or malformed result row')
        k=(row['root'],row['qid'])
        fail_if_not(k in need_keys and k not in observed,'duplicated, out-of-source, or missing held case')
        q=next(x for x in expected if x['root']==k[0])
        q=next(x for x in q['questions'] if x['id']==k[1])
        fail_if_not(row['question_sha']==q['text_sha'],'question substitution')
        fail_if_not(type(row['ranks']) is dict and set(row['ranks'])==set(ARMS),'missing original counterfactual')
        for a,ordered in row['ranks'].items():
            fail_if_not(type(ordered) is list and len(ordered)==256 and len(set(ordered))==256
                        and set(ordered)==banks[k[0]],'incomplete original document rank for arm '+a)
        observed[k]=row['ranks']
    fail_if_not(set(observed)==need_keys,'incomplete held cohort')
    return gold,banks,observed,cost,total


def count_original(raw:bytes,packet:dict,runs:dict)->dict:
    gold,banks,found,cost,seq=verify_original(raw,packet,runs)
    metrics={}
    roots=defaultdict(dict)
    for arm in ARMS:
        hits={f'any_at_{k}':0 for k in (1,3,5,10)}
        hits.update({f'all_at_{k}':0 for k in (1,3,5)})
        coverage_any=0;coverage_all=0
        for (root,qid), ranks in found.items():
            support=set(gold[(root,qid)])
            visible=support & banks[root]
            coverage_any+=int(bool(visible))
            coverage_all+=int(bool(support) and support<=banks[root])
            for k in (1,3,5,10):
                yes=bool(support and support & set(ranks[arm][:k]))
                hits[f'any_at_{k}']+=int(yes)
                if k==5:
                    roots[root][arm]=roots[root].get(arm,0)+int(yes)
            for k in (1,3,5):
                hits[f'all_at_{k}']+=int(bool(support) and support<=set(ranks[arm][:k]))
        metrics[arm]={**hits,'denominator':96,
                      'at_least_one_gold_in_fixed_corpus':coverage_any,
                      'all_gold_in_fixed_corpus':coverage_all}
    # Paired outcomes are clustered (4 roots), hence descriptive only.
    pairs={}
    for base in ('bm25','cosine','sham_rank8','zero_features'):
        wins=losses=ties=0
        for (r,q), ranked in found.items():
            s=set(gold[(r,q)])
            a=bool(s & set(ranked['rank8'][:5]));b=bool(s & set(ranked[base][:5]))
            wins+=int(a and not b)
            losses+=int(b and not a)
            ties+=int(a==b)
        pairs[f'rank8_vs_{base}']={'rescues':wins,'harms':losses,'ties':ties}
    return {'schema':'hepta.hdsi.g5.original-publisher-independent-evidence-review.v1',
            'original_source_sha256':LOCOMO_SHA,
            'prelabel_predictions_sha256':runs['digest'],
            'independent_original_source_reconstruction':True,
            'source_independent_held_conversation_roots':4,
            'historical_original_publisher_questions':96,
            'original_publisher_human_evidence_labels':True,
            'actual_pretrained_encoder_sequences_unattested':seq,
            'actual_encoder_wall_cpu_unattested':cost,
            'metrics':metrics,'paired_descriptive':pairs,
            'per_root_any_at_5':dict(roots),
            'genuine_future_calendar_windows':0,
            'natural_answer_quality_evaluated':False,
            'ndu_incremental_utility_verified':False,
            'cell_split_authorized':False,
            'production_authorized':False,
            'disposition':'HOLD_NO_GO'}


def main():
    arg=argparse.ArgumentParser()
    arg.add_argument('--original',required=True,type=Path)
    arg.add_argument('--source',required=True,type=Path)
    arg.add_argument('--run',required=True,type=Path)
    arg.add_argument('--output',required=True,type=Path)
    a=arg.parse_args()
    original=a.original.read_bytes()
    prepared=read_packet(a.source,2_000_000)
    runs=read_packet(a.run,3_000_000)
    review=count_original(original,prepared,runs)
    fail_if_not(not a.output.exists() and not a.output.is_symlink(),'cannot overwrite independent scored review')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as out:
        out.write(packed(review)+b'\n');out.flush();os.fsync(out.fileno())
    print(packed({'sha256':h(a.output.read_bytes()),'disposition':'HOLD_NO_GO',
                  'true_original_publisher_human_evidence_reviewer':True}).decode())

if __name__=='__main__':
    main()
