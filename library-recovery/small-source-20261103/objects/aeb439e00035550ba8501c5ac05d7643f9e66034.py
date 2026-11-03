"""V34: physically separate original Cell0-only stage1 and later Cell1 adaptation.

Stage1 sees only four sealed 24×384 old-source capsules, not the original
64-TRAIN file nor Cell1's unlabeled feature matrix. This is data staging and
process separation, not prospective evaluation or an independent source owner.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path

import numpy as np
from safetensors.numpy import load as load_numpy, save as save_numpy
import torch

import v32_original_cell_learning as base
import v33_fold_disjoint_training as prior

SCHEMA = 'hepta.stem.v34.old-only-process-separated.v1'
STEPS = base.STEPS
SEEDS = base.SEEDS
ARMS = base.ARMS


def old_scaler(raw: np.ndarray):
    """No Cell1 or held Cell0 statistics; only the 24 old input rows."""
    base.require(isinstance(raw, np.ndarray) and raw.dtype == np.float32
                 and raw.shape == (24, base.WIDTH) and np.isfinite(raw).all(),
                 'stage1 must have exactly 24 old-only pretrained features')
    mean = raw.mean(0).astype('<f4')
    scale = np.maximum(raw.std(0), np.float32(0.1)).astype('<f4')
    base.require(np.isfinite(mean).all() and np.isfinite(scale).all()
                 and bool((scale >= np.float32(0.1)).all()),
                 'nonfinite old-only normalization')
    return mean, scale, base.sha(mean.tobytes() + scale.tobytes())


def capsule_paths(root: Path, fid: int):
    base.require(type(fid) is int and fid in range(4), 'invalid fold')
    return root / f'old-fold-{fid}.safetensors', root / f'old-fold-{fid}.json'


def project_old_only(source: Path, destination: Path):
    """Projection process alone may read the complete original TRAIN material."""
    raw, rows, _ = prior.original(source)
    base.require(not destination.exists() and not destination.is_symlink(),
                 'project output must be create-only')
    destination.mkdir(mode=0o700)
    folds = base.split_folds(rows)
    summary = []
    for fid, held in enumerate(folds):
        old = [i for i, r in enumerate(rows) if r['cell'] == 0 and i not in set(held)]
        new = [i for i, r in enumerate(rows) if r['cell'] == 1 and i not in set(held)]
        base.require(len(old) == len(new) == 24 and len(held) == 16,
                     'original 24+24 /16 fold membership changed')
        tensor = save_numpy({'features': raw[old].astype('<f4').copy()})
        record = {'schema': SCHEMA + '.old-source', 'fold': fid,
                  'original_source_sha256': base.STAGED_SOURCE_SHA,
                  'original_feature_sha256': base.STAGED_TRAIN_FEATURE_SHA,
                  'train_count': 24, 'feature_width': base.WIDTH,
                  'source_cell': 0, 'original_cell1_count_visible_to_model': 0,
                  'original_held_count_visible_to_model': 0,
                  'features_sha256': base.sha(tensor),
                  'old_rows': [{k: rows[i][k] for k in ('case_id','group','cell','split','label')}
                               for i in old],
                  'future_windows': 0, 'production_authorized': False}
        features_path, metadata_path = capsule_paths(destination, fid)
        base.write_only(features_path, tensor)
        base.write_only(metadata_path, base.canonical(record))
        summary.append({'fold': fid, 'features_sha256': base.sha(tensor),
                        'metadata_sha256': base.sha(base.canonical(record))})
    base.write_only(destination/'capsule-index.json', base.canonical({
        'schema': SCHEMA + '.capsule-index', 'source_sha256': base.STAGED_SOURCE_SHA,
        'folds': summary, 'model_visible_new_cell_features': False,
        'model_visible_hold_features': False, 'production_authorized': False}))
    return summary


def load_capsules(root: Path):
    """Exact exclusive directory census so hidden additional inputs fail closed."""
    base.require(root.is_dir() and not root.is_symlink(), 'old-only capsule directory missing')
    expected = {'capsule-index.json'}
    for fid in range(4):
        a, b = capsule_paths(root, fid)
        expected.update({a.name, b.name})
    base.require({p.name for p in root.iterdir()} == expected
                 and all(p.is_file() and not p.is_symlink() for p in root.iterdir()),
                 'extra original-feature or new-Cell input in stage1 directory')
    idx = base.strict_json(base.verified_file(root/'capsule-index.json'))
    base.require(idx.get('schema') == SCHEMA + '.capsule-index'
                 and idx.get('source_sha256') == base.STAGED_SOURCE_SHA
                 and idx.get('model_visible_new_cell_features') is False
                 and idx.get('model_visible_hold_features') is False
                 and idx.get('production_authorized') is False
                 and type(idx.get('folds')) is list and len(idx['folds']) == 4,
                 'untrusted capsule index')
    result = []
    ids = set()
    for fid in range(4):
        fe, me = capsule_paths(root, fid)
        feature_raw, meta_raw = base.verified_file(fe), base.verified_file(me)
        item = base.strict_json(meta_raw)
        base.require(item.get('schema') == SCHEMA + '.old-source'
                     and item.get('fold') == fid
                     and item.get('train_count') == 24
                     and item.get('feature_width') == base.WIDTH
                     and item.get('original_source_sha256') == base.STAGED_SOURCE_SHA
                     and item.get('original_feature_sha256') == base.STAGED_TRAIN_FEATURE_SHA
                     and item.get('source_cell') == 0
                     and item.get('original_cell1_count_visible_to_model') == 0
                     and item.get('original_held_count_visible_to_model') == 0
                     and item.get('future_windows') == 0
                     and item.get('production_authorized') is False
                     and item.get('features_sha256') == base.sha(feature_raw)
                     and idx['folds'][fid] == {'fold': fid,
                            'features_sha256': base.sha(feature_raw),
                            'metadata_sha256': base.sha(meta_raw)},
                     'capsule is not original immutable old-only source')
        rows = item.get('old_rows')
        base.require(type(rows) is list and len(rows) == 24
                     and all(type(r) is dict and set(r) ==
                             {'case_id','group','cell','split','label'}
                             and r['cell'] == 0 and r['split'] == 'train'
                             and type(r['label']) is int and 0 <= r['label'] < 4
                             for r in rows)
                     and len({r['case_id'] for r in rows}) == 24
                     and len({r['group'] for r in rows}) == 24,
                     'unapproved Cell1/withheld original rows in capsule')
        t = load_numpy(feature_raw)
        base.require(set(t) == {'features'} and t['features'].dtype == np.float32
                     and t['features'].shape == (24,base.WIDTH)
                     and np.isfinite(t['features']).all(), 'not original old-only features')
        mean, scale, scaler_sha = old_scaler(t['features'])
        result.append((item, t['features'], mean, scale, scaler_sha))
        ids.update(r['case_id'] for r in rows)
    base.require(len(ids) == 32, 'old-only fold source identity union must cover 32 originals')
    return result


def fit_old_only(capsules: Path, output: Path):
    """Entire stage1 process loads only old features, old labels and fixed code."""
    base.require(not output.exists() and not output.is_symlink(),
                 'stage1 checkpoint output must be create-only')
    folds = load_capsules(capsules)
    torch.use_deterministic_algorithms(True)
    observations = []
    for seed in SEEDS:
        for fid, (item, original, mean, scale, stat_sha) in enumerate(folds):
            x = torch.from_numpy(((original-mean)/scale).astype('<f4').copy())
            y = torch.tensor([r['label'] for r in item['old_rows']],dtype=torch.long)
            model = base.head()
            meter = base.fit(model, x, y, seed=seed*1000+fid*10, cell=0)
            state = base.state(model)
            observations.append({'seed':seed, 'fold':fid,
                'old_train_case_ids': [r['case_id'] for r in item['old_rows']],
                'old_capsule_sha256': item['features_sha256'],
                'old_scaler_sha256':stat_sha,
                'weights':state,
                'weights_sha256':base.sha(model.weight.detach().numpy().astype('<f4').tobytes() +
                                           model.bias.detach().numpy().astype('<f4').tobytes()),
                'cost':meter,
                'new_cell_feature_rows_seen':0, 'held_feature_rows_seen':0})
    doc = {'schema': SCHEMA + '.stage1-old-only-checkpoints',
           'original_source_sha256':base.STAGED_SOURCE_SHA,
           'stage1_input_census':'FOUR_CAPSULES_24_OLD_ONLY',
           'seed_count':3,'fold_count':4, 'old_only_fit_rows_per_fold':24,
           'total_old_only_updates':len(observations)*STEPS,
           'new_cell_features_accessed_in_model_process':False,
           'held_features_accessed_in_model_process':False,
           'independent_future_windows':0, 'production_authorized':False,
           'records':observations}
    base.write_only(output,base.canonical(doc))
    return doc


def head_from_state(obj):
    base.require(type(obj) is dict and set(obj) == {'w','b'}, 'invalid old Head state')
    w, b = np.asarray(obj['w'], dtype='<f4'),np.asarray(obj['b'],dtype='<f4')
    base.require(w.shape==(4,base.WIDTH) and b.shape==(4,)
                 and np.isfinite(w).all() and np.isfinite(b).all(), 'wrong saved old Head shape')
    model=base.head()
    with torch.no_grad():
        model.weight.copy_(torch.from_numpy(w.copy()))
        model.bias.copy_(torch.from_numpy(b.copy()))
    return model


def adapt_and_compare(source: Path, capsules: Path, stage1_path: Path):
    """Stage2 is the FIRST model process with new Cell1 original features."""
    raw,rows,meta = prior.original(source)
    old_inputs = load_capsules(capsules)
    stage1 = base.strict_json(base.verified_file(stage1_path))
    base.require(stage1.get('schema') == SCHEMA + '.stage1-old-only-checkpoints'
                 and stage1.get('original_source_sha256') == base.STAGED_SOURCE_SHA
                 and stage1.get('stage1_input_census') == 'FOUR_CAPSULES_24_OLD_ONLY'
                 and stage1.get('old_only_fit_rows_per_fold') == 24
                 and stage1.get('total_old_only_updates') == 480
                 and stage1.get('seed_count') == 3 and stage1.get('fold_count') == 4
                 and stage1.get('new_cell_features_accessed_in_model_process') is False
                 and stage1.get('held_features_accessed_in_model_process') is False
                 and stage1.get('independent_future_windows') == 0
                 and stage1.get('production_authorized') is False,
                 'no authentically completed original old-only first phase')
    saved=stage1.get('records')
    base.require(type(saved) is list and len(saved) == 12, 'missing original stage1 checkpoints')
    stage_by={(r['seed'],r['fold']):r for r in saved}
    base.require(len(stage_by)==12, 'duplicate old-only checkpoint')
    folds=base.split_folds(rows)
    labels=torch.tensor([r['label'] for r in rows],dtype=torch.long)
    cells=torch.tensor([r['cell'] for r in rows],dtype=torch.long)
    torch.use_deterministic_algorithms(True)
    records=[];seeds={};stage2_updates=0
    for seed in SEEDS:
        per={arm:{0:[],1:[]} for arm in ARMS}
        for fid,held in enumerate(folds):
            hold=set(held)
            old=[i for i,r in enumerate(rows) if r['cell']==0 and i not in hold]
            new=[i for i,r in enumerate(rows) if r['cell']==1 and i not in hold]
            item,oldraw,mean,scale,statsha=old_inputs[fid]
            base.require([rows[i]['case_id'] for i in old] ==
                         [r['case_id'] for r in item['old_rows']]
                         and np.array_equal(raw[old],oldraw),
                         'new material tampered original stage1 Cell0 source')
            receipt=stage_by.get((seed,fid))
            base.require(type(receipt) is dict
                         and receipt.get('old_capsule_sha256') == item['features_sha256']
                         and receipt.get('old_scaler_sha256') == statsha
                         and receipt.get('old_train_case_ids') == [rows[i]['case_id'] for i in old]
                         and receipt.get('new_cell_feature_rows_seen') == 0
                         and receipt.get('held_feature_rows_seen') == 0,
                         'new/crossfold original material changed old-only stage1')
            model_old=head_from_state(receipt['weights'])
            w=model_old.weight.detach().numpy().astype('<f4')
            b=model_old.bias.detach().numpy().astype('<f4')
            base.require(base.sha(w.tobytes()+b.tobytes())==receipt['weights_sha256']
                         and receipt['cost']['updates']==STEPS
                         and receipt['cost']['source_cell']==0
                         and receipt['cost']['batch']==base.BATCH
                         and receipt['cost']['source_examples_seen']==STEPS*base.BATCH
                         and type(receipt['cost']['cpu_ns']) is int and receipt['cost']['cpu_ns']>0,
                         'unverified stage1 real optimizer/weight receipt')
            # Apply frozen Old-only scaler to ALL subsequent data. No refit on
            # new Cell1 features, not even after Cell1 observations arrive.
            normalized=((raw-mean)/scale).astype('<f4')
            base.require(np.isfinite(normalized).all(), 'nonfinite future transformed features')
            x=torch.from_numpy(normalized.copy())
            keep=deepcopy(model_old)
            continued=deepcopy(model_old)
            replay=deepcopy(model_old)
            clock_continue=base.fit(continued,x[new],labels[new],
                                    seed=seed*1000+fid*10+1,cell=1)
            clock_replay=base.fit(replay,x[new],labels[new],
                                    seed=seed*1000+fid*10+1,cell=None,
                                    replay=(x[old],labels[old],x[new],labels[new]))
            stage2_updates += clock_continue['updates'] + clock_replay['updates']
            outputs=base.forward_matrix((keep,continued,continued,replay),x[held],cells[held])
            for arm,preds in outputs.items():
                for c in (0,1):
                    indices=[j for j,i in enumerate(held) if rows[i]['cell']==c]
                    per[arm][c].append((preds[indices].detach().cpu(),
                                        labels[[held[j] for j in indices]]))
            record={'seed':seed,'fold':fid,
                'old_train_case_ids':[rows[i]['case_id'] for i in old],
                'new_train_case_ids':[rows[i]['case_id'] for i in new],
                'held_case_ids':[rows[i]['case_id'] for i in held],
                'old_stage1_receipt_sha256':base.sha(base.canonical(receipt)),
                'old_only_scaler_sha256':statsha,
                'old_scaler_refit_after_new_data':False,
                'states':{k:base.state(m) for k,m in [('old',keep),('continued',continued),
                                                    ('new',continued),('rehearsal',replay)]},
                'weights_sha256':{k:base.sha(m.weight.detach().numpy().astype('<f4').tobytes()+
                                             m.bias.detach().numpy().astype('<f4').tobytes())
                                   for k,m in [('old',keep),('continued',continued),
                                               ('new',continued),('rehearsal',replay)]},
                'logits':{k:v.detach().cpu().numpy().astype('<f4').tolist()
                          for k,v in outputs.items()},
                'logits_sha256':{k:base.sha(v.detach().cpu().numpy().astype('<f4').tobytes())
                                 for k,v in outputs.items()},
                'cost':{'old':receipt['cost'],'continued':clock_continue,'rehearsal':clock_replay},
                'shared_old_head_state':True,'split_reuses_continued':True}
            records.append(record)
        arms={}
        for arm in ARMS:
            scored={}
            for c in (0,1):
                prediction=torch.cat([t for t,_ in per[arm][c]])
                targets=torch.cat([t for _,t in per[arm][c]])
                base.require(len(targets)==32, 'incomplete old/new held original TRAIN groups')
                scored[c]=base.score(prediction,targets)
            arms[arm]={'cell0_old_oof':scored[0],'cell1_new_oof':scored[1],
                       'total_correct':scored[0]['correct']+scored[1]['correct'],
                       'total_cases':64}
        seeds[str(seed)]=arms
    base.require(stage2_updates==len(SEEDS)*base.FOLDS*2*STEPS,
                 'missing live stage2 training updates')
    output={'schema':SCHEMA+'.public',
            'original_archive_sha256':base.ARCHIVE_SHA,
            'original_pretrained_feature_sha256':base.FEATURE_SHA,
            'original_v32_staged_source_sha256':base.STAGED_SOURCE_SHA,
            'original_train_feature_sha256':base.STAGED_TRAIN_FEATURE_SHA,
            'stage1_input_census':'FOUR_CAPSULES_24_OLD_ONLY',
            'stage1_preprocessing_fitted_old_only':True,
            'stage1_new_cell_feature_exposure':0,
            'old_scaler_refit_after_new_cell':False,
            'old_task_independent_future':False,
            'old_task_retention_frozen_baseline':'NOCHANGE_OLD_HEAD',
            'new_cell_labelled_train_rows_per_fold':24,
            'old_cell_labelled_train_rows_per_fold':24,
            'held_new_old_original_train_each_fold':[8,8],
            'original_source_family_count':1,'independent_future_windows':0,
            'new_encoder_forwards':0,'physical_head_optimizer_updates_paid':480+stage2_updates,
            'stage1_optimizer_updates':480,'stage2_optimizer_updates':stage2_updates,
            'head_parameters_per_cell':1540,'two_head_parameters':3080,
            'source_blind_ensemble_evaluates_two_heads_per_request':True,
            'split_and_ensemble_share_exact_head_weights':True,
            'per_seed':seeds,
            'independent_prospective_utility':None,
            'negative_transfer_on_new_sources':None,
            'matched_end_to_end_lifecycle_cpu':None,
            'production_authorized':False,'model_selection_authorized':False,
            'ndu_selector_authorized':False,'cell_split_authorized':False,
            'final_use_authorized':False,'authority':'DENY_ALL',
            'decision':'HOLD_OLD_ONLY_STAGE1_NO_PROSPECTIVE_SELECTION'}
    private={'schema':SCHEMA+'.private-stage2',
             'original_source_sha256':base.STAGED_SOURCE_SHA,
             'stage1_checkpoint_sha256':base.sha(base.canonical(stage1)),
             'records':records, 'calibration_or_blind_labels_present':False,
             'research_only':True,'new_cell_source_in_stage1_process':False}
    return output,private


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('project-old')
    a.add_argument('--source',required=True,type=Path);a.add_argument('--out',required=True,type=Path)
    a=sub.add_parser('train-old')
    a.add_argument('--old-capsules',required=True,type=Path);a.add_argument('--out',required=True,type=Path)
    a=sub.add_parser('adapt')
    a.add_argument('--source',required=True,type=Path);a.add_argument('--old-capsules',required=True,type=Path)
    a.add_argument('--stage1',required=True,type=Path)
    a.add_argument('--public',required=True,type=Path);a.add_argument('--private',required=True,type=Path)
    args=p.parse_args()
    if args.cmd=='project-old':
        project_old_only(args.source,args.out)
        print(json.dumps({'decision':'OLD_ONLY_PROJECTED','old_train_rows_per_fold':24,'new_cell_exposed_to_stage1_model':False}))
    elif args.cmd=='train-old':
        fit_old_only(args.old_capsules,args.out)
        print(json.dumps({'decision':'STAGE1_SEALED','old_optimizer_updates':480,'authority':'DENY_ALL'}))
    else:
        base.require(not args.public.exists() and not args.private.exists(),'create-only result outputs')
        report,private=adapt_and_compare(args.source,args.old_capsules,args.stage1)
        base.write_only(args.public,base.canonical(report))
        base.write_only(args.private,base.canonical(private))
        print(json.dumps({'decision':report['decision'],'total_updates':report['physical_head_optimizer_updates_paid'],
                          'production_authorized':False}))


if __name__=='__main__':main()
