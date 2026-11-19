"""Independent JSON-only reconstruction, without importing the producer."""

from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import time

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = BASE / 'resource-analysis-independent-review-v1'
PRODUCER = BASE / 'resource-analysis-v1'
EXPECTED = {
    'PLAN.json': 'a893ceda6bff869455adf37e9d7ad61a7a8999379a9d1639fdc9dc5951a1472e',
    'analyze_resources.py': 'dc398a012bd25d611c0bbbfc09f64a3c76c7d1d367c84c5178864140c769ee95',
    'output-v1/RESULT.json': '9a5ca0f21e3a881862eafd9e67e35793a9eaeb5a1d4dbcaebcaf6d3720e01367',
    'output-v1/POINTS.json': '90e9f27b5ce07243621cf6b234c9ef0a406ff328ee42ed106e127f8193a1cf8f',
}
ARMS = ['gru', 'cfc', 'snn_plif', 'event_time_lif', 'ssm_s4d', 'attention', 'hcsn']
SEEDS, LRS, CUTS = [101, 211, 307], [.001, .003], [300, 900, 1800]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def near(a, b, label, tolerance=1e-12):
    require(type(a) in (float, int) and type(b) in (float, int) and math.isfinite(a)
            and math.isfinite(b) and abs(a - b) <= tolerance, label)


def record_point(row):
    return dict(phase=row['phase'], epoch=row['epoch'], kind=row['kind'],
                wall_seconds=row['process_wall_seconds'] if row['phase'] == 'original' else row['cumulative_process_wall_seconds'],
                CPU_lower_seconds=row['process_cpu_seconds'] if row['phase'] == 'original' else row['cumulative_cpu_lower_bound_seconds'],
                CPU_upper_seconds=row['process_cpu_seconds'] if row['phase'] == 'original' else None,
                quality=row['development']['macro_f1_11_classes'])


def best(points, cap=None):
    eligible = [p for p in points if (p['kind'] == 'complete_epoch' if cap is None else p['wall_seconds'] <= cap)]
    return sorted(eligible, key=lambda p: (-p['quality'], p['wall_seconds']))[0] if eligible else None


def main():
    started, cpu0 = time.monotonic(), time.process_time()
    OUT.mkdir(exist_ok=False)
    inputs = {}
    for relative, digest in EXPECTED.items():
        path = PRODUCER / relative
        require(sha(path) == digest, 'frozen resource analysis changed: ' + relative)
        inputs[str(path)] = digest
    result = json.loads((PRODUCER / 'output-v1/RESULT.json').read_bytes())
    compact = json.loads((PRODUCER / 'output-v1/POINTS.json').read_bytes())
    documents = {}
    for name, item in result['input_identities'].items():
        p = Path(item['path'])
        require(p.stat().st_size == item['bytes'] and sha(p) == item['sha256'], 'input identity differs')
        inputs[str(p)] = item['sha256']
        documents[name] = json.loads(p.read_bytes())
    raw = documents['curves']
    require(documents['plan']['fixed_budget_seconds'] == CUTS and documents['plan']['target_D_macro_f1'] == .3,
            'frozen budgets/quality target differ')
    require(result['CPU_axis_used_for_budget_selection'] is False and result['scientific_admission'] == 'HOLD'
            and result['confirmation_access'] is False and result['model_execution'] is False, 'scope changed')
    bindings = {('original', row['name']): row['report_sha256'] for row in documents['baseline_v1']['original_baseline_records']}
    bindings.update({('C1', row['name']): row['child_report_sha256'] for row in documents['baseline_v2']['C1_records']})
    bindings.update({('original', row['name']): row['result_sha256'] for row in documents['hcsn_summary']['rows']})
    fits = {(row['phase'], row['name']): row for row in raw['fits']}
    require(len(fits) == len(raw['fits']) == len(bindings) == 49 and set(fits) == set(bindings), '49 bound reports')
    for key, fit in fits.items():
        require(bindings[key] == fit['report_sha256'] == fit['outer']['result_sha256'], 'report receipt binding')
        require(fit['source_unchanged'] and fit['common_weights_unchanged'] and fit['actual_original_hard_wall_seconds'] >= 1800,
                'source/granted budget gate')
    by_fit = defaultdict(list)
    metric_error, support, counts = 0., None, defaultdict(int)
    for row in raw['observations']:
        fit = fits[row['phase'], row['name']]
        require(row['report_sha256'] == fit['report_sha256'] and row['report_bytes'] == fit['report_bytes'], 'point source mismatch')
        m, cm = row['development'], row['development']['confusion_matrix']
        require(len(cm) == 11 and all(len(r) == 11 and all(type(v) is int and v >= 0 for v in r) for r in cm), 'CM invalid')
        actual_support = [sum(r) for r in cm]
        predicted = [sum(cm[i][j] for i in range(11)) for j in range(11)]
        require(sum(actual_support) == m['events'] == 31952, 'D incomplete')
        if support is None:
            support = actual_support
        require(actual_support == support, 'D labels differ across observations')
        f1 = [Fraction(2 * cm[i][i], actual_support[i] + predicted[i]) if actual_support[i] + predicted[i] else Fraction(0) for i in range(11)]
        present = [i for i in range(11) if actual_support[i]]
        computed = dict(accuracy=float(Fraction(sum(cm[i][i] for i in range(11)), 31952)),
                        macro_f1_11_classes=float(sum(f1) / 11),
                        macro_f1_present_classes=float(sum(f1[i] for i in present) / len(present)),
                        balanced_accuracy_present_classes=float(sum(Fraction(cm[i][i], actual_support[i]) for i in present) / len(present)))
        for key, value in computed.items():
            near(value, m[key], 'independent rational CM metric mismatch')
            metric_error = max(metric_error, abs(value - m[key]))
        by_fit[row['phase'], row['name']].append(row)
        counts[row['kind']] += 1
    require(len(raw['observations']) == 2969 and counts == {'development_before': 42, 'complete_epoch': 2927}, 'observation count')
    interval_count = 0
    for key, rows in by_fit.items():
        points = [record_point(row) for row in rows]
        require(all(a['wall_seconds'] < b['wall_seconds'] for a, b in zip(points, points[1:])), 'clock order')
        packed = [[p[k] for k in compact['columns']] for p in points]
        require(packed == compact['by_phase_and_name']['/'.join(key)], 'compact points differ from raw source')
        if key[0] == 'C1':
            fit, parent = fits[key], fits['original', key[1]]
            parent_points = by_fit['original', key[1]]
            parent_wall = parent['outer']['whole_process_wall_seconds']
            near(fit['outer']['parent_outer_wall_seconds'], parent_wall, 'C1 parent wall')
            require(fit['parent_report_sha256'] == parent['report_sha256'], 'C1 parent report')
            parent_cpu_lb = max(parent['all_report_clock_fields']['cpu_seconds'],
                                *(r['process_cpu_seconds'] for r in parent_points if r['process_cpu_seconds'] is not None))
            near(parent_cpu_lb, fit['parent_cpu_lower_bound_seconds'], 'parent CPU bound')
            for row in rows:
                early, late = row['phase_process_wall_seconds'], row['cumulative_process_wall_seconds'] - parent_wall
                require(0 <= early <= late <= fit['outer']['whole_process_wall_seconds'], 'original C1 two-clock interval')
                near(row['cumulative_cpu_lower_bound_seconds'], parent_cpu_lb + row['phase_full_process_cpu_seconds'], 'C1 CPU bound')
                require(row['cumulative_cpu_upper_bound_seconds'] is None and row['cumulative_full_process_cpu_seconds'] is None,
                        'C1 invented exact CPU')
                interval_count += 1
    require(interval_count == 351, 'C1 interval count')
    reconstructed, audit_rows = {}, []
    for view, include_c1 in [('original42_only', False), ('original42_plus_separate_C1', True)]:
        table = {}
        for cap in [*CUTS, None]:
            output_rows = {}
            for arm in ARMS:
                selected_by_lr, costs, rss, failures, adequate, chains = [], [], [], [], 0, {}
                for lr in LRS:
                    members = []
                    for seed in SEEDS:
                        name = f'{arm}-s{seed}-lr{lr:g}'
                        original, child = fits['original', name], fits.get(('C1', name)) if include_c1 else None
                        rows = by_fit['original', name] + (by_fit['C1', name] if child else [])
                        points = [record_point(row) for row in rows]
                        chosen = best(points, cap)
                        fullwall = original['outer']['whole_process_wall_seconds'] + (child['outer']['whole_process_wall_seconds'] if child else 0)
                        cost = fullwall if cap is None else min(fullwall, cap)
                        terminal = child or original
                        members.append(dict(name=name, seed=seed, observation=chosen,
                                            diagnostic_passed=original['diagnostic_passed'], final_training_adequacy=terminal['training_adequacy_established'],
                                            charged_wall_seconds=cost))
                        costs.append(cost)
                        rss.append(max(original['peak_rss_bytes'], child['peak_rss_bytes'] if child else 0))
                        adequate += terminal['training_adequacy_established']
                        if not original['diagnostic_passed']:
                            failures.append(name)
                        chains[name] = dict(points=points, fullwall=fullwall, terminal=terminal)
                    quality = [m['observation']['quality'] for m in members if m['observation'] is not None]
                    selected_by_lr.append(dict(learning_rate=lr, observed_seed_count=len(quality),
                                               three_seed_mean=statistics.mean(quality) if len(quality) == 3 else None,
                                               sample_standard_deviation=statistics.stdev(quality) if len(quality) == 3 else None, members=members))
                eligible = [c for c in selected_by_lr if c['three_seed_mean'] is not None]
                selected = sorted(eligible, key=lambda c: (-c['three_seed_mean'], c['learning_rate']))[0] if eligible else None
                key = 'final' if cap is None else str(cap)
                observed = next(r for r in result['views'][view]['tables'][key] if r['arm'] == arm)
                require(observed['candidates'] == selected_by_lr, 'budget/member/LR table differs')
                for field, expected in [('selected_common_learning_rate', selected['learning_rate'] if selected else None),
                                        ('selected_three_seed_mean', selected['three_seed_mean'] if selected else None),
                                        ('selected_sample_standard_deviation', selected['sample_standard_deviation'] if selected else None),
                                        ('all_six_complete_attempt_max_RSS_bytes', max(rss)), ('all_six_final_adequate_count', adequate)]:
                    require(observed[field] == expected, 'aggregate field differs: ' + field)
                require(set(observed['all_six_diagnostic_failed_names']) == set(failures), 'diagnostic failures discarded')
                near(observed['all_six_charged_wall_sum_seconds'], math.fsum(costs), 'six-candidate cost', 1e-8)
                if cap is None:
                    crossings, times, selected_ok = {}, [], 0
                    for seed in SEEDS:
                        name = f'{arm}-s{seed}-lr{selected["learning_rate"]:g}'
                        chain = chains[name]
                        crossing = next((p for p in chain['points'] if p['kind'] == 'complete_epoch' and p['quality'] >= .3), None)
                        crossings[name] = dict(name=name, crossing=crossing,
                                               right_censor_outer_wall_seconds=chain['fullwall'] if crossing is None else None)
                        if crossing:
                            times.append(crossing['wall_seconds'])
                        selected_ok += chain['terminal']['training_adequacy_established']
                        require(best(chain['points'])['epoch'] == chain['terminal']['best_epoch'], 'final strict best differs')
                    require({r['name']: r for r in observed['target_crossings']} == crossings, 'target clock/right censoring differs')
                    require(observed['selected_adequate_count'] == selected_ok, 'selected adequacy differs')
                    require(observed['median_first_observed_target_seconds_if_all_cross'] == (statistics.median(times) if len(times) == 3 else None),
                            'target median uses incomplete/censored seeds')
                output_rows[arm] = dict(selected_lr=selected['learning_rate'] if selected else None,
                                        mean=selected['three_seed_mean'] if selected else None,
                                        sd=selected['sample_standard_deviation'] if selected else None,
                                        observed_seeds_by_LR=[c['observed_seed_count'] for c in selected_by_lr],
                                        all_six_wall_sum=math.fsum(costs), all_six_RSS=max(rss), all_six_adequate=adequate,
                                        diagnostic_failures=failures)
                audit_rows.append((view, key, arm))
            table['final' if cap is None else str(cap)] = output_rows
        reconstructed[view] = table
    require(len(audit_rows) == 56, 'view/table coverage')
    require(all(sha(path) == digest for path, digest in inputs.items()), 'review changed inputs')
    verdict = dict(schema='independent-resource-analysis-review-v1', passed=True, findings=[],
                   input_sha256=inputs, producer_imported=False, model_execution=False, training_steps=0,
                   confusion_matrices=2969, CM_metrics_max_absolute_error=metric_error, report_bindings=49,
                   C1_clock_intervals=351, tables_recomputed=56, all_LR_seed_member_records_recomputed=336,
                   views=reconstructed, scientific_admission='HOLD', whole_training_admission=False,
                   limitations=['D is reused for LR/epoch selection; seed variation is initialization variability, not held-out population uncertainty.',
                                'C1 is a distinct adaptive post-cap stage; its extra costs are retained only in the explicitly combined view.',
                                'C1 CPU remains a lower bound and never determines a budget cut.',
                                'RSS is the maximum across all whole candidate attempts, not a target-time memory measurement.',
                                'The costs here cover these candidate chains; separate tuning, qualification and audit overheads remain additional.',
                                'Hash binding trusts the separately frozen/exported raw-report extraction, whose source was statically reviewed; no models were loaded.'],
                   whole_script_wall_seconds=time.monotonic() - started, own_process_CPU_seconds=time.process_time(),
                   computation_CPU_seconds=time.process_time() - cpu0, own_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                   observed_utc=datetime.now(timezone.utc).isoformat())
    (OUT / 'RESULT.json').write_text(json.dumps(verdict, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps(dict(passed=True, result=str(OUT / 'RESULT.json'), sha256=sha(OUT / 'RESULT.json'),
                         wall_seconds=verdict['whole_script_wall_seconds'], cpu_seconds=verdict['computation_CPU_seconds'],
                         HCSN=reconstructed['original42_only']['final']['hcsn'])))


if __name__ == '__main__':
    main()
