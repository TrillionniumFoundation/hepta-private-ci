"""Render descriptive V3 figures from sealed scoring outputs; no policy selection."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def render(run, evaluation, output):
    runs = json.loads((Path(run) / 'runs.json').read_text())
    result = json.loads((Path(evaluation) / 'evaluation.json').read_text())
    ranking = json.loads((Path(evaluation) / 'ranking.json').read_text())
    output = Path(output)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.9), gridspec_kw={'width_ratios': [1.12, 1]})
    for ax, group, title, scale in [
        (axes[0], ('direct_vs_tracking_future', 'remaining_vs_myopic_future'),
         'Future NLL: equal June / July / August means', 1e6),
        (axes[1], ('hard_vs_soft_old', 'hard_vs_warmup_old'),
         'Independent old-test NLL', 1.0)]:
        rows = [r for r in result['primary_contrasts'] if r['id'] in group]
        labels = []
        for y, row in enumerate(rows):
            point = row['difference_left_minus_right'] * scale
            lo, hi = np.asarray(row['bonferroni_percentile_interval']) * scale
            color = '#126D83' if row['criterion_met'] else '#6B7280'
            ax.errorbar(point, y, xerr=[[point-lo], [hi-point]], fmt='o', color=color,
                        capsize=4, linewidth=1.8, markersize=5)
            name = {'direct_vs_tracking_future': 'Direct - tracking',
                    'remaining_vs_myopic_future': 'H8 - H1 (direct)',
                    'hard_vs_soft_old': 'Hard - soft (identical)',
                    'hard_vs_warmup_old': 'Hard - warmup'}[row['id']]
            labels.append(row['head'].capitalize() + ': ' + name)
        ax.set_yticks(range(len(rows)), labels)
        ax.invert_yaxis()
        ax.axvline(0, color='#C64949', linewidth=1, linestyle='--')
        ax.grid(axis='x', alpha=.18)
        ax.set_title(title, fontsize=11, pad=13)
        ax.set_xlabel('NLL difference (micro-nats)' if scale > 1 else 'NLL difference (nats)')
    fig.suptitle('V3: eight registered diagnostics at anchor 16', fontsize=15, weight='bold')
    fig.text(.5, .015, 'Bonferroni-adjusted approximate percentile intervals; fixed fitted seeds. '
             'Negative favors the left method. Hard = soft adds no retention effect.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .045, 1, .92))
    for suffix in ('png', 'svg'):
        fig.savefig(output / ('primary-results.' + suffix), dpi=180, bbox_inches='tight')
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.6), gridspec_kw={'width_ratios': [1.2, 1]})
    colors = {'linear': '#126D83', 'gated': '#BD6B22'}
    for x, model in enumerate(('loss2', 'full')):
        for head, offset in [('linear', -.07), ('gated', .07)]:
            values = [r['kendall_tau_b'] for r in ranking['records']
                      if r['prediction_model'] == model and r['head'] == head
                      and r['common_objective'] == 'direct_soft_total']
            axes[0].scatter(x + offset + np.linspace(-.025, .025, len(values)), values,
                            color=colors[head], s=30, alpha=.85,
                            label=head.capitalize() if x == 0 else None)
    axes[0].set_xticks([0, 1], ['Loss2', 'Full'])
    axes[0].set_ylabel('Kendall tau-b')
    axes[0].set_ylim(-.55, 1.12)
    axes[0].axhline(0, color='#B0B5BC', linewidth=1)
    axes[0].grid(axis='y', alpha=.15)
    axes[0].legend(frameon=False, loc='lower right')
    axes[0].set_title('Common H8 direct-cost ordering', fontsize=11)
    nonzero = [r for r in runs['records'] if r['method_id'] != 'zero' and r['status'] == 'completed']
    values = [np.mean([abs(r['predicted_scores'][model]['direct_soft_total']
                              - r['actual_scores']['direct_soft_total']) for r in nonzero])
              for model in ('loss2', 'full')]
    bars = axes[1].bar(['Loss2', 'Full'], values, color=['#6B7280', '#126D83'], width=.5)
    axes[1].set_yscale('log')
    axes[1].set_ylim(5e-9, 2e-5)
    axes[1].set_ylabel('Mean absolute common-cost error')
    axes[1].set_title('Same 324 nonzero candidate actions', fontsize=11)
    for bar, value in zip(bars, values):
        axes[1].text(bar.get_x() + bar.get_width()/2, value * 1.35, f'{value:.3e}', ha='center')
    axes[1].grid(axis='y', alpha=.15)
    fig.suptitle('Same checkpoints, same actions, different prediction models', fontsize=14, weight='bold')
    fig.text(.5, .015, '18 fixed anchors; descriptive local diagnostics, not 18 independent tasks. '
             'Full optimality is limited to the executed candidate pool.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .045, 1, .92))
    for suffix in ('png', 'svg'):
        fig.savefig(output / ('action-ranking.' + suffix), dpi=180, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'evaluation', 'output'):
        parser.add_argument('--' + name, required=True)
    render(**vars(parser.parse_args()))
