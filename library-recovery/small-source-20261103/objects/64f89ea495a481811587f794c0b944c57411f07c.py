"""Independent NumPy-only old-Cell stage separation and paired-retention audit.

No import of Torch or original producer; checks exact original mmBERT source,
24-only capsule→stage1 states→stage2 inferred logits→held TRAIN outcomes.
Full gradient replay, future windows, independent source-owner attestation and
production admission are explicitly NOT established.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from safetensors.numpy import load as load_numpy

SCHEMA='hepta.stem.v34.old-only-process-separated.v1'
SOURCE='69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096'
FEATURE='2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3'
ARCHIVE='0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
PRETRAINED='e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
V32_SCHEMA='hepta.stem.v32.original-cell-prequential-trainonly.v1'
SEEDS=(41,47,53)
ARMS=('nochange','continued','rehearsal','split','source_blind_ensemble')
WIDTH=384


def need(cond,why):
    if not cond:raise ValueError(why)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def decoded(raw):
    def unique(pairs):
        out={}
        for k,v in pairs:
            need(k not in out,'duplicate source or receipt JSON key');out[k]=v
        return out
    def invalid(_):raise ValueError('nonfinite JSON')
    val=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    canonical(val)
    return val


def take(p,expected=None):
    p=Path(p)
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < 8_000_000,
         'missing or unsafe bounded original material')
    data=p.read_bytes()
    if expected is not None: need(sha(data)==expected,'original byte SHA256 has drifted')
    return data


def folds(rows):
    need(len(rows)==64,'original cohort missing')
    cell=[]
    for c in (0,1):
        seq=sorted((sha(r['case_id'].encode()),i) for i,r in enumerate(rows) if r['cell']==c)
        need(len(seq)==32,'not 32 old/new rows')
        cell.append([[i for _,i in seq[f::4]] for f in range(4)])
    return [cell[0][f]+cell[1][f] for f in range(4)]


def inspect_weights(obj,x):
    need(type(obj) is dict and set(obj)=={'w','b'},'unexpected source Head inventory')
    w,b=np.asarray(obj['w'],dtype='<f4'),np.asarray(obj['b'],dtype='<f4')
    need(w.shape==(4,WIDTH) and b.shape==(4,)
         and np.isfinite(w).all() and np.isfinite(b).all(), 'corrupt original Head parameters')
    return x.astype('<f8')@w.astype('<f8').T+b.astype('<f8'),sha(w.tobytes()+b.tobytes())


def metric(logits,y):
    z=logits.astype('<f8');z=z-z.max(axis=1,keepdims=True)
    p=np.exp(z);p/=p.sum(1,keepdims=True)
    return {'correct':int((p.argmax(1)==y).sum()),
            'brier':float(np.square(p-np.eye(4)[y]).sum(1).mean()),
            'right':p.argmax(1)==y}


def paired(base,candidate):
    a,b=base['right'],candidate['right']
    return {'rescued_old_errors':int((~a & b).sum()),
            'new_old_errors':int((a & ~b).sum()),
            'baseline_correct':int(a.sum()),'candidate_correct':int(b.sum())}


def evaluate(source,old_capsules,stage1_path,public_path,private_path):
    source=Path(source);old_capsules=Path(old_capsules)
    meta=decoded(take(source/'train-source.json',SOURCE))
    need(meta.get('schema')==V32_SCHEMA+'.train-only-source'
         and meta.get('archive_sha256')==ARCHIVE
         and meta.get('original_full_feature_sha256')==PRETRAINED
         and meta.get('train_feature_sha256')==FEATURE
         and meta.get('train_count')==64 and meta.get('train_cell_counts')==[32,32]
         and meta.get('calibration_labels_exposed_to_trainer') is False
         and meta.get('blind_labels_exposed_to_trainer') is False
         and meta.get('independent_future_windows')==0
         and meta.get('production_authorized') is False,
         'source or original TRAIN only custody invalid')
    src=load_numpy(take(source/'train-features.safetensors',FEATURE))
    need(set(src)=={'features'},'unreviewed original feature key')
    raw=src['features']
    need(raw.shape==(64,WIDTH) and raw.dtype==np.float32 and np.isfinite(raw).all(),
         'original source not genuine pretrained fixed-shape FP32')
    rows=meta['rows']
    need(len(rows)==64 and len({r['case_id'] for r in rows})==64
         and len({r['group'] for r in rows})==64
         and all(type(r) is dict and set(r)=={'case_id','group','cell','split','label'}
                 and r['split']=='train' and type(r['cell']) is int and r['cell'] in (0,1)
                 and type(r['label']) is int and 0<=r['label']<4 for r in rows),
         'source rows changed or forbidden CAL/BLIND labels')
    original_folds=folds(rows)
    idx=decoded(take(old_capsules/'capsule-index.json'))
    need(idx.get('schema')==SCHEMA+'.capsule-index'
         and idx.get('source_sha256')==SOURCE
         and idx.get('model_visible_new_cell_features') is False
         and idx.get('model_visible_hold_features') is False
         and idx.get('production_authorized') is False
         and type(idx.get('folds')) is list and len(idx['folds'])==4,
         'untrusted capsule roster')
    capsule_scales={}
    for fid,hold in enumerate(original_folds):
        old=[i for i,r in enumerate(rows) if r['cell']==0 and i not in set(hold)]
        new=[i for i,r in enumerate(rows) if r['cell']==1 and i not in set(hold)]
        need(len(old)==len(new)==24,'not 24 old/new fit')
        prefix=old_capsules/f'old-fold-{fid}'
        srcdata=take(Path(str(prefix)+'.safetensors'))
        metaraw=take(Path(str(prefix)+'.json'))
        cap=decoded(metaraw)
        need(cap.get('schema')==SCHEMA+'.old-source'
             and cap.get('fold')==fid
             and cap.get('source_cell')==0
             and cap.get('train_count')==24
             and cap.get('original_cell1_count_visible_to_model')==0
             and cap.get('original_held_count_visible_to_model')==0
             and cap.get('original_source_sha256')==SOURCE
             and cap.get('original_feature_sha256')==FEATURE
             and cap.get('features_sha256')==sha(srcdata)
             and cap.get('future_windows')==0
             and cap.get('production_authorized') is False
             and cap.get('old_rows')==[rows[i] for i in old]
             and idx['folds'][fid]=={'fold':fid,'features_sha256':sha(srcdata),
                                    'metadata_sha256':sha(metaraw)},
             'stage1 included new/held feature or unexpected original old source')
        tensor=load_numpy(srcdata)
        need(set(tensor)=={'features'} and np.array_equal(tensor['features'],raw[old]),
             'old-only stage1 feature bytes changed or new Cell slipped in')
        mean=raw[old].mean(0).astype('<f4')
        scale=np.maximum(raw[old].std(0),np.float32(.1)).astype('<f4')
        capsule_scales[fid]=(mean,scale,sha(mean.tobytes()+scale.tobytes()))
    stage1=decoded(take(stage1_path))
    need(stage1.get('schema')==SCHEMA+'.stage1-old-only-checkpoints'
         and stage1.get('original_source_sha256')==SOURCE
         and stage1.get('stage1_input_census')=='FOUR_CAPSULES_24_OLD_ONLY'
         and stage1.get('seed_count')==3 and stage1.get('fold_count')==4
         and stage1.get('old_only_fit_rows_per_fold')==24
         and stage1.get('total_old_only_updates')==480
         and stage1.get('new_cell_features_accessed_in_model_process') is False
         and stage1.get('held_features_accessed_in_model_process') is False
         and stage1.get('production_authorized') is False
         and stage1.get('independent_future_windows')==0,
         'stage1 was not old-only')
    first=stage1.get('records')
    need(type(first) is list and len(first)==12,'missing stage1 physical checkpoints')
    stage_by={(r['seed'],r['fold']):r for r in first}
    need(len(stage_by)==12,'duplicate old-only pretrained model')
    public,private=decoded(take(public_path)),decoded(take(private_path))
    need(public.get('schema')==SCHEMA+'.public'
         and private.get('schema')==SCHEMA+'.private-stage2'
         and public.get('original_archive_sha256')==ARCHIVE
         and public.get('original_pretrained_feature_sha256')==PRETRAINED
         and public.get('original_v32_staged_source_sha256')==SOURCE
         and public.get('original_train_feature_sha256')==FEATURE
         and public.get('stage1_input_census')=='FOUR_CAPSULES_24_OLD_ONLY'
         and public.get('stage1_preprocessing_fitted_old_only') is True
         and public.get('stage1_new_cell_feature_exposure')==0
         and public.get('old_scaler_refit_after_new_cell') is False
         and public.get('old_task_independent_future') is False
         and public.get('old_task_retention_frozen_baseline')=='NOCHANGE_OLD_HEAD'
         and public.get('new_cell_labelled_train_rows_per_fold')==24
         and public.get('old_cell_labelled_train_rows_per_fold')==24
         and public.get('held_new_old_original_train_each_fold')==[8,8]
         and public.get('original_source_family_count')==1
         and public.get('independent_future_windows')==0
         and public.get('new_encoder_forwards')==0
         and public.get('physical_head_optimizer_updates_paid')==1440
         and public.get('stage1_optimizer_updates')==480
         and public.get('stage2_optimizer_updates')==960
         and public.get('head_parameters_per_cell')==1540
         and public.get('two_head_parameters')==3080
         and public.get('split_and_ensemble_share_exact_head_weights') is True
         and public.get('source_blind_ensemble_evaluates_two_heads_per_request') is True
         and public.get('independent_prospective_utility') is None
         and public.get('negative_transfer_on_new_sources') is None
         and public.get('matched_end_to_end_lifecycle_cpu') is None
         and public.get('authority')=='DENY_ALL'
         and public.get('decision')=='HOLD_OLD_ONLY_STAGE1_NO_PROSPECTIVE_SELECTION'
         and all(public.get(k) is False for k in
                 ('production_authorized','model_selection_authorized','ndu_selector_authorized',
                  'cell_split_authorized','final_use_authorized'))
         and private.get('original_source_sha256')==SOURCE
         and private.get('stage1_checkpoint_sha256')==sha(canonical(stage1))
         and private.get('research_only') is True
         and private.get('calibration_or_blind_labels_present') is False
         and private.get('new_cell_source_in_stage1_process') is False,
         'fabricated old-only release/retention/future/authorization')
    records=private.get('records')
    need(type(records) is list and len(records)==12,'missing stage2 checkpoint roster')
    stage2_by={(r['seed'],r['fold']):r for r in records}
    need(len(stage2_by)==12,'duplicated stage2 checkpoint')
    results={}
    recounted=0;verified_weights=0
    for seed in SEEDS:
        aggregated={arm:{c:[] for c in (0,1)} for arm in ARMS}
        labels_for_cell={0:[],1:[]}
        for fid,hold in enumerate(original_folds):
            prior=stage_by.get((seed,fid));second=stage2_by.get((seed,fid))
            need(type(prior) is dict and type(second) is dict,'original stage missing')
            old=[i for i,r in enumerate(rows) if r['cell']==0 and i not in set(hold)]
            new=[i for i,r in enumerate(rows) if r['cell']==1 and i not in set(hold)]
            mean,scale,statsha=capsule_scales[fid]
            need(prior.get('old_train_case_ids')==[rows[i]['case_id'] for i in old]
                 and prior.get('old_capsule_sha256')==idx['folds'][fid]['features_sha256']
                 and prior.get('old_scaler_sha256')==statsha
                 and prior.get('new_cell_feature_rows_seen')==0
                 and prior.get('held_feature_rows_seen')==0
                 and second.get('old_train_case_ids')==[rows[i]['case_id'] for i in old]
                 and second.get('new_train_case_ids')==[rows[i]['case_id'] for i in new]
                 and second.get('held_case_ids')==[rows[i]['case_id'] for i in hold]
                 and second.get('old_stage1_receipt_sha256')==sha(canonical(prior))
                 and second.get('old_only_scaler_sha256')==statsha
                 and second.get('old_scaler_refit_after_new_data') is False
                 and second.get('shared_old_head_state') is True
                 and second.get('split_reuses_continued') is True,
                 'source, Old-only preprocessor or checkpoint continuity drift')
            for receipt in (prior['cost'],*second['cost'].values()):
                need(type(receipt) is dict and receipt.get('updates')==40
                     and receipt.get('batch')==16
                     and receipt.get('source_examples_seen')==640
                     and type(receipt.get('cpu_ns')) is int and receipt['cpu_ns']>0
                     and type(receipt.get('optimizer_state_bytes_observed')) is int
                     and receipt['optimizer_state_bytes_observed']>=12320,
                     'missing actual 40-step paid optimizer receipt')
            need(second['cost']['old']==prior['cost']
                 and second['cost']['continued']['source_cell']==1
                 and second['cost']['rehearsal']['source_cell'] is None,
                 'original stage1 count duplicated or replay meter changed')
            transformed=((raw-mean)/scale).astype('<f4')
            xs=transformed[hold]
            observed={}
            need(set(second['states'])=={'old','new','continued','rehearsal'}
                 and set(second['weights_sha256'])==set(second['states'])
                 and set(second['logits'])==set(ARMS)
                 and set(second['logits_sha256'])==set(ARMS),
                 'source bound physical Head inventory incomplete')
            for name,state in second['states'].items():
                predicted,expected_sha=inspect_weights(state,xs)
                need(expected_sha==second['weights_sha256'][name],
                     'unverified materialized model weights')
                observed[name]=predicted
                verified_weights+=1
            old_pred,old_sha=inspect_weights(prior['weights'],xs)
            need(old_sha==prior['weights_sha256']==second['weights_sha256']['old']
                 and prior['weights']==second['states']['old']
                 and second['weights_sha256']['continued']==second['weights_sha256']['new'],
                 'stage1 no-change weights not exactly preserved')
            cell=np.array([rows[i]['cell'] for i in hold],dtype=np.int64)
            predictions={'nochange':old_pred,'continued':observed['continued'],
                         'rehearsal':observed['rehearsal'],
                         'split':np.where(cell[:,None]==1,observed['new'],old_pred),
                         'source_blind_ensemble':(observed['new']+old_pred)/2}
            for arm,ref in predictions.items():
                seen=np.asarray(second['logits'][arm],dtype='<f4')
                need(seen.shape==(16,4) and np.isfinite(seen).all()
                     and sha(seen.tobytes())==second['logits_sha256'][arm]
                     and np.max(np.abs(seen.astype('<f8')-ref))<=1e-4,
                     'physical original per-case prediction SHA or numerical replay changed')
                for c in (0,1):
                    mask=(cell==c)
                    aggregated[arm][c].append(seen[mask])
                recounted+=1
            for c in (0,1):
                labels_for_cell[c].append(np.asarray([rows[i]['label'] for i in hold
                                                       if rows[i]['cell']==c],dtype=np.int64))
        scores={};summaries={}
        for arm in ARMS:
            scores[arm]={}
            for c in (0,1):
                xx=np.concatenate(aggregated[arm][c]);yy=np.concatenate(labels_for_cell[c])
                need(xx.shape==(32,4) and yy.shape==(32,), 'fold old/new held census drift')
                observed=metric(xx,yy)
                published=public['per_seed'][str(seed)][arm][f'cell{c}_{"old" if c==0 else "new"}_oof']
                need(observed['correct']==published['correct']
                     and abs(observed['brier']-published['brier'])<0.000003,
                     'published original old/new task score cannot be reproduced')
                scores[arm][c]=observed
            need(public['per_seed'][str(seed)][arm]['total_correct']==
                 scores[arm][0]['correct']+scores[arm][1]['correct']
                 and public['per_seed'][str(seed)][arm]['total_cases']==64,
                 'forged published original train task totals')
            summaries[arm]={'old_correct':scores[arm][0]['correct'],
                            'new_correct':scores[arm][1]['correct'],
                            'total_correct':scores[arm][0]['correct']+scores[arm][1]['correct'],
                            'old_brier':round(scores[arm][0]['brier'],9),
                            'new_brier':round(scores[arm][1]['brier'],9),
                            'old_rescue_harm_vs_frozen_old':paired(scores['nochange'][0],scores[arm][0])}
        # Strong negative-control claims for SPLIT: its old source routed
        # predictions are bit-identical to the frozen stage1 old-only model.
        need(summaries['split']['old_rescue_harm_vs_frozen_old']['rescued_old_errors']==0
             and summaries['split']['old_rescue_harm_vs_frozen_old']['new_old_errors']==0,
             'split altered the supposedly retained old Head')
        results[str(seed)]=summaries
    need(verified_weights==48 and recounted==60,
         'missing original stage1/2 model weight or inference observations')
    return {'schema':SCHEMA+'.independent-NumPy-only-review',
            'original_archive_sha256':ARCHIVE,
            'original_pretrained_feature_sha256':PRETRAINED,
            'source_family_count':1,'future_windows':0,
            'old_only_capsule_fold_count':4,
            'old_phase_feature_rows_per_fold':24,
            'old_phase_other_cell_features_visible':False,
            'frozen_old_preprocessor_reused_for_new_phase':True,
            'stage1_head_update_count':480,'stage2_head_update_count':960,
            'total_optimizer_updates':1440,
            'verified_stage2_head_states':verified_weights,
            'verified_model_logits':recounted,
            'old_task_historical_oof_only':True,
            'old_task_future_retention_established':False,
            'optimizer_gradients_independently_recomputed':False,
            'per_seed':results,
            'ndu_net_benefit':None,'independent_prospective_utility':None,
            'target_host_4096_cell_verified':False,
            'production_authorized':False,'model_selection_authorized':False,
            'ndu_selector_authorized':False,'cell_split_authorized':False,
            'final_use_authorized':False,
            'authority':'DENY_ALL',
            'decision':'HOLD_OLD_ONLY_STAGE1_NO_PROSPECTIVE_SELECTION'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--old-capsules',required=True,type=Path)
    p.add_argument('--stage1',required=True,type=Path)
    p.add_argument('--public',required=True,type=Path)
    p.add_argument('--private',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    need(not a.output.exists(),'independent report must be create-only')
    result=evaluate(a.source,a.old_capsules,a.stage1,a.public,a.private)
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(canonical(result));f.flush()
    print(json.dumps({'decision':result['decision'],
                      'verified_head_states':result['verified_stage2_head_states'],
                      'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':main()
