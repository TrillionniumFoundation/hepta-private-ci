"""V33: strictly out-of-fold feature normalization on ORIGINAL mmBERT TRAIN groups.

Reuses the original V32 real PyTorch linear Head/fitter/route; only the fold
preprocessing provenance changes. No CAL/BLIND input, future result, grant or
model selection is created. Published V32 transductive observations stay intact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import torch
from safetensors.numpy import load as load_numpy

import v32_original_cell_learning as prior

SCHEMA = 'hepta.stem.v33.fold-disjoint-original-train-oof.v1'
POLICY = 'NORMALIZER_48_FIT_ONLY_NO_WITHHELD_FEATURES'
ARMS = prior.ARMS
SEEDS = prior.SEEDS


def original(folder: Path):
    # Re-admit the source exactly as V32 did, but do not call V32's global
    # 64-sample normalizer even for discarded intermediate calculations.
    metadata_blob=prior.verified_file(folder/'train-source.json',prior.STAGED_SOURCE_SHA)
    metadata=prior.strict_json(metadata_blob)
    prior.require(type(metadata) is dict and
                  metadata.get('schema')==prior.SCHEMA+'.train-only-source' and
                  metadata.get('archive_sha256')==prior.ARCHIVE_SHA and
                  metadata.get('original_full_feature_sha256')==prior.FEATURE_SHA and
                  metadata.get('original_v14_input_sha256')==prior.V14_INPUT_SHA and
                  metadata.get('train_feature_sha256')==prior.STAGED_TRAIN_FEATURE_SHA and
                  metadata.get('train_cell_counts')==[32,32] and
                  metadata.get('train_count')==64 and
                  metadata.get('calibration_labels_exposed_to_trainer') is False and
                  metadata.get('blind_labels_exposed_to_trainer') is False and
                  metadata.get('independent_future_windows')==0 and
                  metadata.get('production_authorized') is False,
                  'original TRAIN source/custody changed')
    rows=metadata['rows']
    prior.require(type(rows) is list and len(rows)==64 and
                  len({r.get('case_id') for r in rows})==64 and
                  len({r.get('group') for r in rows})==64 and
                  all(type(r) is dict and set(r)=={'case_id','group','cell','split','label'} and
                      r['split']=='train' and type(r['cell']) is int and r['cell'] in (0,1) and
                      type(r['label']) is int and 0<=r['label']<4 for r in rows) and
                  [sum(r['cell']==c for r in rows) for c in (0,1)]==[32,32],
                  'original TRAIN identity or forbidden labels entered')
    blob=prior.verified_file(folder/'train-features.safetensors',prior.STAGED_TRAIN_FEATURE_SHA)
    tensor=load_numpy(blob)
    prior.require(set(tensor)=={'features'},'original frozen feature inventory')
    x=tensor['features']
    prior.require(x.shape==(64,prior.WIDTH) and x.dtype==np.float32 and
                  np.isfinite(x).all(),'original raw 64x384 physical mmBERT features')
    return x.copy(),rows,metadata


def fold_normalize(raw: np.ndarray, fit_ids: list[int], held_ids: list[int]):
    """Fit stats only on 48 disjoint training groups; never peek at held features."""
    prior.require(isinstance(raw, np.ndarray) and raw.shape == (64, prior.WIDTH)
                  and raw.dtype == np.float32 and np.isfinite(raw).all(), 'raw frozen features required')
    prior.require(type(fit_ids) is list and type(held_ids) is list
                  and len(fit_ids) == 48 and len(held_ids) == 16
                  and all(type(i) is int and 0 <= i < 64 for i in fit_ids + held_ids)
                  and len(set(fit_ids)) == 48 and len(set(held_ids)) == 16
                  and not set(fit_ids).intersection(held_ids)
                  and set(fit_ids + held_ids) == set(range(64)),
                  'fold normalization cannot include or omit held groups')
    mean = raw[fit_ids].mean(0).astype('<f4')
    floor_std = np.maximum(raw[fit_ids].std(0), np.float32(0.1)).astype('<f4')
    prior.require(np.isfinite(mean).all() and np.isfinite(floor_std).all()
                  and (floor_std >= np.float32(0.1)).all(), 'invalid fold scaler')
    # This expression transforms test features, but they never contribute to
    # mean/std. Do not use a 64-source transductive global normalizer here.
    transformed = ((raw - mean) / floor_std).astype('<f4')
    prior.require(np.isfinite(transformed).all(), 'nonfinite fold-only transformation')
    return transformed, prior.sha(mean.tobytes() + floor_std.tobytes())


def run(folder: Path):
    torch.use_deterministic_algorithms(True)
    raw, rows, meta = original(folder)
    labels = torch.tensor([r['label'] for r in rows], dtype=torch.long)
    cells = torch.tensor([r['cell'] for r in rows], dtype=torch.long)
    folds = prior.split_folds(rows)
    private = {'schema':SCHEMA+'.private', 'source_sha256':prior.STAGED_SOURCE_SHA,
               'feature_sha256':prior.STAGED_TRAIN_FEATURE_SHA,
               'train_identity_sha256':prior.sha(prior.canonical(rows)),
               'fold_normalization':POLICY,'records':[],
               'research_only':True,'calibration_or_blind_labels_present':False}
    public_seeds = {}
    updates = 0
    for seed in SEEDS:
        grouped={arm:{0:[],1:[]} for arm in ARMS}
        for fid,hold in enumerate(folds):
            held=set(hold)
            old=[i for i,r in enumerate(rows) if r['cell']==0 and i not in held]
            new=[i for i,r in enumerate(rows) if r['cell']==1 and i not in held]
            fit = sorted(old+new)
            prior.require(len(old)==len(new)==24 and len(hold)==16 and len(fit)==48,
                          '48 fitted / 16 withheld original groups required')
            transformed, statsha=fold_normalize(raw,fit,hold)
            x=torch.from_numpy(transformed.copy())
            old_model=prior.head()
            clock_old=prior.fit(old_model,x[old],labels[old],
                                seed=seed*1000+fid*10,cell=0)
            freeze=deepcopy(old_model)
            continue_model=deepcopy(old_model)
            rehearsal=deepcopy(old_model)
            clock_continue=prior.fit(continue_model,x[new],labels[new],
                                     seed=seed*1000+fid*10+1,cell=1)
            clock_rehearsal=prior.fit(rehearsal,x[new],labels[new],
                                      seed=seed*1000+fid*10+1,cell=None,
                                      replay=(x[old],labels[old],x[new],labels[new]))
            meters={'old':clock_old,'continued':clock_continue,'rehearsal':clock_rehearsal}
            updates += sum(m['updates'] for m in meters.values())
            models={'old':freeze,'new':continue_model,'continued':continue_model,'rehearsal':rehearsal}
            predictions=prior.forward_matrix(
                (freeze,continue_model,continue_model,rehearsal),x[hold],cells[hold])
            for arm, values in predictions.items():
                for cell in (0,1):
                    idx=[j for j,i in enumerate(hold) if rows[i]['cell']==cell]
                    grouped[arm][cell].append((values[idx].detach().cpu(),
                                               labels[[hold[j] for j in idx]]))
            private['records'].append({
                'seed':seed,'fold':fid,
                'fitted_case_ids':[rows[i]['case_id'] for i in fit],
                'old_train_case_ids':[rows[i]['case_id'] for i in old],
                'new_train_case_ids':[rows[i]['case_id'] for i in new],
                'held_case_ids':[rows[i]['case_id'] for i in hold],
                'held_cells':[rows[i]['cell'] for i in hold],
                'normalization_fit_group_count':48,
                'normalizer_sha256':statsha,
                'normalization_has_held_features':False,
                'states':{k:prior.state(m) for k,m in models.items()},
                'weights_sha256':{k:prior.sha(m.weight.detach().numpy().astype('<f4').tobytes()+
                                               m.bias.detach().numpy().astype('<f4').tobytes())
                                  for k,m in models.items()},
                'logits':{k:v.detach().cpu().numpy().astype('<f4').tolist()
                          for k,v in predictions.items()},
                'logits_sha256':{k:prior.sha(v.detach().cpu().numpy().astype('<f4').tobytes())
                                  for k,v in predictions.items()},
                'cost':meters,'split_reuses_continued':True,
            })
        arm_scores={}
        for arm in ARMS:
            per={}
            for cell in (0,1):
                pred=torch.cat([v for v,_ in grouped[arm][cell]])
                gold=torch.cat([y for _,y in grouped[arm][cell]])
                prior.require(len(gold)==32, 'crossfit missing physical original groups')
                per[f'cell{cell}']=prior.score(pred,gold)
            arm_scores[arm]={'cell0_old_oof':per['cell0'],
                             'cell1_new_oof':per['cell1'],
                             'total_correct':per['cell0']['correct']+per['cell1']['correct'],
                             'total_cases':64}
        public_seeds[str(seed)]=arm_scores
    prior.require(updates==len(SEEDS)*prior.FOLDS*3*prior.STEPS,
                  'not all 1440 real PyTorch updates executed')
    public={
        'schema':SCHEMA+'.public', 'original_archive_sha256':prior.ARCHIVE_SHA,
        'original_pretrained_feature_sha256':prior.FEATURE_SHA,
        'original_v32_staged_source_sha256':prior.STAGED_SOURCE_SHA,
        'train_feature_sha256':prior.STAGED_TRAIN_FEATURE_SHA,
        'fold_normalization':POLICY,'fitted_source_groups_per_fold':48,
        'held_source_groups_per_fold':16,'held_groups_used_for_fit':False,
        'old_new_train_items':[32,32], 'seeds':list(SEEDS), 'arms':list(ARMS),
        'physical_head_optimizer_updates':updates,
        'head_parameters_per_model':1540,'two_head_parameters':3080,
        'same_two_heads_used_in_split_and_ensemble':True,
        'source_blind_ensemble_evaluates_two_heads_per_request':True,
        'task_data_source_family_count':1,'independent_future_windows':0,
        'new_encoder_forwards':0,'evaluation_scope':'RETROSPECTIVE_TRAIN_OUT_OF_FOLD',
        'historical_v32_transductive_normalization_not_overwritten':True,
        'per_seed':public_seeds,
        'independent_prospective_utility':None,'negative_transfer_on_new_sources':None,
        'end_to_end_latency_measurement':None,
        'production_authorized':False,'model_selection_authorized':False,
        'ndu_selector_authorized':False,'cell_split_authorized':False,
        'authority':'DENY_ALL',
        'decision':'HOLD_STRICT_FOLD_PREPROCESS_NOT_PROSPECTIVE',
    }
    return public,private


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--private',type=Path,required=True)
    a=p.parse_args()
    prior.require(not a.output.exists() and not a.private.exists(),
                  'create-only real original study outputs')
    out,private=run(a.source)
    prior.write_only(a.output,prior.canonical(out))
    prior.write_only(a.private,prior.canonical(private))
    print(json.dumps({'decision':out['decision'],
                      'physical_head_optimizer_updates':out['physical_head_optimizer_updates'],
                      'prospective_future_windows':0,'production_authorized':False},sort_keys=True))


if __name__=='__main__':main()
