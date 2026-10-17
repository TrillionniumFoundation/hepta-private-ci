"""Physically paid selected RRF after independently sealed label-blind plan.

Each paid arm allocates fresh feature forwards, including overlapping inputs;
mathematically identical Bellman and deterministic NDU share one output only
for parity verification, not as a separately paid execution claim.
"""
from __future__ import annotations

import json
import time
import resource
from pathlib import Path

from g6_coverage_source import HELD,validate,write_new
from g6_coverage_model import bm25_all
from g5_batched_encoder import BatchedMiniLM, verified_encoder_only
from g7_policy import feature_band,verify_plan,verify_profile,hash_object,need
from g7_train import rrf_ranking, SCHEMA as TRAIN_SCHEMA
from real_minilm_reference import CHECKSUMS

SCHEMA='hepta.hdsi.g7.on-policy-paid-rerank.v1'


def run_selected(root:Path,public:dict,train_record:dict)->dict:
    validate(public)
    need(type(train_record) is dict and train_record.get('schema')==TRAIN_SCHEMA
         and train_record.get('source_digest')==public['digest']
         and train_record.get('material_sha')==CHECKSUMS['encoder/model.safetensors']
         and train_record.get('real_pretrained_train_model') is True
         and train_record.get('held_gold_accessed') is False
         and train_record.get('production_authorized') is False
         and train_record.get('disposition')=='HOLD_NO_GO'
         and train_record.get('digest')==hash_object({k:v for k,v in train_record.items() if k!='digest'}),
         'invalid exact previously sealed TRAIN-only physical record')
    profile=train_record['profile'];proposal=train_record['sealed_plan']
    verify_profile(profile,public)
    verify_plan(public,profile,proposal)
    need(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'HELD human labels may not be visible to model worker')
    verified_encoder_only(root)
    import torch
    torch.set_num_threads(1)
    clock=time.perf_counter();cpu0=time.process_time()
    enc=BatchedMiniLM(root,batch_size=16)
    by_choice={(r['root'],r['qid']):r for r in proposal['decisions']}
    output=[];cost={};total_lex=0
    for group in public['roots']:
        if group['split']!='HELD':continue
        docs=group['docs'];qs=group['questions'];name=group['root']
        ranks,lex=bm25_all(docs,qs);total_lex+=lex
        policy_results={}
        # Selected and fixed control must pay distinct forwards even for shared inputs.
        for policy in ('ndu','fixed'):
            selected=[]
            for j,q in enumerate(qs):
                row=by_choice[name,q['id']]
                need(row['bm25_top5_ids']==[docs[k]['id'] for k in ranks[j][:5]]
                     and row['band']==feature_band(q['text'],docs[ranks[j][0]]['text']),
                     'source/route changed after prior plan seal')
                if row[policy]=='RERANK':selected.append(j)
            need(len(selected)<=proposal['cap_per_root'],'over-budget physical calls')
            chosen_union=sorted({k for j in selected for k in ranks[j][:64]})
            before=enc.calls;batch_before=enc.actual_batches;token_before=enc.tokens
            result={}
            if selected:
                tensors=enc.encode_batch([(qs[j]['text'].encode(),'text') for j in selected]
                                         +[(docs[k]['text'].encode(),'text') for k in chosen_union])
                t=torch.tensor(tensors,dtype=torch.float32)
                query_vectors=t[:len(selected)]
                doc_vectors=t[len(selected):]
                doc_idx={k:i for i,k in enumerate(chosen_union)}
                with torch.inference_mode():scores=(query_vectors@doc_vectors.T).tolist()
                for ji,j in enumerate(selected):
                    shortlist=ranks[j][:64]
                    semantic=[scores[ji][doc_idx[k]] for k in shortlist]
                    reordered=rrf_ranking(ranks[j],semantic)
                    need(set(reordered[:64])==set(shortlist) and reordered[64:]==ranks[j][64:],
                         'paid model accessed unsupported evidence')
                    result[j]=[docs[k]['id'] for k in reordered[:10]]
            # Distinct physically charged cohorts; no free counterfactual arm.
            seq=enc.calls-before
            need(seq==len(selected)+len(chosen_union),'paid actual source/model call count')
            cost[name+':'+policy]={
                'paid_questions':len(selected),'encoder_sequences':seq,
                'encoder_batches':enc.actual_batches-batch_before,
                'original_tokens':enc.tokens-token_before,
                'distinct_documents_encoded':len(chosen_union)}
            policy_results[policy]=result
        for j,q in enumerate(qs):
            selection=by_choice[name,q['id']]
            b=[docs[k]['id'] for k in ranks[j][:10]]
            out={'root':name,'qid':q['id'],'source_sha':q['text_sha'],'bm25_top10':b,
                 'ndu':{'action':selection['ndu'],
                        'top10':policy_results['ndu'].get(j,[]) if selection['ndu']=='RERANK'
                                 else ([] if selection['ndu']=='STOP' else b)},
                 'bellman':{'action':selection['bellman'],
                        'top10':policy_results['ndu'].get(j,[]) if selection['bellman']=='RERANK'
                                 else ([] if selection['bellman']=='STOP' else b)},
                 'fixed':{'action':selection['fixed'],
                         'top10':policy_results['fixed'].get(j,[]) if selection['fixed']=='RERANK'
                                 else b}}
            need(out['ndu']==out['bellman'],'same-profile Bellman/NDU path changed')
            output.append(out)
    need(len(output)==96,'incomplete external exact original root panel')
    need(enc.calls==sum(v['encoder_sequences'] for v in cost.values()),
         'actual original prepaid model work not conserved')
    result={'schema':SCHEMA,'source_digest':public['digest'],
            'train_record_digest':train_record['digest'],'profile_digest':profile['digest'],
            'sealed_plan_digest':proposal['digest'],
            'material_sha':CHECKSUMS['encoder/model.safetensors'],
            'decisions':output,'by_root_and_policy_cost':cost,
            'shared_lexical_comparisons':total_lex,
            'real_selected_original_pretrained_forward':True,
            'actual_forward_sequences':enc.calls,'actual_model_batches':enc.actual_batches,
            'actual_tokens':enc.tokens,
            'cost':{'cpu_seconds_unattested':time.process_time()-cpu0,
                    'wall_seconds_unattested':time.perf_counter()-clock,
                    'resident_peak_bytes_unattested':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                    'energy_joules':None,'target_host_p99_ms':None},
            'mathematical_Bellman_NDU_parity':True,
            'true_future_cohort_verified':False,'natural_answer_quality_verified':False,
            'ndu_incremental_net_gain_verified':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO'}
    result['digest']=hash_object(result)
    return result


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--model-only',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=run_selected(a.model_only,json.loads(a.source.read_bytes()),json.loads(a.training.read_bytes()))
    write_new(a.output,result)
    print(json.dumps({'paid_model_sequences':result['actual_forward_sequences'],
                      'prelabel_plan':result['sealed_plan_digest'],
                      'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
