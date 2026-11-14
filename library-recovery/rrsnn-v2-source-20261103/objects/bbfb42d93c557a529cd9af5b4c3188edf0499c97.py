"""Create static scientific figures from saved results; no new model fitting."""
from pathlib import Path
import json
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rrsnn-matplotlib')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
LABELS = {
    'lif': 'LIF', 'alif': 'ALIF', 'resource_lif': 'Resource LIF',
    'fp_no_maturity': 'FP, no maturity', 'fp_multi_fixed': 'Multi-maturity, fixed',
    'rr_full': 'RR candidate', 'ctrnn': 'CT-RNN (16)',
    'ctrnn_budget': 'CT-RNN (budget)', 'rr_no_rollover': 'No rollover feedback',
    'rr_collapse_maturity': 'Collapsed maturities',
    'rr_shuffle_maturity': 'Past-profile resampling',
    'rr_frozen_resource': 'Frozen resource signal',
}


def main():
    aggregate = json.loads((ROOT/'results/aggregate.json').read_text())
    rows = {r['variant']: r for r in aggregate['rows']}
    scaling = json.loads((ROOT/'models/scaling_results.json').read_text())['results']
    gap = json.loads((ROOT/'hepta/proxy_exact_gap.json').read_text())['summaryByHorizon']
    destination = ROOT/'figures'
    destination.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(14.2, 10.2), layout='constrained')
    ax = axes[0, 0]
    names = ['lif', 'alif', 'resource_lif', 'fp_no_maturity', 'fp_multi_fixed',
             'rr_full', 'ctrnn', 'ctrnn_budget']
    y = np.arange(len(names))
    for offset, key, label, color in (
        (-.18, 'test_expected', 'Same distribution', '#175E9B'),
        (.18, 'future_expected', 'Synthetic distribution shift', '#D46B2D'),
    ):
        means = [100*rows[v]['evaluation'][key]['normalized_utility_mean']['mean'] for v in names]
        sds = [100*rows[v]['evaluation'][key]['normalized_utility_mean']['seed_sd'] for v in names]
        ax.errorbar(means, y+offset, xerr=sds, fmt='o', color=color, capsize=3, label=label)
    ax.axhspan(4.6, 5.4, color='#DDE9DD', alpha=.55, zorder=-1)
    ax.set_yticks(y, [LABELS[v] for v in names]); ax.invert_yaxis()
    ax.set_xlim(45, 96)
    ax.set_xlabel('Achieved / oracle utility (%)')
    ax.set_title('A. Frozen protocol: 5 training seeds\nExpected/probability proxy; error bars = seed SD', loc='left', fontsize=12)
    ax.legend(fontsize=8, loc='lower left')
    ax.grid(axis='x', alpha=.2)

    ax = axes[0, 1]
    names = ['rr_full', 'rr_no_rollover', 'rr_collapse_maturity',
             'rr_shuffle_maturity', 'fp_multi_fixed', 'rr_frozen_resource']
    y = np.arange(len(names))
    for offset, key, label, color in (
        (-.16, 'future_expected', 'Expected mode', '#2F6B53'),
        (.16, 'future_hard', 'Hard proxy replay', '#8D67A0'),
    ):
        means = [100*rows[v]['evaluation'][key]['normalized_utility_mean']['mean'] for v in names]
        sds = [100*rows[v]['evaluation'][key]['normalized_utility_mean']['seed_sd'] for v in names]
        ax.errorbar(means, y+offset, xerr=sds, fmt='o', color=color, capsize=3, label=label)
    labels = [LABELS[v] for v in names]
    labels[4] = 'Fixed boundary (same as multi-fixed)'
    ax.set_yticks(y, labels); ax.invert_yaxis()
    ax.set_xlim(48, 88)
    ax.set_xlabel('Achieved / oracle utility (%)')
    ax.set_title('B. Mechanism ablations under synthetic shift\nHard replay remains an observation-grid proxy', loc='left', fontsize=12)
    ax.legend(fontsize=8, loc='lower left'); ax.grid(axis='x', alpha=.2)

    ax = axes[1, 0]
    for name, color in [('lif', '#175E9B'), ('rr_full', '#C04A35'), ('ctrnn_budget', '#2F6B53')]:
        selected = sorted((r for r in scaling if r['variant'] == name), key=lambda r:r['batch_instances'])
        ax.plot([r['batch_instances'] for r in selected], [r['latency_ms_p50'] for r in selected],
                'o-', color=color, label=LABELS[name])
    ax.set_xscale('log', base=2); ax.set_yscale('log')
    ax.set_xticks([64, 256, 1024, 4096], ['64', '256', '1024', '4096'])
    ax.set_xlabel('Independent state rows (shared weights)')
    ax.set_ylabel('Median batch latency (ms)')
    ax.set_title('C. Complete 8-step model + 81-output head\nOne CPU thread; 20 timings; current execution host', loc='left', fontsize=12)
    ax.legend(fontsize=9); ax.grid(alpha=.2, which='both')

    ax = axes[1, 1]
    xx = [r['horizon'] for r in gap]
    yy = [100*r['meanAbsoluteMeanClosureProbabilityGap'] for r in gap]
    maximum = [100*r['maximumAbsoluteMeanClosureProbabilityGap'] for r in gap]
    ax.plot(xx, yy, 'o-', color='#C04A35', label='Mean absolute error')
    ax.plot(xx, maximum, 's--', color='#CD9B40', label='Maximum absolute error')
    ax.axvspan(0, 1, color='#DDE9DD', alpha=.45, label='Observed interval range up to 1')
    ax.axhline(0, color='#2F6B53', lw=1.5)
    ax.set_xlim(0, 4.1); ax.set_ylim(-.4, 10)
    ax.set_xlabel('Total interval H')
    ax.set_ylabel('First-hit probability error (percentage points)')
    ax.set_title('D. One interval versus two half intervals\nConditional-mean closure; 32 frozen trained controls', loc='left', fontsize=12)
    ax.text(.34, .40, 'Full surviving-density composition:\nmaximum error 3.33e-16 over 96 checks',
            transform=ax.transAxes, va='top', fontsize=9, color='#2F6B53')
    ax.legend(fontsize=8, loc='lower right'); ax.grid(alpha=.2)
    fig.suptitle('RR-SNN v0: measured utility, cost, and the distribution-propagation gap', fontsize=16)
    fig.savefig(destination/'rrsnn_results_overview.png', dpi=180, facecolor='white')
    plt.close(fig)
    print(destination/'rrsnn_results_overview.png')

    paired = json.loads((ROOT/'runtime/results/paired_counterfactual/summary.json').read_text())
    by_name = {r['variant']:r for r in paired['rows']}
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), layout='constrained',
                             gridspec_kw={'width_ratios':[1.65,1]})
    x = np.arange(4)
    conditions = paired['conditions']
    for offset, name, color in [(-.18,'rr_full','#C04A35'),(.18,'ctrnn_budget','#2F6B53')]:
        scores = [by_name[name]['by_condition'][c]['normalized_utility'] for c in conditions]
        axes[0].bar(x+offset,[100*s['mean'] for s in scores],width=.34,
                    yerr=[100*s['seed_sd'] for s in scores],capsize=3,color=color,
                    alpha=.9,label=LABELS[name])
    axes[0].set_xticks(x,['A: split\nno contraction','A: split\ncontraction 2',
                          'B: clustered\nno contraction','B: clustered\ncontraction 2'])
    axes[0].set_ylim(0,108)
    axes[0].set_ylabel('Achieved / own oracle utility (%)')
    axes[0].set_title('A. Counterfactual conditions\nSame values, budget, obligation mass and mean maturity',loc='left')
    axes[0].legend(fontsize=9,loc='upper left',bbox_to_anchor=(0,1.0))
    axes[0].grid(axis='y',alpha=.15)
    for i,name in enumerate(['rr_full','ctrnn_budget']):
        result=by_name[name]['announced_shock_changes_A_t1_action_fraction']
        color='#C04A35' if i==0 else '#2F6B53'
        axes[1].bar(i,100*result['mean'],width=.5,color=color,alpha=.3)
        axes[1].scatter(i+np.linspace(-.15,.15,5),np.array(result['seed_means'])*100,
                        s=42,color=color,zorder=3)
        axes[1].text(i,100*result['mean']+1.5,f"{100*result['mean']:.2f}%",ha='center',fontweight='bold')
    axes[1].set_xticks([0,1],['RR candidate','CT-RNN\n(budget)'])
    axes[1].set_ylabel('Pairs changing the t=1 action (%)')
    axes[1].set_ylim(0,33)
    axes[1].set_title('B. Response before the t=1.5 contraction\nOnly the announced initial shock amount changes',loc='left')
    axes[1].grid(axis='y',alpha=.15)
    fig.suptitle('128 paired value groups × 4 conditions × 5 frozen training seeds',fontsize=14)
    fig.supxlabel('Left: error bars are training-seed SD.  Right: dots are individual seeds; bars are their mean.  Expected-mode proxies.',fontsize=9)
    fig.savefig(destination/'rrsnn_paired_counterfactual.png',dpi=180,facecolor='white')
    plt.close(fig)
    print(destination/'rrsnn_paired_counterfactual.png')


if __name__ == '__main__':
    main()
