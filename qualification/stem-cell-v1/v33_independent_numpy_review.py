"""Independent NumPy-only V33 replay; no Torch, model fit or producer imports.

Reconstruct original frozen mmBERT features and per-fold 48-only normalization,
then independently replay every saved real Head and CAL-free TRAIN OOF metric.
The original publisher's different-time CAL/BLIND labels are never in scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from safetensors.numpy import load as load_numpy

SCHEMA='hepta.stem.v33.fold-disjoint-original-train-oof.v1'
V32_SCHEMA='hepta.stem.v32.original-cell-prequential-trainonly.v1'
POLICY='NORMALIZER_48_FIT_ONLY_NO_WITHHELD_FEATURES'
ORIGINAL_ARCHIVE='0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7'
PRETRAINED_FEATURE='e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
STAGE_SHA='69bdb09bb235c9cf490da400e239c5d9fabe8e13327cb255721090ea47d2e096'
TRAIN_FEATURE_SHA='2530b62d48b593cebeeb783c3ee754f8229b924558340dd09fb7160c6d1e3cc3'
SEEDS=(41,47,53)
ARMS=('nochange','continued','rehearsal','split','source_blind_ensemble')
WIDTH=384


def check(condition,reason):
    if not condition:raise ValueError(reason)


def sha(x):return hashlib.sha256(x).hexdigest()


def canonical(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def strict(raw):
    def unique(pairs):
        d={}
        for k,v in pairs:
            check(k not in d,'duplicate original evidence field')
            d[k]=v
        return d
    def invalid(x):raise ValueError('nonfinite evidence JSON '+x)
    doc=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    canonical(doc)
    return doc


def read(path,sha256=None):
    path=Path(path)
    check(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<8_000_000,
          'missing/unsafe/oversized original evidence')
    raw=path.read_bytes()
    if sha256:check(sha(raw)==sha256,'original evidence digest drift')
    return raw


def separate_folds(rows):
    check(len(rows)==64,'fold source count wrong')
    by_cell=[]
    for c in (0,1):
        group=sorted((sha(r['case_id'].encode()),i)
                     for i,r in enumerate(rows) if r['cell']==c)
        check(len(group)==32,'missing independent original Cell group')
        by_cell.append([[i for _,i in group[offset::4]] for offset in range(4)])
    return [by_cell[0][i]+by_cell[1][i] for i in range(4)]


def pure_stats(raw,fit_ids,hold_ids):
    check(raw.shape==(64,WIDTH) and raw.dtype==np.float32 and np.isfinite(raw).all(),
          'unverified raw mmBERT features')
    check(len(fit_ids)==48 and len(hold_ids)==16
          and set(fit_ids).isdisjoint(hold_ids)
          and set(fit_ids+hold_ids)==set(range(64)),
          'TEST fold contaminated fitted scaler')
    center=raw[fit_ids].mean(0).astype('<f4')
    scale=np.maximum(raw[fit_ids].std(0),np.float32(0.1)).astype('<f4')
    check(np.isfinite(center).all() and np.isfinite(scale).all(), 'nonfinite stage statistics')
    return ((raw-center)/scale).astype('<f4'), sha(center.tobytes()+scale.tobytes())


def apply_head(record,features):
    check(type(record) is dict and set(record)=={'w','b'},'missing learned model parameters')
    w=np.asarray(record['w'],dtype='<f4')
    b=np.asarray(record['b'],dtype='<f4')
    check(w.shape==(4,WIDTH) and b.shape==(4,) and np.isfinite(w).all() and np.isfinite(b).all(),
          'corrupt Head weight tensor')
    return features.astype(np.float64)@w.astype(np.float64).T+b.astype(np.float64), sha(w.tobytes()+b.tobytes())


def score(logits,labels):
    x=logits.astype(np.float64)
    x=x-x.max(1,keepdims=True)
    e=np.exp(x); p=e/e.sum(1,keepdims=True)
    return {'correct':int((p.argmax(1)==labels).sum()),
            'brier':float(((p-np.eye(4,dtype=np.float64)[labels])**2).sum(1).mean())}


def review(stage_dir,public_path,private_path):
    source=strict(read(Path(stage_dir)/'train-source.json',STAGE_SHA))
    blob=read(Path(stage_dir)/'train-features.safetensors',TRAIN_FEATURE_SHA)
    check(source.get('schema')==V32_SCHEMA+'.train-only-source'
          and source.get('archive_sha256')==ORIGINAL_ARCHIVE
          and source.get('original_full_feature_sha256')==PRETRAINED_FEATURE
          and source.get('train_feature_sha256')==TRAIN_FEATURE_SHA
          and source.get('train_count')==64 and source.get('train_cell_counts')==[32,32]
          and source.get('calibration_labels_exposed_to_trainer') is False
          and source.get('blind_labels_exposed_to_trainer') is False
          and source.get('independent_source_family_count')==1
          and source.get('independent_future_windows')==0
          and source.get('production_authorized') is False,
          'original source identity or withheld-label boundary mismatch')
    raw=load_numpy(blob)
    check(set(raw)=={'features'},'original pretrained feature inventory drift')
    x=raw['features']
    check(x.shape==(64,WIDTH) and x.dtype==np.float32 and np.isfinite(x).all(),
          'original physical TRAIN material changed')
    rows=source['rows']
    check(len(rows)==64 and len({r['case_id'] for r in rows})==64
          and len({r['group'] for r in rows})==64
          and all(set(r)=={'case_id','group','cell','split','label'}
                  and r['split']=='train' and type(r['cell']) is int and r['cell'] in (0,1)
                  and type(r['label']) is int and 0<=r['label']<4 for r in rows),
          'source groups or held source labels changed')
    public=strict(read(public_path));private=strict(read(private_path))
    check(public.get('schema')==SCHEMA+'.public' and private.get('schema')==SCHEMA+'.private'
          and public.get('original_archive_sha256')==ORIGINAL_ARCHIVE
          and public.get('original_pretrained_feature_sha256')==PRETRAINED_FEATURE
          and public.get('original_v32_staged_source_sha256')==STAGE_SHA
          and public.get('train_feature_sha256')==TRAIN_FEATURE_SHA
          and private.get('source_sha256')==STAGE_SHA
          and private.get('feature_sha256')==TRAIN_FEATURE_SHA
          and private.get('train_identity_sha256')==sha(canonical(rows))
          and public.get('fold_normalization')==private.get('fold_normalization')==POLICY
          and public.get('fitted_source_groups_per_fold')==48
          and public.get('held_source_groups_per_fold')==16
          and public.get('held_groups_used_for_fit') is False
          and public.get('old_new_train_items')==[32,32]
          and public.get('seeds')==list(SEEDS) and public.get('arms')==list(ARMS)
          and public.get('physical_head_optimizer_updates')==1440
          and public.get('head_parameters_per_model')==1540
          and public.get('two_head_parameters')==3080
          and public.get('same_two_heads_used_in_split_and_ensemble') is True
          and public.get('source_blind_ensemble_evaluates_two_heads_per_request') is True
          and public.get('task_data_source_family_count')==1
          and public.get('independent_future_windows')==0
          and public.get('new_encoder_forwards')==0
          and public.get('evaluation_scope')=='RETROSPECTIVE_TRAIN_OUT_OF_FOLD'
          and public.get('independent_prospective_utility') is None
          and public.get('negative_transfer_on_new_sources') is None
          and public.get('end_to_end_latency_measurement') is None
          and public.get('historical_v32_transductive_normalization_not_overwritten') is True
          and public.get('authority')=='DENY_ALL'
          and public.get('decision')=='HOLD_STRICT_FOLD_PREPROCESS_NOT_PROSPECTIVE'
          and all(public.get(k) is False for k in ('production_authorized',
                 'model_selection_authorized','ndu_selector_authorized','cell_split_authorized'))
          and private.get('research_only') is True
          and private.get('calibration_or_blind_labels_present') is False,
          'false normalization, NDU, authority or future evidence')
    records=private.get('records')
    check(type(records) is list and len(records)==12,'missing physical seed/fold receipts')
    by_key={(r['seed'],r['fold']):r for r in records}
    check(len(by_key)==len(records),'duplicate seed/fold')
    folded=separate_folds(rows)
    analysis={}
    count=0
    for seed in SEEDS:
        grouped={arm:{0:[],1:[]} for arm in ARMS}
        for fid,held in enumerate(folded):
            receipt=by_key.get((seed,fid))
            check(type(receipt) is dict and receipt.get('split_reuses_continued') is True
                  and receipt.get('normalization_has_held_features') is False
                  and receipt.get('normalization_fit_group_count')==48,
                  'incorrect original fold receipt or normalization')
            fit=sorted(set(range(64))-set(held))
            old=[i for i in fit if rows[i]['cell']==0]
            new=[i for i in fit if rows[i]['cell']==1]
            check(len(old)==len(new)==24
                  and receipt['fitted_case_ids']==[rows[i]['case_id'] for i in fit]
                  and receipt['old_train_case_ids']==[rows[i]['case_id'] for i in old]
                  and receipt['new_train_case_ids']==[rows[i]['case_id'] for i in new]
                  and receipt['held_case_ids']==[rows[i]['case_id'] for i in held]
                  and receipt['held_cells']==[rows[i]['cell'] for i in held],
                  'TRAIN/validation source case overlap or replay')
            normalized,statsha=pure_stats(x,fit,held)
            check(receipt['normalizer_sha256']==statsha,
                  'fold scaler used a withheld-group input')
            models=receipt['states']
            check(type(models) is dict and set(models)=={'old','new','continued','rehearsal'}
                  and type(receipt.get('weights_sha256')) is dict
                  and set(receipt['weights_sha256'])==set(models)
                  and type(receipt.get('logits_sha256')) is dict
                  and set(receipt['logits_sha256'])==set(ARMS)
                  and type(receipt.get('logits')) is dict
                  and set(receipt['logits'])==set(ARMS),
                  'Head model/save field mismatch')
            outputs={}
            for name,m in models.items():
                out,weights_sha=apply_head(m,normalized[held]);outputs[name]=out
                check(weights_sha==receipt['weights_sha256'][name],
                      'physical Head weight digest tampered')
            check(receipt['weights_sha256']['new']==receipt['weights_sha256']['continued'],
                  'split new Head state not reused')
            cell=np.array([rows[i]['cell'] for i in held],dtype=np.int64)
            derived={'nochange':outputs['old'],
                     'continued':outputs['continued'],
                     'rehearsal':outputs['rehearsal'],
                     'split':np.where(cell[:,None]==1,outputs['new'],outputs['old']),
                     'source_blind_ensemble':(outputs['old']+outputs['new'])/2}
            for arm in ARMS:
                logits=np.asarray(receipt['logits'][arm],dtype='<f4')
                check(logits.shape==(16,4) and np.isfinite(logits).all()
                      and sha(logits.tobytes())==receipt['logits_sha256'][arm],
                      'physical model output digests not bound')
                check(float(np.max(np.abs(derived[arm]-logits)))<1e-4,
                      'independent original feature -> Head forward disagrees')
                for c in (0,1):
                    mask=(cell==c)
                    labels=np.array([rows[i]['label'] for j,i in enumerate(held) if mask[j]],dtype=np.int64)
                    grouped[arm][c].append((logits[mask],labels))
                count+=1
            cost=receipt['cost']
            check(type(cost) is dict and set(cost)=={'old','continued','rehearsal'}
                  and all(type(v['updates']) is int and v['updates']==40
                          and v['batch']==16 and v['source_examples_seen']==640
                          and type(v['cpu_ns']) is int and v['cpu_ns']>0
                          and type(v['optimizer_state_bytes_observed']) is int
                          and v['optimizer_state_bytes_observed']>=12320
                          for v in cost.values()), 'unpaid or unobserved optimizer work')
        summary={}
        for arm in ARMS:
            items={}
            for cell in (0,1):
                logits=np.concatenate([v for v,_ in grouped[arm][cell]])
                labels=np.concatenate([v for _,v in grouped[arm][cell]])
                check(logits.shape==(32,4) and labels.shape==(32,),
                      'missing original TRAIN source group')
                metric=score(logits,labels)
                published=public['per_seed'][str(seed)][arm][f'cell{cell}_{"old" if cell==0 else "new"}_oof']
                check(type(published.get('correct')) is int
                      and published['correct']==metric['correct']
                      and abs(published['brier']-metric['brier'])<3e-6,
                      'original pretrained TRAIN OOF score drift')
                items[cell]=metric
            check(public['per_seed'][str(seed)][arm]['total_correct']==
                  items[0]['correct']+items[1]['correct'], 'reported total accuracy changed')
            summary[arm]={'old_correct':items[0]['correct'],'new_correct':items[1]['correct'],
                          'old_brier':round(items[0]['brier'],9),'new_brier':round(items[1]['brier'],9)}
        analysis[seed]=summary
    check(count==60 and len(analysis)==3,'incomplete real Head forward observations')
    return {'schema':SCHEMA+'.independent-review', 'original_archive_sha256':ORIGINAL_ARCHIVE,
            'original_train_groups':64,'normalized_withheld_groups_used':False,
            'preprocessor_stats_built_from_training_groups':48,
            'physical_head_optimizer_updates_paid':1440,
            'checkpoint_count':48,'source_bound_model_prediction_count':60,
            'independent_numpy_weight_forward_replay':True,
            'independent_optimizer_gradient_replay':False,
            'independent_source_time_windows':0,'source_family_count':1,
            'per_seed':analysis,
            'production_authorized':False,'ndu_selector_authorized':False,
            'model_selection_authorized':False,'cell_split_authorized':False,
            'authority':'DENY_ALL',
            'decision':'HOLD_CORRECTED_FOLD_NORMALIZATION_NOT_PROSPECTIVE'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--public',type=Path,required=True)
    p.add_argument('--private',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    check(not a.output.exists() and not a.output.is_symlink(), 'create-only output')
    data=review(a.source,a.public,a.private)
    Path(a.output).write_bytes(canonical(data))
    print(json.dumps({'decision':data['decision'],
                      'source_bound_model_prediction_count':data['source_bound_model_prediction_count'],
                      'production_authorized':False},sort_keys=True))


if __name__=='__main__':main()
