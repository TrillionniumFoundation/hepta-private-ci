"""Independent postseal P0.8 reviewer, historical publisher labels only after seal.

Structural and label-score audit is independent of producer's SGD; without an
independently executed second physical Encoder this is not model-forward parity.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from p08_cohort import (SCHEMA,HUFF_SHA,MODEL_REV,MODEL_SAFETENSORS_SHA,
     Denied,strict,sha,dump,require,read_regular,put_private,make_panel,verify_panel)
from p08_run import (SEEDS,ARMS,TRAINED,STEPS,LR,WEIGHT_DECAY,PARAMS_PER_SLOT,FEATURE_WIDTH)


def exact_two_sided(wins: int,losses:int) -> float:
    n=wins+losses
    if n==0:return 1.0
    k=min(wins,losses)
    return min(1.0,2.0*math.fsum(math.comb(n,j) for j in range(k+1))/2**n)


def review(*, agnews:Path,huff:Path,panel_file:Path,prelabel_file:Path,sealed_sha:str)->dict:
    require(type(sealed_sha) is str and len(sealed_sha)==64 and
            all(c in '0123456789abcdef' for c in sealed_sha),'invalid immutable prelabel claim')
    original=read_regular(prelabel_file,350_000)
    require(sha(original)==sealed_sha,'unsealed, tampered or substituted prelabel output')
    source=strict(read_regular(panel_file,180_000));verify_panel(source)
    # The reviewer opens *unavailable-to-producer* historical publisher source here.
    # The original curated view & original gold commitment must both match exactly.
    recreated,gold_digest=make_panel(agnews,read_regular(huff,105_000_000))
    require(dump(recreated)==dump(source) and gold_digest==source['gold_commitment'],
            'source or committed independent publisher gold has drifted')
    payload=strict(original)
    expected={'schema','source_sha256','head_schedule','baseline_work','routing_sha256',
              'train_only_cluster_iterations','seeds','predictions','flags','physical'}
    require(type(payload) is dict and set(payload)==expected,'missing independent producer evidence')
    require(payload['schema']==SCHEMA+'.prelabel.v1' and
            payload['source_sha256']==sha(dump(source)),'changed source or predictor')
    require(payload['head_schedule']=={'seeds':list(SEEDS),'sgd_updates':STEPS,
            'lr':LR,'weight_decay':WEIGHT_DECAY,
            'per_active_head_scalars':PARAMS_PER_SLOT,'class_count':4,'feature_width':FEATURE_WIDTH},
            'Head training plan changed')
    require(type(payload['baseline_work']) is dict and
            payload['baseline_work'].get('train_only_loo_fits')==512 and
            payload['baseline_work'].get('zero_sgd_but_nonzero_math_work') is True and
            payload['baseline_work'].get('centroid_temperature') in (0.125,0.25,0.5,1.,2.,4.,8.,16.),
            'unpaid calibration work')
    flags=payload['flags']
    require(flags=={'authentic_publisher_gold_in_predictor':False,'future_window_verified':False,
            'independent_human_gold_issuer':False,'live_model_promotion':False,
            'native_effect_authorized':False,'production_authorized':False,'authority':'DENY_ALL'},
            'unsafe model/authority claim')
    phys=payload['physical']
    require(type(phys) is dict and phys.get('model_repo')=='jhu-clsp/mmBERT-small' and
            phys.get('revision')==MODEL_REV and phys.get('weight_sha256')==MODEL_SAFETENSORS_SHA and
            phys.get('actual_cpu_model_forward_invocations')==32 and
            phys.get('original_pretrained_feature_rows')==128 and
            type(phys.get('actual_forward_input_tokens')) is int and
            phys['actual_forward_input_tokens']>=128 and
            phys.get('original_historical_checkpoint_reused') is False and
            phys.get('gpu_backend_used') is False and
            phys.get('original_weight_signature_issuer_attested') is False,
            'no authenticated source-pinned real pretrained run receipt')
    require(type(payload['routing_sha256']) is str and len(payload['routing_sha256'])==64 and
            payload['train_only_cluster_iterations']==8,'unverified clustering lineage')
    seed_reports=payload['seeds'];require(type(seed_reports) is list and len(seed_reports)==3,'seed material drift')
    for row,seed in zip(seed_reports,SEEDS,strict=True):
        require(type(row) is dict and row.get('seed')==seed and
                type(row.get('arms')) is dict and set(row['arms'])==set(TRAINED),'invalid training tuple')
        for arm,t in row['arms'].items():
            correct_size=PARAMS_PER_SLOT*(1 if arm=='shared' else 2)
            require(type(t) is dict and t.get('actual_sgd_updates')==STEPS and
                    t.get('actual_parameter_touches')==STEPS*PARAMS_PER_SLOT and
                    t.get('allocated_head_scalars')==correct_size and
                    t.get('allocated_head_bytes')==correct_size*8 and
                    t.get('per_query_head_forwards')==1 and
                    type(t.get('weight_sha256')) is str and len(t['weight_sha256'])==64,
                    'equal-touch/head residency mismatch')
    from agnews_crossfamily import read_original
    agrows=[strict(line) for line in read_original(agnews)['dataset.jsonl'].splitlines()]
    old_gold={ 'ag:'+sha(row['case_id'].encode())[:40]:row['label'] for row in agrows if row['split']=='holdout'}
    # Independently reconstruct labels from ORIGINAL immutable publisher source,
    # without accepting a label claim in the producer or prelabel artifact.
    from p08_cohort import choose_huff
    new_gold={r['id']:r['target'] for r in choose_huff(read_regular(huff,105_000_000))}
    expected_groups={'retention':old_gold,'transfer':new_gold}
    require(all(len(g)==32 for g in expected_groups.values()),'independent original-gold count mismatch')
    rows=payload['predictions']
    require(type(rows) is list and len(rows)==len(SEEDS)*64,'prelabel output count mismatch')
    accum={p:{s:{a:[] for a in ARMS} for s in SEEDS} for p in ('retention','transfer')}
    seen=set()
    for v in rows:
        require(type(v) is dict and set(v)=={'id','source','seed','p'},'unexpected producer case fields')
        group=v['source'];seed=v['seed'];ident=v['id']
        require(group in expected_groups and seed in SEEDS and ident in expected_groups[group] and
                (group,seed,ident) not in seen,'wrong publisher/seed identity')
        seen.add((group,seed,ident))
        probs=v['p'];require(type(probs) is dict and set(probs)==set(ARMS),'missing true no-op/cheap controls')
        label=expected_groups[group][ident]
        for name,vector in probs.items():
            require(type(vector) is list and len(vector)==4 and
                    all(type(t) in (int,float) and math.isfinite(t) and 0<=t<=1 for t in vector) and
                    abs(math.fsum(vector)-1)<=1e-11,'invalid row probability vector')
            pred=max(range(4),key=lambda i:vector[i]);brier=math.fsum((vector[i]-int(i==label))**2 for i in range(4))
            accum[group][seed][name].append((ident,int(pred==label),brier, -math.log(max(1e-300,vector[label]))))
    require(len(seen)==192,'prediction universe incomplete')
    scores={}
    for part in ('retention','transfer'):
        scores[part]={}
        for seed in SEEDS:
            block=accum[part][seed]
            for arm in ARMS:require(len(block[arm])==32,'incomplete per-arm values')
            answer={}
            for arm in ARMS:
                arr=block[arm];answer[arm]={'correct':sum(r[1] for r in arr),'count':32,
                    'brier':math.fsum(r[2] for r in arr)/32,'nll':math.fsum(r[3] for r in arr)/32}
            base={q[0]:q[1] for q in block['centroid_loo']}
            for arm in ('split','shared'):
                w={q[0]:q[1] for q in block[arm]}
                plus=sum(w[i] and not base[i] for i in w)
                minus=sum(base[i] and not w[i] for i in w)
                answer[arm+'_vs_train_loo_centroid']={'wins':plus,'losses':minus,
                  'nominal_exact_p':exact_two_sided(plus,minus)}
            scores[part][str(seed)]=answer
    return {'schema':SCHEMA+'.review.v1','producer_prelabel_sha256':sealed_sha,
       'source_panel_sha256':sha(dump(source)),'publisher_file_sha256':HUFF_SHA,
       'model_publisher_revision':MODEL_REV,'weight_sha256':MODEL_SAFETENSORS_SHA,
       'pretrained_cpu_model_calls_producer_claim':phys['actual_cpu_model_forward_invocations'],
       'original_agnews_old_holdout_count':32,'new_huffpost_historical_source_count':32,
       'head_training_budget_matched_per_arm':STEPS,
       'real_new_pretrained_forward_reported':True,
       'independently_attested_model_forward':False,
       'independent_publisher_gold_issuer':False,
       'source_root_independent_issuer_verified':False,
       'prospective_future_window_verified':False,
       'cross_publisher_label_ontology_exact':False,
       'source_training_text_duplicates_screened':True,
       'scores':scores,
       'disposition':'HOLD_NO_GO','model_promotion_authorized':False,
       'physical_cell_split_authorized':False,'native_effect_authorized':False,
       'production_authorized':False}

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--agnews',type=Path,required=True);ap.add_argument('--huff',type=Path,required=True)
    ap.add_argument('--panel',type=Path,required=True);ap.add_argument('--prelabel',type=Path,required=True)
    ap.add_argument('--prelabel-sha',required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();result=review(agnews=a.agnews,huff=a.huff,panel_file=a.panel,
                                   prelabel_file=a.prelabel,sealed_sha=a.prelabel_sha)
    put_private(a.out,dump(result))
    print(json.dumps({'report_sha256':sha(dump(result)),'new_source_count':32,
        'score_computed':True,'disposition':'HOLD_NO_GO','authority':'DENY_ALL'}))
if __name__=='__main__':main()
