"""Prespecified selective prediction with actual label/uncertain text delivery."""

import json
import time

import numpy as np


def choose(probability, gamma):
    probability = np.asarray(probability, dtype=float)
    if (probability.shape != (10,) or np.any(probability < 0)
            or not np.isfinite(probability).all() or abs(probability.sum()-1) > 1e-10):
        raise ValueError('A normalized10-target posterior is required')
    if gamma == 0:
        values = probability*.99+(1-probability)*(-.51)
        return int(values.argmax()) if float(values.max()) > -.003 else 10
    if gamma != 2:
        raise ValueError('Only the two preregistered preferences are supported')
    moments = probability*np.exp(-1.98)+(1-probability)*np.exp(1.02)
    return int(moments.argmin()) if float(moments.min()) < np.exp(.006) else 10


def statistics(actions, rows):
    utility = np.array([-.003 if action == 10 else (.99 if action == row['target'] else -.51)
                        for action, row in zip(actions, rows)])
    sources = sorted({row['speaker'] for row in rows})
    by_source = {}
    for source in sources:
        keep = np.array([row['speaker'] == source for row in rows])
        selected = np.asarray(actions)[keep]
        u = utility[keep]
        by_source[source] = {'mean_utility': float(u.mean()), 'moment2': float(np.exp(-2*u).mean()),
            'error_rate': float((u == -.51).mean()), 'uncertain_rate': float((selected == 10).mean()),
            'correct_rate': float((u == .99).mean())}
    result = {key: float(np.mean([record[key] for record in by_source.values()]))
              for key in next(iter(by_source.values()))}
    result['certainty_equivalent_gamma2'] = float(-np.log(result['moment2'])/2)
    result['by_speaker'] = by_source
    return result


def compare(left, right):
    sources = sorted(left['by_speaker'])
    choices = np.random.default_rng(272033).integers(len(sources), size=(20000, len(sources)))
    result = {}
    for metric in ('mean_utility', 'certainty_equivalent_gamma2', 'error_rate', 'uncertain_rate', 'correct_rate'):
        field = 'moment2' if metric == 'certainty_equivalent_gamma2' else metric
        a = np.array([left['by_speaker'][source][field] for source in sources])
        b = np.array([right['by_speaker'][source][field] for source in sources])
        if field == 'moment2':
            delta = -np.log(a[choices].mean(1))/2+np.log(b[choices].mean(1))/2
        else:
            delta = (a-b)[choices].mean(1)
        result[metric] = {'difference': left[metric]-right[metric],
                          'ci97_5': np.quantile(delta, [.0125, .9875]).tolist()}
    result['ce_gain'] = result['certainty_equivalent_gamma2']['ci97_5'][0] > 0
    result['mean_gain'] = result['mean_utility']['ci97_5'][0] > 0
    return result


def study(run, laws, rows, captures, make_state, digest):
    models, actions, costs = {}, {}, []
    for family in ('rank_baseline', 'rank_joint'):
        law = laws[family]
        for gamma in (0, 2):
            name = f'risk_{family}_gamma{gamma}'
            wall, cpu = time.perf_counter(), time.process_time()
            path = run/f'DELIVERED_{name}.jsonl'
            with path.open('x') as stream:
                for row in rows:
                    public = {key: row[key] for key in ('sample_id', 'events', 'values')}
                    state = make_state(law, public, captures, np.full(10, .1))
                    for view, event, value in zip(law.views, row['events'], row['values']):
                        state.ingest({'block': 'source', 'view': view, 'alias': event,
                                      'content_sha256': captures[event].content_sha256, 'value': value})
                    action = choose(state.posterior, gamma)
                    stream.write(json.dumps({'sample_id': row['sample_id'],
                        'text': 'uncertain' if action == 10 else str(action),
                        'factor_count': state.snapshot()['factor_count'],
                        'physical_event_count': state.snapshot()['physical_event_count']}, sort_keys=True)+'\n')
            delivered = [json.loads(line) for line in path.read_text().splitlines()]
            if [row['sample_id'] for row in delivered] != [row['sample_id'] for row in rows]:
                raise ValueError('Risk delivery identity changed')
            chosen = [10 if row['text'] == 'uncertain' else int(row['text']) for row in delivered]
            actions[name] = chosen
            models[name] = statistics(chosen, rows)
            costs.append({'file': path.name, 'rows': len(rows), 'sha256': digest(path),
                          'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu})
    comparisons = {str(gamma): compare(models[f'risk_rank_joint_gamma{gamma}'], models[f'risk_rank_baseline_gamma{gamma}'])
                   for gamma in (0, 2)}
    disagreements = {family: int(np.sum(np.array(actions[f'risk_{family}_gamma0'])
                                        != np.array(actions[f'risk_{family}_gamma2'])))
                     for family in ('rank_baseline', 'rank_joint')}
    return {'models': models, 'joint_minus_baseline': comparisons, 'preference_action_disagreements': disagreements,
            'map_accuracy_gate_unchanged': True,
            'payoff_scope': 'Task-defined correct/wrong/uncertain payoffs and delivery fees, not dollars or energy; measured CPU/wall is reported separately.'}, costs
