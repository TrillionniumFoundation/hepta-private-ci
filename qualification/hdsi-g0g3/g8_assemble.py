"""Model-free six-source assembly, no HELD outcome or Torch access."""
from __future__ import annotations
import json
import math
from pathlib import Path

from g6_coverage_model import bm25_all
from g6_coverage_source import TRAIN, HELD, write_new
from g7_policy import feature_band
from g8_policy import digest,freeze,plan,need
from g8_root import SCHEMA as ROOT_SCHEMA
from g8_source import validate
from real_minilm_reference import CHECKSUMS

SCHEMA='hepta.hdsi.g8.train-assembly-prelabel.v1'


def assemble(public, receipts):
    validate(public)
    need(type(receipts) is list and len(receipts)==6 and {r.get('root') for r in receipts}==set(TRAIN),
         'six real independently sealed root traces required')
    observations=[];census={};seq=batches=tokens=paid_lex=0
    roots={r['root']:r for r in public['roots']}
    for t in receipts:
        name=t['root'];source=roots[name];docs=source['docs'];qs=source['questions']
        need(type(t) is dict and set(t)=={'schema','source_digest','root','original_model_sha',
             'frozen_pretrained_encoder','source_census','train_observations',
             'encoder_sequences','encoder_batches','encoder_tokens','run_profile','cost',
             'held_gold_accessed','future_quality_verified','production_authorized',
             'disposition','digest'},'root receipt changed')
        need(t['schema']==ROOT_SCHEMA and t['source_digest']==public['digest']
             and t['original_model_sha']==CHECKSUMS['encoder/model.safetensors']
             and t['frozen_pretrained_encoder'] is True and t['held_gold_accessed'] is False
             and t['future_quality_verified'] is False and t['production_authorized'] is False
             and t['disposition']=='HOLD_NO_GO'
             and t['run_profile']=='fp32_cpu_wordpiece128_length_buckets_batch16'
             and t['digest']==digest({k:v for k,v in t.items() if k!='digest'}),
             'unbound actual pretrained root')
        ranks,lex=bm25_all(docs,qs)
        unique={j for ranking in ranks for j in ranking[:64]}
        co=t['source_census']
        need(type(co) is dict and set(co)=={'full_docs','full_questions',
              'encoded_unique_documents','bm25_pair_scores','support'}
             and co['full_docs']==len(docs) and co['full_questions']==24
             and co['encoded_unique_documents']==len(unique)
             and co['bm25_pair_scores']==lex
             and t['encoder_sequences']==24+len(unique)
             and t['encoder_batches']==math.ceil(t['encoder_sequences']/16)
             and t['encoder_tokens']>=t['encoder_sequences'],
             'false actual model resource manifest')
        need(type(t['train_observations']) is list and len(t['train_observations'])==24,
             'partial training root')
        expected={(name,q['id']):q for q in qs};seen=set()
        hits={'all':0,'top5':0,'top64':0,'rrf5':0}
        for ob in t['train_observations']:
            key=(ob['root'],ob['qid'])
            need(key in expected and key not in seen,'wrong TRAIN observation source')
            seen.add(key)
            qi=next(i for i,q in enumerate(qs) if q['id']==ob['qid'])
            q=expected[key];ranking=ranks[qi];bank={d['id'] for d in docs}
            truth=set(q['train_support'])
            need(ob['source_sha']==q['text_sha']
                 and ob['band']==feature_band(q['text'],docs[ranking[0]]['text'])
                 and ob['bm25_top10']==[docs[j]['id'] for j in ranking[:10]]
                 and set(ob['rrf_top10']).issubset({docs[j]['id'] for j in ranking[:64]}),
                 'label/subset/lexical substitution')
            hits['all']+=int(bool(truth&bank))
            hits['top5']+=int(bool(truth&set(ob['bm25_top10'][:5])))
            hits['top64']+=int(bool(truth&{docs[j]['id'] for j in ranking[:64]}))
            hits['rrf5']+=int(bool(truth&set(ob['rrf_top10'][:5])))
        need(seen==set(expected) and hits==co['support'] and hits['all']==24,
             'training context/label coverage not proven')
        observations+=t['train_observations']
        census[name]=co
        seq+=t['encoder_sequences'];batches+=t['encoder_batches'];tokens+=t['encoder_tokens']
        paid_lex+=lex
    profile=freeze(public,observations)
    held=[];held_lex=0
    for name in HELD:
        r=roots[name];ranked,work=bm25_all(r['docs'],r['questions']);held_lex+=work
        for q,indices in zip(r['questions'],ranked):
            held.append({'root':name,'qid':q['id'],'source_sha':q['text_sha'],
                         'band':feature_band(q['text'],r['docs'][indices[0]]['text']),
                         'bm25_top10':[r['docs'][j]['id'] for j in indices[:10]]})
    held.sort(key=lambda x:(x['root'],x['qid']))
    decision=plan(public,profile,held)
    summary={'schema':SCHEMA,'source_digest':public['digest'],
             'material_sha':CHECKSUMS['encoder/model.safetensors'],
             'source_root_digests':{r['root']:r['digest'] for r in receipts},
             'train_observations':observations, 'full_train_census':census,
             'profile':profile,'sealed_held_plan':decision,
             'actual_train_encoder_sequences':seq,'actual_train_encoder_batches':batches,
             'actual_train_encoder_tokens':tokens,'train_bm25_pairs':paid_lex,
             'held_bm25_pairs':held_lex,'source_and_budget_independently_recounted':True,
             'original_held_gold_accessed':False,'unavailable_future_validation':True,
             'host_attested':False,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    summary['digest']=digest(summary)
    return summary


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True,action='append')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=assemble(json.loads(args.source.read_bytes()),[json.loads(p.read_bytes()) for p in args.receipt])
    write_new(args.output,result)
    print(json.dumps({'source':result['source_digest'],'train_sequences':result['actual_train_encoder_sequences'],
         'train_batches':result['actual_train_encoder_batches'],
         'held_actions':{a:sum(v['ndu']==a for v in result['sealed_held_plan']['choices'])
                         for a in ('STOP','BM25','RERANK')},'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
