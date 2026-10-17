"""Pay for exactly the G8 admission-supported actions and a fixed eight control.

Unselected neural branches are NEVER calculated and never counted as savings
relative to a precomputed full action slate. BM25 is charged once as a shared
first-stage prerequisite. Current 6-root gate usually admits no NDU rerank.
"""
from __future__ import annotations
import json
from pathlib import Path
import resource
import time

from g5_batched_encoder import BatchedMiniLM, verified_encoder_only
from g6_coverage_model import bm25_all
from g6_coverage_source import HELD, write_new
from g7_train import rrf_ranking
from g8_source import validate
from g8_policy import digest,need,validate_profile,verify_plan
from g8_assemble import SCHEMA as ASSEMBLY_SCHEMA
from real_minilm_reference import CHECKSUMS, wordpiece

SCHEMA='hepta.hdsi.g8.paid-original-episode-v1'


def execute(root:Path,public:dict,assembled:dict):
    validate(public)
    need(type(assembled) is dict and assembled.get('schema')==ASSEMBLY_SCHEMA
         and assembled.get('source_digest')==public['digest']
         and assembled.get('material_sha')==CHECKSUMS['encoder/model.safetensors']
         and assembled.get('source_and_budget_independently_recounted') is True
         and assembled.get('original_held_gold_accessed') is False
         and assembled.get('production_authorized') is False
         and assembled.get('digest')==digest({k:v for k,v in assembled.items() if k!='digest'}),
         'invalid sealed predecessor training')
    profile=assembled['profile'];decision=assembled['sealed_held_plan']
    validate_profile(profile,public);verify_plan(public,profile,decision)
    need(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'raw original held gold is visible to model worker')
    verified_encoder_only(root)
    import torch
    torch.set_num_threads(1)
    clock=time.perf_counter();cpu=time.process_time()
    model=BatchedMiniLM(root,batch_size=16)
    lookup={(x['root'],x['qid']):x for x in decision['choices']}
    outcomes=[];cost={};checks=0
    for group in public['roots']:
        if group['root'] not in HELD:continue
        name=group['root'];docs=group['docs'];qs=group['questions']
        ranked,work=bm25_all(docs,qs);checks+=work
        top_ids=[[docs[j]['id'] for j in indices[:10]] for indices in ranked]
        by_policy={}
        for arm in ('ndu','fixed'):
            selected=[]
            for qi,q in enumerate(qs):
                planned=lookup[(name,q['id'])]
                need(planned['bm25_top10']==top_ids[qi],
                     'source changed after original labelled training was sealed')
                if planned[arm]=='RERANK':selected.append(qi)
            need(len(selected)<=8,'runtime exceeded original fixed per-root compute envelope')
            indices=sorted({j for qi in selected for j in ranked[qi][:64]})
            start=model.calls;batches=model.actual_batches;tokens=model.tokens
            reranked={}
            if selected:
                payloads=[qs[j]['text'].encode() for j in selected]+[docs[j]['text'].encode() for j in indices]
                lengths=[len(wordpiece(buf.decode('utf-8'),model.vocab)) for buf in payloads]
                permutation=sorted(range(len(payloads)),key=lambda i:(lengths[i],i))
                vectors=model.encode_batch([(payloads[j],'text') for j in permutation])
                inversion=[None]*len(payloads)
                for j,v in zip(permutation,vectors): inversion[j]=v
                t=torch.tensor(inversion,dtype=torch.float32)
                with torch.inference_mode():matrix=(t[:len(selected)]@t[len(selected):].T).tolist()
                pos={idx:j for j,idx in enumerate(indices)}
                for ij,qi in enumerate(selected):
                    first=ranked[qi][:64]
                    s=[matrix[ij][pos[k]] for k in first]
                    order=rrf_ranking(ranked[qi],s)
                    need(set(order[:64])==set(first) and order[64:]==ranked[qi][64:],
                         'unsupported rerank candidate insertion')
                    reranked[qi]=[docs[j]['id'] for j in order[:10]]
            spent=model.calls-start
            need(spent==len(selected)+len(indices), 'missing physical MiniLM computation')
            cost[name+':'+arm]={'paid_rerank_questions':len(selected),
                    'physically_encoded_queries_and_docs':spent,
                    'pretrained_forward_batches':model.actual_batches-batches,
                    'real_original_input_token_positions':model.tokens-tokens,
                    'unique_rerank_documents':len(indices)}
            by_policy[arm]=reranked
        for qi,q in enumerate(qs):
            case=lookup[(name,q['id'])]
            result={'root':name,'qid':q['id'],'source_sha':q['text_sha'],
                    'bm25_top10':top_ids[qi]}
            for arm in ('ndu','bellman','fixed'):
                action=case[arm]
                shared='ndu' if arm=='bellman' else arm
                result[arm]={'action':action,
                    'top10':([] if action=='STOP' else by_policy[shared][qi]
                             if action=='RERANK' else top_ids[qi])}
            need(result['ndu']==result['bellman'],'ordinary Bellman is not a different model output')
            outcomes.append(result)
    need(len(outcomes)==96 and model.calls==sum(v['physically_encoded_queries_and_docs'] for v in cost.values()),
         'incomplete on-policy original resource conservation')
    output={'schema':SCHEMA,'source_digest':public['digest'],
            'assembled_digest':assembled['digest'],'plan_digest':decision['digest'],
            'profile_digest':profile['digest'],
            'original_model_sha':CHECKSUMS['encoder/model.safetensors'],
            'decisions':outcomes,'model_cost_by_source_and_policy':cost,
            'actual_pretrained_sequence_forwards':model.calls,
            'actual_pretrained_batches':model.actual_batches,
            'actual_pretrained_token_positions':model.tokens,
            'shared_bm25_pair_scores':checks,
            'model_worker_cost':{'cpu_seconds_self_reported':time.process_time()-cpu,
                'wall_seconds_self_reported':time.perf_counter()-clock,
                'peak_rss_bytes_self_reported':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                'hardware_attested':False,'energy_joules':None},
            'held_human_gold_accessed':False,'independent_future_efficacy_verified':False,
            'mathematical_NDU_Bellman_parity':True,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}
    output['digest']=digest(output)
    return output


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--model-only',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    out=execute(a.model_only,json.loads(a.source.read_bytes()),json.loads(a.training.read_bytes()))
    write_new(a.output,out)
    print(json.dumps({'paid_questions':sum(v['paid_rerank_questions'] for v in out['model_cost_by_source_and_policy'].values()),
         'real_model_sequences':out['actual_pretrained_sequence_forwards'],
         'real_model_batches':out['actual_pretrained_batches'],'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
