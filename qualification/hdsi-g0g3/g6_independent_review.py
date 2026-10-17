"""Model-free post-seal original human evidence scorer, independent of G6 producer.

Reconstruct original fixed TRAIN/HELD cohorts and full transcript from SHA-pinned
published bytes; no model/Torch/producer imports. Never infer answer quality from
retrieval hits or promote a model based on historical public test material.
"""
from __future__ import annotations

from collections import Counter,defaultdict
import hashlib
import json
import math
import os
import re
from pathlib import Path

from g5_independent_review import expected_root, without_dup

ORIGINAL = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
MODEL = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
TRAIN = ('conv-26','conv-30','conv-41','conv-42','conv-43','conv-44')
HELD = ('conv-47','conv-48','conv-49','conv-50')
ARMS = ('bm25_full','bm25_64','cosine_64','rank8_64','sham_64','rrf_64')
DOM = b'hepta.hdsi.g6.source.v1\0'
RUN_DOM = b'hepta.hdsi.g6.original-prelabel.v1\0'
WORD = re.compile(r'(?u)\b\w+\b')


def need(condition, message):
    if condition is not True:
        raise ValueError(message)


def digest(buf:bytes)->str:
    return hashlib.sha256(buf).hexdigest()


def encoded(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()


def original_full_docs(record):
    by={}
    for field,items in record['conversation'].items():
        if not field.startswith('session_') or type(items) is not list:continue
        for item in items:
            if type(item) is not dict:continue
            k,t,s=item.get('dia_id'),item.get('text'),item.get('speaker')
            if (type(k) is not str or not re.fullmatch(r'D[0-9]+:[0-9]+',k)
                or type(t) is not str or not t.strip() or len(t.encode())>8192
                or type(s) is not str or not s or len(s)>80):continue
            need(k not in by,'duplicate original dialogue entry')
            text=s+': '+t
            by[k]={'id':k,'text':text,'text_sha':digest(text.encode())}
    need(300<=len(by)<=2000,'wrong full original document population')
    return sorted(by.values(),key=lambda d:d['id'])


def independent_bm25(docs,questions):
    # Independent implementation, not importing training or G6 model scorer.
    token_docs=[WORD.findall(item['text'].casefold()) for item in docs]
    doc_tf=[Counter(ts) for ts in token_docs]
    totals=Counter()
    for bag in doc_tf:
        totals.update(bag.keys())
    avg=sum(len(t) for t in token_docs)/len(token_docs)
    result=[]
    for q in questions:
        terms=sorted(set(WORD.findall(q['text'].casefold())))
        scores=[]
        for idx, (tokens, tf) in enumerate(zip(token_docs,doc_tf)):
            scale=.25+.75*len(tokens)/avg
            score=0.
            for term in terms:
                count=tf.get(term,0)
                if count:
                    idf=math.log1p((len(docs)-totals[term]+.5)/(totals[term]+.5))
                    score+=idf*(2.2*count)/(count+1.2*scale)
            scores.append((score,docs[idx]['id']))
        result.append([id for _,id in sorted(scores,key=lambda row:(-row[0],row[1]))])
    return result


def independent_rebuild(raw):
    need(len(raw)<4_000_000 and digest(raw)==ORIGINAL,'publisher original hash mismatch')
    roots=json.loads(raw,object_pairs_hook=without_dup)
    need(type(roots) is list and len(roots)==10,'wrong original root count')
    by={row['sample_id']:row for row in roots}
    need(set(by)==set(TRAIN+HELD),'wrong original group IDs')
    expected=[]; gold={}
    for root in sorted(by):
        split='TRAIN' if root in TRAIN else 'HELD'
        v,private=expected_root(by[root],root,split)
        if split=='HELD':
            v['docs']=original_full_docs(by[root])
            gold.update({(root,qid):set(ids) for qid,ids in private.items()})
        expected.append(v)
    return expected,gold


def independently_score(original:bytes,public:dict,pred:dict)->dict:
    expected,gold=independent_rebuild(original)
    need(type(public) is dict and set(public)=={'schema','original_sha','model_sha',
          'original_g5_packet_digest','train_documents_per_root','candidate_documents',
          'questions_per_root','rerank_shortlist','roots','research_only','production_authorized',
          'disposition','digest'},'G6 public packet contains unknown fields')
    need(public['schema']=='hepta.hdsi.g6.coverage-first-source.v1'
         and public['original_sha']==ORIGINAL
         and public['model_sha']=='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
         and public['train_documents_per_root']==256
         and public['candidate_documents']=='all_held_original_dialogues'
         and public['questions_per_root']==24 and public['rerank_shortlist']==64
         and public['research_only'] is True and public['production_authorized'] is False
         and public['disposition']=='HOLD_NO_GO','unqualified public source')
    need(public['digest']==digest(DOM+encoded({k:v for k,v in public.items() if k!='digest'})),
         'tampered source seal')
    need(public['roots']==expected,'original-source and question-group reconstruction mismatch')
    # Avoid importing the G5 producer: independently reconstruct its original source digest.
    g5_roots=[]
    for item in expected:
        if item['split']=='TRAIN':g5_roots.append(item)
        else:
            orig=json.loads(original)
            source=next(r for r in orig if r['sample_id']==item['root'])
            v,_=expected_root(source,item['root'],'HELD')
            g5_roots.append(v)
    v={'schema':'hepta.hdsi.g5.locomo-original-source.v1','original_sha':ORIGINAL,
       'model_sha':'53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db',
       'doc_cap':256,'questions_per_root':24,'train_root_count':6,'held_root_count':4,
       'roots':g5_roots,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    g5_digest=digest(b'hepta.hdsi.g5.original-source\0'+encoded(v))
    need(public['original_g5_packet_digest']==g5_digest,'wrong inherited G5 source selection')
    run_fields={'schema','source_digest','model_sha','original_sha','supervised_head',
                'wrong_supervision_head','source_counters','actual_encoder_sequences',
                'actual_encoder_batches','actual_encoder_token_positions','logical_borrows',
                'original_bm25_pair_scores','held_rankings','cost','real_pretrained_forward',
                'true_future_cohort_verified','natural_answer_quality_verified',
                'ndu_incremental_net_utility_verified','production_authorized','disposition','digest'}
    need(type(pred) is dict and set(pred)==run_fields,'model did not deliver complete receipt')
    need(pred['schema']=='hepta.hdsi.g6.real-original-two-stage.v1'
         and pred['source_digest']==public['digest']
         and pred['model_sha']==public['model_sha']
         and pred['original_sha']==ORIGINAL
         and pred['real_pretrained_forward'] is True
         and pred['true_future_cohort_verified'] is False
         and pred['natural_answer_quality_verified'] is False
         and pred['ndu_incremental_net_utility_verified'] is False
         and pred['production_authorized'] is False and pred['disposition']=='HOLD_NO_GO',
         'false real model or NDU authority statement')
    need(pred['digest']==digest(RUN_DOM+encoded({k:v for k,v in pred.items() if k!='digest'})),
         'original predictions modified after postseal')
    for key in ('supervised_head','wrong_supervision_head'):
        data=pred[key]
        need(type(data) is dict and set(data)=={'initial_sha','trained_sha','steps','train_supported',
                                               'parameters','training_elapsed_wall_seconds','training_loss_final'}
             and data['steps']==100 and data['parameters']==6144
             and 1<=data['train_supported']<=144
             and all(type(data[k]) is str and re.fullmatch('[a-f0-9]{64}',data[k])
                     for k in ('initial_sha','trained_sha'))
             and data['initial_sha']!=data['trained_sha']
             and all(type(data[k]) in (int,float) and math.isfinite(data[k]) and data[k]>=0
                     for k in ('training_elapsed_wall_seconds','training_loss_final')),
             'unsupported original SGD training material')
    need(pred['supervised_head']['initial_sha']==pred['wrong_supervision_head']['initial_sha']
         and pred['supervised_head']['train_supported']==pred['wrong_supervision_head']['train_supported'],
         'Head budget/initialization mismatch')
    cost=pred['cost']
    need(type(cost) is dict and set(cost)=={'process_cpu_seconds_unattested',
          'process_wall_seconds_unattested','process_peakrss_bytes_unattested','energy_joules','host_p99_ms'}
         and cost['energy_joules'] is None and cost['host_p99_ms'] is None
         and type(cost['process_peakrss_bytes_unattested']) is int and cost['process_peakrss_bytes_unattested']>0
         and all(type(cost[k]) in (int,float) and math.isfinite(cost[k]) and cost[k]>0
                 for k in ('process_cpu_seconds_unattested','process_wall_seconds_unattested')),
         'unqualified cost or missing physical evidence')
    # Independent source-first full BM25 ranking is reconstructed before human
    # evidence is used to compute accuracy or paired results.
    by_root={r['root']:r for r in expected}
    bm25_ref={name:independent_bm25(r['docs'],r['questions']) for name,r in by_root.items() if name in HELD}
    required={(root,q['id']) for root,r in by_root.items() if root in HELD for q in r['questions']}
    need(type(pred['held_rankings']) is list and len(pred['held_rankings'])==len(required)==96,
         'incomplete original public question panel')
    observed={}
    metrics={k:{'hit_at_1':0,'hit_at_3':0,'hit_at_5':0,'hit_at_10':0,
                'all_at_5':0} for k in ARMS}
    recall={'gold_any_in_full':0,'gold_any_in_bm25_32':0,'gold_any_in_bm25_64':0}
    for row in pred['held_rankings']:
        need(type(row) is dict and set(row)=={'root','qid','question_sha','rankings','shortlist_size'}
             and row['shortlist_size']==64,'wrong ranking row')
        k=row['root'],row['qid']
        need(k in required and k not in observed,'duplicate, unknown or cross-source question')
        r=by_root[k[0]]
        qi=next(i for i,q in enumerate(r['questions']) if q['id']==k[1])
        need(row['question_sha']==r['questions'][qi]['text_sha'],'question substitution')
        true_order=bm25_ref[k[0]][qi]
        need(type(row['rankings']) is dict and set(row['rankings'])==set(ARMS),'missing arm')
        for arm,ranks in row['rankings'].items():
            need(type(ranks) is list and len(ranks)==len(true_order) and len(set(ranks))==len(true_order)
                 and set(ranks)==set(true_order),'missing or counterfeit source ranks')
            if arm.startswith('bm25'):
                need(ranks==true_order,'manipulated original cheap baseline')
            else:
                need(set(ranks[:64])==set(true_order[:64]) and ranks[64:]==true_order[64:],
                     'wrong independent 64-candidate computation budget')
            gt=gold[k]
            for m in (1,3,5,10):
                metrics[arm][f'hit_at_{m}']+=int(bool(gt & set(ranks[:m])))
            metrics[arm]['all_at_5']+=int(bool(gt) and gt.issubset(set(ranks[:5])))
        recall['gold_any_in_full']+=int(bool(gold[k] & set(true_order)))
        recall['gold_any_in_bm25_32']+=int(bool(gold[k] & set(true_order[:32])))
        recall['gold_any_in_bm25_64']+=int(bool(gold[k] & set(true_order[:64])))
        observed[k]=row['rankings']
    need(set(observed)==required,'missing heldout question')
    need(pred['original_bm25_pair_scores']==sum(len(by_root[root]['docs'])*24 for root in HELD),
         'cheap full scan underreported')
    counts=pred['source_counters']
    need(type(counts) is dict and set(counts)==set(TRAIN+HELD),'missing scoped Encoder root')
    need(pred['actual_encoder_sequences']==sum(v['model_sequences'] for v in counts.values())
         and pred['actual_encoder_batches']==sum(v['model_batches'] for v in counts.values())
         and pred['logical_borrows']==sum(v['logical_borrows'] for v in counts.values())
         and pred['actual_encoder_token_positions']>=pred['actual_encoder_sequences'],
         'false counted physical computation')
    for name,v in counts.items():
        need(type(v) is dict and set(v)=={'model_sequences','model_batches','logical_borrows',
                'identity_count','source_scope'}, 'incorrect root resource scope')
        need(type(v['model_sequences']) is int and 1<=v['model_sequences']<=v['logical_borrows']
             and v['identity_count']==v['model_sequences']
             and v['model_batches']==math.ceil(v['model_sequences']/16)
             and v['source_scope']=='g6-'+name,
             'model sequence/batch or source re-use mismatch')
        if name in TRAIN:
            need(v['logical_borrows']==280,'TRAIN model panel modified')
        else:
            need(88<=v['logical_borrows']<=len(by_root[name]['docs'])+24,
                 'HELD feature reuse cost not physically counted')
    pairs={}
    for arm in ('cosine_64','rank8_64','sham_64','rrf_64'):
        win=loss=tie=0
        for k,item in observed.items():
            labels=gold[k]
            a=bool(labels & set(item[arm][:5]))
            b=bool(labels & set(item['bm25_full'][:5]))
            win+=int(a and not b);loss+=int(b and not a);tie+=int(a==b)
        pairs[arm+'_vs_bm25']={'rescues':win,'harms':loss,'ties':tie}
    return {'schema':'hepta.hdsi.g6.independent-original-human-review.v1',
            'original_publisher_sha_verified':True,'model_free_independent_reconstruction':True,
            'denominator':96,'held_original_roots':4,'gold_coverage':recall,
            'arms':metrics,'paired':pairs,
            'resource':{'actual_original_encoder_sequences':pred['actual_encoder_sequences'],
                        'actual_original_encoder_batches':pred['actual_encoder_batches'],
                        'logical_borrows':pred['logical_borrows'],
                        'original_bm25_pair_scores':pred['original_bm25_pair_scores'],
                        'model_worker_wall_seconds_unattested':cost['process_wall_seconds_unattested'],
                        'model_worker_cpu_seconds_unattested':cost['process_cpu_seconds_unattested'],
                        'target_energy_joules':None,'target_host_p99_ms':None},
            'natural_answer_quality_verified':False,'new_source_families_verified':False,
            'ndu_task_lift_verified':False,'cell_split_authorized':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--predictions',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    root=a.original.read_bytes();src=json.loads(a.source.read_bytes(),object_pairs_hook=without_dup)
    rec=json.loads(a.predictions.read_bytes(),object_pairs_hook=without_dup)
    result=independently_score(root,src,rec)
    if a.output.exists() or a.output.is_symlink():raise ValueError('independent reviewer is create-only')
    raw=encoded(result)+b'\n'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(a.output,os.O_EXCL|os.O_CREAT|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    print(json.dumps({'denominator':result['denominator'],'disposition':'HOLD_NO_GO',
                      'original_score_sha256':digest(raw)},sort_keys=True))

if __name__=='__main__':
    main()
