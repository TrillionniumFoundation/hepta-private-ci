"""Open new evaluation labels only after frozen candidates replay in this process."""

import argparse
import json
from pathlib import Path

import numpy as np

from bounded_text_inputs import canonical
from cell_learning_metrics import task_metrics
from cell_learning_models import NumpyCellHead
from fit_input_coverage import load_inputs, sha_file
from prepare_input_coverage import TASKS


def paired_contrast(records, predictions, labels, *, left, right, budget=128):
    differences, ys = [], []
    for task in TASKS:
        task_difference = []
        for seed in (7, 17, 29):
            matches = []
            for policy, arm in (left, right):
                match = [i for i, r in enumerate(records) if (r['task'], r['seed'], r['budget'], r['policy'], r['arm'])
                         == (task, seed, budget, policy, arm)]
                if len(match) != 1:
                    return {'status': 'unavailable', 'reason': 'a fixed task/seed/method is unavailable'}
                matches.append(predictions[match[0]].argmax(axis=1) == labels[task])
            task_difference.append(matches[0].astype(float) - matches[1].astype(float))
        if set(labels[task]) != {0, 1}:
            return {'status': 'unavailable', 'reason': 'a fixed task lacks both evaluation classes'}
        differences.append(np.mean(task_difference, axis=0))
        ys.append(labels[task])

    def statistic(indices):
        values = []
        for d, y in zip(differences, ys, strict=True):
            selected_y, selected_d = y[indices], d[indices]
            if set(selected_y) != {0, 1}:
                return None
            values.append(0.5 * (selected_d[selected_y == 0].mean() + selected_d[selected_y == 1].mean()))
        return float(np.mean(values))

    rng, draws, rejected = np.random.default_rng(20261024), [], 0
    while len(draws) < 2000 and rejected < 10000:
        value = statistic(rng.integers(0, len(ys[0]), len(ys[0])))
        if value is None:
            rejected += 1
        else:
            draws.append(value)
    if len(draws) != 2000:
        return {'status': 'unavailable', 'reason': 'insufficient valid paired source-group bootstrap draws'}
    lower, upper = np.quantile(draws, [0.025, 0.975])
    point = statistic(np.arange(len(ys[0])))
    return {'status': 'measured', 'difference': point, 'ci95': [float(lower), float(upper)],
            'positive_interval': bool(lower > 0), 'negative_interval': bool(upper < 0),
            'paired_source_group_draws': 2000, 'rejected_absent_class_draws': rejected,
            'conditioning': 'fixed historical tasks, training sources, seeds, and fitted states',
            'left': list(left), 'right': list(right), 'budget': budget}


def score(dataset, features, fitted, output):
    dataset, features, fitted, output = map(Path, (dataset, features, fitted, output))
    if output.exists():
        raise ValueError('new score directory required; never overwrite exposed evaluation')
    rows, manifest, feature_report, matrices = load_inputs(dataset, features)
    plan = json.loads((fitted / 'fit_manifest.json').read_text())
    if (plan['dataset_manifest_sha256'] != sha_file(dataset / 'manifest.json')
            or plan['feature_report_sha256'] != sha_file(features / 'report.json')):
        raise ValueError('frozen fitting plan changed its data or features')
    for relative, expected in plan['files'].items():
        path = fitted / relative
        if path.is_symlink() or '..' in Path(relative).parts or sha_file(path) != expected:
            raise ValueError('fitted artifact changed: ' + relative)
    with np.load(fitted / 'predictions.npz', allow_pickle=False) as archive:
        predictions = archive['evaluation']
    evaluation_rows = [i for i, row in enumerate(rows) if row['split'] == 'evaluation']
    if plan['evaluation_source_ids'] != [rows[i]['source_id'] for i in evaluation_rows]:
        raise ValueError('evaluation source order changed')
    replayed = 0
    for case in plan['cases']:
        head = NumpyCellHead.load(fitted / 'cases' / case['case'] / 'head',
                                  feature_report['identities'][case['policy']])
        replay = head.predict_proba(matrices[case['policy']][evaluation_rows], case['head']['temperature'])
        indices = [i for i, record in enumerate(plan['records'])
                   if record['case'] == case['case'] and record['arm'] == 'linear']
        if len(indices) != 1 or not np.array_equal(replay, predictions[indices[0]]):
            raise ValueError('independent-process frozen Head replay differs')
        replayed += 1
    # This is the first parsing of evaluation labels by the fit/score pipeline.
    evaluation_path = dataset / 'evaluation_labels.json'
    if sha_file(evaluation_path) != manifest['files'][evaluation_path.name]:
        raise ValueError('frozen evaluation labels changed')
    values = json.loads(evaluation_path.read_text())
    if [row['source_id'] for row in values] != plan['evaluation_source_ids']:
        raise ValueError('evaluation labels do not match prediction identities')
    labels = {task: np.asarray([r['labels'][task] for r in values]) for task in TASKS}
    scored = [{**record, 'evaluation_metrics': task_metrics(predictions[i], labels[record['task']])}
              for i, record in enumerate(plan['records'])]
    summaries = []
    for policy in ('prefix', 'head_tail'):
        for budget in (32, 128):
            for arm in ('linear', 'prototype', 'dense_topk', 'bm25_topk', 'class_prior', 'untrained', 'off'):
                chosen = [r['evaluation_metrics'] for r in scored if (r['policy'], r['budget'], r['arm']) == (policy, budget, arm)]
                summaries.append({'policy': policy, 'budget': budget, 'arm': arm, 'fixed_task_seed_rows': len(chosen),
                    **{metric: (float(np.mean([m[metric] for m in chosen]))
                                if chosen and all(m[metric] is not None for m in chosen) else None) for metric in
                       ('balanced_accuracy', 'forced_accuracy', 'positive_recall', 'nll', 'coverage', 'overall_success')}})
    primary = paired_contrast(plan['records'], predictions, labels,
                              left=('head_tail', 'linear'), right=('prefix', 'linear'))
    secondary = [paired_contrast(plan['records'], predictions, labels, left=('head_tail', 'linear'),
                                right=('head_tail', arm)) for arm in ('prototype', 'dense_topk', 'bm25_topk')]
    report = {'schema': 'hepta.input-coverage-score.v1', 'authority': 'DENY_ALL',
        'fit_manifest_sha256': sha_file(fitted / 'fit_manifest.json'),
        'independent_process_head_replays': replayed, 'all_replays_bitwise_equal': True,
        'source_groups': len(evaluation_rows), 'task_count': len(plan['available_tasks']),
        'primary': primary, 'descriptive_secondary_contrasts_unadjusted': secondary,
        'summaries': summaries, 'records': scored, 'feature_cost': feature_report,
        'fitting_cost': plan['cost'], 'score_source_sha256': sha_file(Path(__file__)),
        'exposed_evaluation_must_not_be_reused_as_fresh_acceptance': True,
        'claims_not_established': ['future qualification', 'autonomous repair quality', 'cell split benefit',
                                   'learned edge benefit', 'production or general intelligence']}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'results.json').write_bytes(canonical(report) + b'\n')
    print(json.dumps({'stage': 'scored', 'primary': primary, 'summaries': summaries,
                      'replayed_heads': replayed, 'result_sha256': sha_file(output / 'results.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'features', 'fitted', 'output'):
        parser.add_argument('--' + name, required=True)
    score(**vars(parser.parse_args()))
