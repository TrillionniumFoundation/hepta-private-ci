"""Verify paired physical predictions, all archived state dictionaries and cold wall accounting."""
import hashlib
import json
from pathlib import Path
from statistics import mean
import zipfile

import numpy as np

from summarize import independent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main(root):
    rows = json.loads((root / 'readout_results.json').read_text())
    semantic = json.loads((root / 'semantic_summary.json').read_text())['arms']['centered']['runs']
    frontend_wall = json.loads((root / 'frontend_receipt.json').read_text())['total_wall']
    parents = {r['seed']: r for r in semantic}
    keyed = {(r['mode'], r['method'], r['seed']): r for r in rows}
    assert len(keyed) == len(rows) == 12
    output = {'source_sha256': digest((root / 'readout_results.json').read_bytes()),
              'frozen_speech_preparation_wall': frontend_wall, 'runs': [], 'methods': {}}
    archive_name = root / 'selected_checkpoints.zip'
    with zipfile.ZipFile(archive_name) as z:
        assert z.testzip() is None
        n = 0
        for folder, input_file in [('run', 'lowlevel_results.json'), ('neural_run', 'semantic_results.json'),
                                   ('quadratic', 'readout_results.json')]:
            seal = json.loads(z.read(folder + '/seal.json'))
            scores = json.loads((root / input_file).read_bytes())
            if isinstance(scores, dict):
                scores = scores['rows']
            for r in scores:
                if r['mode'] == 'fit':
                    ident = r.get('arm', r.get('method')) + '_' + str(r['seed'])
                    assert digest(z.read(folder + '/' + ident + '.pt')) == seal[ident] == r.get('candidate_sha256', r.get('checkpoint'))
                    n += 1
        assert n == 30
        output['archive'] = {'sha256': digest(archive_name.read_bytes()), 'verified_states': n}
    max_record_error = 0
    for seed, parent in parents.items():
        f = {m: keyed['fit', m, seed] for m in ('direct', 'bp')}
        e = {m: keyed['eval', m, seed] for m in f}
        assert f['direct']['parent_sha256'] == f['bp']['parent_sha256']
        equal_quality = True
        margin_gap, brier_gap = 0, 0
        details = {}
        for split, expected in [('test', 48), ('retain', 32)]:
            metrics = {}
            for m, row in e.items():
                panel = row[split]
                assert panel['labels'] == e['direct'][split]['labels']
                assert panel['groups'] == e['direct'][split]['groups']
                assert len(panel['labels']) == expected
                for col, tag, actual in [('margins', m, 'edited'), ('parent_margins','parent','parent')]:
                    measures = independent(panel[col], panel['labels'])
                    max_record_error = max(max_record_error, max(abs(float(v)-panel[actual][k]) for k,v in measures.items()))
                    metrics[tag] = {k:float(v) for k,v in measures.items()}
            err = abs(metrics['direct']['brier']-metrics['bp']['brier'])
            equal_quality &= metrics['direct']['accuracy'] == metrics['bp']['accuracy'] and err <= .0001
            margin_gap = max(margin_gap, float(np.max(np.abs(np.array(e['direct'][split]['margins']) - e['bp'][split]['margins']))))
            brier_gap = max(brier_gap, err)
            details[split] = metrics
        improved = details['test']['direct']['accuracy'] > details['test']['parent']['accuracy'] and details['retain']['direct']['accuracy'] >= details['retain']['parent']['accuracy']
        run = {'seed':seed, **details, 'matched_quality': bool(equal_quality), 'improved':bool(improved),
               'max_direct_bp_margin_difference':margin_gap,'max_direct_bp_brier_difference':brier_gap,
               'parent_fit_wall':parent['fit_wall']}
        for method in f:
            fit, evaluate = f[method], e[method]
            run[method] = {'solve_wall':fit['solve_wall'],'fit_wall':fit['process_wall'],
                           'eval_wall':evaluate['process_wall'],'edit_fit_plus_eval_wall':fit['process_wall']+evaluate['process_wall'],
                           'frontend_parent_edit_fit_eval_wall':frontend_wall+parent['fit_wall']+fit['process_wall']+evaluate['process_wall'],
                           'objective':fit['objective'], 'grad_norm':fit['gradient_norm'],'closure_calls':fit['calls'],
                           'projected_physical_error':fit['projected_physical_error']}
        output['runs'].append(run)
    assert max_record_error < 3e-6
    output['micro_vs_reported_max_error'] = max_record_error
    for method in ['direct','bp']:
        output['methods'][method] = {k:mean(r[method][k] for r in output['runs']) for k in output['runs'][0][method]}
    output['ratio_bp_over_direct'] = {k:output['methods']['bp'][k]/output['methods']['direct'][k] for k in
                                       ('solve_wall','fit_wall','eval_wall','edit_fit_plus_eval_wall','frontend_parent_edit_fit_eval_wall')}
    dest = root/'readout_summary.json'
    dest.write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')


if __name__ == '__main__':
    main(Path(__file__).resolve().parent)
