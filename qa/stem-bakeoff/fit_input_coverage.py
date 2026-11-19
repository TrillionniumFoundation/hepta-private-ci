"""Fit fixed small Heads and strong source controls without reading test labels."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from bounded_text_inputs import canonical
from cell_learning_metrics import calibrate_temperature, probabilities, task_metrics
from cell_learning_models import NumpyCellHead
from coverage_retrieval import CoverageRetrieval
from prepare_input_coverage import TASKS


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_inputs(dataset, features):
    dataset, features = Path(dataset), Path(features)
    manifest = json.loads((dataset / 'manifest.json').read_text())
    if sha_file(dataset / 'predictors.json') != manifest['files']['predictors.json']:
        raise ValueError('frozen predictor bytes changed')
    rows = json.loads((dataset / 'predictors.json').read_text())
    report = json.loads((features / 'report.json').read_text())
    if sha_file(features / 'features.npz') != report['files']['features.npz']:
        raise ValueError('frozen features changed')
    matrices = {}
    with np.load(features / 'features.npz', allow_pickle=False) as archive:
        if set(archive.files) != {'prefix', 'head_tail'}:
            raise ValueError('both predeclared input policies required')
        for policy in archive.files:
            if report['identities'][policy]['dataset_manifest_sha256'] != sha_file(dataset / 'manifest.json'):
                raise ValueError('feature identity differs from selected source groups')
            matrices[policy] = archive[policy]
            if matrices[policy].shape != (896, 1024) or not np.isfinite(matrices[policy]).all():
                raise ValueError('fixed finite feature dimensions required')
    return rows, manifest, report, matrices


def labels_for(dataset, manifest, rows, split):
    if split not in ('train', 'calibration'):
        raise ValueError('fitter may read only train and calibration labels')
    path = Path(dataset) / (split + '_labels.json')
    if sha_file(path) != manifest['files'][path.name]:
        raise ValueError('frozen labels changed')
    values = json.loads(path.read_text())
    expected = [r['source_id'] for r in rows if r['split'] == split]
    if [r['source_id'] for r in values] != expected:
        raise ValueError('label row identity differs from predictor order')
    return {task: np.asarray([r['labels'][task] for r in values], dtype=np.int64) for task in TASKS}


def balanced_order(labels, seed):
    rng = np.random.default_rng(seed)
    groups = [rng.permutation(np.flatnonzero(labels == label)) for label in (0, 1)]
    if min(map(len, groups)) < 64:
        raise ValueError('fixed balanced 128-source training budget unavailable')
    return np.asarray([index for pair in zip(groups[0][:64], groups[1][:64], strict=True) for index in pair])


def fit(dataset, features, output):
    dataset, features, output = Path(dataset), Path(features), Path(output)
    rows, manifest, feature_report, matrices = load_inputs(dataset, features)
    train_labels = labels_for(dataset, manifest, rows, 'train')
    calibration_labels = labels_for(dataset, manifest, rows, 'calibration')
    indices = {split: np.asarray([i for i, r in enumerate(rows) if r['split'] == split])
               for split in ('train', 'calibration', 'evaluation')}
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    records, predictions, calibration_predictions, cases = [], [], [], []
    available = [task for task in TASKS if manifest['task_availability'][task]['available']]
    if not available:
        raise ValueError('no predeclared task supports its training budget; no substitute selected')
    for task in available:
        for seed in (7, 17, 29):
            order = balanced_order(train_labels[task], seed)
            for budget in (32, 128):
                chosen = indices['train'][order[:budget]]
                y = train_labels[task][order[:budget]]
                cal_y = calibration_labels[task]
                train_texts = [rows[i]['text'] for i in chosen]
                cal_texts = [rows[i]['text'] for i in indices['calibration']]
                eval_texts = [rows[i]['text'] for i in indices['evaluation']]
                prior_positive = (float(cal_y.sum()) + 0.5) / (len(cal_y) + 1)
                for policy in ('prefix', 'head_tail'):
                    x = matrices[policy]
                    slug = f'{task}-s{seed}-n{budget}-{policy}'
                    case_root = output / 'cases' / slug
                    case_root.mkdir(parents=True)
                    head = NumpyCellHead(1024, 2, mode='linear', seed=seed)
                    before = head.digest()
                    arms = {}
                    for split in ('calibration', 'evaluation'):
                        arms.setdefault('untrained', {})[split] = head.predict_proba(x[indices[split]])
                    head.train(x[chosen], y, steps=200, learning_rate=0.02, l2=0.001)
                    temperature, temp_report = calibrate_temperature(head.predict_logits(x[indices['calibration']]), cal_y)
                    head.save(case_root / 'head', feature_report['identities'][policy])
                    head_report = {'temperature': temperature, 'calibration': temp_report,
                                   'initial_sha256': before, 'training': head.report}
                    arms['linear'] = {split: head.predict_proba(x[indices[split]], temperature)
                                      for split in ('calibration', 'evaluation')}
                    control = CoverageRetrieval(x[chosen], y, train_texts)
                    control_reports = {}
                    for arm in ('dense_topk', 'bm25_topk'):
                        cal_similarity, cal_cost = control.similarities(arm, x[indices['calibration']], cal_texts)
                        selected = control.calibrate(cal_similarity, cal_y)
                        eval_similarity, eval_cost = control.similarities(arm, x[indices['evaluation']], eval_texts)
                        arms[arm] = {'calibration': control.predict(cal_similarity, selected),
                                     'evaluation': control.predict(eval_similarity, selected)}
                        control_reports[arm] = {'calibration': selected, 'calibration_query_cost': cal_cost,
                                                'evaluation_query_cost': eval_cost}
                    proto_t, proto_report = calibrate_temperature(control.prototype_logits(x[indices['calibration']]), cal_y)
                    arms['prototype'] = {split: probabilities(control.prototype_logits(x[indices[split]]), proto_t)
                                          for split in ('calibration', 'evaluation')}
                    control_reports['prototype'] = {'temperature': proto_t, 'calibration': proto_report}
                    for arm, vector in (('off', [0.5, 0.5]), ('class_prior', [1 - prior_positive, prior_positive])):
                        arms[arm] = {split: np.tile(vector, (len(indices[split]), 1))
                                     for split in ('calibration', 'evaluation')}
                    with (case_root / 'retrieval.npz').open('xb') as stream:
                        np.savez_compressed(stream, features=control.x, labels=control.y,
                                            centroids=control.centroids, source_indices=chosen)
                    with gzip.open(case_root / 'bm25_index.json.gz', 'wt', encoding='utf-8') as stream:
                        json.dump({token: [idx.tolist(), weight.tolist()] for token, (idx, weight) in control.postings.items()}, stream,
                                  ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                    case = {'case': slug, 'task': task, 'seed': seed, 'budget': budget, 'policy': policy,
                            'training_source_ids': [rows[i]['source_id'] for i in chosen],
                            'head': head_report, 'controls': control_reports,
                            'control_fit_cost': control.fit_cost, 'control_memory': control.memory}
                    (case_root / 'case.json').write_bytes(canonical(case) + b'\n')
                    cases.append(case)
                    for arm, values in arms.items():
                        records.append({'case': slug, 'task': task, 'seed': seed, 'budget': budget,
                                        'policy': policy, 'arm': arm,
                                        'calibration_metrics': task_metrics(values['calibration'], cal_y)})
                        predictions.append(values['evaluation'])
                        calibration_predictions.append(values['calibration'])
                print(json.dumps({'stage': 'fitting', 'task': task, 'seed': seed, 'budget': budget,
                                  'cases_saved': len(cases)}), flush=True)
    with (output / 'predictions.npz').open('xb') as stream:
        np.savez_compressed(stream, evaluation=np.stack(predictions), calibration=np.stack(calibration_predictions))
    plan = {'schema': 'hepta.input-coverage-fit.v1', 'authority': 'DENY_ALL',
        'dataset_manifest_sha256': sha_file(dataset / 'manifest.json'),
        'feature_report_sha256': sha_file(features / 'report.json'),
        'available_tasks': available, 'all_predeclared_tasks': list(TASKS),
        'evaluation_source_ids': [rows[i]['source_id'] for i in indices['evaluation']],
        'evaluation_labels_parsed_by_fitter': False, 'evaluation_predictions_saved_before_scoring': True,
        'records': records, 'cases': cases,
        'cost': {'wall_ns': time.perf_counter_ns() - started, 'cpu_ns': time.process_time_ns() - cpu_started,
                 'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                 'head_training_wall_ns': sum(c['head']['training']['wall_ns'] for c in cases),
                 'head_example_updates': sum(c['head']['training']['example_updates'] for c in cases),
                 'encoder_calls': 0},
        'files': {str(p.relative_to(output)): sha_file(p) for p in sorted(output.rglob('*')) if p.is_file()},
        'source_code_sha256': {p.name: sha_file(p) for p in [Path(__file__), *[Path(__file__).with_name(name)
                for name in ('coverage_retrieval.py', 'cell_learning_models.py', 'cell_learning_metrics.py')]]}}
    (output / 'fit_manifest.json').write_bytes(canonical(plan) + b'\n')
    print(json.dumps({'stage': 'all_candidates_frozen', 'cases': len(cases), 'predictions': len(records),
                      'fit_manifest_sha256': sha_file(output / 'fit_manifest.json'), 'cost': plan['cost']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'features', 'output'):
        parser.add_argument('--' + name, required=True)
    fit(**vars(parser.parse_args()))
