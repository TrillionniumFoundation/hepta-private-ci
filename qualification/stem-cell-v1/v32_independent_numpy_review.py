"""Pure NumPy independent replay of original mmBERT train-only OOF Cell Heads.

Never imports torch, the learner module, or any pretrained model. Verifies every
observed model output against original feature bytes and separately saved weights.
NO independent gradient replay, source custody, blind labels, NDU or FinalUse.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import numpy as np
from safetensors.numpy import load as load_numpy

SCHEMA='hepta.stem.v32.original-cell-prequential-trainonly.v1'
ARCHIVE_SHA='0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
FEATURE_SHA='e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
V14_SHA='d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a'
STAGED_SOURCE_SHA='69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096'
STAGED_TRAIN_FEATURE_SHA='2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3'
SEEDS=(41,47,53)
ARMS=('nochange','continued','rehearsal','split','source_blind_ensemble')
FOLDS,STEPS,WIDTH=4,40,384


def need(condition,msg):
    if not condition:raise ValueError(msg)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def strict_json(raw):
    def unique(pairs):
        out={}
        for k,v in pairs:
            need(k not in out,'duplicate source/result key')
            out[k]=v
        return out
    def bad(_):raise ValueError('nonfinite JSON')
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=bad)
    canonical(value)
    return value


def read(path):
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < 8_000_000,
         'invalid original evidence material')
    return path.read_bytes()


def folds(rows):
    need(len(rows)==64,'missing original Cell cases')
    by_cell=[]
    for c in (0,1):
        order=sorted((sha(row['case_id'].encode()),i) for i,row in enumerate(rows) if row['cell']==c)
        need(len(order)==32 and len({i for _,i in order})==32,'Cell group malformed')
        by_cell.append([[i for _,i in order[k::FOLDS]] for k in range(FOLDS)])
    return [by_cell[0][f]+by_cell[1][f] for f in range(FOLDS)]


def metric(logits,labels):
    p=logits.astype(np.float64)
    p-=p.max(1,keepdims=True)
    np.exp(p,out=p)
    p/=p.sum(1,keepdims=True)
    return {'correct':int((p.argmax(1)==labels).sum()),
            'brier':float(np.square(p-np.eye(4,dtype=np.float64)[labels]).sum(1).mean())}


def param_predict(weights,features):
    need(type(weights) is dict and set(weights)=={'w','b'}, 'unapproved Head tensor roster')
    w=np.asarray(weights['w'],dtype='<f4');b=np.asarray(weights['b'],dtype='<f4')
    need(w.shape==(4,WIDTH) and b.shape==(4,) and np.isfinite(w).all() and np.isfinite(b).all(),
         'missing/nonfinite original Head weights')
    return features.astype(np.float64)@w.astype(np.float64).T+b.astype(np.float64),w,b


def assess(source_folder:Path,public_file:Path,private_file:Path):
    source_meta_bytes=read(source_folder/'train-source.json')
    need(sha(source_meta_bytes)==STAGED_SOURCE_SHA,'original TRAIN-only source JSON byte identity mismatch')
    stage=strict_json(source_meta_bytes)
    source_blob=read(source_folder/'train-features.safetensors')
    need(sha(source_blob)==STAGED_TRAIN_FEATURE_SHA,'original TRAIN-only feature raw bytes changed')
    need(stage.get('schema')==SCHEMA+'.train-only-source' and
         stage.get('archive_sha256')==ARCHIVE_SHA and
         stage.get('original_full_feature_sha256')==FEATURE_SHA and
         stage.get('original_v14_input_sha256')==V14_SHA and
         sha(source_blob)==stage.get('train_feature_sha256') and
         stage.get('train_count')==64 and stage.get('train_cell_counts')==[32,32] and
         stage.get('calibration_labels_exposed_to_trainer') is False and
         stage.get('blind_labels_exposed_to_trainer') is False and
         stage.get('production_authorized') is False and
         stage.get('independent_future_windows')==0,
         'original TRAIN-only source/revision gate false')
    x=load_numpy(source_blob)['features']
    need(x.dtype==np.float32 and x.shape==(64,WIDTH) and np.isfinite(x).all(),
         'unverified original shared pretrained feature panel')
    x=((x-x.mean(0))/np.maximum(x.std(0),np.float32(0.1))).astype('<f4')
    need(np.isfinite(x).all(), 'independent TRAIN-only normalization nonfinite')
    rows=stage['rows']
    need(len(rows)==64 and len({r['case_id'] for r in rows})==64 and
         all(set(r)=={'case_id','group','cell','split','label'} and
             r['split']=='train' and type(r['label']) is int and 0<=r['label']<4 and
             type(r['cell']) is int and r['cell'] in (0,1) for r in rows),
         'TRAIN identities or labels invalid')
    panels=folds(rows)
    public=strict_json(read(public_file));private=strict_json(read(private_file))
    need(public.get('schema')==SCHEMA+'.sanitized' and private.get('schema')==SCHEMA+'.private-checkpoints' and
         public.get('original_archive_sha256')==ARCHIVE_SHA and
         public.get('original_feature_sha256')==FEATURE_SHA and
         public.get('original_v14_source_sha256')==V14_SHA and
         public.get('train_feature_sha256')==STAGED_TRAIN_FEATURE_SHA and
         public.get('train_rows')==64 and public.get('original_old_cell0_rows')==32 and
         public.get('original_new_cell1_rows')==32 and
         public.get('train_only_oof_cases_per_seed')==64 and
         public.get('fold_count')==FOLDS and public.get('seeds')==list(SEEDS) and
         public.get('arms')==list(ARMS) and
         public.get('authority')=='DENY_ALL' and
         public.get('decision')=='HOLD_ORIGINAL_TRAIN_OOF_NO_PROSPECTIVE_SELECTION' and
         public.get('production_authorized') is False and public.get('model_or_cell_split_authorized') is False and
         public.get('final_use_authorized') is False and public.get('ndu_selection_authorized') is False and
         public.get('calibration_labels_used_for_selection') is False and public.get('blind_labels_used') is False and
         public.get('chronological_future_windows')==0 and public.get('source_family_count')==1 and
         public.get('total_physical_optimizer_updates_paid')==len(SEEDS)*FOLDS*3*STEPS and
         public.get('shared_encoder_additional_forwards')==0 and
         public.get('cell_head_parameters')==1540 and public.get('two_head_parameters')==3080 and
         public.get('split_new_model_reuses_continued_head_without_duplicate_training') is True and
         public.get('source_blind_ensemble_shares_exact_split_weights') is True and
         private.get('train_material_sha256')==stage.get('train_feature_sha256') and
         private.get('case_identity_sha256')==sha(canonical(rows)) and
         private.get('cal_or_blind_labels_present') is False and private.get('research_only') is True,
         'invalid source Head cost/authority or fabricated future result')
    records=private['records']
    need(type(records) is list and len(records)==len(SEEDS)*FOLDS,'missing original train-only optimizer traces')
    index={(r['seed'],r['fold']):r for r in records}
    need(len(index)==len(records),'duplicate physical seed/fold')
    scores={}
    digests=[]
    for seed in SEEDS:
        accum={arm:{0:[],1:[]} for arm in ARMS}
        for fold_idx,hold in enumerate(panels):
            record=index.get((seed,fold_idx))
            need(type(record) is dict and record.get('split_new_model_state_reuses_continued') is True,
                 'split duplicated training or wrong source fold')
            withheld=set(hold)
            old=[i for i,r in enumerate(rows) if r['cell']==0 and i not in withheld]
            new=[i for i,r in enumerate(rows) if r['cell']==1 and i not in withheld]
            need(len(old)==len(new)==24 and
                 record.get('train_old_case_ids')==[rows[i]['case_id'] for i in old] and
                 record.get('train_new_case_ids')==[rows[i]['case_id'] for i in new] and
                 record.get('held_case_ids')==[rows[i]['case_id'] for i in hold] and
                 record.get('held_source_cell')==[rows[i]['cell'] for i in hold],
                 'TRAIN fold leakage, CAL substitution or source-cell routing mismatch')
            states=record['weights']
            need(set(states)=={'old','new','continued','rehearsal'} and
                 set(record.get('weights_sha256',{}))==set(states) and
                 set(record.get('logits',{}))==set(ARMS) and
                 set(record.get('logits_sha256',{}))==set(ARMS),
                 'incomplete physically learned Head inventory')
            physical={}
            for key,obj in states.items():
                logits,w,b=param_predict(obj,x[hold])
                need(sha(w.tobytes()+b.tobytes())==record['weights_sha256'][key],
                     'saved original Head material digest mismatch')
                physical[key]=logits
            need(record['weights_sha256']['new']==record['weights_sha256']['continued'],
                 'identical continuation and split new Head do not reuse actual state')
            aligned=np.array([rows[i]['cell'] for i in hold],dtype=np.int64)
            calc={
                'nochange':physical['old'],
                'continued':physical['continued'],
                'rehearsal':physical['rehearsal'],
                'split':np.where(aligned[:,None]==1,physical['new'],physical['old']),
                'source_blind_ensemble':(physical['new']+physical['old'])/2,
            }
            for arm in ARMS:
                observed=np.asarray(record['logits'][arm],dtype='<f4')
                need(observed.shape==(16,4) and np.isfinite(observed).all() and
                     sha(observed.tobytes())==record['logits_sha256'][arm],
                     'model logits missing/source-bound digest different')
                need(float(np.max(np.abs(observed.astype(np.float64)-calc[arm])))<0.0001,
                     'independent NumPy pretrained-feature forward replay differs from Torch')
                for c in (0,1):
                    mask=(aligned==c)
                    y=np.array([rows[i]['label'] for j,i in enumerate(hold) if mask[j]],dtype=np.int64)
                    accum[arm][c].append((observed[mask],y))
                digests.append([seed,fold_idx,arm,record['logits_sha256'][arm]])
            cost=record['cost']
            need(set(cost)=={'old','continued','rehearsal'} and
                 all(type(v['updates']) is int and v['updates']==STEPS and
                     v['batch']==16 and v['source_examples_seen']==STEPS*16 and
                     type(v['cpu_ns']) is int and v['cpu_ns']>0 and
                     type(v['optimizer_state_bytes_observed']) is int and
                     v['optimizer_state_bytes_observed']>=12320
                     for v in cost.values()), 'Head optimizer state/meter not observed')
        info={}
        for arm in ARMS:
            c_scores={}
            for c in (0,1):
                xx=np.concatenate([a for a,_ in accum[arm][c]])
                yy=np.concatenate([b for _,b in accum[arm][c]])
                need(xx.shape==(32,4) and yy.shape==(32,), 'crossfit incomplete Cell evaluation')
                m=metric(xx,yy)
                reported=public['per_seed'][str(seed)]['arms'][arm][f'cell{c}_{"old" if c==0 else "new"}_oof']
                need(type(reported.get('correct')) is int and reported['correct']==m['correct'] and
                     abs(reported['brier']-m['brier'])<0.000003,
                     'independent OOF source labels or Brier conflict')
                c_scores[c]=m
            info[arm]={'old_correct':c_scores[0]['correct'],
                       'new_correct':c_scores[1]['correct'],
                       'old_brier':round(c_scores[0]['brier'],9),
                       'new_brier':round(c_scores[1]['brier'],9)}
        scores[seed]=info
    need(set(public['per_seed'])=={str(s) for s in SEEDS},'missing original random seeds')
    return {'schema':SCHEMA+'.numpy-original-review',
            'original_archive_sha256':ARCHIVE_SHA,'full_pretrained_feature_sha256':FEATURE_SHA,
            'stage_train_feature_sha256':stage['train_feature_sha256'],
            'original_train_groups':64,'original_publisher_source_families':1,
            'physical_head_updates_charge':len(SEEDS)*FOLDS*3*STEPS,
            'checkpoint_count':len(records)*4,
            'source_bound_model_prediction_count':len(digests),
            'crossfit_cell_old_new_scores':scores,
            'independent_numpy_weight_forward_replay':True,
            'physical_optimizer_gradient_independently_replayed':False,
            'unseen_future_windows':0,'historical_calibration_blind_score_read':False,
            'production_authorized':False,'ndu_selection_authorized':False,
            'cell_split_authorized':False,'authority':'DENY_ALL',
            'decision':'HOLD_TRAIN_ONLY_ORIGINAL_OOF_NOT_PROSPECTIVE'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--public',required=True,type=Path)
    p.add_argument('--private',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    need(not a.out.exists(),'independent review must be create-only')
    doc=assess(a.source,a.public,a.private)
    a.out.write_bytes(canonical(doc))
    print(json.dumps({'decision':doc['decision'],'checkpoint_count':doc['checkpoint_count'],
                      'independent_numpy_forward':True,'production_authorized':False},sort_keys=True))

if __name__=='__main__':main()
