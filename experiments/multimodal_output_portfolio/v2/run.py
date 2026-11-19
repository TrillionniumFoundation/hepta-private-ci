#!/usr/bin/env python3
"""Source-frozen confirmation, or isolated development smoke; never test tuning."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import numpy as np
import torch

from control import CalibrationModel, portfolio_grid
from controlled_model import (evaluation_loss_table, external_loss_tensor,
                              train_controlled)
from evaluate import predict_all
from generation_control import GenerationPlanner
from model import mac_counts, save_model, train_model
from world import canonical, render, sample_worlds
from evaluation import rollout, select_static
from reporting import (audit, contrasts, digest, report_text, runtime_receipt,
                       source_manifest, write_json)
from training import all_depth_macs, train_matched_supervised, train_ndu


def paid_predictions(model, raw):
    start = time.process_time()
    predictions, receipt = predict_all(model, raw)
    receipt['process_cpu_seconds'] = time.process_time() - start
    profile = mac_counts(model)
    receipt['forward_linear_macs'] = sum(receipt['encoded_examples'][name] * cost
                                       for name, cost in profile['encoder'].items())
    return predictions, receipt


def world_receipt(world):
    return {'count': len(world['truth']),
            'truth_sha256': hashlib.sha256(world['truth'].tobytes()).hexdigest(),
            'raw_sha256': {name: hashlib.sha256(raw.tobytes()).hexdigest()
                           for name, raw in world['raw'].items()},
            'first_id': str(world['ids'][0]), 'last_id': str(world['ids'][-1])}


def candidate_table(model, grid, targets):
    wall, cpu = time.perf_counter(), time.process_time()
    with torch.inference_mode():
        direct = external_loss_tensor(model, grid, targets).numpy()
        independent = evaluation_loss_table(model, grid, targets)
    error = float(np.abs(direct - independent).max())
    if error > 2e-6:
        raise AssertionError(f'external loss table parity failed: {error}')
    return direct, {'external_metric_max_error': error,
                    'forward_linear_macs': 2 * all_depth_macs(model, len(grid)),
                    'wall_seconds': time.perf_counter() - wall,
                    'process_cpu_seconds': time.process_time() - cpu,
                    'two_actual_all_depth_forwards_charged': True}


def execute(output, tier, smoke):
    if np.__version__ != '1.26.4' or str(torch.__version__).split('+')[0] != '2.5.1':
        raise RuntimeError('registered runtime requires numpy1.26.4 and torch2.5.1')
    torch.set_num_threads(4)
    protocol = json.loads((HERE / 'protocol.json').read_text())
    if protocol['budgets_after_initial_text'] != [8, 12, 16]:
        raise RuntimeError('implementation expects the registered budgets')
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'protocol.json', protocol)
    manifest = source_manifest()
    runtime = runtime_receipt(tier, smoke, manifest)
    write_json(output / 'runtime-start.json', runtime)
    started, started_cpu = time.perf_counter(), time.process_time()

    def progress(event, **fields):
        row = {'event': event, 'elapsed_seconds': time.perf_counter() - started, **fields}
        with (output / 'progress.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)

    sizes = dict(protocol['splits'])
    seeds = [protocol['development_seed']] if smoke else protocol['seeds']
    if smoke:
        sizes = {key: min(value, 128 if key == 'train' else 96)
                 for key, value in sizes.items()}
        sizes['calibration'] = 256
    steps = (32, 16, 3, 3) if smoke else (
        protocol['base_train_steps'], protocol['depth_supervision_steps'],
        protocol['matched_supervised_steps'], protocol['ndu_train_steps'])
    rng = protocol['rng']
    namespace = rng['split_prefix'] + ('-development' if smoke else '-confirmation')
    grid, targets = portfolio_grid(), canonical()
    budgets = protocol['budgets_after_initial_text']
    summary_rows, audit_rows, offline_rows, retained = [], [], [], {}
    columns = ['seed', 'scenario', 'budget', 'arm', 'world_id', 'truth', 'loss',
               'quality', 'omission', 'contradiction', 'raw_error', 'linear_macs',
               'remaining', 'portfolio_index', 'portfolio', 'depth', 'preference', 'trace']
    with gzip.open(output / 'per_world.csv.gz', 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for seed in seeds:
            progress('seed_start', seed=seed)
            directory = output / f'seed-{seed}'
            directory.mkdir()
            offset = rng['development_base'] if smoke else 0
            label_seed = rng['train_labels_base'] + offset + seed
            render_seed = rng['train_render_base'] + offset + seed
            labels = np.random.default_rng(label_seed).integers(8, size=sizes['train'])
            raw = render(labels, seed=render_seed, nuisance=True)
            base, base_training = train_model(raw, labels, targets, seed, steps=steps[0])
            base_training['v2_data'] = {'label_seed': label_seed, 'render_seed': render_seed,
                                       'namespace': namespace + '-clean-training',
                                       'raw_sha256': {key: hashlib.sha256(value.tobytes()).hexdigest()
                                                      for key, value in raw.items()}}
            write_json(directory / 'base-training.json', base_training)
            warm, warm_receipt = train_controlled(base, targets, seed, steps=steps[1])
            write_json(directory / 'warmup-training.json', warm_receipt)
            save_model(warm, directory / 'warmup-model.pt')
            del raw, base
            progress('shared_warmup_complete', seed=seed)

            calibration_world = sample_worlds(sizes['calibration'],
                seed=rng['calibration_base'] + offset + seed,
                split=namespace + '-calibration', scenario='iid')
            predictions, calibration_cost = paid_predictions(warm, calibration_world['raw'])
            calibration = CalibrationModel(calibration_world['truth'], predictions,
                                            protocol['joint_smoothing_total_count'])
            calibration_data = world_receipt(calibration_world)
            np.savez_compressed(directory / 'calibration.npz', joint=calibration.joint,
                                truth=calibration_world['truth'], predictions=predictions)
            del calibration_world
            supervised, supervised_training = train_matched_supervised(
                warm, calibration, targets, grid, seed, protocol, steps[2])
            write_json(directory / 'supervised-training.json', supervised_training)
            progress('matched_supervised_complete', seed=seed)
            joint, joint_training = train_ndu(warm, calibration, targets, grid,
                                              seed, protocol, steps[3])
            write_json(directory / 'joint-training.json', joint_training)
            del warm
            if supervised_training['initial_hashes'] != joint_training['initial_hashes']:
                raise AssertionError('fine-tuning did not start at identical checkpoints')
            if supervised_training['forward_linear_macs'] != joint_training['forward_linear_macs']:
                raise AssertionError('supervised and NDU forward budgets differ')
            models = {'supervised': supervised, 'joint': joint}
            tables, table_cost = {}, {}
            for name, model in models.items():
                save_model(model, directory / f'{name}-model.pt')
                tables[name], table_cost[name] = candidate_table(model, grid, targets)
            np.savez_compressed(directory / 'loss-tables.npz', portfolios=grid, **tables)
            progress('ndu_training_complete', seed=seed,
                     first_utility=joint_training['history'][0]['initial_recursive_utility'],
                     last_utility=joint_training['history'][-1]['initial_recursive_utility'])

            modes = {'supervised_ndu': 'ndu', 'joint_ndu': 'ndu', 'joint_myopic': 'myopic',
                     'joint_fixed_risk': 'fixed', 'joint_risk_neutral': 'neutral'}
            planners, planner_cost = {}, {}
            for arm, mode in modes.items():
                name = arm.split('_')[0]
                planner = GenerationPlanner(calibration, tables[name], grid,
                    gamma=protocol['gamma'], mode=mode, penalty=protocol['penalty'])
                cpu = time.process_time()
                planner.compile(budgets)
                planner_cost[arm] = {'states': planner.state_count,
                    'compile_wall_seconds': planner.compile_seconds,
                    'compile_process_cpu_seconds': time.process_time() - cpu}
                check = {'seed': seed, 'arm': arm, **audit(planner, budgets)}
                audit_rows.append(check)
                planners[arm] = planner
                progress('policy_audited', seed=seed, arm=arm, states=check['states'])
            validation = sample_worlds(sizes['validation'],
                seed=rng['validation_base'] + offset + seed,
                split=namespace + '-validation', scenario='iid')
            validation_predictions, validation_cost = paid_predictions(supervised, validation['raw'])
            validation_data = world_receipt(validation)
            static, selected = {}, {}
            start, cpu = time.perf_counter(), time.process_time()
            for name in models:
                for budget in budgets:
                    specification = select_static(validation_predictions, validation['truth'],
                                                  tables[name], grid, budget)
                    static[(name + '_static', budget)] = specification
                    selected[f'{name}_static:{budget}'] = specification
            selection_cost = {'wall_seconds': time.perf_counter() - start,
                              'process_cpu_seconds': time.process_time() - cpu}
            write_json(directory / 'validation-selection.json', selected)
            selection_hash = digest(directory / 'validation-selection.json')
            offline = {'seed': seed, 'calibration': calibration_cost,
                       'calibration_data': calibration_data, 'validation': validation_cost,
                       'validation_data': validation_data, 'candidate_tables': table_cost,
                       'planner_compilation': planner_cost, 'static_search': selection_cost,
                       'initial_text_budget_excluded_but_encoder_MAC_included': True}
            offline_rows.append(offline)
            write_json(directory / 'offline-costs.json', offline)
            del validation
            progress('policy_selection_frozen_before_new_worlds', seed=seed,
                     selection_sha256=selection_hash)

            for scenario_index, scenario in enumerate(
                    ('test_iid', 'correlation_shift', 'all_shared_wrong')):
                scenario_seed = (rng['development_base'] if smoke else rng['heldout_base']) + 100 * seed + scenario_index
                world = sample_worlds(sizes[scenario], seed=scenario_seed,
                    split=namespace + '-' + scenario,
                    scenario='iid' if scenario == 'test_iid' else scenario)
                write_json(directory / f'{scenario}-worlds.json',
                           {'seed': scenario_seed, **world_receipt(world)})
                for budget in budgets:
                    for arm in protocol['arms']:
                        model = models[arm.split('_')[0]]
                        policy = static[(arm, budget)] if arm.endswith('_static') else planners[arm]
                        misses = None if isinstance(policy, dict) else policy.solve.cache_info().misses
                        scores, receipt, summary = rollout(model, world, policy, budget, grid, targets)
                        if misses is not None and misses != policy.solve.cache_info().misses:
                            raise AssertionError('unaccounted policy compilation during heldout')
                        if receipt['budget_violations'] or not receipt['all_four_outputs']:
                            raise AssertionError('output contract failed')
                        retained.setdefault((scenario, budget, arm), []).append({
                            **scores, **{key: receipt[key] for key in ('linear_macs', 'depth', 'portfolio')}})
                        summary_rows.append({'seed': seed, 'scenario': scenario,
                                             'budget': budget, 'arm': arm, **summary})
                        write_json(directory / f'{scenario}-{budget}-{arm}-execution.json',
                            {key: receipt[key] for key in ('encoder_calls', 'encoded_examples',
                             'output_sha256', 'all_four_outputs', 'budget_violations')})
                        for index, world_id in enumerate(world['ids']):
                            row = {'seed': seed, 'scenario': scenario, 'budget': budget,
                                   'arm': arm, 'world_id': str(world_id),
                                   'truth': int(world['truth'][index])}
                            row.update({key: float(scores[key][index]) for key in
                                        ('loss', 'quality', 'omission', 'contradiction', 'raw_error')})
                            row.update({key: int(receipt[key][index]) for key in
                                        ('linear_macs', 'remaining', 'depth', 'preference')})
                            row['portfolio_index'] = int(receipt['portfolio'][index])
                            row['portfolio'] = json.dumps(grid[row['portfolio_index']].tolist())
                            row['trace'] = json.dumps(receipt['trace'][index], separators=(',', ':'))
                            writer.writerow(row)
                progress('scenario_complete', seed=seed, scenario=scenario)
                del world
            if digest(directory / 'validation-selection.json') != selection_hash:
                raise AssertionError('selection mutated after heldout')
            del models, planners, supervised, joint, calibration

    progress('estimating_preregistered_contrasts')
    results = contrasts(retained, protocol, audit_rows, smoke)
    if manifest != source_manifest():
        raise AssertionError('source dependency changed during execution')
    write_json(output / 'summaries.json', summary_rows)
    write_json(output / 'audits.json', audit_rows)
    write_json(output / 'offline-costs.json', offline_rows)
    write_json(output / 'results.json', results)
    with (output / 'REPORT.md').open('x', encoding='utf-8') as report:
        report.write(report_text(results, summary_rows, runtime))
    progress('completed', primary_passed=results['primary_passed'], smoke_only=smoke)
    write_json(output / 'completion.json', {'execution_completed': True,
        'source_unchanged': True, 'seeds': seeds, 'world_evaluations': sum(row['n'] for row in summary_rows),
        'wall_seconds': time.perf_counter() - started,
        'process_cpu_seconds': time.process_time() - started_cpu,
        'primary_passed': results['primary_passed'], 'smoke_only': smoke})
    write_json(output / 'artifact-manifest.json', {
        str(path.relative_to(output)): {'bytes': path.stat().st_size, 'sha256': digest(path)}
        for path in sorted(output.rglob('*')) if path.is_file()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tier', choices=('local-cpu', 'hosted-cpu', 'dedicated-cloud'), default='local-cpu')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output path exists; preserve every prior attempt')
    try:
        execute(args.output, args.tier, args.smoke)
    except Exception:
        if args.output.is_dir() and not (args.output / 'failure.json').exists():
            write_json(args.output / 'failure.json', {'traceback': traceback.format_exc(),
                                                     'completed': False})
        raise


if __name__ == '__main__':
    main()
