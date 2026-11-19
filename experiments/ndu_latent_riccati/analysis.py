"""Frozen paired hierarchical analysis of NDU continuous-latent run evidence.

Training seeds are the outer resampling units. Each sampled world retains all
of its generated draws and remains paired between the selected comparator and
NDU. The primary estimand is the mean of seed-specific world-loss CVaR90s.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


EPSILON = 1e-8


def cvar90(values):
    values = np.asarray(values, dtype=np.float64)
    n_tail = max(1, (len(values) + 9) // 10)
    return float(np.partition(values, len(values) - n_tail)[-n_tail:].mean())


def world_metrics(arrays, draws):
    """Recompute statistics from raw evidence independently of evaluate.py."""
    loss = np.asarray(arrays['factual_loss'], dtype=np.float64).reshape(-1, draws)
    lawful = np.asarray(arrays['lawful_consistent'], dtype=np.float64).reshape(-1, draws)
    style = np.asarray(arrays['style_positive'], dtype=np.float64).reshape(-1, draws)
    resolved = np.asarray(arrays['correct_resolved'], dtype=np.float64).reshape(-1, draws)
    if not all(np.isfinite(x).all() for x in (loss, lawful, style, resolved)):
        raise ValueError('Nonfinite primary evidence cannot be silently excluded')
    if len(loss) == 0 or np.any(loss < 0):
        raise ValueError('Factual losses must be nonnegative and nonempty')
    if any(np.any((x < 0) | (x > 1)) for x in (lawful, style, resolved)):
        raise ValueError('Lawfulness, style and correctness scores must lie in [0,1]')
    positive = (lawful * style).mean(1)
    negative = (lawful * (1 - style)).mean(1)
    mass = positive + negative
    fraction = np.divide(positive, mass, out=np.full_like(mass, .5), where=mass > 0)
    entropy = -(fraction * np.log2(np.maximum(fraction, 1e-12))
                + (1 - fraction) * np.log2(np.maximum(1 - fraction, 1e-12))) * mass
    return {'loss': loss.mean(1), 'resolved_correctness': resolved.mean(1),
            'lawful_rate': lawful.mean(1), 'lawful_entropy': entropy,
            'lawful_two_style_coverage': ((positive > 0) & (negative > 0)).astype(float)}


def point_metrics(world):
    return {'world_cvar90': cvar90(world['loss']), 'factual_loss': float(world['loss'].mean()),
            'correct_resolved': float(world['resolved_correctness'].mean()),
            'lawful_consistent': float(world['lawful_rate'].mean()),
            'conditional_lawful_style_entropy': float(world['lawful_entropy'].mean()),
            'lawful_two_style_coverage': float(world['lawful_two_style_coverage'].mean())}


def pairing_indices(arrays, worlds, draws):
    if 'world_index' not in arrays or 'draw_index' not in arrays:
        return False
    return (np.array_equal(arrays['world_index'], np.repeat(np.arange(worlds), draws))
            and np.array_equal(arrays['draw_index'], np.tile(np.arange(draws), worlds)))


def hierarchical_bootstrap(pairs, replicates, confidence=.95, seed=736193):
    """Resample seeds and paired worlds; generated draws are never independent units."""
    rng = np.random.default_rng(seed)
    samples = np.empty((replicates, 7), dtype=np.float64)
    count = len(pairs)
    for replicate in range(replicates):
        per_seed = []
        for picked in rng.integers(count, size=count):
            ndu, baseline = pairs[picked]
            indices = rng.integers(len(ndu['loss']), size=len(ndu['loss']))
            per_seed.append((cvar90(ndu['loss'][indices]), cvar90(baseline['loss'][indices]),
                             (ndu['resolved_correctness'][indices] - baseline['resolved_correctness'][indices]).mean(),
                             ndu['lawful_entropy'][indices].mean(), baseline['lawful_entropy'][indices].mean(),
                             (ndu['lawful_rate'][indices] - baseline['lawful_rate'][indices]).mean(),
                             (ndu['loss'][indices] - baseline['loss'][indices]).mean()))
        samples[replicate] = np.mean(per_seed, axis=0)
    tail = (1 - confidence) / 2

    def interval(values):
        return [float(x) for x in np.quantile(values, [tail, 1-tail])]

    baseline_nonzero = samples[:, 1] > EPSILON
    relative = (samples[:, 1] - samples[:, 0]) / np.maximum(samples[:, 1], EPSILON)
    return {'replicates': replicates, 'random_seed': seed, 'confidence': confidence,
            'method': 'paired percentile hierarchical bootstrap; seeds then worlds; all draws stay grouped',
            'cvar90_delta_ci': interval(samples[:, 0] - samples[:, 1]),
            'relative_cvar_improvement_ci': interval(relative) if baseline_nonzero.all() else None,
            'resolved_correctness_delta_ci': interval(samples[:, 2]),
            'ndu_lawful_entropy_ci': interval(samples[:, 3]),
            'baseline_lawful_entropy_ci': interval(samples[:, 4]),
            'lawful_rate_delta_ci': interval(samples[:, 5]),
            'mean_factual_loss_delta_ci': interval(samples[:, 6])}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validation_audit(folder, selection, draws):
    path = folder / 'validation.json'
    if not path.is_file():
        return {'passed': False, 'reason': 'Missing validation evidence'}, []
    recorded = json.loads(path.read_text())
    reference, candidates = recorded['primary'], recorded['candidates']
    cap = float(reference['cpu_seconds_per_world']) * 1.10
    eligible = [r for r in candidates if r['cpu_seconds_per_world'] <= cap]
    same_actuator = [r for r in eligible if r['choice']['arm'] == 'free_joint']
    expected_fairness = bool(same_actuator)
    winner = min(eligible, key=lambda r: (r['world_cvar90'], r['cpu_seconds_per_world'])) if expected_fairness else min(candidates, key=lambda r: r['world_cvar90'])
    mismatches, files = [], [path]
    for report in [reference] + candidates:
        name = 'primary' if report is reference else report['choice']['name']
        raw_path = folder / f'validation__{name}.npz'
        files.append(raw_path)
        with np.load(raw_path, allow_pickle=False) as loaded:
            points = point_metrics(world_metrics(loaded, draws))
        for key, value in points.items():
            if not math.isclose(float(report[key]), value, rel_tol=1e-6, abs_tol=1e-6):
                mismatches.append({'arm': name, 'metric': key})
    valid = (not mismatches and selection.get('fairness_gate') == expected_fairness
             and selection['choice']['name'] == winner['choice']['name']
             and math.isclose(float(selection['cpu_seconds_cap']), cap, rel_tol=1e-12, abs_tol=1e-12))
    return {'passed': bool(valid), 'expected_fairness': expected_fairness,
            'expected_selected_name': winner['choice']['name'], 'raw_metric_mismatches': mismatches}, files


def analyze_run(output, config):
    output = Path(output)
    draws = int(config['draws_per_world'])
    primary = config['primary']
    primary_scenario = primary['scenario']
    primary_name = f"{primary['arm']}__n{config['primary_steps']}"
    per_seed, pairs, evidence, aggregate = [], [], {}, {}
    mismatch, index_failures, provenance_failures = [], [], []
    for seed in config['seeds']:
        folder = output / 'seeds' / str(seed)
        selection_path, eval_path = folder / 'selection.json', folder / 'evaluation.json'
        selection = json.loads(selection_path.read_text())
        val_audit, val_files = validation_audit(folder, selection, draws)
        for path in val_files:
            evidence[str(path.relative_to(output))] = _digest(path)
        reports = json.loads(eval_path.read_text())
        evidence[str(selection_path.relative_to(output))] = _digest(selection_path)
        evidence[str(eval_path.relative_to(output))] = _digest(eval_path)
        if not isinstance(reports, list):
            raise ValueError('evaluation.json must be a list of per-scenario arm reports')
        reference = {}
        metrics = {}
        for report in reports:
            key = (report['scenario'], report['choice']['name'])
            if key in reference:
                raise ValueError(f'Duplicate evaluation report for seed={seed}: {key}')
            reference[key] = report
            path = folder / f'{key[0]}__{key[1]}.npz'
            with np.load(path, allow_pickle=False) as loaded:
                arrays = {name: loaded[name] for name in loaded.files}
            world = world_metrics(arrays, draws)
            expected_worlds = int(config['heldout_worlds'][key[0]])
            if len(world['loss']) != expected_worlds:
                raise ValueError(f'Wrong number of worlds for {path.name}')
            if not pairing_indices(arrays, expected_worlds, draws):
                index_failures.append({'seed': seed, 'scenario': key[0], 'arm': key[1]})
            point = point_metrics(world)
            for name, value in point.items():
                if name not in report or not math.isclose(float(report[name]), value, rel_tol=1e-6, abs_tol=1e-6):
                    mismatch.append({'seed': seed, 'scenario': key[0], 'arm': key[1], 'metric': name,
                                     'recomputed': value, 'reported': report.get(name)})
            metrics[key] = (world, point)
            aggregate.setdefault(key, []).append({'seed': seed, **point,
                                                  'cpu_seconds_per_world': float(report['cpu_seconds_per_world']),
                                                  'wall_seconds_per_world': float(report['seconds_per_world'])})
            evidence[str(path.relative_to(output))] = _digest(path)
        for scenario in config['heldout_worlds']:
            scenario_reports = [r for (s, _), r in reference.items() if s == scenario]
            worlds_path = folder / f'{scenario}__worlds.npz'
            expected_world_seed = config['split_seed_offsets']['test'] + 10000 * list(config['heldout_worlds']).index(scenario) + seed
            valid = bool(scenario_reports) and worlds_path.is_file()
            if valid:
                with np.load(worlds_path, allow_pickle=False) as raw:
                    facts_hash = hashlib.sha256(raw['facts'].tobytes()).hexdigest()
                evidence[str(worlds_path.relative_to(output))] = _digest(worlds_path)
                noise_hashes = {r.get('noise_sha256') for r in scenario_reports}
                valid = (all(r.get('facts_sha256') == facts_hash and r.get('world_seed') == expected_world_seed for r in scenario_reports)
                         and len(noise_hashes) == 1 and isinstance(next(iter(noise_hashes)), str)
                         and len(next(iter(noise_hashes))) == 64)
            if not valid:
                provenance_failures.append({'seed': seed, 'scenario': scenario})
        baseline_name = selection['choice']['name']
        ndu_key, baseline_key = (primary_scenario, primary_name), (primary_scenario, baseline_name)
        ndu_world, ndu_point = metrics[ndu_key]
        baseline_world, baseline_point = metrics[baseline_key]
        if len(ndu_world['loss']) != len(baseline_world['loss']):
            raise ValueError('Primary and comparator worlds are not paired')
        ndu_report, baseline_report = reference[ndu_key], reference[baseline_key]
        ndu_cpu, baseline_cpu = float(ndu_report['cpu_seconds_per_world']), float(baseline_report['cpu_seconds_per_world'])
        if min(ndu_cpu, baseline_cpu) <= 0 or not all(math.isfinite(v) for v in (ndu_cpu, baseline_cpu)):
            raise ValueError('Measured CPU inference costs must be positive finite values')
        training_path = folder / 'training.json'
        training = json.loads(training_path.read_text()) if training_path.is_file() else None
        training_summary = {'receipt_present': training is not None}
        if training is not None:
            evidence[str(training_path.relative_to(output))] = _digest(training_path)
            training_summary.update({key: training.get(key) for key in
                                     ('codec_seconds', 'foundation_seconds', 'continuation_seconds',
                                      'continuation_updates', 'free_to_ndu_training_time_ratio', 'parameters')})
            updates = training.get('continuation_updates', {})
            times = training.get('continuation_seconds', {})
            training_summary['equal_update_comparator_present'] = (
                updates.get('free_equal_updates') == updates.get('ndu_trained') == config['continued_updates'])
            training_summary['free_training_budget_reached'] = (
                float(times.get('free_trained', 0)) >= float(times.get('ndu_trained', math.inf)))
            training_summary['free_training_cap_hit'] = (
                updates.get('free_trained') == config['free_controller_compute_match']['maximum_updates'])
        per_seed.append({'seed': seed, 'selected_baseline': baseline_name,
                         'validation_selection_fairness': bool(selection.get('fairness_gate', False)),
                         'validation_selection_audit': val_audit,
                         'validation_cpu_cap': selection.get('cpu_seconds_cap'),
                         'ndu': ndu_point, 'baseline': baseline_point,
                         'cvar90_delta': ndu_point['world_cvar90'] - baseline_point['world_cvar90'],
                         'ndu_cpu_seconds_per_world': ndu_cpu, 'baseline_cpu_seconds_per_world': baseline_cpu,
                         'baseline_to_ndu_cpu_ratio': baseline_cpu / ndu_cpu,
                         'ndu_to_baseline_cpu_ratio': ndu_cpu / baseline_cpu,
                         'training': training_summary})
        pairs.append((ndu_world, baseline_world))
    if not pairs:
        raise ValueError('No seed evidence was provided')
    mean_ndu = {key: float(np.mean([r['ndu'][key] for r in per_seed])) for key in per_seed[0]['ndu']}
    mean_baseline = {key: float(np.mean([r['baseline'][key] for r in per_seed])) for key in per_seed[0]['baseline']}
    intervals = hierarchical_bootstrap(pairs, int(primary['paired_hierarchical_bootstrap_replicates']),
                                       float(primary['confidence']))
    delta = mean_ndu['world_cvar90'] - mean_baseline['world_cvar90']
    relative = -delta / mean_baseline['world_cvar90'] if mean_baseline['world_cvar90'] > EPSILON else None
    entropy_ndu = mean_ndu['conditional_lawful_style_entropy']
    entropy_baseline = mean_baseline['conditional_lawful_style_entropy']
    entropy_ratio = entropy_ndu / entropy_baseline if entropy_baseline > EPSILON else None
    lawful_delta = mean_ndu['lawful_consistent'] - mean_baseline['lawful_consistent']
    quality_delta = mean_ndu['correct_resolved'] - mean_baseline['correct_resolved']
    gates = {
        'heldout_metrics_match_raw_evidence': not mismatch,
        'world_draw_pairing_indices_verified': not index_failures,
        'shared_world_and_noise_provenance_verified': not provenance_failures,
        'validation_selection_independently_recomputed': all(r['validation_selection_audit']['passed'] for r in per_seed),
        'validation_same_actuator_budget_eligibility': all(r['validation_selection_fairness'] for r in per_seed),
        'selected_comparator_within_NDU_test_cpu_budget': all(r['baseline_to_ndu_cpu_ratio'] <= 1.10 for r in per_seed),
        'equal_update_free_comparator_recorded': all(r['training'].get('equal_update_comparator_present', False) for r in per_seed),
        'free_controller_training_budget_matched': all(r['training'].get('free_training_budget_reached', False) for r in per_seed),
        'primary_relative_tail_improvement': relative is not None and relative >= float(primary['relative_improvement_required']),
        'primary_tail_delta_CI_upper_below_zero': intervals['cvar90_delta_ci'][1] < 0.,
        'resolved_correctness_noninferiority': intervals['resolved_correctness_delta_ci'][0] >= -float(primary['max_resolved_correctness_drop']),
        'lawful_style_entropy_preserved': entropy_ndu > EPSILON and entropy_ndu >= float(primary['min_style_entropy_ratio']) * entropy_baseline,
        'lawful_output_rate_preserved': lawful_delta >= -float(primary.get('max_lawful_consistent_rate_drop', .02)),
    }
    descriptive = []
    for (scenario, name), rows in sorted(aggregate.items()):
        keys = [key for key in rows[0] if key != 'seed']
        descriptive.append({'scenario': scenario, 'arm': name, 'seeds': [r['seed'] for r in rows],
                            'seed_mean': {key: float(np.mean([r[key] for r in rows])) for key in keys},
                            'per_seed': rows})
    development = (config.get('development', False) or config.get('development_only', False) or config.get('development_seed') in config['seeds']
                   or len(config['seeds']) < 5)
    return {'schema': 'ndu-continuous-latent-analysis-v2', 'protocol_id': config['protocol_id'],
            'primary_scenario': primary_scenario, 'primary_arm': primary_name,
            'estimand': 'mean across training seeds of CVaR90 of four-draw world-mean factual loss',
            'training_seed_count': len(pairs), 'worlds_per_seed': [len(p[0]['loss']) for p in pairs],
            'draws_per_world': draws, 'development_only': bool(development),
            'primary': {'ndu': mean_ndu, 'selected_baseline': mean_baseline, 'cvar90_delta': delta,
                        'relative_cvar_improvement': relative, 'resolved_correctness_delta': quality_delta,
                        'lawful_entropy_ratio': entropy_ratio, 'lawful_rate_delta': lawful_delta,
                        'entropy_zero_threshold': EPSILON, 'bootstrap': intervals},
            'gates': gates, 'all_analysis_gates_passed': bool(all(gates.values())),
            'scientific_superiority_gate_passed': bool(all(gates.values()) and not development),
            'scientific_success': bool(all(gates.values()) and not development),
            'per_seed': per_seed, 'descriptive_arms': descriptive,
            'evidence_audit': {'metric_mismatches': mismatch, 'pairing_index_failures': index_failures,
                               'world_noise_provenance_failures': provenance_failures,
                               'sha256': evidence, 'analysis_source_sha256': _digest(Path(__file__))},
            'interpretation_limits': [
                'Only the iid comparison is confirmatory; OOD, ablations and training/inference factorials are descriptive.',
                'Five training seeds give limited information about between-training variability; percentile bootstrap coverage is not guaranteed at this sample size.',
                'Four draws estimate per-world lawful style diversity coarsely; the entropy score is multiplied by lawful output mass.',
                'The inference cost gate requires baseline CPU time <=1.10 times NDU, not that NDU is faster than its baseline.',
                'Wall-clock training matching is approximate; equal-update and measured-budget free-controller continuations are both retained.',
                'Local analysis cannot certify remote runner identity, preregistration publication timing, or a global nonlinear Riccati theorem.',
                'A passed numerical/statistical gate concerns this synthetic experiment, not foundation models or native Hepta qualification.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--protocol', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = analyze_run(args.run, json.loads(args.protocol.read_text()))
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), 'gates': result['gates'],
                      'scientific_superiority_gate_passed': result['scientific_superiority_gate_passed']}, indent=2))
