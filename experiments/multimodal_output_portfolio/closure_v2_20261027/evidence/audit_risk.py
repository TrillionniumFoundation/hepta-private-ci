"""Independent realized-utility and paired source-bootstrap reconstruction."""

import json

import numpy as np


def verify_risk(run, laws, rows):
    sources = sorted({row['speaker'] for row in rows})
    results, actions = {}, {}
    for family in ('rank_baseline', 'rank_joint'):
        table = laws[family]
        for gamma in (0, 2):
            name = f'risk_{family}_gamma{gamma}'
            output = [json.loads(line) for line in (run/f'DELIVERED_{name}.jsonl').read_text().splitlines()]
            if len(output) != len(rows):
                raise AssertionError('Selective-prediction output census differs')
            utilities, actions[name] = [], []
            for row, text in zip(rows, output):
                evidence = table[row['values'][0], row['values'][1]]
                posterior = evidence/evidence.sum()
                label = int(posterior.argmax())
                good, bad, refused = 1.-.01, -.5-.01, -.003
                if gamma == 0:
                    label_value = posterior[label]*good+(1-posterior[label])*bad
                    expected = str(label) if label_value > refused else 'uncertain'
                else:
                    label_moment = posterior[label]*np.exp(-2*good)+(1-posterior[label])*np.exp(-2*bad)
                    expected = str(label) if label_moment < np.exp(-2*refused) else 'uncertain'
                if (text['sample_id'] != row['sample_id'] or text['text'] != expected
                        or text['factor_count'] != 1 or text['physical_event_count'] != 1):
                    raise AssertionError('Actual selective output differs from the frozen risk action')
                action = 10 if text['text'] == 'uncertain' else int(text['text'])
                actions[name].append(action)
                utilities.append(refused if action == 10 else good if action == row['target'] else bad)
            by_source = {}
            for source in sources:
                indices = [i for i, row in enumerate(rows) if row['speaker'] == source]
                u = np.asarray(utilities)[indices]
                a = np.asarray(actions[name])[indices]
                by_source[source] = {'mean_utility': float(u.mean()), 'moment2': float(np.mean(np.exp(-2*u))),
                    'error_rate': float(np.mean(u == bad)), 'uncertain_rate': float(np.mean(a == 10)),
                    'correct_rate': float(np.mean(u == good))}
            aggregate = {field: float(np.mean([group[field] for group in by_source.values()]))
                         for field in next(iter(by_source.values()))}
            aggregate['certainty_equivalent_gamma2'] = float(-np.log(aggregate['moment2'])/2)
            aggregate['by_speaker'] = by_source
            results[name] = aggregate
    comparisons = {}
    for gamma in (0, 2):
        left, right = results[f'risk_rank_joint_gamma{gamma}'], results[f'risk_rank_baseline_gamma{gamma}']
        indices = np.random.default_rng(272033).integers(len(sources), size=(20000, len(sources)))
        compared = {}
        for field in ('mean_utility', 'certainty_equivalent_gamma2', 'error_rate', 'uncertain_rate', 'correct_rate'):
            key = 'moment2' if field == 'certainty_equivalent_gamma2' else field
            a = np.array([left['by_speaker'][source][key] for source in sources])
            b = np.array([right['by_speaker'][source][key] for source in sources])
            if key == 'moment2':
                samples = (np.log(b[indices].mean(1))-np.log(a[indices].mean(1)))/2
            else:
                samples = np.mean((a-b)[indices], axis=1)
            compared[field] = {'difference': left[field]-right[field],
                                'ci97_5': np.percentile(samples, [1.25, 98.75]).tolist()}
        compared['ce_gain'] = compared['certainty_equivalent_gamma2']['ci97_5'][0] > 0
        compared['mean_gain'] = compared['mean_utility']['ci97_5'][0] > 0
        comparisons[str(gamma)] = compared
    return {'models': results, 'joint_minus_baseline': comparisons,
            'preference_action_disagreements': {family: int(np.count_nonzero(np.array(actions[f'risk_{family}_gamma0'])
                                                                         != np.array(actions[f'risk_{family}_gamma2'])))
                                               for family in ('rank_baseline', 'rank_joint')},
            'map_accuracy_gate_unchanged': True,
            'payoff_scope': 'Task-defined correct/wrong/uncertain payoffs and delivery fees, not dollars or energy; measured CPU/wall is reported separately.'}
