"""Render reported confirmation estimates; no fitting, selection or new data."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def retention(run, output):
    data = json.loads((run / 'retention_confirmation/BRIEF.json').read_text())['arms']
    keys = ['frozen', 'online', 'replay', 'fixed_mixture', 'likelihood_mixture',
            'protected', 'protected_quantized']
    labels = ['Frozen anchor', 'Online adaptation', 'Replay', 'Fixed mixture',
              'Likelihood mixture', 'Protected FP64', 'Protected Q24']
    colors = ['#8995a4'] * 5 + ['#007f86', '#4658bb']
    positions = np.arange(len(keys))
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.8, 5.6),
                                     gridspec_kw={'width_ratios': [1.2, 1]})
    loss = [data[key]['worst_old_gaussian_nll_degradation'] for key in keys]
    coverage = [100 * data[key]['mean_shift_new']['coverage95'] for key in keys]
    left.barh(positions, loss, color=colors, height=.58)
    left.axvline(.02, color='#ba4a28', lw=1.5, ls='--', label='Registered limit +0.02')
    for row, value in enumerate(loss):
        left.text(.35, row, f'{value:+.6f}', va='center', ha='right', fontsize=9,
                  bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .9, 'pad': 1})
    left.set_yticks(positions, labels)
    left.invert_yaxis()
    left.set_xlim(-.005, .36)
    left.set_xlabel('Worst-window old-task Gaussian NLL increase')
    left.set_title('A. Retention protection succeeds', loc='left', fontweight='bold')
    left.legend(loc='lower center', frameon=False, fontsize=9)
    right.scatter(coverage, positions, s=58, c=colors, zorder=3)
    right.axvline(95, color='#ba4a28', lw=1.5, ls='--')
    for row, value in enumerate(coverage):
        right.text(value + .13, row + .24, f'{value:.2f}%', ha='left', fontsize=9)
    right.set_yticks(positions, [''] * len(keys))
    right.set_ylim(left.get_ylim())
    right.set_xlim(87.5, 96.2)
    right.set_xlabel('Actual coverage of nominal 95% intervals (%)')
    right.set_title('B. Drift calibration remains limited', loc='left', fontweight='bold')
    for axis in [left, right]:
        axis.spines[['top', 'right']].set_visible(False)
        axis.grid(axis='x', color='#dbe2e8', lw=.6, alpha=.6)
        axis.set_axisbelow(True)
    fig.suptitle('Hepta analytic event neuron · frozen Round 2 confirmation',
                 fontsize=15, x=.02, ha='left', y=1.01, fontweight='bold')
    fig.text(.02, -.02, '5 training seeds · 12 adaptation windows · fixed anchor · '
             'point estimates, not uncertainty intervals\n'
             'Old-loss protection and new-domain calibration are separate acceptance criteria.',
             fontsize=10, color='#4b5865')
    fig.tight_layout(pad=2.1)
    for suffix in ['png', 'svg']:
        fig.savefig(output / ('RETENTION_TRADEOFF.' + suffix), dpi=180,
                    bbox_inches='tight', facecolor='white')
    plt.close(fig)


def primary(run, output):
    results = json.loads((run / 'RESULTS.json').read_text())
    contrasts = results['primary_contrasts']
    keys = ['continuous_vs_history', 'continuous_vs_sparse', 'event_vs_continuous']
    if not all(key in contrasts for key in keys):
        keys = list(contrasts)
    labels = [f"{contrasts[key]['candidate']} − {contrasts[key]['baseline']}" for key in keys]
    fig, axis = plt.subplots(figsize=(10.7, 4.8))
    for row, key in enumerate(keys):
        item = contrasts[key]
        mean, (low, high) = item['mean_difference'], item['interval']
        color = '#007f86' if item['passes_registered_superiority'] else '#b84a2a'
        axis.errorbar(mean, row, xerr=[[mean - low], [high - mean]],
                      fmt='o', capsize=5, color=color, lw=2.3, markersize=7)
        axis.text(high + .012, row, f'{mean:+.5f}\n[{low:+.5f}, {high:+.5f}]',
                  va='center', fontsize=10)
    axis.axvline(0, color='#8995a4', lw=1)
    axis.axvline(.01, color='#4658bb', lw=1.4, ls='--', label='Superiority threshold +0.01')
    axis.set_yticks(np.arange(len(keys)), labels)
    axis.set_ylim(len(keys) - .5, -.5)
    xmin = min(item['interval'][0] for item in contrasts.values())
    xmax = max(item['interval'][1] for item in contrasts.values())
    axis.set_xlim(min(-.05, xmin - .03), xmax + .19)
    axis.set_xlabel('Paired net-utility difference (candidate minus baseline)')
    axis.set_title('Primary Gaussian-task comparisons', loc='left', fontweight='bold', fontsize=14)
    axis.spines[['top', 'right']].set_visible(False)
    axis.grid(axis='x', color='#dbe2e8', alpha=.7, lw=.6)
    axis.legend(loc='lower right', frameon=False, fontsize=9)
    fig.text(.02, -.01, '5 seeds × 256 paired trajectories · 4,000 two-stage bootstrap replicates · '
             'family alpha 0.05 across 3 contrasts\n'
             'Pass requires adjusted interval lower bound > +0.01 and all five seed means > 0. '
             'Intervals are empirical.', fontsize=9, color='#4b5865')
    fig.tight_layout(pad=2)
    for suffix in ['png', 'svg']:
        fig.savefig(output / ('PRIMARY_COMPARISONS.' + suffix), dpi=180,
                    bbox_inches='tight', facecolor='white')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    retention(arguments.run, arguments.output)
    if (arguments.run / 'RESULTS.json').exists():
        primary(arguments.run, arguments.output)
