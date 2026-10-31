"""Plot frozen A/B intervals without re-estimating any statistic.

Run this file with the experiment's Python environment. Input pins are checked
on every render. The one-time --initialize-pins option refuses to replace pins.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile


FULL_REPORT_SHA = '58c54ad94267a2ddb3c18ad2fc91932572cb83ad715060cbf8e063272ec8a99e'
PRIMARY = (
    ('risk_training_under_fixed', 'Risk-sensitive vs mean training\n(fixed inference)'),
    ('feedback_under_output_ndu', 'Feedback vs fixed inference\n(NDU-trained generator)'),
)
DESCRIPTIVE = (
    ('shared_state_fixed_path', 'Shared state: full − clamp\n(fixed semantic → couple)'),
    ('feedback_vs_draft_masked_feedback', 'Feedback − draft-masked'),
    ('feedback_vs_tuned_static', 'Feedback − tuned static'),
    ('feedback_vs_one_shot_route', 'Feedback − one-shot'),
    ('feedback_vs_allocation_only_feedback', 'Feedback − allocation-only'),
    ('feedback_vs_risk_neutral_feedback', 'Feedback − risk-neutral'),
    ('feedback_vs_modality_local_feedback', 'Feedback − modality-local'),
    ('feedback_vs_independent_random_stream_MPC', 'Feedback − independent-stream MPC'),
)
COLORS = {'primary': '#17639C', 'secondary': '#D27C22'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extracted_input(path):
    raw = path.read_bytes()
    report = json.loads(raw)
    if report['full_report_original_sha256'] != FULL_REPORT_SHA:
        raise ValueError('Expected the original frozen A/B analysis report')
    if report['census']['source_pairs'] != 128 or report['census']['training_seeds'] != 5:
        raise ValueError('Source/seed census changed')
    points = []
    for panel, selected, observers, confidence in (
        ('registered_primary', PRIMARY, ('primary',), .975),
        ('descriptive', DESCRIPTIVE, ('primary', 'secondary'), .95),
    ):
        for order, (comparison, label) in enumerate(selected):
            for observer in observers:
                item = report['observers'][observer]['comparisons'][comparison]
                metric = item['net_ce']
                if metric['confidence'] != confidence:
                    raise ValueError('Do not relabel or recompute the registered interval level')
                points.append({'panel': panel, 'order': order, 'label': label, 'observer': observer,
                               'comparison': comparison, 'original_kind': item['kind'],
                               'candidate': item['candidate'], 'reference': item['reference'],
                               'source_metric': 'net_ce', 'confidence': metric['confidence'],
                               'estimate': metric['gain'], 'lower': metric['interval'][0],
                               'upper': metric['interval'][1],
                               'source_json_path': f'observers.{observer}.comparisons.{comparison}.net_ce'})
    return {'schema': 'hepta-AB-frozen-effect-interval-input-v1',
            'source': {'file': path.name, 'sha256': sha(raw), 'bytes': len(raw),
                       'full_report_original_sha256': FULL_REPORT_SHA},
            'census': report['census'], 'points': points, 'statistics_reestimated': False,
            'metric_definition': 'Net joint CE of U minus0.002 per continuation action; not measured latency or money',
            'direction': 'candidate minus reference; positive favors candidate',
            'inference_note': 'Original source/seed crossed-bootstrap intervals. Five seeds do not guarantee confirmatory coverage. Views, generation scenarios, replay rows and repeated observers do not increase independent source count.',
            'new_success_thresholds_or_gates': False}


def draw(inputs, output):
    # Keep even transient plotting/font-cache writes inside the repository.
    with tempfile.TemporaryDirectory(prefix='.plot-mpl-', dir=Path(__file__).parent) as cache:
        os.environ['MPLCONFIGDIR'] = cache
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.ticker import FuncFormatter

        plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                             'axes.unicode_minus': True, 'axes.edgecolor': '#CBD3DC',
                             'axes.labelcolor': '#223145', 'xtick.color': '#526172',
                             'ytick.color': '#223145', 'savefig.facecolor': 'white'})
        fig = plt.figure(figsize=(12, 10.2), facecolor='white')
        grid = fig.add_gridspec(2, 1, height_ratios=[2.0, 6.5], left=.32, right=.965,
                               bottom=.175, top=.845, hspace=.56)
        axes = [fig.add_subplot(grid[0]), fig.add_subplot(grid[1])]
        fig.suptitle('A/B effects | 128 source pairs, 5 training seeds', x=.50, y=.975,
                     fontsize=18.5, fontweight='semibold', color='#18283B')
        fig.text(.50, .942, 'Net joint certainty equivalent · frozen source/seed crossed-bootstrap intervals',
                 ha='center', fontsize=10.5, color='#526172')
        for axis, panel, selected in zip(axes, ('registered_primary', 'descriptive'), (PRIMARY, DESCRIPTIVE)):
            count = len(selected)
            for order in range(count):
                if order % 2 == 0:
                    y = count - 1 - order
                    axis.axhspan(y - .46, y + .46, color='#F4F7FA', zorder=0)
            axis.axvline(0, color='#6B7785', linewidth=1.15, linestyle=(0, (4, 3)), zorder=1)
            axis.set_axisbelow(True)
            axis.grid(axis='x', color='#E4E9EF', linewidth=.7)
            for point in inputs['points']:
                if point['panel'] != panel:
                    continue
                observer = point['observer']
                offset = 0 if panel == 'registered_primary' else (.14 if observer == 'primary' else -.14)
                y = count - 1 - point['order'] + offset
                # Only display geometry is calculated; the estimate/CI endpoints are copied verbatim.
                axis.errorbar(point['estimate'], y,
                              xerr=[[point['estimate'] - point['lower']], [point['upper'] - point['estimate']]],
                              fmt='o' if observer == 'primary' else 's', markersize=5.6,
                              color=COLORS[observer], markeredgecolor='white', markeredgewidth=.7,
                              elinewidth=2.0, capsize=3.3, capthick=1.4, zorder=3)
            axis.set_yticks(list(reversed(range(count))), [label for _, label in selected])
            axis.set_ylim(-.62, count - .38)
            axis.set_xlim(-.011, .022)
            axis.set_xticks([-.010, -.005, 0, .005, .010, .015, .020])
            axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: '0' if value == 0 else f'{value:+.3f}'.replace('-', '−')))
            axis.tick_params(axis='y', length=0, pad=13, labelsize=10.2)
            axis.tick_params(axis='x', labelsize=9.5, length=3)
            for side in ('top', 'left', 'right'):
                axis.spines[side].set_visible(False)

        position_a, position_b = [axis.get_position() for axis in axes]
        fig.text(.045, position_a.y1 + .032, 'A   Registered primary comparisons',
                 fontsize=12.2, fontweight='semibold', color='#18283B')
        fig.text(.965, position_a.y1 + .033, 'Primary observer · nominal 97.5% CIs',
                 fontsize=10.2, color='#526172', ha='right')
        fig.text(.045, position_b.y1 + .035, 'B   Descriptive contrasts · 95% CIs',
                 fontsize=12.2, fontweight='semibold', color='#18283B')
        handles = [Line2D([0], [0], marker=marker, color=COLORS[observer], linewidth=2,
                          markersize=5.5, label=label)
                   for observer, marker, label in (('primary', 'o', 'Primary observer'),
                                                    ('secondary', 's', 'Secondary observer'))]
        fig.legend(handles=handles, loc='lower right', bbox_to_anchor=(.974, position_b.y1 + .019),
                   frameon=False, ncol=2, fontsize=9.8, columnspacing=1.6, handlelength=2)
        axes[1].set_xlabel('Net joint CE gain (candidate − reference; positive favors candidate)',
                           fontsize=11.2, labelpad=14)
        fig.text(.045, .070, 'Intervals are copied from the frozen report; no statistics were re-estimated.',
                 fontsize=9.2, color='#526172')
        fig.text(.045, .047, 'Independent source count = 128. Seeds, views, scenarios and policy replays are not additional sources.',
                 fontsize=9.2, color='#526172')
        fig.text(.045, .024, 'Five-seed crossed-bootstrap intervals do not guarantee confirmatory coverage; no new success gate is introduced.',
                 fontsize=9.2, color='#526172')
        fig.savefig(output, dpi=200, metadata={'Title': 'Frozen Hepta A/B effect intervals',
                                             'Description': '128 source pairs;5 training seeds;unchanged original estimates and CIs'})
        version = matplotlib.__version__
        plt.close(fig)
    return version


def main():
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, default=directory / 'summary.json')
    parser.add_argument('--pins', type=Path, default=directory / 'effect-intervals-input.json')
    parser.add_argument('--output', type=Path, default=directory / 'effect-intervals.png')
    parser.add_argument('--initialize-pins', action='store_true')
    args = parser.parse_args()
    inputs = extracted_input(args.summary)
    if args.initialize_pins:
        with args.pins.open('x') as stream:
            stream.write(json.dumps(inputs, sort_keys=True, indent=2) + '\n')
    if json.loads(args.pins.read_bytes()) != inputs:
        raise ValueError('Plot input differs from the frozen metadata pins or selected original intervals')
    version = draw(inputs, args.output)
    receipt = {'schema': 'hepta-AB-frozen-effect-plot-v1', 'source_sha256': inputs['source']['sha256'],
               'input_pins_sha256': sha(args.pins.read_bytes()), 'plot_script_sha256': sha(Path(__file__).read_bytes()),
               'png_sha256': sha(args.output.read_bytes()), 'python_version': platform.python_version(),
               'matplotlib_version': version, 'font': 'DejaVu Sans', 'dpi': 200,
               'size_pixels': [2400, 2040], 'displayed_intervals': len(inputs['points']),
               'statistics_reestimated': False, 'source_file_modified': False,
               'source_pairs': 128, 'training_seeds': 5, 'new_success_gates': False}
    args.output.with_suffix('.receipt.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
