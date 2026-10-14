"""Independent NumPy replay and retrospective scoring for E2 real feature sweep.

Does not import Torch, Head fitter or E2 training module. Checks every saved
checkpoint/row and original physical Encoder feature identity before scoring.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import math

import numpy as np
from safetensors.numpy import load

from experiments.shared_stem_cell.physical_head_replay import replay
from experiments.shared_stem_cell.preflight_review import checked_bytes, require
from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

SCHEMA = 'hepta.stem.e2-modern-budget-sweep.v2'
MODEL_ID = 'answerdotai/ModernBERT-base'
MODEL_REVISION = 'fa3113d09d6dacfe5528708803dd92a62240237a'
BUDGETS = (2048, 8192, 16384, 65536, 262144)
SEEDS = (11, 23, 47)


def independent_probabilities(features: np.ndarray, tensors: dict, width: int, classes: int, rank: int):
    specs = {'down.weight': (rank, width), 'down.bias': (rank,),
             'up.weight': (classes, rank), 'up.bias': (classes,)}
    require(set(tensors) == set(specs)
            and all(tensors[k].shape == v and tensors[k].dtype == np.float32
                    and bool(np.isfinite(tensors[k]).all()) for k, v in specs.items()),
            'checkpoint tensor identity/type/dimensions invalid')
    hidden = np.tanh(features @ tensors['down.weight'].T + tensors['down.bias'])
    logits = hidden @ tensors['up.weight'].T + tensors['up.bias']
    logits -= logits.max(axis=-1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=-1, keepdims=True)


def _truth(root, plan):
    raw = checked_bytes(root / plan['dataset']['path'], plan['dataset']['sha256'])
    rows = [decode(line) for line in raw.splitlines()]
    require(len(rows) == 128 and len({r['case_id'] for r in rows}) == len(rows),
            'source case census drift')
    return rows


def review_sweep(manifest_path: Path, producer: Path, report_sha256: str, sweep: Path) -> dict:
    source = replay(manifest_path, producer, report_sha256)
    plan = decode(checked_bytes(manifest_path))
    data = _truth(manifest_path.parent, plan)
    report = decode(checked_bytes(producer / 'report.json', report_sha256))
    archive = decode(checked_bytes(producer / 'frozen-features/manifest.json',
                                   report['frozen_features']['manifest_sha256']))
    feature_raw = checked_bytes(producer / 'frozen-features/features.safetensors', archive['file_sha256'])
    f = load(feature_raw)
    require(set(f) == {'features'} and f['features'].shape == (128, 768)
            and f['features'].dtype == np.float32, 'physical features missing')
    features = f['features']
    actual = decode(checked_bytes(sweep / 'run.json'))
    require(actual.get('schema') == SCHEMA and actual.get('origin') == 'real_pretrained_cached_features'
            and actual.get('source_report_sha256') == report_sha256
            and actual.get('source_feature_manifest_sha256') == report['frozen_features']['manifest_sha256']
            and actual.get('dataset_sha256') == plan['dataset']['sha256']
            and actual.get('stem_sha256') == source['model_manifest_sha256']
            and actual.get('feature_width') == 768
            and actual.get('encoder_id') == MODEL_ID
            and actual.get('encoder_revision') == MODEL_REVISION
            and plan.get('model', {}).get('model_id') == MODEL_ID
            and plan['model'].get('revision') == MODEL_REVISION
            and actual.get('classes') == 4
            and actual.get('cells') == 2 and actual.get('budgets') == list(BUDGETS)
            and actual.get('seeds') == list(SEEDS) and actual.get('train_steps') == 20
            and actual.get('training_batch_size') == 16
            and actual.get('architecture') == 'factorized_tanh_no_dense_base'
            and actual.get('production_accepted') is False
            and actual.get('future_ndu_evaluated') is False,
            'E2 evidence identity or authority drift')
    stored = decode(checked_bytes(sweep / 'predictions.json', actual['predictions_sha256']))
    require(stored.get('schema') == SCHEMA and type(stored.get('predictions')) is list,
            'sealed E2 predictions absent')
    index = {}
    for r in stored['predictions']:
        require(type(r) is dict and set(r) == {'seed','ceiling','cell','role','case_id','scope',
                                               'split','group','input_sha256','probabilities'},
                'invalid E2 prediction shape')
        key = (r['seed'], r['ceiling'], r['cell'], r['role'], r['case_id'])
        require(key not in index and r['role'] in ('trained','frozen'), 'duplicate/unknown Head role')
        p = r['probabilities']
        require(type(p) is list and len(p) == 4 and all(type(x) in (float,int)
                and math.isfinite(x) and 0 <= x <= 1 for x in p)
                and abs(math.fsum(p)-1) <= 1e-5, 'untrusted E2 probability vector')
        index[key] = r
    original = decode(checked_bytes(producer / 'predictions.json', report['predictions_sha256']))
    original_linear = {(x['case_id'], x['arm']): x for x in original['predictions']}
    expected_artifacts = {(seed, budget, cell) for seed in SEEDS for budget in BUDGETS for cell in (0,1)}
    rows = actual['artifacts']
    require(type(rows) is list and len(rows) == len(expected_artifacts)
            and {(r.get('seed'),r.get('ceiling'),r.get('cell')) for r in rows} == expected_artifacts,
            'incomplete E2 budget/seed/Cell census')
    seen_predictions = set()
    metrics = defaultdict(lambda: {'count':0,'correct':0,'brier':0.0,'paired_gains':0,
                                   'paired_losses':0,'linear_correct':0})
    minibatches = defaultdict(set)
    checkpoint_count = 0
    largest_error = 0.0
    for a in rows:
        seed, budget, cell = (a[k] for k in ('seed','ceiling','cell'))
        rank = (budget-4)//773
        params = rank*773+4
        require(a.get('rank') == rank and a.get('parameters') == params and params <= budget
                and a.get('training_steps') == 20 and a.get('examples_processed') == 320
                and type(a.get('minibatch_sha256')) is str and len(a['minibatch_sha256']) == 64,
                'E2 parameter or work accounting drift')
        minibatches[cell].add(a['minibatch_sha256'])
        ids = [i for i, r in enumerate(data) if r['cell'] == cell and r['split'] in ('calibration','holdout')]
        require(len(ids) == 32, 'Cell evaluation slice does not match frozen cohort')
        require(set(a.get('checkpoints', {})) == {'trained','frozen'}, 'missing Head checkpoint')
        loaded_probs={}
        for role in ('trained','frozen'):
            spec = a['checkpoints'][role]
            expected_path = f'heads/seed-{seed}/budget-{budget}/cell-{cell}/{role}.safetensors'
            require(type(spec) is dict and spec.get('path') == expected_path,
                    'path cannot redirect outside owned Head artifacts')
            raw = checked_bytes(sweep / expected_path, spec.get('sha256'))
            require(spec.get('file_bytes') == len(raw) and len(raw) < 2*1024*1024,
                    'Head checkpoint size or identity drift')
            try:
                weights = load(raw)
            except Exception as exc:
                raise ValueError('invalid sealed safetensors') from exc
            require(sum(x.size for x in weights.values()) == params,
                    'actual saved trainable parameters differ from manifest')
            expected = independent_probabilities(features[ids], weights, 768, 4, rank)
            loaded_probs[role] = expected
            checkpoint_count += 1
            for index_in_batch, i in enumerate(ids):
                item = data[i]
                key = (seed,budget,cell,role,item['case_id'])
                obs=index.get(key)
                require(obs is not None and obs['scope']==item['scope']
                        and obs['split']==item['split'] and obs['group']==item['group']
                        and obs['input_sha256']==sha(canonical([item['scope'],item['text']])),
                        'E2 case pairing drift')
                seen_predictions.add(key)
                discrepancy=float(np.max(np.abs(expected[index_in_batch]-np.asarray(obs['probabilities'],dtype=np.float32))))
                require(discrepancy <= 2e-5 and expected[index_in_batch].argmax() ==
                        np.argmax(np.asarray(obs['probabilities'])), 'Head checkpoint/prediction inconsistency')
                largest_error=max(largest_error,discrepancy)
        for index_in_batch,i in enumerate(ids):
            row=data[i]
            if row['split']!='holdout':continue
            y=row['label']; trained=loaded_probs['trained'][index_in_batch]
            frozen=loaded_probs['frozen'][index_in_batch]
            old=original_linear[(row['case_id'],'linear')]['probabilities']
            output=metrics[(budget,seed)]
            output['count'] +=1
            trained_correct=int(int(trained.argmax())==y)
            frozen_correct=int(int(frozen.argmax())==y)
            output['correct'] += trained_correct
            output['linear_correct'] +=int(int(np.argmax(old))==y)
            output['paired_gains'] += int(trained_correct > frozen_correct)
            output['paired_losses'] += int(trained_correct < frozen_correct)
            output['brier'] +=float(np.sum((trained-np.eye(4,dtype=np.float32)[y])**2))
    require(set(index)==seen_predictions and len(index)==3*5*64*2,
            'missing/unpaired/added E2 output observations')
    require(all(len(v)==1 for v in minibatches.values()),
            'unequal training sample streams across parameter budgets or seeds')
    scored=[]
    for (budget,seed), m in sorted(metrics.items()):
        require(m['count']==32,'holdout per-budget future-score count drift')
        scored.append({'ceiling':budget,'seed':seed,'actual_parameters_per_cell':
                       next(x['parameters'] for x in rows if x['ceiling']==budget),
                       'holdout_count':32,'trained_correct':m['correct'],
                       'original_linear_correct':m['linear_correct'],
                       'trained_accuracy':m['correct']/32,
                       'brier':m['brier']/32,
                       'trained_vs_frozen_gains':m['paired_gains'],
                       'trained_vs_frozen_losses':m['paired_losses']})
    return {'schema':'hepta.stem.e2-independent-review.v1',
            'source_report_sha256':report_sha256,
            'e2_run_sha256':sha(checked_bytes(sweep/'run.json')),
            'predictions_sha256':actual['predictions_sha256'],
            'physical_head_checkpoint_count':checkpoint_count,
            'independently_replayed_prediction_vectors':len(index),
            'max_prediction_abs_diff':largest_error,
            'minibatch_streams_same_across_budgets':True,
            'scored':scored,
            'original_linear_is_not_production_no_change':True,
            'independent_source_groups_verified':False,
            'future_ndu_evaluated':False,
            'e2_full_selection_qualified':False, 'two_encoder_joint_qualified':False,
            'production_accepted':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',type=Path,required=True)
    ap.add_argument('--producer',type=Path,required=True)
    ap.add_argument('--report-sha256',required=True)
    ap.add_argument('--sweep',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    q=ap.parse_args()
    out=review_sweep(q.manifest,q.producer,q.report_sha256,q.sweep)
    q.output.parent.mkdir(parents=True,exist_ok=True)
    write_once(q.output,out)


if __name__=='__main__':main()
