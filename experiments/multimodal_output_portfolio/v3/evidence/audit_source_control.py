"""Supplemental independent calibration/action audit of frozen v3 evidence.

The original run saved calibration identities, summaries and executed actions,
not every compiled table. We reconstruct all histories independently, compare
them with a deterministic replay of the frozen source compiler, and check all
recorded heldout actions. No training, selection or threshold is changed.
"""

import argparse
from collections import defaultdict
import gzip
from itertools import combinations_with_replacement
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from audit_confirmation import MODALITIES, Replay, close, read, require, sha


def encode_reports(model, raw):
    reports = np.full((len(raw['text']), 4), 8, dtype=np.int64)
    start = model.macs
    for index, name in enumerate(MODALITIES):
        available = np.any(raw[name] != 0, axis=1)
        if available.any():
            reports[available, index] = model.encode(raw[name][available], name)
    return reports, model.macs - start


def indices(reports):
    return ((reports[:, 0] * 9 + reports[:, 1]) * 9 + reports[:, 2]) * 9 + reports[:, 3]


@torch.inference_mode()
def audit(args):
    wall, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(4)
    repo, run = args.repo.resolve(), args.run.resolve()
    protocol, runtime = read(run / 'protocol.json'), read(run / 'runtime-start.json')
    previous_path = Path(__file__).with_name('review_confirmation.json')
    previous = read(previous_path)
    require(previous['audit_passed'] and previous['confirmatory'] and not runtime['smoke'], 'completed confirmatory evidence required')
    require(previous['audit_script_sha256'] == sha(Path(__file__).with_name('audit_confirmation.py').read_bytes()), 'unchanged primary auditor')
    require(previous['artifact_manifest_sha256'] == sha((run / 'artifact-manifest.json').read_bytes()), 'same formal evidence')
    for name, receipt in read(run / 'artifact-manifest.json').items():
        require(sha((run / name).read_bytes()) == receipt['sha256'], ('formal artifact', name))
    for name, expected in runtime['source_sha256'].items():
        require(sha((repo / name).read_bytes()) == expected, ('frozen source', name))
    sys.path[:0] = [str(repo / 'experiments/multimodal_output_portfolio/v3'),
                   str(repo / 'experiments/multimodal_output_portfolio')]
    from world import canonical, render, sample_worlds
    # This compiler is the implementation under comparison, never the oracle.
    from source_control import compile_source_policy
    from model import load_model
    settings = protocol['robust_sources']
    namespace = protocol['rng_namespace'] + '-confirmation'
    grid = np.array([np.bincount(row, minlength=8) / 4.
                    for row in combinations_with_replacement(range(8), 4)] + [np.full(8, .125)])
    vertices = np.array([np.flatnonzero((grid == np.eye(8)[c]).all(1))[0] for c in range(8)])
    histories = 9 ** 4
    gamma = 2.
    price = settings['verifier_proxy_cost'] * settings['verifier_utility_penalty']
    summaries = {(r['seed'], r['scenario'], r['arm']): r for r in read(run / 'source-summaries.json')}
    recorded = defaultdict(list)
    with gzip.open(run / 'source-worlds.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            recorded[row['seed'], row['scenario'], row['arm']].append(row)
    audit_rows, comparisons = [], []
    independent_macs, implementation_replay_macs = 0, 0
    evaluated_actions = 0
    for seed in protocol['seeds']:
        model = Replay(run / f'seed-{seed}/ndu-model.pt', canonical())
        stored = read(run / f'seed-{seed}/source-compilation.json')
        posteriors, joints, calibration_cost = [], [], 0
        for index, scenario in enumerate(settings['scenarios']):
            data = sample_worlds(settings['calibration_worlds_per_regime'], 1200000 + 100 * seed + index,
                                 namespace + '-source-calibration-' + scenario, scenario)
            reports, cost = encode_reports(model, data['raw'])
            calibration_cost += cost
            receipt = stored['calibration'][index]
            require(receipt['scenario'] == scenario and receipt['examples'] == len(data['truth']), 'calibration shape')
            require(sha(data['truth'].tobytes()) == receipt['truth_sha256'], 'calibration labels')
            require(sha(reports.tobytes()) == receipt['reports_sha256'], 'calibration actual encoder reports')
            require(cost == receipt['ideal_linear_macs'], 'calibration actual Linear MAC')
            # Independent flattened integer histogram, then one smoothing add.
            counts = np.bincount(data['truth'] * histories + indices(reports), minlength=8 * histories)
            counts = counts.reshape(8, histories).astype(float) + 32. / (8 * histories)
            joints.append(counts / counts.sum())
            posteriors.append((counts / counts.sum(0)).T)
        posteriors = np.stack(posteriors)
        output = model.decode(model.anchor(torch.as_tensor(grid, dtype=torch.float32)))
        losses = np.stack([model.scores(output, np.full(len(grid), c))['loss'] for c in range(8)], 1)
        # CE maximization is equivalent to minimizing expected exp(gamma*loss).
        # Robust minimum CE is the maximum exponential moment over regimes.
        moments = np.einsum('rhc,ac->rha', posteriors, np.exp(gamma * losses))
        nominal = np.argmin(moments[0], axis=1)
        worst = np.max(moments, axis=0)
        robust = np.argmin(worst, axis=1)
        best_stop_moment = np.min(worst, axis=1)
        witness_classes = np.repeat(np.arange(8), 2)
        tokens = np.column_stack((witness_classes // 2, np.full(16, 6),
                                  4 + witness_classes % 2, np.tile([7, 8], 8)))
        witness_support = np.eye(10, dtype=np.float32)[tokens].reshape(16, 40)
        witness_encoded = model.encode(witness_support)
        encoder_channel = np.bincount(witness_classes * 8 + witness_encoded, minlength=64).reshape(8, 8) / 2.
        channel = np.full((8, 8), settings['independent_verifier_error'] / 7.)
        np.fill_diagonal(channel, 1 - settings['independent_verifier_error'])
        channel = channel @ encoder_channel
        terminal = losses[vertices].T
        query_moment = np.einsum('rhc,cy,cy->rh', posteriors, channel, np.exp(gamma * terminal)).max(0)
        query_advantage = np.log(best_stop_moment / query_moment) / gamma - price
        query = query_advantage > 1e-12
        require(np.array_equal(encoder_channel, np.asarray(stored['witness_encoder_channel'])), 'actual witness encoder channel')
        require(np.array_equal(channel, np.asarray(stored['effective_witness_channel'])), 'effective witness channel')
        require(int(query.sum()) == round(stored['query_fraction_of_all_support'] * histories), 'all-support query count')
        compile_cost = calibration_cost + 16 * model.encoder_cost + len(grid) * (model.anchor_cost + model.emit_cost)
        require(compile_cost == stored['offline_forward_linear_macs'], 'full source compilation cost')
        source = protocol['source_checkpoints'][str(seed)]
        source_path = args.source_run / source['path']
        require(sha(source_path.read_bytes()) == source['sha256'], 'frozen compiler source model')
        reference = compile_source_policy(load_model(source_path), canonical(), seed, settings, namespace)
        implementation_replay_macs += reference['receipt']['offline_forward_linear_macs']
        require(np.array_equal(reference['grid'], grid), 'all candidate portfolios')
        loss_error = float(np.max(np.abs(reference['losses'] - losses)))
        joint_error = float(np.max(np.abs(reference['joint'].reshape(3, 8, histories) - np.stack(joints))))
        require(loss_error < 1e-12 and joint_error < 1e-12, 'independent generated loss/joint calibration')
        chosen = np.arange(histories)
        nominal_regret = np.log(moments[0, chosen, reference['nominal']] / moments[0].min(1)) / gamma
        robust_regret = np.log(worst[chosen, reference['robust']] / best_stop_moment) / gamma
        require(np.max(nominal_regret) < 1e-10 and np.max(robust_regret) < 1e-10, 'finite candidate optimum')
        require(np.array_equal(query, reference['query']), 'every history query/stop decision')
        close(float(reference['stop_values'].min()), float((-np.log(best_stop_moment) / gamma).min()), 'robust stop minimum')
        require(np.max(np.abs(reference['stop_values'] + np.log(best_stop_moment) / gamma)) < 1e-10, 'all robust stop values')
        require(np.max(np.abs(reference['query_values'] + np.log(query_moment) / gamma + price)) < 1e-10, 'all query values')
        audit_rows.append({'seed': seed, 'calibration_worlds': len(settings['scenarios']) * settings['calibration_worlds_per_regime'],
            'histories': histories, 'direct_portfolios_per_history': len(grid),
            'nominal_exact_selector_mismatches': int(np.count_nonzero(nominal != reference['nominal'])),
            'robust_exact_selector_mismatches': int(np.count_nonzero(robust != reference['robust'])),
            'maximum_nominal_utility_regret': float(np.max(nominal_regret)),
            'maximum_robust_utility_regret': float(np.max(robust_regret)),
            'query_selector_mismatches': 0, 'query_histories': int(query.sum()),
            'minimum_query_utility_advantage': float(query_advantage.min()),
            'maximum_query_utility_advantage': float(query_advantage.max()),
            'loss_table_max_error': loss_error, 'calibration_joint_max_error': joint_error,
            'offline_forward_linear_macs_verified': compile_cost,
            'independent_policy_sha256': {name: sha(value.tobytes()) for name, value in
                [('nominal', nominal), ('robust', robust), ('query', query), ('losses', losses)]}})
        for scenario_index, scenario in enumerate(settings['scenarios']):
            world_seed = 1300000 + 100 * seed + scenario_index
            count = settings['heldout_worlds_per_scenario']
            data = sample_worlds(count, world_seed, namespace + '-source-heldout-' + scenario, scenario)
            reports, _ = encode_reports(model, data['raw'])
            history = indices(reports)
            rng = np.random.default_rng(world_seed ^ 0x639812)
            wrong = (data['truth'] + rng.integers(1, 8, count)) % 8
            witness_classes = np.where(rng.random(count) < settings['independent_verifier_error'], wrong, data['truth'])
            witness_raw = render(witness_classes, world_seed ^ 0x51777, nuisance=True)['text']
            witness_reports = model.encode(witness_raw)
            for arm in settings['arms']:
                rows = recorded[seed, scenario, arm]
                require(len(rows) == count and [r['world_id'] for r in rows] == data['ids'], 'heldout identity')
                if arm == 'verifier_only':
                    query_selected = np.ones(count, dtype=bool)
                    portfolios = vertices[witness_reports]
                else:
                    portfolios = reference['nominal' if arm == 'nominal' else 'robust'][history].copy()
                    query_selected = query[history] if arm == 'robust_verified' else np.zeros(count, dtype=bool)
                    portfolios[query_selected] = vertices[witness_reports[query_selected]]
                require(np.array_equal(query_selected, [r['queried'] for r in rows]), 'recorded heldout query choice')
                require(np.array_equal(portfolios, [r['portfolio_index'] for r in rows]), 'recorded heldout finite optimal action')
                evaluated_actions += count
            left = recorded[seed, scenario, 'robust_verified']
            right = recorded[seed, scenario, 'verifier_only']
            a, b = summaries[seed, scenario, 'robust_verified'], summaries[seed, scenario, 'verifier_only']
            comparisons.append({'seed': seed, 'scenario': scenario, 'worlds': count,
                'robust_verified_query_fraction': a['query_fraction'], 'verifier_only_query_fraction': b['query_fraction'],
                'exact_same_portfolio_and_query_per_world': all((x['portfolio_index'], x['queried']) ==
                    (y['portfolio_index'], y['queried']) for x, y in zip(left, right)),
                'all_four_output_batch_hashes_equal': a['output_sha256'] == b['output_sha256'],
                'all_world_loss_and_quality_equal': all((x['loss'], x['quality']) ==
                    (y['loss'], y['quality']) for x, y in zip(left, right)),
                'mean_loss_delta': a['mean_loss'] - b['mean_loss'],
                'mean_quality_delta': a['mean_quality'] - b['mean_quality'],
                'robust_verified_linear_macs': a['forward_linear_macs'],
                'verifier_only_linear_macs': b['forward_linear_macs'],
                'online_linear_mac_ratio': a['forward_linear_macs'] / b['forward_linear_macs']})
        independent_macs += model.macs
    require(all(r['query_histories'] == histories for r in audit_rows), 'observed universal-query degeneration')
    require(all(r['exact_same_portfolio_and_query_per_world'] and r['all_four_output_batch_hashes_equal']
                and r['all_world_loss_and_quality_equal'] for r in comparisons), 'witness-only equivalence')
    return {'schema': 'hepta.source-control.supplemental-audit.v3', 'audit_passed': True,
        'run': str(run), 'source_commit': runtime['implementation_commit'],
        'script_sha256': sha(Path(__file__).read_bytes()),
        'primary_audit_sha256': sha(previous_path.read_bytes()),
        'frozen_primary_auditor_sha256': previous['audit_script_sha256'],
        'all_history_audits': audit_rows, 'heldout_arm_world_actions_verified': evaluated_actions,
        'witness_only_comparisons': comparisons,
        'conclusion': 'The finite registered robust query rule is optimal within its declared action set, but queries in every history. It reduces exactly to verifier-only output selection and has additional online encoder cost. No NDU-specific witness quality advantage is established.',
        'allowed_action_class': '331 direct portfolios or one fixed fallback that emits the newly observed witness class; not arbitrary post-query controls',
        'all_histories_method': 'Original compiled arrays were not persisted. Deterministic frozen-source replay is compared against independent manual neural execution and NumPy exponential-moment minimization. Actual heldout actions are compared against the recorded original run.',
        'calibration_method': 'Independent flattened integer histogram plus registered smoothing; actual encoded-report and label hashes match original receipts.',
        'independent_audit_forward_linear_macs': independent_macs,
        'frozen_compiler_replay_forward_linear_macs': implementation_replay_macs,
        'audit_cost_separate_from_experiment': True,
        'wall_seconds': time.perf_counter() - wall, 'process_cpu_seconds': time.process_time() - cpu}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'run', 'source-run', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = audit(args)
    payload = json.dumps(report, indent=2, allow_nan=False)
    with args.output.open('x') as destination:
        destination.write(payload + '\n')
    print(json.dumps({key: report[key] for key in ('audit_passed', 'heldout_arm_world_actions_verified',
                                                 'conclusion', 'wall_seconds')}))


if __name__ == '__main__':
    main()
