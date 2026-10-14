"""R9 read-only audit: exact lazy rejection, original gate, all tensors and laws."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
import numpy as np


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def verify(source, root, out):
    sys.path.insert(0, str(source.resolve()))
    import torch
    from run import sources, specs, name_for, panels, digest, dump, PROTOCOL_COMMIT
    from core import (WidePolicy, training_rule, rule, make_problem, evaluate,
                      TARGET, TOLERANCE, CADENCE, CAP, qualifies)
    import reference
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    plan = json.loads((root/'PLAN.json').read_text())
    done = json.loads((root/'COMPLETE.json').read_text())
    require(plan['source'] == sources(), 'source mismatch')
    require(plan['protocol'] == PROTOCOL_COMMIT, 'protocol mismatch')
    require(done['plan_sha256'] == digest((root/'PLAN.json').read_bytes()), 'plan hash mismatch')
    require(plan['cases'] == specs(), 'case specification mismatch')
    require([x['name'] for x in done['census']] == [name_for(x) for x in specs()], 'incomplete census')
    require(done['completed'] == 96 and done['failed'] == 0, 'execution failures')
    require((plan['target'], plan['tolerance'], plan['cadence'], plan['cap']) ==
            (TARGET, TOLERANCE, CADENCE, CAP), 'gate changed')
    require(plan['law_sha256'] == digest((root/'LAWS.npz').read_bytes()), 'law hash mismatch')
    laws = {}
    with np.load(root/'LAWS.npz', allow_pickle=False) as stored:
        for name in ('cc5', 'gl5', 'cc9'):
            s, w = training_rule(name) if name != 'cc9' else rule(name)
            np.testing.assert_array_equal(stored[name+'_states'], s)
            np.testing.assert_array_equal(stored[name+'_weights'], w)
            laws[name] = s, w
    dense_s, dense_w = rule('cc17')
    rows, groups, checkpoint_rows = [], {}, []
    totals = dict(checkpoints=0, skipped_fine_recomputed=0, panels=0, scalar_entries=0,
                  max_replay_error=0., independent_action_checks=0, independent_action_error=0.)
    # Scalars only; cache identical initial/checkpoint values without growing graphs.
    cache = {}
    for entry in done['census']:
        require(entry['case'] == plan['cases'][len(rows)], 'case plan identity mismatch')
        folder = root/entry['name']
        require(entry['status'] == 'completed', 'failed case')
        rb = (folder/'REPORT.json').read_bytes()
        require(digest(rb) == entry['report_sha256'], 'report hash mismatch')
        report = json.loads(rb)
        child = json.loads((folder/'PLAN.json').read_text())
        require(child['protocol'] == PROTOCOL_COMMIT, 'child protocol mismatch')
        require(report['case'] == entry['case'] == child['case'], 'identity mismatch')
        require(report['plan_sha256'] == digest((folder/'PLAN.json').read_bytes()), 'child plan mismatch')
        require(report['source'] == child['source'] == plan['source'], 'child source mismatch')
        require(tuple(child[k] for k in ('target', 'tolerance', 'cadence', 'cap')) ==
                (TARGET, TOLERANCE, CADENCE, CAP), 'child gate changed')
        info = json.loads((folder/'FIT.json').read_text())
        seal = json.loads((folder/'FIT_SEAL.json').read_text())
        require(info == report['fit'], 'fit/report mismatch')
        require(seal['fit'] == digest((folder/'FIT.json').read_bytes()), 'fit hash mismatch')
        require(seal['checkpoints'] == digest((folder/'CHECKPOINTS.npz').read_bytes()), 'checkpoint hash mismatch')
        case = entry['case']; pol = WidePolicy(case['width'], case['seed'])
        with np.load(folder/'WEIGHTS.npz', allow_pickle=False) as data:
            theta = data['theta'].copy()
        with np.load(folder/'INITIAL.npz', allow_pickle=False) as data:
            initial = data['theta'].copy()
        with np.load(folder/'CHECKPOINTS.npz', allow_pickle=False) as data:
            cps = data['theta'].copy()
        np.testing.assert_array_equal(initial, pol.initial)
        require(theta.size == report['parameters'] == 50+7*case['width'], 'parameter count mismatch')
        require(digest(initial.tobytes()) == report['initial_sha256'], 'initial tensor mismatch')
        require(digest(theta.tobytes()) == seal['weights'] == report['weights_sha256'], 'weight hash mismatch')
        require(report['changed'] == (not np.array_equal(theta, initial)), 'changed flag mismatch')
        require(len(cps) == len(info['checks']) > 0, 'checkpoint census mismatch')
        eligible, skipped, previous_end = [], 0, -1.
        for idx, (cp, ck) in enumerate(zip(cps, info['checks'])):
            require(ck['index'] == idx and ck['start'] >= previous_end and ck['end'] >= ck['start'], 'invalid timing')
            require(ck['within_cap'] == (ck['end'] <= CAP), 'false within-cap flag')
            previous_end = ck['end']; costs = {}
            for name in ('cc5', 'cc9'):
                key = case['width'], digest(cp.tobytes()), name
                if key not in cache:
                    s, w = laws[name]
                    cache[key] = float(w@evaluate(pol, torch.tensor(cp), make_problem(), s, chunk=256).mean(1))
                costs[name] = cache[key]
            require(np.isclose(costs['cc5'], ck['cc5'], rtol=1e-12, atol=1e-13), 'coarse monitor mismatch')
            if ck['cc9'] is None:
                require(case['monitor'] == 'lazy' and not ck['terminal'] and ck['cc5'] > TARGET,
                        'invalid fine skip')
                skipped += 1
            else:
                require(np.isclose(costs['cc9'], ck['cc9'], rtol=1e-12, atol=1e-13), 'fine monitor mismatch')
            good = qualifies(costs['cc5'], costs['cc9'])
            require(ck['predicate'] == good, 'false gate predicate')
            if good and ck['within_cap']:
                eligible.append(idx)
            checkpoint_rows.append(dict(run=entry['name'], index=idx, cc5=costs['cc5'], cc9=costs['cc9'],
                                        skipped=ck['cc9'] is None, predicate=good, within_cap=ck['within_cap']))
        require(info['success'] == bool(eligible), 'false success')
        if eligible:
            require(eligible[0] == len(cps)-1, 'continued after qualifying')
            require(info['observed_wall'] == info['checks'][eligible[0]]['end'], 'false observed time')
        else:
            require(info['observed_wall'] is None, 'censoring became success time')
            require(info['checks'][-1]['terminal'] and info['checks'][-1]['cc9'] is not None,
                    'missing full terminal check')
        np.testing.assert_array_equal(theta, cps[-1])
        counts = info['counts']
        require(counts['skipped_fine'] == skipped and counts['coarse_calls'] == len(cps) and
                counts['fine_calls'] == len(cps)-skipped, 'monitor counts mismatch')
        require(counts['full_hessians'] == 0, 'dense fallback')
        require(info['wall'] >= info['checks'][-1]['end'] and info['wall'] >= info['monitor_wall'], 'unmetered monitor')
        require(np.isclose(info['monitor_wall'], sum(c['end']-c['start'] for c in info['checks']), rtol=1e-12, atol=1e-9), 'monitor time mismatch')
        require(report['predictions_sha256'] == digest((folder/'PREDICTIONS.npz').read_bytes()), 'prediction hash mismatch')
        with np.load(folder/'PREDICTIONS.npz', allow_pickle=False) as raw:
            for name, s, w, problem in panels():
                values = evaluate(pol, torch.tensor(theta), problem, s, chunk=256)
                error = float(np.max(np.abs(values-raw[name])))
                require(error <= 1e-13, 'prediction replay mismatch')
                require(np.isclose(float(w@values.mean(1)), report['costs'][name], rtol=1e-12, atol=1e-13), 'metric mismatch')
                totals['max_replay_error'] = max(totals['max_replay_error'], error)
                totals['panels'] += 1; totals['scalar_entries'] += values.size
        dense_values = evaluate(pol, torch.tensor(theta), make_problem(), dense_s, chunk=256)
        with open(out/(entry['name']+'-CC17.npz'), 'xb') as stream:
            np.savez_compressed(stream, values=dense_values)
        dense_cost = float(dense_w@dense_values.mean(1))
        # Independent implementation, first fresh QMC state / both initial regimes.
        states = next(s for name,s,w,p in panels() if name == 'qmc0')[:1]
        with torch.no_grad():
            value, levels, _, _, _ = pol.tree(torch.tensor(theta), make_problem(), states)
        for i in range(2):
            actions = np.concatenate([L['u'][i*2**k:(i+1)*2**k].numpy().reshape(-1) for k,L in enumerate(levels)])
            problem = make_problem(); tree = reference.build(problem, states[0], i)
            cost = reference.evaluate(actions, problem, tree, False)[0]
            error = abs(cost-float(value[i]))
            require(error <= 1e-12, 'independent action mismatch')
            totals['independent_action_error'] = max(totals['independent_action_error'], error)
            totals['independent_action_checks'] += 1
        totals['checkpoints'] += len(cps); totals['skipped_fine_recomputed'] += skipped
        groups.setdefault((case['width'], case['seed']), []).append(report['initial_sha256'])
        row = dict(name=entry['name'], **case, parameters=theta.size, success=info['success'],
                   observed_wall=info['observed_wall'], fit_wall=info['wall'], fit_cpu=info['cpu'],
                   monitor_wall=info['monitor_wall'], monitor_cpu=info['monitor_cpu'],
                   fine_calls=counts['fine_calls'], skipped=skipped, updates=counts['updates'], hvp=counts['hvp'],
                   fit_peak_rss=info['fit_peak_rss'], cc17=dense_cost, **report['costs'],
                   child_wall=entry['child_wall'], child_cpu=entry['child_cpu'])
        rows.append(row)
        dump(out/(entry['name']+'.verified.json'), row)
        print(json.dumps(dict(verified=len(rows), name=entry['name'], success=info['success'])), flush=True)
    for group in groups.values():
        require(len(group) == 16 and len(set(group)) == 1, 'factorial initial mismatch')
    for name, data in (('SCORES.csv', rows), ('CHECKPOINTS.csv', checkpoint_rows)):
        with open(out/name, 'x', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    dump(out/'AUDIT.json', dict(runs=len(rows), **totals, cc17_panels=len(rows), initial_groups=len(groups),
                               wall=time.perf_counter()-wall, cpu=time.process_time()-cpu,
                               timing_externally_authenticated=False, production_authorized=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--runs', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(); verify(args.source, args.runs, args.out)
