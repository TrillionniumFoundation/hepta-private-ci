"""Build a source-bound, descriptive report; never fit or select a model.

Scientific sources and prepared data are verified before and after rendering.
Only README.md and evidence/figures are written. This reporting helper is not
part of the frozen scientific source inventory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from ..freeze import verify
from .bind_calibration_review import confirmation_inventory, object_sha

PROJECT = Path(__file__).resolve().parent.parent
REPO = PROJECT.parents[2]
SOURCE_COMMIT = '65df1c8166c8ed370ab6773522186b2b783c94e3'
FREEZE_SHA256 = 'e7fd9c474e0c4a0ad56ad910a643ab84970da430600e6f8caccae2849c824c2d'
LABELS = {'frozen': 'Frozen anchor', 'replay': 'Selected replay Gaussian',
          'mixture_zero': 'Exact mixture / no context', 'moment_zero': 'Gaussian moment / no context',
          'mixture_context': 'Exact mixture / 8 histories', 'moment_context': 'Fitted Gaussian moment / 8 histories',
          'same_weight_moment': 'Same-weight Gaussian projection', 'mixture_classical': 'Dense classical mixture',
          'mixture_q24': 'Mixture / parameter Q24', 'mixture_q24_classical': 'Dense classical / parameter Q24',
          'event': 'Signed event packet', 'direct': 'Absolute integer packet', 'float': 'FP64 packet',
          'gaussian': 'Fitted K1 Gaussian', 'probit': 'Dense K1 / probit',
          'analytic': 'Analytic sparse readout', 'numeric': 'Numeric sparse readout', 'history': 'History readout'}


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_calibration_review(run):
    binding = load(run / 'reviews/CALIBRATION_CONFIRM_REVIEW_BINDING.json')
    current = confirmation_inventory(run)
    bound_path = run / binding['bound_review_path']
    review = load(bound_path)
    required = (
        binding.get('passed') is True,
        binding.get('bound_review_passed') is True,
        binding.get('before_after_identical') is True,
        binding.get('source_commit') == SOURCE_COMMIT,
        binding.get('freeze_sha256') == FREEZE_SHA256,
        binding.get('results_sha256') == sha(run / 'calibration_confirmation/RESULTS.json'),
        binding.get('prepared_sha256') == sha(run / 'calibration_prepared/PREPARED.json'),
        binding.get('bound_review_sha256') == sha(bound_path),
        binding.get('original_review_sha256') == sha(run / binding['original_review_path']),
        binding.get('reviewer_source_sha256') == sha(Path(__file__).with_name('review_calibration.py')),
        binding.get('binding_wrapper_sha256') == sha(Path(__file__).with_name('bind_calibration_review.py')),
        binding.get('started_receipt_sha256') == sha(run / binding['started_receipt_path']),
        binding.get('confirmation_files_sha256') == {name: row['sha256'] for name, row in current.items()},
        binding.get('confirmation_file_bytes') == {name: row['bytes'] for name, row in current.items()},
        binding.get('before_confirmation_inventory_sha256') == object_sha(current),
        binding.get('after_confirmation_inventory_sha256') == object_sha(current),
        binding.get('confirmation_file_count') == len(current),
        binding.get('confirmation_total_file_bytes') == sum(row['bytes'] for row in current.values()),
        review.get('passed') is True,
        review.get('phase') == 'confirm',
        review.get('reviewer_source_sha256') == binding.get('reviewer_source_sha256'),
        review.get('prepared_sha256') == binding.get('prepared_sha256'),
    )
    if not all(required):
        raise ValueError('Current calibration bytes require the preserved fresh before/after review binding')
    return review, binding


def verified_runtime_review(run):
    runtime_path = run / 'RUNTIME_RESULTS.json'
    review_path = run / 'reviews/RUNTIME_FINAL_REVIEW.json'
    runtime, audit = load(runtime_path), load(review_path)
    if (not runtime['complete'] or not audit['passed'] or audit.get('results_sha256') != sha(runtime_path)
            or audit.get('freeze_sha256') != FREEZE_SHA256 or audit.get('source_commit') != SOURCE_COMMIT
            or audit.get('reviewer_sha256') != sha(Path(__file__).with_name('review_runtime_final.py'))):
        raise ValueError('Complete, source-bound independent runtime results are required')
    bound = {str(path.relative_to(run)): sha(path) for path in (runtime_path, review_path)}
    recovery = audit['runtime_recovery']
    if recovery['path'] != 'runtime_recovery_v2/COMPLETED.json':
        raise ValueError('The completed serial recovery must be independently reviewed')
    recovery_path = run / recovery['path']
    receipt = load(recovery_path)
    if (sha(recovery_path) != recovery['sha256'] or receipt != recovery['receipt']
            or not receipt['passed'] or receipt['runtime_results_sha256'] != sha(runtime_path)):
        raise ValueError('Completed recovery receipt/result binding differs')
    bound[recovery['path']] = recovery['sha256']
    incidents = audit['interrupted_attempts']['main_receipts']
    if {item['path'] for item in incidents} != {'RUNTIME_INTERRUPTION.json', 'RUNTIME_SECOND_INTERRUPTION.json'}:
        raise ValueError('Both interrupted attempts must remain explicitly bound')
    for item in incidents:
        if sha(run / item['path']) != item['sha256']:
            raise ValueError('An interruption receipt changed after independent review')
        bound[item['path']] = item['sha256']
    scoring = audit['scoring_only_recovery2017']
    scoring_path = run / scoring['path']
    scoring_receipt = load(scoring_path)
    if (scoring['path'] != 'runtime_recovery_v2/SCORING_RECOVERY_seed_2017.json'
            or sha(scoring_path) != scoring['sha256'] or scoring_receipt != scoring['receipt']
            or not scoring_receipt['passed'] or not scoring_receipt['original_inputs_unchanged']
            or not scoring_receipt['reused_in_completed_cohort'] or scoring_receipt['reexecuted_policy']
            or not scoring_receipt['count_completed_worker_native_cost_once_in_formal_cohort']
            or scoring_receipt['original_outer_wall_ns'] is not None
            or scoring_receipt['original_outer_cpu_ns'] is not None
            or scoring_receipt['original_outer_exit_code'] is not None
            or scoring_receipt['scoring_recovery']['native_requests'] != 0
            or scoring_receipt['scoring_recovery']['native_ticks'] != 0):
        raise ValueError('Reused worker/scoring provenance or cost scope differs')
    bound[scoring['path']] = scoring['sha256']
    directory = run / 'runtime_confirmation/seed_2017'
    original_inputs = dict(scoring_receipt['inputs_sha256'])
    original_inputs.update({'ROWS.json.gz': scoring_receipt['scored_rows_sha256'],
                            'SUMMARY.json': scoring_receipt['summary_sha256']})
    for name, digest in original_inputs.items():
        path = directory / name
        if sha(path) != digest:
            raise ValueError('Reused worker or recovered score bytes changed')
        bound[str(path.relative_to(run))] = digest
    return runtime, audit, bound


def number(value, places=6):
    if value is None:
        return 'Unmeasured / unavailable'
    if isinstance(value, (int, np.integer)):
        return f'{value:,}'
    if abs(value) < 1e-5 and value != 0:
        return f'{value:.4e}'
    return f'{value:.{places}f}'


def delta(value, places=6):
    return f'{value:+.{places}f}' if abs(value) >= 1e-5 or value == 0 else f'{value:+.4e}'


def bounds(values, places=6):
    return '[' + ', '.join(delta(x, places) for x in values) + ']'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                      *['| ' + ' | '.join(str(cell).replace('|', '\\|').replace('\n', ' ') for cell in row) + ' |' for row in rows]])


def status(value):
    return 'PASS' if value else '**FAIL**'


def setup_style():
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.titlesize': 12,
                         'axes.labelsize': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.hashsalt': 'hepta-analytic-event-round4', 'savefig.facecolor': 'white'})


def save_figure(fig, name):
    target = PROJECT / 'evidence/figures'
    target.mkdir(parents=True, exist_ok=True)
    fig.savefig(target / (name + '.png'), dpi=220, bbox_inches='tight', metadata={'Software': 'Hepta Round 4 report'})
    fig.savefig(target / (name + '.svg'), bbox_inches='tight', metadata={'Date': None, 'Creator': 'Hepta Round 4 report'})
    plt.close(fig)


def calibration_figure(result):
    setup_style()
    names = ['frozen', 'replay', 'mixture_zero', 'moment_zero', 'mixture_context', 'moment_context', 'mixture_q24']
    labels = ['Frozen anchor', 'Replay Gaussian', 'Exact mixture\nno context', 'Gaussian moment\nno context',
              'Exact mixture\n8 public histories', 'Gaussian moment\n8 public histories', 'Mixture parameter Q24\n8 public histories']
    colors = ['#8796a5', '#8796a5', '#c47a30', '#c47a30', '#176b9c', '#176b9c', '#765a9c']
    y = np.arange(len(names))
    fig, axes = plt.subplots(2, 2, figsize=(14, 10.8), constrained_layout=True)
    fig.suptitle('Round 4: calibration improves with additional public history\nOriginal-information and context profiles retain separate acceptance gates', fontsize=16)
    a, b, c, d = axes.flat
    eces = [result['arms'][name]['pooled_shifted_classwise_ece'] for name in names]
    a.barh(y, eces, color=colors, height=.62)
    a.axvline(.04, color='#ad3d40', ls='--', lw=1.4, label='Registered limit 0.04')
    a.set_xlim(0, .075)
    a.set_title('A  Shifted classwise ECE (lower is better)', loc='left', fontweight='bold')
    for i, value in enumerate(eces):
        a.text(value + .001, i, f'{value:.4f}', va='center', fontsize=9)
    a.legend(loc='lower right', frameon=False, fontsize=9)
    coverage = [result['arms'][name]['pooled_shifted_coverage95'] for name in names]
    b.axvspan(.92, .98, color='#3c9567', alpha=.12, label='Accepted coverage [0.92, 0.98]')
    b.axvline(.95, color='#6e7881', ls=':', lw=1)
    b.scatter(coverage, y, c=colors, s=55, zorder=3)
    b.set_xlim(.87, 1.005)
    b.set_title('B  Coverage of the central 95% interval', loc='left', fontweight='bold')
    for i, value in enumerate(coverage):
        b.text(value + .002, i, f'{value:.4f}', va='center', fontsize=9)
    b.legend(loc='lower right', frameon=False, fontsize=9)
    average = [result['arms'][name]['worst_cross_seed_mean_old_nll_increase'] for name in names]
    individual = [result['arms'][name]['worst_single_seed_window_old_nll_increase'] for name in names]
    c.barh(y, average, color=colors, height=.6, label='Worst seed-averaged window')
    c.scatter(individual, y, marker='x', color='#ad3d40', s=48, linewidths=1.8, label='Worst individual seed/window', zorder=3)
    c.axvline(.02, color='#ad3d40', ls='--', lw=1.2)
    c.set_xlim(-.001, .041)
    c.set_title('C  Old-task NLL increase: distinct retention scopes', loc='left', fontweight='bold')
    c.set_xlabel('NLL change from the original anchor')
    c.legend(loc='lower right', frameon=False, fontsize=8.5)
    for i, name in enumerate(names):
        contrast = result['arms'][name]['final_new_nll_difference']
        mean, (lo, hi) = contrast['mean_difference'], contrast['interval']
        d.errorbar(mean, i, xerr=[[mean-lo], [hi-mean]], fmt='o', color=colors[i], capsize=3, ms=5)
    d.axvline(0, color='#6e7881', lw=1)
    d.set_xlim(-.215, .012)
    d.set_title('D  Final-new NLL change from the anchor', loc='left', fontweight='bold')
    d.set_xlabel('Negative means improved density prediction')
    for axis in (a, b, c, d):
        axis.set_yticks(y, labels)
        axis.set_ylim(len(names)+.35, -.55)
        axis.grid(axis='x', color='#e5e9ed', lw=.7, zorder=0)
        axis.set_axisbelow(True)
        axis.spines['left'].set_visible(False)
        axis.tick_params(axis='y', length=0)
    fig.get_layout_engine().set(h_pad=.18, w_pad=.18, hspace=.11, wspace=.10)
    fig.text(.5, -.015, 'Five trained seeds; 12 fixed windows. Original old blocks are reused. Context adds 8 prior public histories per query.\nPanel D: exact no-context/context primary profiles use 97.5% intervals; other intervals are descriptive 95%. Full results retain all 10 arms.',
             ha='center', va='top', fontsize=9, color='#46535d')
    save_figure(fig, 'calibration_retention')


def runtime_figure(result):
    setup_style()
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 5.4), constrained_layout=True, gridspec_kw={'width_ratios': [1.15, 1, 1]})
    fig.suptitle('Round 4: utility preservation and measured packet/execution costs', fontsize=16)
    a, b, c = axes
    keys = ['event_vs_direct', 'event_vs_float']
    labels = ['Event − absolute integer', 'Event − FP64 packet']
    for i, key in enumerate(keys):
        row = result['utility_contrasts'][key]
        mean, (lo, hi) = row['mean_difference'], row['interval']
        a.errorbar(mean, i, xerr=[[mean-lo], [hi-mean]], fmt='o', color='#176b9c', capsize=4)
        a.annotate(f'{mean:+.6f}', (mean, i), xytext=(5, 10), textcoords='offset points', fontsize=9)
    a.axvline(-.01, color='#ad3d40', ls='--', lw=1.3, label='Noninferiority margin −0.01')
    a.axvline(0, color='#75808a', lw=.8)
    left = min(-.01, *(result['utility_contrasts'][key]['interval'][0] for key in keys))
    right = max(0, *(result['utility_contrasts'][key]['interval'][1] for key in keys))
    padding = max(.00025, (right-left)*.12)
    a.set_xlim(left-padding, right+padding)
    a.set_ylim(1.45, -.6)
    a.set_yticks(range(2), labels)
    a.set_title('A  Paired utility differences (97.5% CI)', loc='left', fontweight='bold')
    a.set_xlabel('Event utility minus comparator utility')
    a.legend(loc='lower left', frameon=False, fontsize=8.5)
    names, short = ['event', 'direct', 'float'], ['Event', 'Absolute\ninteger', 'FP64\npacket']
    for axis, metric, factor, title, ylabel, places in (
        (b, 'packet_bytes', 1, 'B  Complete transmitted frame bytes', 'Mean bytes per executed trajectory', 2),
        (c, 'wall_ns', 1e-6, 'C  Execution before archival', 'Mean wall time before archival (ms)', 2)):
        values = [result['metrics'][name][metric] * factor for name in names]
        axis.bar(range(3), values, color=['#176b9c', '#5d8ba5', '#8796a5'], width=.62)
        axis.set_xticks(range(3), short)
        axis.set_ylim(0, max(values) * 1.24)
        axis.set_title(title, loc='left', fontweight='bold')
        axis.set_ylabel(ylabel)
        for i, value in enumerate(values):
            axis.text(i, value + max(values) * .035, f'{value:.{places}f}', ha='center', fontsize=10)
    for axis in axes:
        axis.grid(axis='x' if axis is a else 'y', color='#e5e9ed', lw=.7)
        axis.set_axisbelow(True)
    fig.text(.5, -.035, 'Paired random arm order; five seeds, 1,280 independent trajectories. Shared-host timings include mixed concurrency across seeds.\nExecution ends after final readback and receipt persistence; subsequent ZIP compression/verification/cleanup is excluded.\nFP64 denotes the eligible packet profile: K−1 weights are stored and the final weight is reconstructed; native head parameters still use Q24.',
             ha='center', va='top', fontsize=9, color='#46535d')
    save_figure(fig, 'runtime_tradeoffs')


def runtime_tables(runtime):
    rows = []
    for name, item in runtime['metrics'].items():
        rows.append([LABELS[name], number(item['utility']), number(item['squared_error']), number(item['cost']),
                     number(item['packet_bytes'], 2), number(item['wall_ns'] / 1e6, 3),
                     f"{item['waits']:,} / {item['repairs']:,}"])
    performance = table(['Arm', 'Mean utility', 'Squared error', 'Paid task cost', 'Frame bytes / execution',
                         'Wall before archival (ms)', 'Waits / repairs'], rows)
    contrast_rows = []
    for key, item in runtime['utility_contrasts'].items():
        left, right = key.split('_vs_')
        contrast_rows.append([LABELS[left] + ' − ' + LABELS[right], delta(item['mean_difference']), bounds(item['interval']),
                              '97.5% primary' if item['primary_noninferiority'] else '95% descriptive',
                              status(item['passes_noninferiority']) if item['primary_noninferiority'] else 'No registered superiority claim'])
    contrasts = table(['Comparison', 'Utility difference', 'Paired interval', 'Scope', 'Registered decision'], contrast_rows)
    cost_rows = []
    for comparison, metrics in runtime['descriptive_paired_cost_contrasts'].items():
        for metric in ('packet_bytes', 'wall_ns', 'cpu_ns', 'native_roundtrip_ns'):
            item = metrics[metric]
            scale = 1 if metric == 'packet_bytes' else 1e-6
            cost_rows.append([comparison.replace('_vs_', ' − '), metric.replace('_ns', ' (ms)').replace('_', ' '),
                              delta(item['mean_difference'] * scale), bounds([v * scale for v in item['interval']]),
                              '95% descriptive'])
    costs = table(['Comparison', 'Measured endpoint', 'Mean difference', 'Interval', 'Status'], cost_rows)
    tail_rows = []
    for name, item in runtime['metrics'].items():
        tail_rows.append([LABELS[name], number(item['initial_classwise_ece']), number(item['initial_exact_mixture_95_coverage']),
                          number(item['initial_physical_event_nll']), number(item['initial_released_event_nll']),
                          item['raw_q24_any_zero_rows'], item['raw_q24_true_event_zero_rows'], item['released_zero_forecasts'],
                          number(item['max_native_to_released_coordinate_error'])])
    tails = table(['Arm', 'Initial ECE', 'Initial coverage', 'Effective-law event NLL', 'Released event NLL',
                   'Raw zero-category rows', 'Raw true-event zeros', 'Released zero forecasts', 'Max final-release error'], tail_rows)
    return performance, contrasts, costs, tails


def calibration_tables(result):
    rows, mechanisms = [], []
    for name in result['registration']['arms']:
        item = result['arms'][name]
        rows.append([LABELS[name], delta(item['worst_cross_seed_mean_old_nll_increase']),
                     delta(item['worst_single_seed_window_old_nll_increase']),
                     delta(item['final_new_nll_difference']['mean_difference']),
                     bounds(item['final_new_nll_difference']['interval']), number(item['pooled_shifted_classwise_ece']),
                     number(item['pooled_shifted_coverage95']), status(item['passes_joint_empirical_gate'])])
    for key, item in result['mechanism_comparisons'].items():
        left, right = key.split('_minus_')
        mechanisms.append([LABELS[left] + ' − ' + LABELS[right], delta(item['mean_difference']), bounds(item['interval'])])
    return table(['Arm', 'Worst old seed mean', 'Worst old individual', 'Final-new NLL Δ', 'Interval', 'Shifted ECE', 'Coverage', 'Joint gate'], rows), table(['Head comparison on six drift windows', 'Density NLL difference', 'Descriptive 95% interval'], mechanisms)


def wrapper_table(run):
    paths = sorted((run / 'execution').glob('*_COMPLETED.json'))
    rows = []
    for path in paths:
        item = load(path)
        if any(word in item['label'] for word in ('report_build', 'render_report')):
            continue
        rows.append([item['label'], item['returncode'], number(item['wall_ns'] / 1e9, 3),
                     number(item['children_user_seconds'], 3), number(item['children_system_seconds'], 3)])
    return table(['Captured invocation', 'Exit', 'Elapsed wall (s)', 'Child user CPU (s)', 'Child system CPU (s)'], rows)


def interruption_table(audit):
    attempts = audit['interrupted_attempts']['attempts']
    if not attempts:
        return 'No interrupted invocation receipt is present.'
    rows = []
    for attempt in attempts:
        if attempt.get('reused_in_completed_cohort'):
            accounting = 'Complete worker reused; charged once in formal cohort'
        elif attempt.get('overlapping_parent_scope'):
            accounting = 'Nested parent scope; do not add child work again'
        else:
            accounting = 'Discarded partial work; additional attempted cost'
        rows.append([attempt['original_label'],
                     number(attempt['observed_lifetime_lower_bound_seconds'], 3),
                     number(attempt['detected_stopped_lifetime_upper_bound_seconds'], 3),
                     number(attempt['retained_file_bytes']),
                     number(attempt['exit_code']), number(attempt['total_cpu_seconds']), accounting])
    return table(['Interrupted invocation', 'Lifetime lower bound (s)', 'Lifetime upper bound (s)',
                  'Retained evidence bytes', 'Exit', 'Whole invocation CPU (s)', 'Accounting scope'], rows)


def runtime_phase_table(runtime):
    """Display nested scopes without silently adding them or replacing nulls."""
    def seconds(value):
        return number(value / 1e9, 3) if value is not None else number(None)

    rows = []
    for scope in runtime['scopes']:
        execution = scope['execution']
        worker = execution['worker']
        scoring = execution.get('scoring_recovery', {})
        rows.append([scope['seed'], seconds(worker['wall_ns']), seconds(worker['cpu_ns']),
                     seconds(execution['wall_ns']), seconds(execution['cpu_ns']),
                     seconds(scoring.get('wall_ns')) if scoring else 'Included in completed parent',
                     seconds(scoring.get('cpu_ns')) if scoring else 'Included in completed parent'])
    return table(['Seed', 'Worker wall incl. archival (s)', 'Worker Python CPU (s)',
                  'Original confirmation parent wall (s)', 'Original parent Python CPU (s)',
                  'Recovered scoring wall (s)', 'Recovered scoring Python CPU (s)'], rows)


def scalar_flatten(value, prefix=''):
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(scalar_flatten(child, prefix + '.' + key if prefix else key))
    elif isinstance(value, list):
        if len(value) <= 8 and all(not isinstance(x, (dict, list)) for x in value):
            rows.append((prefix, json.dumps(value)))
    elif isinstance(value, (int, float)) or value is None or isinstance(value, bool):
        rows.append((prefix, 'Unknown / unmeasured' if value is None else str(value)))
    return rows


def accounting_tables(audit):
    accounting = audit['serialized_write_accounting']
    arms = accounting['formal_confirmation_per_arm']
    writes, retained, operations = [], [], []
    for arm, row in arms.items():
        writes.append([LABELS[arm], *[number(row[key]) for key in (
            'packet_serialized_write_bytes', 'adapter_pending_serialized_write_bytes',
            'adapter_state_serialized_write_bytes', 'adapter_witness_serialized_write_bytes',
            'adapter_cumulative_serialized_write_bytes')]])
        retained.append([LABELS[arm], *[number(row[key]) for key in (
            'adapter_final_state_retained_bytes', 'adapter_final_witness_retained_bytes',
            'native_journal_tick_receipt_write_bytes', 'native_journal_retained_file_bytes',
            'native_witness_retained_file_bytes', 'native_journal_extra_retained_bytes_outside_tick_receipts')]])
        operations.append([LABELS[arm], *[number(row[key]) for key in (
            'owners_reconstructed', 'packet_write_operations', 'adapter_pending_write_operations',
            'adapter_state_write_operations', 'adapter_witness_write_operations')]])
    sections = [
        '#### Completed formal cohort: serialized payload bytes\n\n' + table(
            ['Arm', 'Complete packets', 'Adapter pending', 'Adapter state', 'Adapter witness', 'Adapter cumulative (excludes packets)'], writes),
        '#### Completed formal cohort: retained files and observed native tick writes\n\n' + table(
            ['Arm', 'Final adapter state', 'Final adapter witness', 'Native tick-receipt writes',
             'Retained native journals', 'Retained native witnesses', 'Retained journal bytes outside tick receipts'], retained),
        '#### Completed formal cohort: successful owner/write counts\n\n' + table(
            ['Arm', 'Owners', 'Packet writes', 'Pending writes', 'State writes', 'Witness writes'], operations)]
    shared = accounting['shared_preparation']
    preparation = []
    for split, row in shared['per_split'].items():
        archives = [scope for scope in shared['scopes'] if scope['split'] == split]
        preparation.append([split, *[number(row[key]) for key in (
            'owners_reconstructed', 'packet_serialized_write_bytes', 'adapter_cumulative_serialized_write_bytes',
            'native_journal_tick_receipt_write_bytes')],
            number(sum(scope['archive_bytes'] for scope in archives)),
            number(sum(scope['archive_uncompressed_member_bytes'] for scope in archives))])
    sections.append('#### Shared preparation, counted once across fitted heads\n\n' + table(
        ['Split', 'Owners', 'Complete packet bytes', 'Cumulative adapter bytes',
         'Native tick-receipt bytes', 'ZIP bytes', 'Uncompressed member bytes'], preparation))
    archive_rows = [[scope['seed'], number(scope['archive_bytes']), number(scope['archive_uncompressed_member_bytes']),
                     number(scope['replay_archive_bytes']), number(scope['qualification_archive_bytes'])]
                    for scope in audit['scopes']]
    sections.append('#### Completed runtime archives\n\n' + table(
        ['Seed', 'Formal ZIP bytes', 'Formal uncompressed member bytes', 'Native-replay ZIP bytes', 'Qualification ZIP bytes'], archive_rows))
    unknown_names = {
        'qualification_adapter_cumulative_write_bytes': 'Qualification fault/recovery adapter writes',
        'native_journal_cumulative_write_bytes': 'All native journal writes including initialization',
        'native_witness_cumulative_write_bytes': 'All native witness writes',
        'filesystem_metadata_or_journaling_write_amplification_bytes': 'Filesystem metadata / journaling amplification',
        'physical_device_bytes': 'Physical device bytes', 'hardware_energy': 'Hardware energy'}
    sections.append('#### Quantities without complete observation\n\n' + table(
        ['Quantity', 'Recorded value'], [[name, number(accounting.get(key))] for key, name in unknown_names.items()]))
    return '\n\n'.join(sections)


def generate(run, runtime, audit, frozen):
    cal = load(run / 'calibration_confirmation/RESULTS.json')
    cal_review, cal_binding = verified_calibration_review(run)
    prepared_review = load(run / 'reviews/CALIBRATION_PREPARE_REVIEW.json')
    prefreeze = load(run / 'validation/PREFREEZE_REVIEW.json')
    publication = load(run / 'PRECONFIRMATION_PUBLICATION.json')
    math = prefreeze['math_reference']
    if load(run / 'MATH_REFERENCE.json') != math or load(PROJECT / 'evidence/MATH_REFERENCE.json') != math:
        raise ValueError('Standalone mathematical reference differs from the bound prefreeze review')
    calibration_table, mechanism_table = calibration_tables(cal)
    runtime_table, utility_table, cost_table, tails_table = runtime_tables(runtime)
    quantum_table = table(['Coordinate', 'Logical integer quantum units'],
                          [[key.replace('_', ' '), number(value)] for key, value in runtime['event_integer_quantum_units'].items()])
    q = runtime['acceptance']
    qualification = [scope['qualification'] for scope in runtime['scopes']]
    groups = len(math['checks'])
    ordinary = sum(x['ordinary_forecasts'] for x in qualification)
    fresh = sum(x['fresh_processes'] for x in qualification)
    bridge = sum(x['calibration_bridge_forecasts'] for x in qualification)
    tail_count = sum(x['tails'] for x in qualification)
    traces = [load(run / 'runtime_prepared' / f'seed_{seed}' / 'TRAINING_RECEIPT.json') for seed in runtime['seeds']]
    trained_heads = [fit for receipt in traces for fit in receipt['fits'].values()]
    fitted_change = min(x['parameter_l2_change'] for x in trained_heads)
    runtime_acceptance = table(['Runtime requirement', 'Result'], [[key.replace('_', ' '), status(value)] for key, value in q.items() if key != 'production_promotion'])
    math_rows = []
    for name, item in math['checks'].items():
        detail = {key: value for key, value in item.items() if key in ('cases', 'rows', 'histories', 'models', 'maximum_absolute_error', 'maximum_errors', 'maximum_quantile_cdf_error', 'event_steps', 'maximum_error')}
        math_rows.append([name.replace('_', ' '), status(item['pass']), '`' + json.dumps(detail, sort_keys=True) + '`'])
    math_table = table(['Independent numerical check', 'Result', 'Selected measured detail'], math_rows)
    accounting_table = accounting_tables(audit)
    float_table = table(['FP64 packet diagnostic', 'Value'], scalar_flatten(audit.get('float_transport_corpus_weight_diagnostics', {})))
    scope_rows = []
    audited_scopes = {scope['seed']: scope for scope in audit['scopes']}
    totals = np.zeros(10, dtype=np.int64)
    for scope in runtime['scopes']:
        tr, ex, replay = scope['training']['native'], scope['execution']['worker']['native'], scope['audit']['native_replay']
        q_scope = scope['qualification']
        qn = q_scope['in_process_native']
        fresh_native = audited_scopes[scope['seed']]['qualification_fresh_process_native']
        values = [tr['requests'], tr['ticks'], ex['requests'], ex['ticks'], replay['requests'], replay['ticks'],
                  qn['requests'], qn['ticks'], fresh_native['requests'], fresh_native['ticks']]
        totals += values
        scope_rows.append([scope['seed'], f"{values[0]:,} / {values[1]:,}", f"{values[2]:,} / {values[3]:,}",
                           f"{values[4]:,} / {values[5]:,}", f"{values[6]:,} / {values[7]:,}", f"{values[8]:,} / {values[9]:,}"])
    scope_rows.append(['Total', *[f'{totals[j]:,} / {totals[j+1]:,}' for j in (0, 2, 4, 6, 8)]])
    scope_table = table(['Seed', 'Shared preparation requests/ticks', 'Formal cohort requests/ticks',
                         'Formal native replay requests/ticks', 'Qualification in-process requests/ticks', 'Fresh-process qualification requests/ticks'], scope_rows)
    preparation_review_path = run / 'reviews/RUNTIME_PREPARE_REVIEW.json'
    if not preparation_review_path.exists():
        preparation_review_path = PROJECT / 'evidence/RUNTIME_PREPARE_REVIEW.json'
    preparation_replay = load(preparation_review_path)
    prep_requests = sum(row['native_replay']['requests'] for row in preparation_replay['scopes'])
    prep_ticks = sum(row['native_replay']['ticks'] for row in preparation_replay['scopes'])
    hashes = table(['Artifact', 'SHA256'], [[name, '`' + sha(path) + '`'] for name, path in [
        ('Calibration results', run / 'calibration_confirmation/RESULTS.json'),
        ('Original calibration independent review', run / 'reviews/CALIBRATION_CONFIRM_REVIEW.json'),
        ('Fresh calibration independent review', run / 'reviews/CALIBRATION_CONFIRM_REVIEW_BOUND.json'),
        ('Current calibration before/after binding', run / 'reviews/CALIBRATION_CONFIRM_REVIEW_BINDING.json'),
        ('Runtime results', run / 'RUNTIME_RESULTS.json'),
        ('Runtime independent review', run / 'reviews/RUNTIME_FINAL_REVIEW.json'),
        ('Completed serial recovery', run / 'runtime_recovery_v2/COMPLETED.json'),
        ('Reused-worker scoring recovery', run / 'runtime_recovery_v2/SCORING_RECOVERY_seed_2017.json'),
        ('First interruption receipt', run / 'RUNTIME_INTERRUPTION.json'),
        ('Second interruption receipt', run / 'RUNTIME_SECOND_INTERRUPTION.json'),
        ('Immutable freeze', run / 'FREEZE.json')]])
    primary_event = runtime['utility_contrasts']['event_vs_float']
    content = f'''# Round 4 — exact conditional laws, bounded public context and packed native feedback

## Outcome and scope

The registered Round 4 implementations, fresh preparation, confirmation execution and independent reviews are complete. **The original-information calibration profile still fails its joint gate. The separately registered eight-history context profile passes.** A fitted Gaussian moment model with the same context also passes, so the result does not establish an advantage of exact mixture shape in that context task. Event transport is evaluated through its registered utility, equivalence, probability-release and recovery gates; those results remain separate from prediction calibration.

In the completed paid-feedback study, event versus direct-integer utility noninferiority is {status(q['event_vs_direct_noninferiority'])}, and event versus FP64-packet noninferiority is {status(q['event_vs_float_noninferiority'])}. Exact event/direct action, output and utility equivalence is {status(q['event_direct_exact_actions_outputs_utility'])}; the positive-Q24 release gate is {status(q['positive_q24_all_scored_outputs'])}. Completed-cohort replay is {status(q['all_replays_passed'])} and the separately specified runtime qualification is {status(q['all_runtime_qualifications_passed'])}. These are measured research gates within the registered corpus, with interrupted attempts and their costs retained separately.

All work is confined to this experimental extension. Round 1–3 frozen sources and historical results remain unchanged. There is no production promotion: native confidence is zero, abstention remains enabled, and authority is `DENY_ALL`. This round does not train a first-passage/reset cell, demonstrate a new neural function class, perform DQN updates, or establish hardware energy savings.

The published scientific source is [{SOURCE_COMMIT}](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/{SOURCE_COMMIT}/experiments/analytic_event_neuron/round4). Its immutable freeze has SHA256 `{FREEZE_SHA256}`. Publication bound **{publication['source_files']} scientific source files and {publication['prepared_artifacts']} prepared artifacts before confirmation construction**. [Protocol](PROTOCOL.json), [event/law contract](CONTRACT.md), [calibration contract](CALIBRATION_CONTRACT.md), [runtime contract](RUNTIME_CONTRACT.md), [acceptance record](evidence/ACCEPTANCE.json), and [evidence manifest](evidence/EVIDENCE_MANIFEST.json) define the exact scope.

### Six requested work packages

| Work package | Concrete delivery and validation | Scientific limit |
| --- | --- | --- |
| 1. Mathematical and event contract | One terminal conditional law; ordered put/neutral/call events; separate physical time, observation stage, packet sequence, missingness and reset meanings. | Communication increments and terminal tails do not supply a first-passage/reset mechanism. |
| 2. Analytic core and independent references | Stable component CDF/log tails, exact mixture sums and log densities, quantile inversion, dense covariance references, trained-prior gradients and component semigroup checks; {groups} numerical groups pass. | The GH64 continuation rule is an approximation, with separately measured error. |
| 3. Trainable prototype and controls | Fresh diffusion/noise/prior fits, Gaussian moment and dense/probit controls, actual native sparse features and learned readouts, signed/direct/FP64 packet controls. | Hard packets and the original sparse update kernel are not trained end to end by backpropagation. |
| 4. A task with subsequent actions | Hidden mixture residual, independent noisy feedback, paid wait/repair/stop, actual repair amplitude, and final delivered utility over {runtime['independent_trajectories']:,} independent confirmation trajectories. | A controlled synthetic task with named numerical continuation approximation. |
| 5. Actual Hepta feedback chain | Actual text/PNG delivery, reopen/readback, versioned owner, actual native component/sparse ticks, target-free policy subprocess, delayed scoring and native cohort replay. | Ordinary process/dataflow separation is not a hostile same-UID security guarantee. |
| 6. Runtime and broader research | Native adapter, positive Q24 release, durable state, {ordinary:,} ordinary qualification forecasts, {fresh} fresh processes, {bridge} actual calibration bridge forecasts, and separate calibration/retention/cost endpoints. | The zero-context ECE gate remains failed; extra-context success, finite retention and numeric profiles are not interchangeable. |

## 1. Conditional probabilities and a coherent component law

For each fitted component,

\\[
dX_t=b_j\\,dt+\\sqrt{{q_j}}\\,dW_t,\\qquad X_0\\sim N(0,1),\\quad q_j>0.
\\]

The acquired history determines component means and variances. Without another observation, `m_j(h)=m_j+b_j h`, `v_j(h)=v_j+q_j h`, and posterior component weights stay fixed. The exact conditional forecast is

\\[
p_h(x\\mid\\mathcal F_t)=\\sum_j w_j(\\mathcal F_t)\\,\\varphi(x;m_j(h),v_j(h)).
\\]

Call, neutral and put are directional integrals of this shared law. At a common threshold `k`, put means `P(X≤k)` and call means `P(X>k)`; with two thresholds, the middle interval retains its own mass. Call and put are two output ports of one conditional-law operator, so they share fitted dynamics and conserve probability mass. They do not require two unrelated parameter families. They are physical task probabilities rather than discounted risk-neutral option prices. A normal-CDF node is a probit parameterization. Mixtures preserve additional distributional shape, but a matched classical implementation remains an essential control.

All component posterior log weights are retained with stable `logaddexp` identities. Density and event-log scores do not recover the small component by subtracting its rounded complement from one. The physical log-scoring domain can therefore be broader than the positive-weight runtime export domain. If a finite physical log weight underflows when converted to a linear weight, `law_at` rejects export; it removes only a structural zero. Finite component log densities and posterior log odds remain required.

The scalar bridge schema is `hepta.conditional-law.v4`: `weights`, `means` and `variances` are matching arrays for one or two components, and `semantics` is exactly `terminal`. Weights are positive and normalized; variances are positive. The internal log-domain scoring representation and the scalar runtime export therefore have separately declared valid domains. The recipient never infers a first-passage or reset meaning merely from a call/put output name.

The augmented state `(component, X)` has the declared componentwise transition semigroup. The marginalized state alone need not be Markov. The projected Gaussian control intentionally replaces a mixture by two moments; it does not inherit that exact joint transition law. Missing observations advance physical time without a likelihood factor; unoccupied storage advances neither. Same-time acquired sensors each contribute their own factor.

## 2. Fresh fitting and the two information experiments

The new seeds are `1213,1427,1619,1823,2017`. Each calibration seed fits a fresh old-environment anchor from 512 labelled trajectories, then follows twelve registered windows alternating the original drift 0.12 and shifted drift 0.32. Each window supplies 256 fresh training trajectories, 256 retained original training rows, 256 old-development rows and 256 new-development rows. The four exact/projected zero/context heads each fit their own prior; replay and those four heads each select from 21 predeclared development candidates under the same old-NLL guard.

There are **365 successful optimizer fits**: 5 fresh anchors, 120 component updates and 240 prior fits, followed by **300 selections over 6,300 candidates**. The smallest actual component parameter change is {prepared_review['details']['component_min_parameter_change']:.10f}; the smallest fitted prior-logit change is {prepared_review['details']['prior_min_logit_change']:.10f}. Thus drift/noise and prior parameters genuinely participate in training. The optimizer uses correlated training acquisition stages and horizons; these do not multiply the independent trajectory count. Unique labelled preparation queries total 48,640, and old replay rows are reused rather than counted anew. Preparation also acquires **378,880 unlabelled prior public histories**: they add information and acquisition work, although they add no future-target labels to the fit budget.

The **zero-context** profile receives the original query history. The **context** profile also receives eight prior public sensor histories from independent paths sharing that query's latent regime. Their internal clocks restart on each path; all eight histories precede the query. Block membership is public but does not reveal the regime. Context files contain observations, physical times, masks, occupancy and sensor variances, never their latent/future labels. All informative context controls use the same histories; the Gaussian moment control actively exploits their likelihood evidence. The single-component replay baseline has the same available information but its fixed-component architecture cannot use that evidence to infer a regime.

A context/query block is one independent sampling unit. Confirmation has **16,640 unique query blocks and 133,120 prior public histories**, or **149,760 acquired paths**, with three correlated scored horizons per query. All nine acquired histories in each context block are included in this information budget. The 1,280 original old blocks are reused at twelve checkpoints. The extra eight histories are an information/acquisition cost; the context result cannot be substituted for success with the original query information. Twelve recurring windows are a finite retention study, not unlimited preservation or arbitrary change-point detection.

### Calibration and retention results

The old-retention margin is .02 for the worst **seed-averaged** old NLL increase across windows. Efficacy also requires final-new improvement of at least .005, improvement for every training seed and a bootstrap upper endpoint below zero. Drift calibration separately requires classwise ten-bin ECE ≤ .04 and coverage in [.92,.98]. The two primary profiles have Bonferroni-family 97.5% intervals; other arm intervals below are descriptive 95%. Bootstrap resampling uses training-seed clusters and independent whole query/context blocks, with the three correlated horizons kept together. Repeated evaluation of the same old block is not counted as a new independent trajectory.

{calibration_table}

![Calibration, coverage, retention scope and final-new NLL](evidence/figures/calibration_retention.png)

The original-information exact mixture has ECE **0.0512513284**, so its joint gate fails despite improved NLL and acceptable coverage. With eight public histories, the exact mixture reaches ECE **0.0231024872**, coverage **0.9446614583**, and final-new NLL change **−0.1666765786** with primary interval **[−0.1995604611, −0.1330396132]**. Its worst seed-averaged old increase is **+0.0096899044**.

That last retention statement has a narrower scope than individual protection: the worst single seed/window is **+0.0356166940** at seed 1213, window 11. It exceeds .02. The worst seed-averaged window is window 7. A development reserve `mean+1.645 paired SE` is a selection heuristic, and a passed finite-sample empirical gate is not a pointwise or population theorem.

{mechanism_table}

The context advantage over zero context includes the additional public information and the prior fitted/selected with that information. Exact context mixture versus its independently fitted Gaussian moment control crosses zero, and the fixed-weight projection comparison also crosses zero. The modest zero-context exact-versus-projected gain is a secondary fitted-family comparison with separately optimized priors, not a fixed-weight shape-only effect; its ECE gate remains failed. Dense classical prediction matches to {cal['equivalence']['fp64']:.4e}, and the parameter-Q24 classical counterpart matches to {cal['equivalence']['q24']:.4e}.

## 3. Paid hidden-state feedback and original native execution

The feedback task is distinct from the diffusion calibration task. A hidden static residual has generating weights `(0.65,0.35)`, means `(-0.45,0.85)` and variances `(0.09,0.36)`. The private target is initial output plus that residual. The first sensor has noise variance in `{{0.04,0.36,1.44}}`; waiting acquires and pays for a second independent sensor with variance in `{{0.04,0.16,0.64}}`. Repair costs are in `{{0.03,0.12,0.48}}` and wait costs in `{{0.01,0.04,0.12}}`, in task-utility units. A target-free worker chooses stop/repair/wait, then stop/repair after a paid wait. It delivers the final text/PNG output and reopens it before the scoring process uses the private target:

\\[
U=1-(\\mathrm{{delivered}}-Y)^2-c\\,1_{{\\mathrm{{repair}}}}-w\\,1_{{\\mathrm{{wait}}}}.
\\]

The five fresh priors receive 80 EM updates each, and sensor noise scale is fitted from training labels. The K1 Gaussian uses the same training rows and has an independent dense/probit control. Fifteen analytic/numeric/history readouts use three ridge choices, 600 gradient steps per choice and five development offsets: 45 gradient runs, 27,000 steps and 225 development candidates. The smallest selected readout parameter change is {fitted_change:.9f}. The original sparse kernel executes real ticks; only its input/readout mechanism is changed and fitted.

Each fitted head has 256 training and 128 development trajectories per seed, followed by 256 fresh confirmation trajectories per seed. Thus confirmation contains **{runtime['independent_trajectories']:,} independent trajectories and {runtime['completed_control_executions']:,} paired arm executions**. Policy isolation is ordinary target-free process/dataflow separation, not protection against a hostile same-UID process reading all files.

Repair gain is `2*a*posterior_mean-a²-c`, using the actual Q24 repair amplitude. Waiting integrates the positive future repair gain under the exact mixture's predictive sensor law with 64 Gauss–Hermite nodes per component. Independent adaptive integration measures a development-fixture error as large as **0.0012554211**. This is a numerical continuation approximation, not roundoff or an exact Bellman certificate. All codec arms share it; actual chosen actions and delivered outcomes determine utility. Learned readouts can depart from this common plug-in planner.

{runtime_table}

{utility_table}

The two primary requirements are event-minus-direct and event-minus-FP64 **noninferiority**, margin .01, paired 97.5% intervals and every seed mean above −.01. The hierarchical bootstrap resamples training-seed clusters and complete trajectories while preserving arm pairing; the eight executions of one trajectory are not eight independent samples. Five trained seeds support this registered empirical interval, not a distribution-free or population guarantee. Equivalent codecs are not required to show superiority. Event-minus-FP64 utility is {delta(primary_event['mean_difference'])}, interval {bounds(primary_event['interval'])}. The original native Gaussian/probit and sparse/history controls remain in the table even when equivalent or unsuccessful. Secondary intervals do not introduce a new superiority gate after observing outcomes.

## 4. Packet identity, quantization, recovery and actual bridge

The packed owner implements three profiles with the same framing, file write, flush/fsync, reopen, decoder, lock, pending journal, state/witness and native output path. Event and direct integer profiles share positive Q24 mixture weights and a 2^-12 mean/log-variance grid. Event packets send signed differences; direct packets send absolute integers. Exact decoded identity is an implementation result of difference coding one representation, not a new predictive function class or trained biological spike mechanism.

The owner allows at most 16 requests. Its feedback clock counts acquired observation stages (one or two); sequence additionally orders refreshes at the same stage. A `propagation` packet in this static-residual task is an unchanged-stage refresh, not a diffusion time step. After transport decoding, component means must satisfy `abs(mean) ≤ 8` and variances must lie in `[2^-24,8]`; native parameter and threshold rounding is then checked separately. The accepted source set is the preimage of these decoded/native bounds, so an unrounded source slightly outside a boundary can round inside, and different codec profiles need not accept identical boundary inputs.

The FP64 packet profile sends the floating coordinates without that 2^-12 grid. It still stores only K−1 mixture weights and reconstructs the final weight as `1−sum(previous weights)`, and the native head still rounds its inputs to Q24. It is therefore **not globally lossless continuous-law transport**. A positive final weight near `exp(-40)` can disappear under complement subtraction and be rejected, while reversing component order can be accepted; around log odds 36 the reconstructed small weight can differ materially in relative terms. Ordinary-corpus errors and accepted-source scope are measured below. The matched experiment uses the common eligible corpus and retains every registered execution.

{float_table}

Every component reaches the original native typed prediction head. The returned native component vectors are mixed using the received weights. The released positive categorical code is

\\[
n_i=1+\\operatorname{{Hamilton}}_i((2^{{24}}-3)p),\\qquad \\widehat p_i=n_i/2^{{24}}.
\\]

The integer total is exactly `2^24`, every category has at least one unit, and the componentwise release error relative to the normalized **native mixture** is bounded by `3/2^24 ≈ 1.7881393e-7`. The released event NLL is finite and capped by `24 log(2)`. This is a contamination-and-rounding distribution, not the true value of an extreme physical tail. It supplies no uniform relative-tail or log-score-error bound. Transport/native parameter errors are separate. The planner retains a separate native-effective mean/variance channel, so finite category floors are not automatically an identified cause of better control utility.

The reported stable event-log/NLL diagnostic is evaluated under the **effective continuous reference law after state/weight transport and native input rounding**, using the native-effective boundaries. It is not the untouched source law. The original forecast remains separately recorded as `source_law`, and `max_source_to_effective_category_error` quantifies that upstream change. The final positive-count bound compares the actual native mixture vector with its release, not the original source forecast.

{tails_table}

{runtime_acceptance}

Qualification exercises {sum(x['histories'] for x in qualification):,} distinct public histories, {ordinary:,} ordinary forecasts, {fresh} fresh subprocesses, {tail_count} extreme-tail fixtures and **{bridge} calibration-to-native bridge forecasts**. Fresh-process lost acknowledgements return exact cached receipts without another native tick. Partial packet/component/native commits fail closed. State rollback, corruption, altered duplicates and stale compare-and-swap values are checked against the declared owner/witness arrangement. There is no cross-owner atomicity or hostile replacement-of-all-evidence guarantee; CRC32 is not authentication.

The bridge uses ten deterministic calibration development queries per seed at physical horizon 1.0. It binds each query's full public history, eight-history context and model/data identities into the owner. Its fixed diagnostic cost context supplies thresholds and an observation-stage clock; it is not the conditioning information that produced the calibration law. The bridge demonstrates actual prediction-head adaptation, not paid-feedback utility on the calibration queries or native coverage of every calibration forecast.

Calibration parameter Q24 rounds the fitted dynamics/prior before filtering. Event/direct transport quantizes conditional state, native execution rounds prediction parameters, and final categorical release adds its own positive-count approximation. These are distinct profiles sharing a law schema. Their gates and numeric domains do not transfer automatically.

## 5. Measured costs and observability

![Utility, complete packet frames and execution before archival](evidence/figures/runtime_tradeoffs.png)

Packet bytes include complete frames, not only payloads. The per-arm wall endpoint stops after final delivery readback and receipt persistence; **ZIP compression, member verification and source cleanup occur afterward** and are included only in worker/outer phase times. Row CPU excludes native-child CPU. The outer execution wrapper records CPU for processes it waits for. Randomized paired arm order reduces order bias; several seed scopes ran concurrently, and the retained execution schedule documents that change. These are descriptive shared-host measurements, not isolated hardware latency or energy benchmarks.

{cost_table}

The event representation also records the following sums of absolute integer coordinate increments. They are logical quantum units at different scales, **not individually executed physical spikes or an energy estimate**; complete frame bytes remain the observed communication quantity.

{quantum_table}

The following accounting is reconstructed by the independent runtime review from retained original artifacts. Cumulative adapter writes, final retained state, native tick-receipt writes and physical filesystem writes are different quantities. Shared training/development acquisition is counted once, not once per fitted readout. Where a full native initialization/witness write stream or physical block-write amplification was not observed, the record is null rather than zero.

{accounting_table}

### Interrupted work and recovery

Two execution-service interruptions affected unfinished runtime work. The first stopped four confirmation workers and one native-replay worker around 17:10:28 UTC. The second, around 17:45:19 UTC, interrupted the first recovery orchestration, one unfinished confirmation worker, two partial native replays and the scoring parent of an already completed worker. The original `STARTED` receipts, logs, partial ZIPs and working files are preserved. Completed seed 1213/1427/1823 confirmations were kept; only seed 1619 required another full policy execution after the second interruption. The final recovery ran one heavy phase at a time. The observed memory-pressure counters have no preincident baseline and do not establish the cause of the service interruption.

Seed 2017 already contained all **2,048 unique case/arm outputs**, its worker receipt, archive and manifest. Recovery hash-bound those files, verified their complete inventory, and evaluated the exact saved scoring statements from the unchanged frozen source. It made **zero new policy decisions and zero native calls**. The original worker's {runtime['scopes'][-1]['execution']['worker']['native']['requests']:,} native requests and {runtime['scopes'][-1]['execution']['worker']['native']['ticks']:,} ticks belong to the completed formal cohort and are counted **once**, not again as discarded interrupted work. New scoring time is reported separately. Its missing original parent wall/CPU/exit measurements remain null; intact row/worker measurements do not reconstruct that missing whole-invocation cost.

Registered datasets, model parameters, arm order and scientific gates remain fixed. Saved-data identity checks bind recovery to the original confirmation arrays. Repeating an interrupted execution supplies no new independent sample, and continuing a complete worker's scoring does not justify replacing or selecting its decisions.

{interruption_table(audit)}

These are **observed lifetime bounds**, derived from recorded start times, last retained writes and later stopped-state observations under a consistent wall-clock assumption. They are not completed elapsed measurements. Whole interrupted-invocation exit codes and total CPU remain unknown. Partial ZIP bytes are retained storage, not complete transmitted or filesystem-write cost. Discarded partial attempts are additional attempted work; the reused complete 2017 worker belongs to the formal cohort. An interrupted orchestration parent overlaps its child phases and is not added to their native work or elapsed time. Completed recovery invocations do not replace or erase the interrupted receipts. Both incident records and snapshots are retained with the [operational evidence](evidence/EVIDENCE_MANIFEST.json).

### Nested execution and scoring measurements

{runtime_phase_table(runtime)}

Worker wall includes its archive append/verification/cleanup, whereas the per-arm wall endpoint above stops earlier. Worker and parent Python CPU each measure that process, excluding native-child CPU; the captured wrapper below supplies its separately measured waited-for process-tree CPU. Parent wall contains the worker wall on uninterrupted seeds. For seed 2017, recovered scoring has its own later clock interval and leaves the original parent duration unknown. None of these nested values should be added to their enclosing invocation duration.

### Captured complete invocations

{wrapper_table(run)}

These invocation durations overlap across concurrent seed jobs and contain nested component timers. **Do not sum them into study elapsed time or add inner scoring/replay/IPC times again.** For calibration, the confirmation wrapper is 90.604772063 s while its inner scoring phase is 81.837121789 s; the independent-review wrapper is 19.223993280 s while its inner audit is 18.832821327 s. The separate original pre-tail-fix preparation is retained as an additional development attempt. The first deterministic bridge-binding rebuild and the early 40,000-row feasibility diagnostic lack a complete invocation timer; their full wall/CPU cost is unknown. Hardware energy, monetary execution cost, hostile-environment guarantees and physical disk-write amplification were not measured.

## 6. Independent verification, corrections and provenance

The numerical suite passes **{groups}/{groups} groups**, including independent integration, dense Gaussian conditioning, same-time/missing sensors, exact mixture probabilities and quantiles, trained-prior gradients, componentwise semigroup propagation, packet reconstruction and representation-domain checks. Its continuation-integral row is a diagnostic with a named nonzero approximation error, not an exactness assertion.

{math_table}

The full prepared calibration review passed {prepared_review['checks']:,} checks and {prepared_review['scalar_comparisons']:,} scalar comparisons, independently recomputing 6,300 candidate selections and all prior objective/gradient traces. The confirmation review passed **{cal_review['checks']:,} checks, {cal_review['scalar_comparisons']:,} scalar comparisons and zero failures**, rescoring 307,200 model/domain/query rows and all 16 intervals/gates. Its maximum numerical discrepancy was {cal_review['maximum_absolute_numeric_error']:.4e}. These are verification counts, not independent experimental samples.

The original confirmation-review receipt bound preparation and reviewer source, but did not explicitly record the confirmation inventory or result digest. It is retained unchanged. A later, fresh invocation of the same unchanged numerical reviewer was wrapped by before/after hashing of **{cal_binding['confirmation_file_count']:,} confirmation files ({cal_binding['confirmation_total_file_bytes']:,} bytes)**. The [fresh binding receipt](evidence/results/CALIBRATION_CONFIRM_REVIEW_BINDING.json) and [fresh numerical review](evidence/results/CALIBRATION_CONFIRM_REVIEW_BOUND.json) bind the current unchanged result and data. This is provenance recorded at that later audit, not a retrospective claim about what the original review recorded. No samples, models or gates were changed.

The independent runtime final review reports **{audit.get('checks', 'see receipt')} checks** and `{audit.get('passed')}` acceptance of its audit. It validates outputs, costs, probability semantics, cohort-native replays and the separate qualification scope against original artifacts. Native calls in the **completed** training/development and completed formal-feedback cohorts, including the reused seed 2017 worker, are all replayed. Qualification's injected faults and recovery calls are separate. Discarded interrupted partial or unreturned calls are retained additional work that is not exhaustively replayed; their complete attempt-level native-call count is unknown. This scope qualifies the shorthand `all_actual_native_calls_replayed` registration field; it does not describe every attempted invocation.

{scope_table}

Preparation's independent native replay adds **{prep_requests:,} requests and {prep_ticks:,} ticks**, separate from both the shared original preparation column and the formal confirmation replay column. Requests/ticks count work, so counts may be added across disjoint scopes; their overlapping wall durations may not. Full native initialization/witness filesystem writes and energy remain distinct unmeasured quantities.

Runtime preparation/source correspondence was established through complete current-source deterministic refitting and actual native replay. Its later source-binding review is not a retroactive original-execution source-hash receipt. Calibration preparation separately recorded and checked its scientific source hashes at preparation start and finish. Both prepared collections and the final source were published and bound before confirmation.

### Retained development corrections

1. **Posterior tail cancellation.** Before freeze, `1-expit(logodds)` silently erased a small physical component at log odds 40/100, causing opposite-tail NLL errors of 110/50 nats. The entire first prepared attempt and old source were retained, the log-weight implementation was corrected, and all preparation was rerun before any confirmation. The final log-domain profile preserves such tails; runtime export still rejects unrepresentable positive weights.
2. **Bridge conditioning provenance.** The initial bridge fixture lacked the full conditioning binding. Its original files were preserved. Two agents then rebuilt the same deterministic bound fixture, producing byte-identical final query/model laws. The retained coordination record distinguishes the genuinely unbound originals from a later duplicate whose directory name alone is not a schema assertion. One rebuild has no complete wall timer. Final source models and query laws were not altered to improve outcomes.
3. **Freeze binding.** A final prefreeze review bound the current scientific source set and exact bridge artifact hashes. Freeze refuses stale source/review or bridge bindings and refuses pre-existing confirmation directories. A source/model correction cannot silently reuse a prior freeze.

An exploratory known-parameter diagnostic used 20,000 old and 20,000 shifted development rows with separate seeds to inspect the zero-context tradeoff. It was not a confirmation result, was not used to fit final models, and does not prove impossibility. Its executed code, rounded output and missing complete timing are retained. Failed, equivalent and non-significant outcomes remain part of this round.

{hashes}

The final [evidence manifest](evidence/EVIDENCE_MANIFEST.json) binds archive parts, original member hashes and restoration receipts. [Preconfirmation publication](evidence/PRECONFIRMATION_PUBLICATION.json) records the 102-source/489-prepared binding. [Final publication verification](evidence/FINAL_PUBLICATION_RECEIPT.json) records the final remote identity; that later publication receipt is not recursively included in the earlier immutable scientific freeze. Report/figure rendering does not retrain models or choose acceptance thresholds.

## 7. Reproducing the recorded study

Use an isolated checkout of the final published research commit containing this README and the reporting/review helpers, together with the manifest's verified archives. Its scientific source inventory must match the earlier immutable source commit. Python, NumPy, SciPy, Pillow and platform versions are recorded in [FREEZE.json](evidence/FREEZE.json); Matplotlib is needed only for the figures. The native executable is the existing verified research binary, not a claimed fresh Rust build. No Rust files changed; this partial checkout lacks the required `codex-rs` tree, so `just fmt` is recorded as not run rather than passed. That check did not establish whether the `just` executable itself is installed.

Restore the complete evidence into a fresh destination using the existing hash/path-safe restorer. It rejects path escapes, duplicate archive entries and incompatible overwrites; ensure enough disk space for the retained original native/PNG evidence.

```bash
python -m experiments.analytic_event_neuron.round2.restore_evidence \\
  --manifest experiments/analytic_event_neuron/round4/evidence/EVIDENCE_MANIFEST.json \\
  --repo . --destination /tmp/aen-r4-replay
```

The manifest supplies each bundle's restored root; use its `run/` root for verification. The restored files already include published summaries and audit outputs. Several runtime commands create outputs exclusively, so invoking `summary` or `audit` directly on that untouched restored evidence would fail. Read-only verification and independent review use fresh output destinations:

```bash
python -m experiments.analytic_event_neuron.round4.freeze \\
  --run-dir /tmp/aen-r4-replay/run
python -m experiments.analytic_event_neuron.round4.evidence.review_calibration confirm \\
  --run-dir /tmp/aen-r4-replay/run --output /tmp/calibration-review-repeat.json
python -m experiments.analytic_event_neuron.round4.evidence.review_runtime_final \\
  --repo . --run-dir /tmp/aen-r4-replay/run --output /tmp/runtime-review-repeat.json
```

Recomputing statistics or native replay requires a **second restored working copy**, while the first copy remains the published evidence. In that second copy, preserve the old `RUNTIME_RESULTS.json` under a new published-result name before invoking `runtime_study summary`. For each seed, preserve **all three** existing `AUDIT.json`, `native_replay.zip` and `native_replay.manifest.json` together in a separate published-audit subdirectory before invoking `runtime_study audit --run-dir WORKING_COPY --seed SEED`. The same original native executable must remain present and hash-bound. The per-seed native replay then checks original packet bytes, decoded laws, actual native CDF/Q24 values, sparse inputs, actions and delivered scores. Qualification recovery is a separate operation with separately counted requests.

Archive restoration verifies original byte identities. A new execution produces new timing/operational receipts, so a replay ZIP or full runtime summary is not promised to have the same byte hash. Mathematical/model/action/score agreement is the relevant repeated-execution check. Reusing the frozen data does not create a new independent confirmation sample. To regenerate this descriptive document and its figures from the restored result files, run the reporting helper in an isolated checkout:

```bash
python -m experiments.analytic_event_neuron.round4.evidence.build_report \\
  --run-dir /tmp/aen-r4-replay/run
```

The report builder refuses completion without the full runtime results, final independent runtime review, completed serial recovery, both interruption receipts, reused-worker scoring provenance and fresh calibration before/after binding. It verifies the current calibration inventory, reused worker/score bytes, bound recovery receipts and frozen scientific/prepared bytes before and after rendering. It writes only the report and figures; it does not change models, data or decision rules.

A new scientific iteration must use a new registration, data identities and directory. The old confirmation collection must not be reused to tune these same reported models or move their gates.

## 8. Consequences for Hepta and the theoretical connection

The implemented contribution is a versioned conditional-law interface that can carry an exact mixture into the existing native prediction head and subsequent paid actions, with explicit evidence for probability meaning, readback, state reconstruction and cost. The empirical context gain involves additional acquired public histories and a separately fitted regime prior; it does not establish a new activation family. Exact/direct packet identity makes the communication-cost comparison interpretable. Stable log scores and positive native release solve different numeric problems and remain separate outputs.

[Deep Q-Learning on Hölder Spaces](https://arxiv.org/abs/2606.16846) studies regularity and approximation of Bellman targets in uniformly elliptic diffusion control. The solvable Gaussian transition is relevant as a concrete smoothing operator, but its Cauchy-problem setting excludes the absorbing-boundary complications of a first-passage cell. The paper does not transfer a guarantee for these finite-sample calibration gates, empirical retention, hard packet gradients, exploration/replay/SGD, or practical DQN convergence. This experiment performs no DQN updates.

[Sigma Delta Quantized Networks](https://arxiv.org/abs/1611.02024) is prior art for communicating changes in quantized activations. Signed increments alone are therefore not a novelty claim. A future first-passage/reset neuron would need a separately derived survival/hitting law, censoring likelihood, reset and refractory dynamics, remaining-time propagation and a trainable repeated-firing objective. Those are a new experiment rather than an interpretation of the present terminal probabilities.

The measured research result is conditional: context-enabled prediction and the qualified runtime mechanisms are supported within their declared tasks and domains; the original-information calibration failure, absence of exact-mixture superiority over strong context controls, finite retention scope and unmeasured hardware costs remain visible. Production promotion remains false.
'''
    (PROJECT / 'README.md').write_text(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--calibration-only', action='store_true')
    args = parser.parse_args()
    run = args.run_dir.resolve()
    frozen = verify(run)
    if frozen['source_commit'] != SOURCE_COMMIT or sha(run / 'FREEZE.json') != FREEZE_SHA256:
        raise ValueError('Report requires the declared immutable Round 4 source/freeze')
    cal = load(run / 'calibration_confirmation/RESULTS.json')
    verified_calibration_review(run)
    runtime_bindings = None
    if not args.calibration_only:
        runtime, audit, runtime_bindings = verified_runtime_review(run)
    calibration_figure(cal)
    if not args.calibration_only:
        runtime_figure(runtime)
        generate(run, runtime, audit, frozen)
    verify(run)
    verified_calibration_review(run)
    if runtime_bindings is not None and runtime_bindings != verified_runtime_review(run)[2]:
        raise ValueError('Runtime results/review changed while rendering')
    print(json.dumps({'report_written': not args.calibration_only, 'source_commit': SOURCE_COMMIT,
                      'calibration_results_sha256': sha(run / 'calibration_confirmation/RESULTS.json'),
                      'report_sha256': sha(PROJECT / 'README.md') if not args.calibration_only else None}, sort_keys=True))


if __name__ == '__main__':
    main()
