"""Post-panel calibration of stored first-FIRE future values.

Reads only existing task ledgers and numeric caches. No model is imported,
no teacher is refitted or solved, and no policy or checkpoint is selected.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PRICES = (.001, .005, .02)
FAMILY = 'tabular_bellman'
BOOTSTRAP_REPLICATES = 19999


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def verify(output):
    registration = read_json(output / 'REGISTRATION.json')
    if registration['schema'] != 'hcsn-task-future-calibration-registration.v1':
        raise ValueError('Unknown analysis registration schema')
    for name, expected in registration['files'].items():
        if sha(ROOT / name) != expected:
            raise ValueError('Registered analysis input changed: ' + name)
    return read_json(output / 'PROTOCOL.json')


def native_panel(source, streams, scope):
    forecasts, outcomes, fire_clocks, identity = [], [], [], None
    rows = []
    for price in PRICES:
        price_forecasts, price_outcomes, price_clocks, price_ids = [], [], [], []
        for stream in range(streams):
            path = source / 'evaluation' / ('price_' + str(price)) / FAMILY / ('stream_' + str(stream)) / 'RESULT.json'
            record = read_json(path)
            context = record['context_identity']
            if (record['status'] != 'completed' or context['family'] != FAMILY
                    or context['price'] != price or context['stream_number'] != stream
                    or context['objective']['discount_per_tick'] != 1.):
                raise ValueError('Executed task identity/objective changed')
            tasks = record['task_results']
            if not tasks or tasks[0]['task_index'] != 0:
                raise ValueError('Missing recorded first FIRE')
            first = tasks[0]
            stops = [event for event in record['events'] if event['kind'] == 'read_and_decide'
                     and event['task_index'] == 0 and event['action'] == 'stop']
            if len(stops) != 1 or stops[0]['clock'] != first['fire_clock']:
                raise ValueError('First FIRE ledger and native action disagree')
            forecast = float(first['teacher_future_after_reset'])
            if stops[0]['teacher_future_after_reset'] != forecast:
                raise ValueError('First FIRE forecast differs across existing ledger entries')
            for task in tasks:
                expected_correct = int(task['prediction'] == task['label'])
                expected_net = expected_correct - price * task['actual_reads']
                if task['correct'] != expected_correct or abs(task['net_reward'] - expected_net) > 1e-12:
                    raise ValueError('Actual task reward is inconsistent with label/read ledger')
            actual = float(sum(task['correct'] - price * task['actual_reads'] for task in tasks[1:]))
            if (abs(actual - record['later_task_net_reward']) > 1e-12
                    or abs(record['utility'] - first['net_reward'] - actual) > 1e-12):
                raise ValueError('Stored actual later reward does not match subsequent tasks')
            price_forecasts.append(forecast)
            price_outcomes.append(actual)
            price_clocks.append(first['fire_clock'])
            price_ids.append(context['source_ids'])
            rows.append({'scope': scope, 'stream': stream, 'price': price,
                         'source_ids': context['source_ids'], 'first_fire_clock': first['fire_clock'],
                         'first_fire_forecast_future': forecast, 'actual_later_net_reward': actual,
                         'error_forecast_minus_actual': forecast - actual,
                         'source_result': relative(path), 'source_sha256': sha(path)})
        if identity is None:
            identity = price_ids
        elif identity != price_ids:
            raise ValueError('Different source queues were paired across prices')
        forecasts.append(price_forecasts)
        outcomes.append(price_outcomes)
        fire_clocks.append(price_clocks)
    return dict(forecast=np.asarray(forecasts), actual=np.asarray(outcomes),
                fire_clock=np.asarray(fire_clocks), source_ids=np.asarray(identity), rows=rows,
                status='available')


def cached_panel(source):
    forecasts, outcomes, clocks, queue_identity, rows = [], [], [], None, []
    metadata = read_json(source / 'data/fresh_mnist.json')
    all_ids = np.asarray(metadata['image_source_ids'])
    for price in PRICES:
        path = source / 'evaluation' / ('price_' + str(price)) / (FAMILY + '_counterfactual.npz')
        if not path.is_file():
            return {'status': 'skipped', 'reason': 'Missing per-stream cache: ' + relative(path)}
        with np.load(path, allow_pickle=False) as archive:
            needed = {'first_fire_predicted_future', 'actual_later_net_reward',
                      'task_reads', 'task_correct', 'fire_clock', 'queues', 'utility'}
            missing = sorted(needed - set(archive.files))
            if missing:
                return {'status': 'skipped', 'reason': 'Missing per-stream fields, no reconstruction from means',
                        'missing_fields': missing, 'path': relative(path)}
            stored = {name: np.array(archive[name], copy=True) for name in needed}
        forecast, actual = stored['first_fire_predicted_future'], stored['actual_later_net_reward']
        if forecast.shape != (128,) or actual.shape != (128,):
            raise ValueError('Unexpected counterfactual stream shape')
        if stored['task_reads'].shape != (128, 3) or stored['task_correct'].shape != (128, 3):
            raise ValueError('Expected three task slots in each stored stream')
        checked = stored['task_correct'][:, 1:].sum(-1) - price * stored['task_reads'][:, 1:].sum(-1)
        checked_total = stored['task_correct'].sum(-1) - price * stored['task_reads'].sum(-1)
        if (not np.allclose(checked, actual, atol=1e-12, rtol=0)
                or not np.allclose(checked_total, stored['utility'], atol=1e-12, rtol=0)):
            raise ValueError('Counterfactual saved rewards do not match saved task ledgers')
        queues = stored['queues']
        if queue_identity is None:
            queue_identity = queues
        elif not np.array_equal(queue_identity, queues):
            raise ValueError('Different cached queues were paired across prices')
        for stream in range(128):
            rows.append({'scope': 'v1_cached128', 'stream': stream, 'price': price,
                         'source_ids': all_ids[queues[stream]].tolist(),
                         'first_fire_clock': int(stored['fire_clock'][stream, 0]),
                         'first_fire_forecast_future': float(forecast[stream]),
                         'actual_later_net_reward': float(actual[stream]),
                         'error_forecast_minus_actual': float(forecast[stream] - actual[stream]),
                         'source_result': relative(path), 'source_sha256': sha(path)})
        forecasts.append(forecast)
        outcomes.append(actual)
        clocks.append(stored['fire_clock'][:, 0])
    return dict(forecast=np.stack(forecasts), actual=np.stack(outcomes),
                fire_clock=np.stack(clocks), source_ids=all_ids[queue_identity],
                rows=rows, status='available')


def summarize(output, name, panel, *, bootstrap_seed=None):
    if panel['status'] != 'available':
        return panel
    forecast, actual = panel['forecast'], panel['actual']
    if forecast.shape != actual.shape or forecast.shape[0] != len(PRICES):
        raise ValueError('Paired forecast/realized dimensions disagree')
    if not np.isfinite(forecast).all() or not np.isfinite(actual).all():
        raise ValueError('Nonfinite recorded forecast or outcome')
    ids = panel['source_ids']
    if len(np.unique(ids)) != ids.size:
        raise ValueError('Duplicate image source inside a panel requires a different cluster unit')
    macro_forecast, macro_actual = forecast.mean(0), actual.mean(0)
    errors = forecast - actual
    macro_error = macro_forecast - macro_actual
    price_absolute_error_mean = np.abs(errors).mean(0)
    np.savez_compressed(output / (name + '_pairs.npz'),
        prices=np.asarray(PRICES), forecast_by_price=forecast, actual_by_price=actual,
        source_ids=ids, first_fire_clock_by_price=panel['fire_clock'],
        macro_forecast=macro_forecast, macro_actual=macro_actual, macro_error=macro_error,
        macro_absolute_error=np.abs(macro_error), per_price_absolute_error_mean=price_absolute_error_mean)
    summary = {
        'status': 'available', 'streams': int(forecast.shape[1]), 'prices': list(PRICES),
        'mean_predicted_future': float(macro_forecast.mean()),
        'mean_actual_later_net_reward': float(macro_actual.mean()),
        'bias_prediction_minus_actual': float(macro_error.mean()),
        'mae_of_price_macro_errors': float(np.abs(macro_error).mean()),
        'mean_of_per_price_absolute_errors': float(price_absolute_error_mean.mean()),
        'macro_forecast_range': [float(macro_forecast.min()), float(macro_forecast.max())],
        'macro_actual_range': [float(macro_actual.min()), float(macro_actual.max())],
        'per_price': {str(price): {
            'mean_predicted_future': float(forecast[p].mean()),
            'mean_actual_later_net_reward': float(actual[p].mean()),
            'bias_prediction_minus_actual': float(errors[p].mean()),
            'mae': float(np.abs(errors[p]).mean()),
            'first_fire_clock_mean': float(panel['fire_clock'][p].mean())}
            for p, price in enumerate(PRICES)},
        'bootstrap': None,
    }
    if bootstrap_seed is not None:
        n = len(macro_error)
        indexes = np.random.default_rng(bootstrap_seed).integers(0, n, size=(BOOTSTRAP_REPLICATES, n))
        bootstrap = dict(
            bias=macro_error[indexes].mean(-1),
            mae_of_price_macro_errors=np.abs(macro_error)[indexes].mean(-1),
            mean_of_per_price_absolute_errors=price_absolute_error_mean[indexes].mean(-1),
            predicted_future=macro_forecast[indexes].mean(-1),
            actual_later_net_reward=macro_actual[indexes].mean(-1))
        np.savez_compressed(output / (name + '_bootstrap.npz'), **bootstrap)
        summary['bootstrap'] = {
            'method': 'nominal descriptive 95% percentile, whole stream after equal three-price macro',
            'replicates': BOOTSTRAP_REPLICATES, 'seed': bootstrap_seed,
            'cluster_count': n, 'confidence_level': .95,
            'intervals': {key: np.quantile(value, [.025, .975]).tolist()
                          for key, value in bootstrap.items()},
            'formal_preregistered_hypothesis_test': False,
        }
    else:
        summary['no_bootstrap_reason'] = 'Two reused-VAL source streams: engineering description only; no population inference'
    return summary


def analyze(output):
    protocol = verify(output)
    source, v2 = ROOT / protocol['source'], ROOT / protocol['v2_source']
    panels = {
        'v1_cached128': cached_panel(source),
        'v1_native16': native_panel(source, 16, 'v1_native16'),
        'v2_engineering2': native_panel(v2, 2, 'v2_engineering2'),
    }
    parity = {'status': 'skipped', 'reason': 'Cached per-stream future fields unavailable'}
    if panels['v1_cached128']['status'] == 'available':
        a, b = panels['v1_cached128'], panels['v1_native16']
        parity = {key: bool(np.allclose(a[key][:, :16], b[key], atol=1e-12, rtol=0))
                  for key in ('forecast', 'actual', 'fire_clock')}
        parity['source_ids_equal'] = bool(np.array_equal(a['source_ids'][:16], b['source_ids']))
        if not all(parity.values()):
            raise ValueError('Matched cached/native forecast-outcome pairs disagree')
        parity['status'] = 'passed'
    summaries = {name: summarize(output, name, panel, bootstrap_seed=seed)
                 for (name, panel), seed in zip(panels.items(), (730151, 730152, None), strict=True)}
    rows = [row for panel in panels.values() if panel['status'] == 'available' for row in panel['rows']]
    write_json(output / 'PAIRED_ROWS.json', rows)
    result = {'schema': 'hcsn-task-future-calibration.v1', 'status': 'completed',
              'registered_post_panel_analysis': True, 'panels': summaries,
              'cached_native_first16_parity': parity,
              'paired_definition': 'Stored first FIRE future_after_reset minus the same executed policy subsequent actual correctness less every later READ price',
              'discount_per_tick': 1., 'first_task_reward_excluded': True,
              'reset_and_refractory_handled_by_existing_deadline_execution': True,
              'scope': 'Marginal prediction calibration on observed streams; no exact neural belief-state claim',
              'new_inference_steps': 0, 'new_training_updates': 0, 'new_dp_solves': 0,
              'new_policy_selection': False}
    verify(output)
    write_json(output / 'SUMMARY.json', result)
    lines = ['# Stored first-FIRE future value: post-panel calibration', '',
        'This separate analysis reads only already sealed per-stream records. It does not refit a teacher, rerun a neural model, solve another Bellman table, select a policy, or change any original result. The larger policy outcomes were already known when this analysis was specified.', '',
        'The forecast is the value assigned at the first FIRE to tasks after reset/refractory. The outcome is that same policy\'s subsequent actual classification correctness minus every subsequent READ charge. The first task reward and first task reads are excluded from both sides. The registered discount is one, so no additional temporal discount is applied here.', '',
        'Positive bias means overprediction: forecast minus actual. For each source stream, predictions and outcomes are first averaged over the three registered prices. Bias and the principal MAE then use this stream-level macro error. A second MAE averages absolute error before price averaging, exposing cancellation across prices. The two definitions are separately named.', '',
        '| Panel | Streams | Mean forecast | Actual later net reward | Bias | Nominal 95% bias interval | Macro-error MAE | Nominal 95% MAE interval | Pricewise MAE average |',
        '| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |']
    for name, value in summaries.items():
        if value['status'] != 'available':
            lines.append('| ' + name + ' | skipped: ' + value['reason'] + ' | | | | | | | |')
            continue
        intervals = value['bootstrap']['intervals'] if value['bootstrap'] else None
        bias_interval = f'[{intervals["bias"][0]:.6f}, {intervals["bias"][1]:.6f}]' if intervals else 'Not estimated'
        mae_interval = f'[{intervals["mae_of_price_macro_errors"][0]:.6f}, {intervals["mae_of_price_macro_errors"][1]:.6f}]' if intervals else 'Not estimated'
        lines.append(f'| {name} | {value["streams"]} | {value["mean_predicted_future"]:.6f} | '
            f'{value["mean_actual_later_net_reward"]:.6f} | {value["bias_prediction_minus_actual"]:.6f} | '
            f'{bias_interval} | {value["mae_of_price_macro_errors"]:.6f} | {mae_interval} | '
            f'{value["mean_of_per_price_absolute_errors"]:.6f} |')
    lines += ['', '## Per-price descriptions', '',
        '| Panel | Price | Forecast | Actual later net reward | Bias | MAE | Mean first FIRE clock |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, value in summaries.items():
        if value['status'] != 'available':
            continue
        for price, row in value['per_price'].items():
            lines.append(f'| {name} | {price} | {row["mean_predicted_future"]:.6f} | '
                f'{row["mean_actual_later_net_reward"]:.6f} | {row["bias_prediction_minus_actual"]:.6f} | '
                f'{row["mae"]:.6f} | {row["first_fire_clock_mean"]:.3f} |')
    lines += ['', '## Interpretation and limits', '',
        'A value formula can correctly include post-reset future tasks while its fitted probabilities, transition model or sufficient-state assumption are wrong. This audit checks marginal forecast errors under the realized policy, not the algebraic inclusion of the future term. The four-bin neural observation state discards hidden state, predicted class and much of the history. TRAIN-fitted Bellman predictions must not be treated as an exact neural belief-state oracle.', '',
        'A nonzero outcome-level MAE alone is not proof of miscalibration: random classification rewards retain irreducible dispersion even under a correct conditional expectation. The signed mean discrepancy and its descriptive interval are the relevant marginal calibration diagnostic here. An interval containing zero also does not establish conditional calibration or the Markov assumption.', '',
        'The bootstrap uses 19,999 whole-stream resamples after the three-price macro, with no independent resampling of prices or individual tasks. Intervals are nominal, descriptive, post-panel and unadjusted for multiple descriptions. Source queues are drawn without replacement from a finite data cohort. The native16 panel is exactly a subset of cached128; their matching pairs are audited but are not independent replications and must not be pooled.', '',
        'The v2 engineering panel uses only two three-image streams from six reused validation images. It receives no confidence interval or population significance claim. Its forecast comes from its own 64-TRAIN-image observation model and differs from the old frozen-v1 planner.', '',
        'PAIRED_ROWS.json and the *_pairs.npz files retain each original forecast/outcome pair, first-FIRE time and image source identity. Bootstrap sample statistics, registration hashes and complete analysis-process costs are retained. No calibration adjustment or policy reselection is performed.', '']
    with (output / 'REPORT.md').open('x') as handle:
        handle.write('\n'.join(lines))


def run(output, source, v2):
    output, source, v2 = Path(output).resolve(), Path(source).resolve(), Path(v2).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if read_json(source / 'EVALUATION_SUMMARY.json')['status'] != 'completed':
        raise ValueError('Original task study is incomplete')
    if read_json(v2 / 'COMPLETE.json')['status'] != 'completed':
        raise ValueError('Original v2 engineering study is incomplete')
    protocol = {
        'schema': 'hcsn-task-future-calibration-protocol.v1', 'source': relative(source),
        'v2_source': relative(v2), 'study_id': output.name, 'family': FAMILY,
        'analysis_timing': 'Post-panel; existing policy outcomes and one ledger example already inspected',
        'prices': list(PRICES), 'native_streams': 16, 'cached_streams': 128, 'v2_engineering_streams': 2,
        'forecast': 'Stored first FIRE teacher_future_after_reset or first_fire_predicted_future',
        'actual': 'Stored actual later net reward, independently checked against per-task correct/read ledgers',
        'error_sign': 'forecast minus actual; positive is overprediction',
        'macro': 'Equal three-price average within each source stream before mean error, principal MAE and bootstrap',
        'additional_mae': 'Average per-price absolute errors within each stream, reported separately to expose cancellation',
        'bootstrap_replicates': BOOTSTRAP_REPLICATES, 'bootstrap_seeds': {'v1_cached128': 730151, 'v1_native16': 730152},
        'bootstrap': 'Nominal descriptive two-sided 95% percentile over whole streams',
        'v2_bootstrap': False, 'cached_if_missing_fields': 'Skip, never fabricate per-stream values from aggregate means',
        'new_inference': False, 'new_training': False, 'new_solver': False, 'new_selection': False,
    }
    write_json(output / 'PROTOCOL.json', protocol)
    files = [Path(__file__).resolve(), output / 'PROTOCOL.json',
             *[source / name for name in ('PROTOCOL.json', 'REGISTRATION.json', 'SELECTION_LOCK.json',
                                          'EVALUATION_SUMMARY.json', 'AUDIT.json', 'data/fresh_mnist.json')],
             *[v2 / name for name in ('PROTOCOL.json', 'REGISTRATION.json', 'TEACHER_LOCK.json',
                                      'COMPLETE.json', 'EVALUATION_SUMMARY.json')],
             *[Path(__file__).with_name(name) for name in ('task_value.py', 'task_value_heads.py', 'task_value_native.py')]]
    for price in PRICES:
        cache = source / 'evaluation' / ('price_' + str(price)) / (FAMILY + '_counterfactual.npz')
        if cache.is_file():
            files.append(cache)
        for base, count in ((source, 16), (v2, 2)):
            files += [base / 'evaluation' / ('price_' + str(price)) / FAMILY / ('stream_' + str(stream)) / 'RESULT.json'
                      for stream in range(count)]
    snapshot = output / 'registered_source'
    snapshot.mkdir()
    copied = snapshot / Path(__file__).name
    shutil.copy2(__file__, copied)
    files.append(copied)
    write_json(output / 'REGISTRATION.json', {
        'schema': 'hcsn-task-future-calibration-registration.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'files': {relative(path): sha(path) for path in files},
        'registration_is_post_panel_not_preregistration': True})
    command = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.task_future_calibration',
               '--worker', '--output', str(output)]
    start = time.monotonic()
    with (output / 'analysis.log').open('x') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    execution = {'command': command, 'exit_code': child.returncode,
                 'complete_child_cpu_seconds': usage.ru_utime + usage.ru_stime,
                 'wall_seconds': time.monotonic() - start, 'peak_rss_kib_linux': usage.ru_maxrss,
                 'scope': 'Complete read-only numerical analysis worker including imports; no neural/model/solver calls'}
    write_json(output / 'EXECUTION.json', execution)
    if child.returncode:
        raise RuntimeError('Read-only analysis failed; log and costs retained')
    verify(output)
    write_json(output / 'COMPLETE.json', {
        'status': 'completed', 'source_inputs_unchanged': True,
        'outputs': {str(path.relative_to(output)): sha(path)
                    for path in sorted(output.iterdir()) if path.is_file()},
        'complete_worker_cpu_seconds': execution['complete_child_cpu_seconds'],
        'coordinator_self_cpu_through_cutoff': time.process_time(),
        'new_model_inference_steps': 0, 'new_training_updates': 0, 'new_bellman_solves': 0})
    print(json.dumps({'status': 'completed', 'output': str(output),
                      'analysis_cpu_seconds': execution['complete_child_cpu_seconds']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--v2-source', type=Path)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        analyze(args.output.resolve())
    else:
        success, error = False, None
        try:
            if args.source is None or args.v2_source is None:
                raise ValueError('Both sealed source studies must be supplied')
            run(args.output, args.source, args.v2_source)
            success = True
        except Exception as caught:
            error = {'type': type(caught).__name__, 'message': str(caught)}
            raise
        finally:
            if args.output.is_dir():
                write_json(args.output / 'PARENT_EXECUTION.json', {
                    'status': 'completed' if success else 'failed', 'failure': error,
                    'whole_self_cpu_seconds_through_cutoff': time.process_time(),
                    'scope': 'Coordinator self CPU includes imports, registration and audit; add complete worker CPU once'})
