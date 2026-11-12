"""Read pinned development logits; report hard-prediction concentration only."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def invalid(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(raw, parse_constant=invalid)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metrics(logits, labels):
    require(len(logits) == len(labels) == 192, 'exact 192-query denominator required')
    predictions, losses, ties = [], [], 0
    for row, label in zip(logits, labels):
        require(len(row) == 8 and all(type(x) in (float, int) and math.isfinite(x) for x in row),
                'eight finite class logits required')
        require(type(label) is int and 0 <= label < 8, 'integer class label required')
        largest = max(row)
        predictions.append(max(range(8), key=lambda index: row[index]))
        ties += sum(x == largest for x in row) > 1
        losses.append(math.log(math.fsum(math.exp(x - largest) for x in row)) - (row[label] - largest))
    predicted = Counter(predictions)
    correct = Counter(p for p, y in zip(predictions, labels) if p == y)
    confusion = [[0] * 8 for _ in range(8)]
    for p, y in zip(predictions, labels):
        confusion[y][p] += 1
    return dict(query_count=len(labels), class_order=list(range(8)),
                prediction_counts=[predicted[k] for k in range(8)],
                correct_counts_by_predicted_class=[correct[k] for k in range(8)],
                label_counts=[labels.count(k) for k in range(8)],
                total_correct=sum(correct.values()), accuracy=sum(correct.values()) / len(labels),
                cross_entropy_nats=math.fsum(losses) / len(losses),
                unique_predicted_classes=len(predicted), all_queries_one_argmax=len(predicted) == 1,
                argmax_tie_rows=ties, argmax_tie_breaking='lowest class index',
                distinct_logit_vectors=len({tuple(row) for row in logits}),
                confusion_true_rows_predicted_columns=confusion)


def audit(command_path):
    started = time.perf_counter()
    command_raw = command_path.read_bytes()
    command = strict_json(command_raw)
    source_path = Path(__file__).resolve()
    source_before = digest(source_path.read_bytes())
    require(source_before == command['script_sha256'], 'executing script differs from launch pin')
    raw_inputs, parsed = {}, {}
    for role, identity in command['inputs'].items():
        path = Path(identity['path'])
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 4 * 1024**2,
                'bounded regular input required: ' + role)
        raw = path.read_bytes()
        require(digest(raw) == identity['sha256'], 'input differs from launch pin: ' + role)
        raw_inputs[role] = raw
        parsed[role] = strict_json(raw)
    h, g = parsed['hcsn_summary'], parsed['gru_summary']
    require(h['status'] == g['status'] == 'completed_pilot', 'both producer summaries must be complete')
    require(sorted((r['seed'], r['arm']) for r in h['runs']) ==
            sorted((seed, arm) for seed in (11, 23, 37)
                   for arm in ('c0_b0', 'c0_b1', 'c1_b0', 'c1_b1')), 'exact factorial roster required')
    require(sorted(r['seed'] for r in g['runs']) == [11, 23, 37], 'exact baseline roster required')
    require(h['data_sha256'] == g['inputs']['DATA.json']['sha256'] ==
            command['inputs']['hcsn_data']['sha256'] == command['inputs']['gru_data']['sha256'],
            'both producers and retained datasets must share one DATA identity')
    require(raw_inputs['hcsn_data'] == raw_inputs['gru_data'], 'retained DATA bytes differ')
    require(Path(g['inputs']['DATA.json']['path']).resolve() ==
            Path(command['inputs']['gru_data']['path']).resolve(), 'baseline DATA path differs from producer')
    data = parsed['hcsn_data']['development']
    expected_labels = [label for episode in data for label in episode['y'] if label >= 0]
    expected_episodes = [episode['id'] for episode in data]
    require(len(expected_labels) == 192 and len(expected_episodes) == 24, 'unexpected development denominator')
    rows = []
    for model, summary in (('hcsn', h), ('gru', g)):
        for seed in (11, 23, 37):
            run = next(r for r in summary['runs'] if r['seed'] == seed
                       and (model == 'gru' or r['arm'] == 'c1_b1'))
            require(run['status'] == 'completed', 'selected producer run incomplete')
            role = model + '_seed' + str(seed) + '_development'
            saved = parsed[role]
            require(saved['labels'] == expected_labels and saved['episode_ids'] == expected_episodes,
                    'saved query labels or episode ordering differ: ' + role)
            measured = metrics(saved['logits'], saved['labels'])
            ce_error = abs(measured['cross_entropy_nats'] - run['development']['cross_entropy'])
            accuracy_error = abs(measured['accuracy'] - run['development']['accuracy'])
            require(ce_error < 2e-14 and accuracy_error < 2e-14,
                    'raw logits metrics differ from pinned producer summary: ' + role)
            rows.append(dict(model='HCSN c1_b1' if model == 'hcsn' else 'PyTorch GRU7 + projection9',
                             seed=seed, development_role=role, metrics=measured,
                             maximum_summary_metric_error=max(ce_error, accuracy_error)))
    label_counts = [expected_labels.count(k) for k in range(8)]
    references = dict(classes=8, uniform_probability_vector=[1 / 8] * 8,
        uniform_probability_cross_entropy_nats=math.log(8),
        uniform_probability_brier_mean_classes=7 / 64,
        random_uniform_label_expected_accuracy=1 / 8,
        constant_predicted_class_accuracies=[count / len(expected_labels) for count in label_counts],
        equal_logits_deterministic_argmax_class=0,
        equal_logits_deterministic_argmax_actual_development_accuracy=label_counts[0] / len(expected_labels),
        interpretation='Uniform probabilities have CE ln(8) for every label; random uniform class selection has expected accuracy 1/8; deterministic argmax accuracy depends on this fixed dataset class frequency.')
    require(digest(command_path.read_bytes()) == digest(command_raw), 'launch manifest changed during read-only audit')
    for role, identity in command['inputs'].items():
        require(digest(Path(identity['path']).read_bytes()) == identity['sha256'],
                'input changed during read-only audit: ' + role)
    source_after = digest(source_path.read_bytes())
    require(source_after == source_before, 'script changed during read-only audit')
    means = {}
    for model in ('HCSN c1_b1', 'PyTorch GRU7 + projection9'):
        selected = [row['metrics'] for row in rows if row['model'] == model]
        means[model] = {key: math.fsum(row[key] for row in selected) / len(selected)
                        for key in ('accuracy', 'cross_entropy_nats')}
    return dict(schema='hcsn-gru-hard-prediction-concentration-audit-v1', status='completed', passed=True,
        checked_utc=datetime.now(timezone.utc).isoformat(), command_sha256=digest(command_raw),
        script_sha256_before=source_before, script_sha256_after=source_after, source_unchanged=True,
        inputs=command['inputs'], inputs_unchanged=True,
        development_episodes=24, development_query_count=192, development_label_counts=label_counts,
        rows=rows, descriptive_seed_means=means, reference_predictors=references,
        model_imported=False, model_forward_calls=0, optimizer_steps=0,
        label_source='Pinned original development DATA; the same labels appear in all six raw prediction files.',
        limitations=['Hard argmax concentration does not assert that all logits or probabilities are identical.',
                     'The three initializations reuse one fixed synthetic development set; no new independent source.',
                     'The observed accuracy differences track fixed class frequencies and do not establish learned sequence memory.',
                     'Uniform-probability and random-class references are arithmetic references, not newly trained baselines.',
                     'This audit binds saved bytes and checks producer metrics; it does not rerun checkpoint inference.'],
        wall_seconds=time.perf_counter() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'preserve earlier attempts with a new output')
    try:
        report = audit(args.command)
        exit_code = 0
    except Exception as error:
        report = dict(schema='hcsn-gru-hard-prediction-concentration-audit-v1', status='failed', passed=False,
                      error_type=type(error).__name__, error_message=str(error), model_forward_calls=0,
                      optimizer_steps=0)
        exit_code = 1
    with args.output.open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status=report['status'], passed=report['passed'])))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
