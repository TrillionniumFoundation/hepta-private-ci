"""Measure underfitting and generalization before claiming a capacity repair."""

import argparse
import json
from pathlib import Path
import time

import torch

from ....abc_next.value import load_controller
from ....abc_recovery.base_recovery import file_sha, write_json
from ..development import cost_quote, evaluate, select_paths
from ..features import from_tree
from ..models import Bundle, actor_values, fit_head, load, save
from ..registry import HERE, pins, asset_pins


@torch.no_grad()
def labels(full, teacher):
    return torch.cat((teacher.choose(full[:, 0], 2)[:, None],
                      teacher.choose(full[:, 1:].flatten(0, 1), 1).reshape(-1, 4)), 1)


@torch.no_grad()
def fidelity(actor, public, target):
    roots = actor_values(actor, public[:, 0], 2).argmax(-1)
    children = actor_values(actor, public[:, 1:].flatten(0, 1), 1).argmax(-1).reshape(-1, 4)
    match = torch.cat(((roots == target[:, 0])[:, None], children == target[:, 1:]), 1)
    reached = target[:, 0] != 0
    rows = torch.nonzero(reached).flatten()
    chosen_children = children[rows, target[rows, 0] - 1] == target[rows, target[rows, 0]]
    onpath_correct = int(match[:, 0].sum()) + int(chosen_children.sum())
    return {'root_H2': float(match[:, 0].float().mean()), 'all_child_H1': float(match[:, 1:].float().mean()),
            'all_actual_nodes': float(match.float().mean()), 'teacher_reached_nodes': onpath_correct / (len(public) + len(rows)),
            'actual_nodes': int(match.numel()), 'teacher_reached_node_count': len(public) + len(rows)}


def run(asset, development, output):
    spec_path = Path(__file__).with_name('PROTOCOL.json')
    spec = json.loads(spec_path.read_text()); original_spec = json.loads((HERE / 'PROTOCOL.json').read_text())
    original = json.loads((development / 'result.json').read_text())
    if original['source_sha256'] != pins() or original['status'] != 'completed':
        raise ValueError('Original frozen development changed')
    source = pins() | {str(p.resolve()): file_sha(p) for p in Path(__file__).parent.glob('*.py')} | {str(spec_path.resolve()): file_sha(spec_path)}
    assets = asset_pins(asset)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(output / 'registration.json', {'source_sha256': source, 'assets_sha256': assets, 'started_unix_ns': time.time_ns(),
               'scope': spec['source_scope'], 'candidates': spec['candidates'], 'original_development_sha256': file_sha(development / 'result.json')})
    all_rows = []
    for old in original['records']:
        seed = old['seed']; folder = asset / f'abc4-control-runs/development-001/seed-{seed}'
        for group in ('fit', 'selection'):
            if file_sha(folder / f'{group}/data.pt') != old[f'{group}_sha256']:
                raise ValueError('Historical development data changed')
        fit = torch.load(folder / 'fit/data.pt', map_location='cpu', weights_only=True)
        selection = torch.load(folder / 'selection/data.pt', map_location='cpu', weights_only=True)
        if (fit['role'], fit['pair_start'], fit['pair_count'], selection['role'], selection['pair_start'], selection['pair_count']) != ('forecast_fit', 480, 256, 'forecast_calibration', 448, 128):
            raise ValueError('Only the frozen historical development roles are allowed')
        fit_x, select_x = from_tree(fit, folder / 'fit'), from_tree(selection, folder / 'selection')
        teacher = load_controller(asset / f'abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt')
        original_path = development / f'seed-{seed}/bundle.pt'
        if file_sha(original_path) != old['bundle_sha256']:
            raise ValueError('Original actor/critic changed')
        original_bundle = load(original_path)
        fit_y, select_y = labels(fit['features'], teacher), labels(selection['features'], teacher)
        for candidate in spec['candidates']:
            trained_wall, trained_cpu = time.perf_counter_ns(), time.process_time_ns()
            if candidate['reuse_original_actor']:
                actor, trace = original_bundle.actor, old['actor_trace']
            else:
                actor, trace = fit_head(fit_x.flatten(0, 1), fit_y.flatten(), width=candidate['hidden'], outputs=5,
                                       seed=2026103500 + seed, steps=candidate['steps'], actor=True)
            training = {'wall_ns': time.perf_counter_ns() - trained_wall, 'cpu_ns': time.process_time_ns() - trained_cpu,
                        'reused_original': candidate['reuse_original_actor'], 'trace': trace}
            bundle = Bundle(original_bundle.critic, actor, None)
            quote = cost_quote(asset, seed, bundle, fit, folder / 'fit', teacher)
            baseline = evaluate(selection, *select_paths(bundle, select_x, selection['features'], teacher, 'teacher'),
                                cheap_ms=quote['cheap_ms'], teacher_ms=quote['teacher_ms'], gate_enabled=False)
            thresholds = [{'threshold': None, 'eligible': True, **baseline}]
            for threshold in original_spec['selection']['thresholds']:
                bundle.threshold = threshold
                value = evaluate(selection, *select_paths(bundle, select_x, selection['features'], teacher, 'gate'),
                                 cheap_ms=quote['cheap_ms'], teacher_ms=quote['teacher_ms'], gate_enabled=True)
                thresholds.append({'threshold': threshold, 'eligible': value['raw_CE'] >= baseline['raw_CE'] and value['success'] >= baseline['success'], **value})
            selected = max((i for i, r in enumerate(thresholds) if r['eligible']), key=lambda i: (thresholds[i]['quoted_net_CE'], -i))
            bundle.threshold = thresholds[selected]['threshold']
            out = output / f"seed-{seed}" / candidate['name']; out.mkdir(parents=True)
            # The diagnostic re-quoted threshold lives only in this new bundle;
            # the original actor/critic and primary threshold are never mutated.
            save(bundle, out / 'bundle.pt')
            checkpoint, digest = str(out / 'bundle.pt'), file_sha(out / 'bundle.pt')
            report = {'seed': seed, 'candidate': candidate, 'training': training,
                      'fit_fidelity': fidelity(actor, fit_x, fit_y), 'selection_fidelity': fidelity(actor, select_x, select_y),
                      'cost_quote': quote, 'threshold_candidates': thresholds, 'selected_index': selected,
                      'development_threshold': bundle.threshold, 'checkpoint': checkpoint, 'checkpoint_sha256': digest,
                      'original_checkpoint_sha256': old['bundle_sha256'],
                      'original_threshold': old['threshold'], 'original_critic_unchanged': True,
                      'prospective_source_evaluation': False, 'primary_changed': False}
            write_json(out / 'report.json', report); all_rows.append(report)
            print(json.dumps({'seed': seed, 'candidate': candidate['name'], 'fit_fidelity': report['fit_fidelity'],
                              'selection_fidelity': report['selection_fidelity'], 'threshold': bundle.threshold}), flush=True)
    if any(file_sha(Path(p)) != expected for p, expected in source.items()):
        raise ValueError('Repair implementation changed')
    write_json(output / 'result.json', {'schema': spec['schema'], 'status': 'completed', 'scope': spec['source_scope'],
               'records': all_rows, 'source_sha256': source, 'wall_ns': time.perf_counter_ns() - wall,
               'cpu_ns': time.process_time_ns() - cpu, 'completed_unix_ns': time.time_ns(),
               'primary_changed': False, 'new_source_evaluation': False, 'all_registered_candidates_executed': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.asset_root, args.development, args.output)
