"""Independent raw-accounting auditor; never imports campaign or its aggregation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def readlines(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def audit(dest, output):
    root = dest.resolve().parents[4]
    p, done = read(dest/'PLAN.json'), read(dest/'COMPLETE.json')
    freeze, fits, service = (read(dest/f) for f in ('EVALUATION_FREEZE.json', 'ANALYTIC_FITS.json', 'SERVICE_FIT.json'))
    checks = 0
    def require(test, message):
        nonlocal checks
        checks += 1
        if not test:
            raise AssertionError(message)
    require(sha(dest/'runs.jsonl.gz') == done['raw_sha256'], 'raw hash')
    require(sha(dest/'worlds.jsonl.gz') == done['worlds_sha256'], 'world hash')
    require(sha(dest/'PLAN.json') == freeze['plan_sha256'], 'plan hash')
    require(sha(dest/'ANALYTIC_FITS.json') == freeze['fit_sha256'], 'fit freeze')
    require(sha(dest/'SERVICE_FIT.json') == freeze['service_sha256'], 'service freeze')
    for path, expected in {**p['source_sha256'], **p['historical_assets']}.items():
        require(sha(root/path) == expected, 'source or historical hash '+path)
    for fs in fits:
        for mode, f in fits[fs].items():
            winner = min(f['candidates'], key=lambda v: (v['train_nll'], v['drift_scale']))
            require(winner['drift_scale'] == f['selected_scale'], 'train-only winner')
            require([v['drift_scale'] for v in f['candidates']] == p['drift_grid'], 'all grid trials retained')
    samples = np.load(dest/'service_samples.npz')
    for t in range(21):
        actual = samples['uniform'][t] < .9-.7*t/20
        require(np.array_equal(samples['success'][t], actual), 'service train outcomes')
        require(int(actual.sum()) == service['success_count'][t], 'service count')
        require(float(actual.mean()) == service['forecast'][t], 'service fit')
    worlds = {(w['condition'], w['index']): w['episode'] for w in readlines(dest/'worlds.jsonl.gz')}
    rows = readlines(dest/'runs.jsonl.gz')
    require(len(rows) == done['runs'] == 2040, 'complete 2040 runs')
    require(len(worlds) == done['worlds'] == 24, '24 worlds')
    indexed = {}
    counters = {'read_requests': 0, 'service_successes': 0, 'service_failures': 0,
                'mandatory_outputs': 0, 'fixed_records': 0, 'same_tick_outcome_conflicts': 0}
    for r in rows:
        key = (r['condition'], r['index'], r['family'], r['fit_seed'], r['mode'], r['controller'], r['risk'], r['fixed'])
        require(key not in indexed, 'duplicate run')
        indexed[key] = r
        world = worlds[key[:2]]
        config, trace, access = p['config'], r['trace'], r['access']
        reads = [v for v in trace if v['action'] == 'READ']
        require(len(reads) <= config['budget'], 'read budget')
        require(len(access) == len(reads), 'every request arrived')
        require([v['arrival_tick'] for v in access] == [v['tick']+1 for v in reads], 'arrival chronology')
        expected_obs = {'time': 0., 'x': world['initial_x'], 'refractory_remaining': 0.,
                        'content_probs': [.2]*5, 'has_read': False}
        arrivals = {a['arrival_tick']: a for a in access}
        predictions = {v['tick']: v for v in r['predictions']}
        require(list(predictions) == config['deadlines'], 'mandatory deadline inventory')
        traces = {v['tick']: v for v in trace}
        for t in range(21):
            if t in arrivals:
                a = arrivals[t]
                success = world['service_uniform'][t] < .9-.7*t/20
                require(a['success'] == success, 'actual world success')
                require(a['fee_charged'] == config['read_cost'], 'failed or successful service costs')
                if success:
                    probs = [0.]*5
                    probs[world['path']['content'][t]] = 1.
                    expected_obs = {'time': t*config['dt'], 'x': world['path']['x'][t],
                        'refractory_remaining': world['path']['refractory_remaining'][t],
                        'content_probs': probs, 'has_read': True}
                require(a['observed_state_after'] == expected_obs, 'service observation update')
                counters['service_successes' if success else 'service_failures'] += 1
            if t in traces:
                require(traces[t]['observation'] == expected_obs, 'causal trace observation')
            if t in predictions:
                v = predictions[t]
                require(v['observed_state'] == expected_obs, 'causal output observation')
                require(v['truth_for_scoring_only'] == world['path']['content'][t], 'score truth')
                probs = v['probabilities']
                require(all(x >= -1e-12 for x in probs) and abs(sum(probs)-1) < 1e-9, 'probability mass')
                counts = v['count_probabilities']
                require(all(x >= -1e-12 for x in counts) and abs(sum(counts)-1) < 1e-9, 'count mass')
                state = expected_obs['content_probs'][:]
                reconstructed = [0.]*5
                for weight in counts:
                    reconstructed = [x+weight*z for x,z in zip(reconstructed, state)]
                    state = [.15*state[j]+.55*state[(j-1)%5]+.30*state[(j+1)%5] for j in range(5)]
                require(max(abs(a-b) for a,b in zip(probs, reconstructed)) < 1e-12, 'independent count-to-content')
                predicted_class = max(range(5), key=lambda j: probs[j])
                require(v['correct'] == int(predicted_class == v['truth_for_scoring_only']), 'correctness')
        accuracy = sum(v['correct'] for v in predictions.values())/4
        require(r['summary']['accuracy'] == accuracy, 'mean accuracy')
        require(r['summary']['reads'] == len(reads), 'read count')
        require(r['summary']['read_fees'] == len(reads)*config['read_cost'], 'fees')
        require(r['summary']['net_reward'] == accuracy-len(reads)*config['read_cost'], 'net reward')
        counters['read_requests'] += len(reads)
        counters['mandatory_outputs'] += 4
        counters['fixed_records'] += r['fixed']
    for c, wi in worlds:
        group = [r for r in rows if (r['condition'], r['index']) == (c, wi)]
        require(len(group) == 85, '85 arms/world')
        for fs in map(str,p['fit_seeds']):
            base = indexed[(c,wi,'analytic',fs,'original','task_value',True,False)]
            schedule = [(v['tick'],v['action']) for v in base['trace']]
            for mode in p['modes']:
                fixed = indexed[(c,wi,'analytic',fs,mode,'task_value',True,True)]
                require([(v['tick'],v['action']) for v in fixed['trace']] == schedule, 'fixed D schedule')
                require(fixed['access'] == base['access'], 'fixed actions give identical services/observations')
    def mean(values):
        return float(np.mean(values))
    def estimate(values):
        rng = np.random.default_rng(916003)
        a = np.array(values)
        draws = a[rng.integers(len(a), size=(10000,len(a)))].mean(1)
        return {'mean': mean(a), 'world_cluster_percentile95': np.quantile(draws,[.025,.975]).tolist(),
                'per_world': a.tolist(), 'worlds': len(a), 'method': 'descriptive world-block; fits averaged within world'}
    summary = {}
    for c in p['conditions']:
        results, risk_effects, shape_effects = {}, {}, {}
        def arm(wi, family, fs, mode, controller, risk=True, fixed=False):
            return indexed[(c,wi,family,fs,mode,controller,risk,fixed)]
        for risk in (True,False):
            contrasts = {k: [] for k in ('A','B','C','D','B-A','D-C','C-A','D-B','interaction')}
            for wi in range(12):
                av = {}
                for label, controller in (('A','lightweight'),('B','task_value')):
                    av[label] = mean([arm(wi, family, fs, 'original', controller, risk)['summary']['net_reward']
                        for fs, family in freeze['ordinary_selections'].items()])
                for label, controller in (('C','lightweight'),('D','task_value')):
                    av[label] = mean([arm(wi,'analytic',str(fs),'original',controller,risk)['summary']['net_reward']
                        for fs in p['fit_seeds']])
                av.update({'B-A':av['B']-av['A'],'D-C':av['D']-av['C'], 'C-A':av['C']-av['A'],
                           'D-B':av['D']-av['B'], 'interaction':(av['D']-av['C'])-(av['B']-av['A'])})
                for k in contrasts:
                    contrasts[k].append(av[k])
            results['risk_aware' if risk else 'risk_omitted'] = {k: estimate(v) for k,v in contrasts.items()}
        for mode in p['modes']:
            effect, changes = [], 0
            for wi in range(12):
                effect.append(mean([arm(wi,'analytic',str(fs),mode,'task_value',True)['summary']['net_reward']-
                    arm(wi,'analytic',str(fs),mode,'task_value',False)['summary']['net_reward'] for fs in p['fit_seeds']]))
                for fs in p['fit_seeds']:
                    a,b = (arm(wi,'analytic',str(fs),mode,'task_value',risk) for risk in (True,False))
                    changes += [(v['tick'],v['action']) for v in a['trace']] != [(v['tick'],v['action']) for v in b['trace']]
            risk_effects[mode] = {'aware_minus_omitted': estimate(effect), 'action_changed_world_fit_pairs': changes}
        for mode in p['modes'][1:]:
            effect = {'closed': [], 'fixed': []}
            probability_changes = class_changes = 0
            for wi in range(12):
                for label,fixed in (('closed',False),('fixed',True)):
                    effect[label].append(mean([arm(wi,'analytic',str(fs),mode,'task_value',True,fixed)['summary']['net_reward']-
                        arm(wi,'analytic',str(fs),'original','task_value',True,False)['summary']['net_reward'] for fs in p['fit_seeds']]))
                for fs in p['fit_seeds']:
                    base = arm(wi,'analytic',str(fs),'original','task_value')
                    fixed = arm(wi,'analytic',str(fs),mode,'task_value',True,True)
                    for a,b in zip(base['predictions'],fixed['predictions']):
                        probability_changes += max(abs(x-y) for x,y in zip(a['probabilities'],b['probabilities'])) > 1e-12
                        class_changes += np.argmax(a['probabilities']) != np.argmax(b['probabilities'])
            shape_effects[mode] = {k:estimate(v) for k,v in effect.items()}
            shape_effects[mode].update(fixed_output_distribution_changes=int(probability_changes), fixed_class_changes=int(class_changes))
        summary[c] = {'four_cells': results,'risk_effects':risk_effects,'refitted_shape_minus_refitted_full':shape_effects}
    result = {'checks': checks, 'status':'passed', 'counters':counters,'conditions':summary,
              'scope':'raw arithmetic/chronology/content-mixture and descriptive statistics; not neural forward replay',
              'limits':['12 independent worlds per condition; historical five ordinary fits',
                        '3 one-dimensional analytic calibration fits; no neural analytic retraining',
                        'risk is a declared stochastic service-success process, not financial Put risk',
                        'refitted drift changes core count forecasts; shared planner simulations retain common original estimated physics',
                        'fixed actions cover shape interventions only; fixed risk-omission replay absent',
                        '1e-12 loss floor assigns finite loss to impossible support in simplified count models',
                        'world-cluster intervals do not include population uncertainty of fitted models']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'checks':checks,'status':'passed','counters':counters}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    audit(args.run,args.out)
