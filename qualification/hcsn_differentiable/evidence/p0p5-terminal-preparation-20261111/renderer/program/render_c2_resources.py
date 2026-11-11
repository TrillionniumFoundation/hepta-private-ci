"""Render admitted saved tables after a separate exact authorization; never select a model."""
import argparse
import json
from pathlib import Path
import time
import traceback

from input_contract import ARMS, authorize, identity, load, verify_unchanged

NAMES = ('GRU', 'CfC', 'Surrogate PLIF', 'Event-time LIF', 'S4D-Lin', 'Causal attention', 'HCSN')
COLORS = ('#28689e', '#008778', '#755a9c', '#a4772b', '#60a3bd', '#3e526b', '#bd3d3a')
VIEWS = (('original42_only', 'Original 42 attempts'), ('original42_plus_separate_C1', 'Original 42 plus separate C1'))


def fmt(value, digits=4):
    return 'Missing' if value is None else f'{value:,.{digits}f}'


def quality(row):
    stats = row['selected_statistics']
    return 'Missing / quality HOLD' if stats is None else f"{fmt(stats['mean'])} ± {fmt(stats['sample_standard_deviation'])}"


def cost_admitted(row, candidates):
    return all(c.get('cost_independently_audited', row['arm'] != 'hcsn') is True
               for c in candidates if c['arm'] == row['arm'])


def cost_text(row, candidates):
    cost = row['all_six_opportunity_cost']
    value = cost['all_opportunity_wall_seconds']
    text = fmt(value, 3) if value is not None else f"Missing full bill; known ≥ {fmt(cost['known_wall_lower_bound_seconds'], 3)}"
    return text if cost_admitted(row, candidates) else text + ' (recorded; cost audit HOLD)'


def target_text(row):
    if row['selected_statistics'] is None:
        return 'Missing / quality HOLD'
    count = row['selected_observed_crossing_count']
    return fmt(row['median_first_observed_target_seconds'], 3) if count == 3 else f'Censored ({count}/3 observed)'


def render(result, old, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter
    rows = {r['arm']: r for r in result['longer_resource_core_table']}
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'svg.hashsalt': 'hcsn-c2-resource-renderer-v1'})
    fig, axes = plt.subplots(2, 2, figsize=(16, 11.5))
    fig.subplots_adjust(left=.13, right=.97, top=.86, bottom=.16, hspace=.5, wspace=.30)
    fig.suptitle('C2 diagnostic continuation: development quality and charged process cost',
                 x=.04, ha='left', y=.97, fontsize=17, weight='bold')
    fig.text(.04, .935, 'D selection data · not independent confirmation · CPU / FP64 · 3 seeds × 2 LRs per core', fontsize=11)
    for ax, (key, title) in zip(axes[0], VIEWS):
        tables = old['views'][key]['tables']
        for arm, name, color in zip(ARMS, NAMES, COLORS):
            points = [next(r for r in tables[str(c)] if r['arm'] == arm) for c in (300, 900, 1800)]
            available = [r for r in points if r['selected_three_seed_mean'] is not None]
            ax.errorbar([r['budget_seconds'] for r in available], [r['selected_three_seed_mean'] for r in available],
                        yerr=[r['selected_sample_standard_deviation'] for r in available], color=color,
                        marker='o', linestyle='none', capsize=3, label=name)
        ax.set_title(title + ': unchanged historical cuts', loc='left', fontsize=11, weight='bold')
        ax.set_xscale('log')
        ax.set_xticks([300, 900, 1800], labels=['300', '900', '1,800'])
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlim(240, 2200)
        ax.set_xlabel('Per-fit process-wall budget (seconds)')
        ax.set_ylabel('D macro-F1, mean ± sample SD')
        ax.grid(axis='y', alpha=.16)
    axes[0, 0].legend(ncol=2, frameon=False, fontsize=8, loc='upper left')
    quality_ax, cost_ax = axes[1]
    for i, (arm, color) in enumerate(zip(ARMS, COLORS)):
        row, stats = rows[arm], rows[arm]['selected_statistics']
        if stats is None:
            quality_ax.text(.02, i, 'Missing / quality HOLD', va='center', color=color)
        else:
            adequate = row['selected_trained_comparison_supported']
            quality_ax.barh(i, stats['mean'], xerr=stats['sample_standard_deviation'], color=color, height=.62,
                            capsize=3, hatch=None if adequate else '///', edgecolor='white')
            label = f"{stats['mean']:.3f} ± {stats['sample_standard_deviation']:.3f}"
            if not adequate:
                label += f"; adequacy HOLD {row['selected_independently_adequate_count']}/3"
            quality_ax.text(.99, i, label, ha='right', va='center', fontsize=8.5)
        cost = row['all_six_opportunity_cost']['all_opportunity_wall_seconds']
        if cost is not None and cost > 0 and cost_admitted(row, result['candidates']):
            cost_ax.barh(i, cost, color=color, height=.62)
            cost_ax.text(cost * 1.04, i, f'{cost:,.0f}', va='center', fontsize=8.5)
        elif cost == 0 and cost_admitted(row, result['candidates']):
            cost_ax.text(.02, i, '0 recorded seconds', transform=cost_ax.get_yaxis_transform(), va='center')
        else:
            cost_ax.text(.02, i, 'Cost HOLD / missing full bill (see report)',
                         transform=cost_ax.get_yaxis_transform(), va='center', fontsize=8.5)
    for ax in axes[1]:
        ax.set_ylim(6.7, -.7)
        ax.set_yticks(range(7), labels=NAMES)
        ax.grid(axis='x', alpha=.15)
        ax.set_axisbelow(True)
    quality_ax.set_xlim(0, 1)
    quality_ax.set_title('New terminal D outcome: existing common-LR table', loc='left', fontsize=11, weight='bold')
    quality_ax.set_xlabel('Strict-best complete-epoch macro-F1; hatched = adequacy HOLD')
    cost_ax.set_xscale('log')
    cost_ax.margins(x=.25)
    cost_ax.set_title('All 6 opportunities: complete C1/C2 wrapper bills', loc='left', fontsize=11, weight='bold')
    cost_ax.set_xlabel('Charged process-wall seconds (overlapping sums, not calendar time)')
    fig.text(.04, .09, 'Missing observations are omitted, never zero-filled or interpolated. Both old views remain byte-bound and unchanged.\n'
             'D is reused for selection; seed SD is initialization variation. Quality clocks are observed evaluation prefixes; bills include complete wrappers.\n'
             'Whole-training numerical qualification and scientific confirmation remain HOLD. Energy, GPU memory and currency were not measured.',
             fontsize=10, color='#414952', linespacing=1.6)
    for extension in ('png', 'svg'):
        fig.savefig(output / ('C2-RESOURCE-COMPARISON.' + extension), dpi=180, facecolor='white',
                    metadata={'Date': None} if extension == 'svg' else {})
    plt.close(fig)
    return matplotlib.__version__


def report(result, old):
    rows = {r['arm']: r for r in result['longer_resource_core_table']}
    text = ['# C2 continuation: saved resource tables and development quality', '',
            '**D was used for model selection; these are not independent confirmation results.** This renderer presents admitted metadata only. It performs no LR selection, statistics recomputation, model evaluation, training or numerical oracle.', '',
            '## Unchanged original budget views', '',
            'The two original RESULT/POINTS files are copied byte-for-byte. At each old cutoff, the saved common-LR three-seed result is displayed, including explicitly timed before-training observations. Missing observations remain missing; C2 does not backfill these cuts. Startup and original diagnostics consume those original budgets.', '']
    for key, title in VIEWS:
        text += ['### ' + title, '', '| Core | 300 s | 900 s | 1,800 s |', '| --- | ---: | ---: | ---: |']
        for arm, name in zip(ARMS, NAMES):
            points = [next(r for r in old['views'][key]['tables'][str(c)] if r['arm'] == arm) for c in (300, 900, 1800)]
            cells = ['Missing' if r['selected_three_seed_mean'] is None else
                     f"{fmt(r['selected_three_seed_mean'])} ± {fmt(r['selected_sample_standard_deviation'])}" for r in points]
            text.append('| ' + name + ' | ' + ' | '.join(cells) + ' |')
        text.append('')
    text += ['## New terminal table, separate from the old resource cuts', '',
             'Baselines retain their previously frozen common LR. HCSN receives a descriptive common LR only when all six quality records have independent admission. Verified but inadequate quality remains visible with adequacy HOLD. SD is sample variation across three initializations on the same reused D subject; it is not a confidence interval.', '',
             '| Core | Common LR | D macro-F1 mean ± sample SD | Selected adequate | First-observed target median (s) | All 6 complete-wrapper wall (s) | Max observed attempt RSS (GiB) |',
             '| --- | ---: | ---: | --- | --- | ---: | ---: |']
    for arm, name in zip(ARMS, NAMES):
        row = rows[arm]
        adequate = f"{row['selected_independently_adequate_count']}/3" + ('' if row['selected_trained_comparison_supported'] else ' — HOLD')
        peak = row['maximum_observed_attempt_RSS_bytes']
        text.append(f"| {name} | {fmt(row['selected_common_learning_rate'], 3)} | {quality(row)} | {adequate} | {target_text(row)} | {cost_text(row, result['candidates'])} | {fmt(None if peak is None else peak / 2**30, 3)} |")
    text += ['', 'Target .30 uses first observed complete-epoch crossings. A median is copied only for 3/3 observed crossings; other outcomes remain censored or missing. Evaluation-prefix wall is not the full final bill, and latent crossings between evaluations are unknown.', '',
             'All six opportunities at both LRs remain charged, including failed candidates, original diagnostics/startup, discarded partial parent work, and complete C1/C2 attempt wrappers. Summed overlapping process walls are not campaign calendar duration or idle-host throughput. Controller/preflight, historical tuning, extra probes, independent audits and transport are separate overlapping accounts, not additions to the per-fit column.', '',
             'Original v8 report CPU omits pre-fit startup/import and post-report exit. Exact C2 child wait4 does not repair those gaps or identify per-fit wrapper CPU. Cumulative per-fit CPU remains a lower bound/unknown; it is not used to choose the wall-budget quality points. RSS is an observed per-attempt process maximum with the coverage recorded in RESULT.json, not concurrent-tree RSS, memory at target crossing or GPU VRAM. Energy, GPU memory and billed currency are unmeasured.', '',
             '## Evidence and limits', '',
             'The complete OS receipt bounds the analysis launcher child from Popen through wait4, including its worker and internal receipt write/exit. The internal core receipt is a nested prefix. The supervisor’s later hash/receipt work is separately recorded and is not represented as its complete OS exit by this renderer. The pinned supervisor supplies the process-group/subreaper observations; this renderer does not repeat /proc inspection.', '',
             'Whole-training numerical qualification and scientific admission remain HOLD. Any independent adequacy indicator is the supplied heuristic training gate, not proof of mechanism benefit or confirmation on E. This rendering reads no E data; historical loader exposure is unchanged by this preparation.', '',
             '[Analysis RESULT](RESULT.json) · [Complete OS receipt](OS-RECEIPT.json) · [Core prefix receipt](CORE-RECEIPT.json) · [Unchanged old RESULT](frozen-original-budget/RESULT.json) · [Unchanged old POINTS](frozen-original-budget/POINTS.json)', '',
             '![D selection-set resource comparison](C2-RESOURCE-COMPARISON.png)', '']
    return '\n'.join(text)


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('authorization', 'authorization-sha', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    auth, tracked = authorize(args.authorization, args.authorization_sha, output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'c2-resource-render-receipt-v1', 'status': 'not_completed', 'presentation_admitted': False,
               'scientific_admission': 'HOLD', 'actual_visual_review_completed': False,
               'confirmation_E_access': False, 'model_calls': 0, 'automatic_retry': False}
    try:
        result, old, raw, contents = load(auth, tracked)
        for name, key in (('RESULT.json', 'RESULT'), ('OS-RECEIPT.json', 'os_receipt'), ('CORE-RECEIPT.json', 'core_receipt')):
            (output / name).write_bytes(raw[key])
        (output / 'frozen-original-budget').mkdir()
        for name in ('RESULT.json', 'POINTS.json'):
            (output / 'frozen-original-budget' / name).write_bytes(contents['frozen-original-budget/' + name])
        receipt['matplotlib'] = render(result, old, output)
        (output / 'REPORT.md').write_text(report(result, old), encoding='utf-8')
        verify_unchanged(tracked)
        receipt.update(status='rendered_pending_visual_review', presentation_admitted=True, inputs_unchanged=True)
    except Exception:
        receipt.update(status='render_failed', presentation_admitted=False, error=traceback.format_exc())
    finally:
        receipt.update(input_identities=tracked, main_entry_wall_prefix_seconds=time.perf_counter() - wall,
                       process_CPU_prefix_seconds=time.process_time() - cpu,
                       cost_scope='Render main-entry prefix; imports, final output hashing, receipt serialization and exit excluded. A later complete OS receipt remains separate.',
                       outputs={str(p.relative_to(output)): identity(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()})
        (output / 'RENDER-RECEIPT.json').write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    return 0 if receipt['presentation_admitted'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
