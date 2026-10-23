"""Independent read-only audit of the frozen v2 confirmation evidence.

No experiment modules are imported. No training or policy selection is run.

Usage: python audit_confirmation.py --repo CHECKOUT --run EVIDENCE_DIRECTORY
           --output NEW_REVIEW_JSON
"""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time

AUDIT_WALL_START = time.perf_counter()
AUDIT_CPU_START = time.process_time()

import numpy as np
import torch
import torch.nn.functional as F

REPO = None
RUN = None
SOURCE = 'c5c6b9df0a83a9a2f95d5583b95909829a982b06'
BASE = '9da3c2b98bf427c5812cdc332d4adda1fc23bac6'
DESTINATION = None
NAMES = ('text', 'audio', 'image', 'video')
DIMS = dict(zip(NAMES, (40, 1024, 768, 3072)))
COSTS = {'audio': 3, 'image': 2, 'video': 5}


def read(name):
    return json.loads((RUN / name).read_text())


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1048576), b''):
            value.update(chunk)
    return value.hexdigest()


def commit_bytes(commit, path):
    return subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=REPO)


def cv90(values):
    """Ascending order with exact top-decile fractional boundary mass."""
    x = np.sort(np.asarray(values), axis=-1)
    mass = x.shape[-1] / 10
    count = math.ceil(mass)
    weight = mass - (count - 1)
    return (x[..., -(count - 1):].sum(axis=-1) + weight * x[..., -count]) / mass


def paired_interval(left, right, statistic):
    count, size = left.shape
    rng = np.random.default_rng(7891)
    replicates = []
    for _ in range(1000):
        seed_indices = rng.integers(count, size=count)
        world_indices = rng.integers(size, size=(count, size))
        differences = []
        for slot, seed_index in enumerate(seed_indices):
            a, b = left[seed_index, world_indices[slot]], right[seed_index, world_indices[slot]]
            differences.append(float(statistic(a) - statistic(b)))
        replicates.append(float(np.mean(differences)))
    lower, upper = np.quantile(replicates, [0.025, 0.975])
    return {'estimate': float(np.mean([statistic(a) - statistic(b) for a, b in zip(left, right)])),
            'ci_low': float(lower), 'ci_high': float(upper),
            'bootstrap_replicates': 1000, 'paired': True, 'independent_seed_worlds': True}


def checkpoint_hashes(state):
    accumulators = {name: hashlib.sha256() for name in ('all', 'encoders', 'shared_refinement', 'decoders')}
    for name in sorted(state):
        array = state[name].detach().cpu().numpy()
        group = 'encoders' if name.startswith('encoders.') else 'decoders' if name.startswith('decoders.') else 'shared_refinement'
        header = json.dumps([name, list(array.shape), str(array.dtype)], separators=(',', ':')).encode()
        payload = len(header).to_bytes(8, 'little') + header + array.tobytes()
        for target in ('all', group):
            accumulators[target].update(payload)
    return {name: value.hexdigest() for name, value in accumulators.items()}


def prototypes():
    """Reconstruct the fixed eight benchmark targets directly from their definitions."""
    colors = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0]], dtype=np.float32)
    text = np.zeros((8, 4, 10), dtype=np.float32)
    images = np.zeros((8, 16, 16, 3), dtype=np.float32)
    videos = np.zeros((8, 4, 16, 16, 3), dtype=np.float32)
    for klass in range(8):
        color, direction = divmod(klass, 2)
        text[klass, np.arange(4), [color, 6, 4 + direction, 7]] = 1
        x = 2 if direction == 0 else 10
        images[klass, 6:10, x:x + 4] = colors[color]
        for frame in range(4):
            x = (10 if direction == 0 else 2) + (2 * direction - 1) * 2 * frame
            videos[klass, frame, 6:10, x:x + 4] = colors[color]
    time = np.arange(1024, dtype=np.float64) / 8192
    audio = (0.85 * np.sin(2 * np.pi * (256 + 64 * np.arange(8))[:, None] * time)).astype(np.float32)
    return {'text': text.reshape(8, -1), 'audio': audio,
            'image': images.reshape(8, -1), 'video': videos.reshape(8, -1)}


def replay(state, portfolios, depths):
    """Execute Linear/GELU/Tanh equations directly, without model/rollout wrappers."""
    output = {name: np.empty((len(depths), DIMS[name]), dtype=np.float32) for name in NAMES}

    def linear(x, prefix):
        return F.linear(x, state[prefix + '.weight'], state[prefix + '.bias'])

    with torch.inference_mode():
        for depth in range(4):
            indices = np.flatnonzero(depths == depth)
            if not len(indices):
                continue
            q = torch.as_tensor(portfolios[indices], dtype=torch.float32)
            latent = linear(q, 'initial_latent')
            for _ in range(depth):
                latent = latent + linear(torch.tanh(linear(latent, 'refinement.0')), 'refinement.2') / 3
            for name in NAMES:
                output[name][indices] = linear(F.gelu(linear(latent, 'decoders.' + name + '.0')),
                                               'decoders.' + name + '.2').numpy()
    return output


def independent_scores(output, truth, targets):
    errors, classes, ambiguous = [], [], []
    for name in NAMES:
        canonical = targets[name].astype(np.float64)
        generated = output[name].astype(np.float64)
        pair_distances = ((canonical[:, None, :] - canonical[None, :, :]) ** 2).mean(-1)
        scale = pair_distances[~np.eye(8, dtype=bool)].mean()
        distance = np.stack([((generated - canonical[c]) ** 2).mean(1) / scale for c in range(8)], axis=1)
        errors.append(np.minimum(distance[np.arange(len(truth)), truth], 2))
        classes.append(distance.argmin(1))
        ordered = np.sort(distance, axis=1)
        ambiguous.append(ordered[:, 1] - ordered[:, 0] < 0.1)
    guessed = np.stack(classes, axis=1)
    contradiction = np.stack([guessed[:, a] != guessed[:, b] for a, b in itertools.combinations(range(4), 2)]).mean(0)
    raw = np.stack(errors).mean(0)
    return {'loss': raw + contradiction / 4, 'raw_error': raw,
            'contradiction': contradiction, 'quality': (guessed == truth[:, None]).mean(1),
            'omission': np.stack(ambiguous).mean(0)}


def main():
    global REPO, RUN, DESTINATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    REPO, RUN, DESTINATION = args.repo.resolve(), args.run.resolve(), args.output.resolve()
    if not (RUN / 'completion.json').exists() or not (RUN / 'artifact-manifest.json').exists():
        raise SystemExit('Confirmation is not complete; no review written.')
    if DESTINATION.exists():
        raise SystemExit('Review already exists; preserve it.')
    torch.set_num_threads(4)
    protocol, runtime, completion = read('protocol.json'), read('runtime-start.json'), read('completion.json')
    assert completion['execution_completed'] and not completion['smoke_only']
    assert runtime['source_commit'] == SOURCE and runtime['source_frozen'] and runtime['tier'] == 'local-cpu'
    issues = []
    source_files = runtime['source_manifest']['files']
    for path, expected in source_files.items():
        if hashlib.sha256(commit_bytes(SOURCE, path)).hexdigest() != expected or sha(REPO / path) != expected:
            issues.append('source hash mismatch: ' + path)
    combined = hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest()
    assert combined == runtime['source_manifest']['combined_sha256']
    assert protocol == json.loads(commit_bytes(SOURCE, 'experiments/multimodal_output_portfolio/v2/protocol.json'))
    artifact = read('artifact-manifest.json')
    for path, entry in artifact.items():
        if (RUN / path).stat().st_size != entry['bytes'] or sha(RUN / path) != entry['sha256']:
            issues.append('artifact hash mismatch: ' + path)
    extra = sorted(str(p.relative_to(RUN)) for p in RUN.rglob('*') if p.is_file()
                   and str(p.relative_to(RUN)) not in artifact and p.name != 'artifact-manifest.json')
    if extra:
        issues.append('unmanifested artifacts: ' + repr(extra))
    old_changes = subprocess.check_output(['git', 'diff', '--name-status', '--diff-filter=MDR', BASE, SOURCE,
                                          '--', 'experiments/multimodal_output_portfolio'], cwd=REPO, text=True)
    current_old_changes = subprocess.check_output(['git', 'diff', '--name-status', '--diff-filter=MDR', BASE,
                                                  '--', 'experiments/multimodal_output_portfolio'], cwd=REPO, text=True)
    if old_changes:
        issues.append('old experiment files modified: ' + old_changes)
    if current_old_changes:
        issues.append('current old experiment files modified: ' + current_old_changes)
    seeds, budgets, arms = protocol['seeds'], protocol['budgets_after_initial_text'], protocol['arms']
    scenarios = ['test_iid', 'correlation_shift', 'all_shared_wrong']
    grids = {seed: np.load(RUN / f'seed-{seed}/loss-tables.npz')['portfolios'] for seed in seeds}
    numeric = ['loss', 'quality', 'omission', 'contradiction', 'raw_error', 'linear_macs',
               'remaining', 'depth', 'portfolio_index', 'preference', 'truth']
    index = {name: column for column, name in enumerate(numeric)}
    groups = {}
    trace_failures = defaultdict(int)
    total = 0
    with gzip.open(RUN / 'per_world.csv.gz', 'rt', encoding='utf-8', newline='') as source:
        for row in csv.DictReader(source):
            key = int(row['seed']), row['scenario'], int(row['budget']), row['arm']
            seed, scenario, budget, arm = key
            if key not in groups:
                groups[key] = {'values': [], 'ids': hashlib.sha256(), 'encoded': dict.fromkeys(NAMES, 0),
                               'call_groups': set(), 'depth': [0] * 4, 'seen': 0}
            group = groups[key]
            expected_id = f"{protocol['rng']['split_prefix']}-confirmation-{scenario}:{protocol['rng']['heldout_base'] + 100 * seed + scenarios.index(scenario)}:{group['seen']:08d}"
            trace_failures['world_id'] += row['world_id'] != expected_id
            group['ids'].update((row['world_id'] + ':' + row['truth'] + '\n').encode())
            values = [float(row[name]) for name in numeric]
            group['values'].append(values)
            depth, portfolio, preference = int(row['depth']), int(row['portfolio_index']), int(row['preference'])
            group['depth'][depth] += 1
            q = np.array(json.loads(row['portfolio']))
            trace_failures['portfolio_index'] += not np.array_equal(q, grids[seed][portfolio])
            trace_failures['metric_identity'] += abs(float(row['loss']) - float(row['raw_error']) - float(row['contradiction']) / 4) > 1e-12
            trace = json.loads(row['trace'])
            obs, p, remaining, refinements, stage, acquisition_round = {}, 0, budget, 0, 'initial', 0
            calculated_macs = 8 * 64 + depth * 2 * 64 * 64 + sum(64 * 64 + 64 * DIMS[name] for name in NAMES)
            for event_index, event in enumerate(trace):
                kind = event['event']
                if kind == 'initial_text':
                    trace_failures['initial_event'] += not (event_index == 0 and stage == 'initial' and event['modality'] == 'text')
                    stage = 'evidence'
                elif kind == 'acquire':
                    trace_failures['acquisition_order'] += not (stage == 'evidence' and event['modality'] not in obs and event['modality'] != 'text')
                    remaining -= COSTS[event['modality']]
                    acquisition_round += 1
                    if event['report'] < 8:
                        conflict = any(report < 8 and report != event['report'] for report in obs.values())
                        p = min(3, max(0, p + (1 if conflict else -1)))
                elif kind == 'initialize':
                    trace_failures['initialization_order'] += stage != 'evidence' or event['portfolio'] != portfolio
                    stage = 'generation'
                    remaining -= 2
                elif kind == 'refine':
                    refinements += 1
                    remaining -= 2
                    trace_failures['refinement_order'] += stage != 'generation' or event['depth'] != refinements
                elif kind == 'emit_all_four':
                    remaining -= 2
                    trace_failures['emission_contract'] += not (stage == 'generation' and event_index == len(trace) - 1 and event['sealed'] and event['depth'] == depth and refinements == depth)
                    stage = 'sealed'
                else:
                    trace_failures['unknown_event'] += 1
                if kind in ('initial_text', 'acquire'):
                    name, report = event['modality'], event['report']
                    obs[name] = report
                    trace_failures['report_range'] += not 0 <= report <= 8
                    if report < 8:
                        calculated_macs += DIMS[name] * 64 + 64 * 8
                        group['encoded'][name] += 1
                        group['call_groups'].add((acquisition_round, name))
                trace_failures['event_budget'] += event['remaining'] != remaining or remaining < 0
            trace_failures['terminal_state'] += stage != 'sealed' or remaining != int(row['remaining']) or p != preference
            trace_failures['linear_macs'] += calculated_macs != int(row['linear_macs'])
            support = {report for report in obs.values() if report < 8}
            trace_failures['portfolio_support'] += bool(support) and any(q[c] != 0 for c in range(8) if c not in support)
            trace_failures['empty_support_uniform'] += not support and not np.array_equal(q, np.full(8, 1 / 8))
            group['seen'] += 1
            total += 1
    expected_rows = len(seeds) * len(budgets) * len(arms) * sum(protocol['splits'][scenario] for scenario in scenarios)
    assert total == expected_rows == completion['world_evaluations']
    assert len(groups) == len(seeds) * len(budgets) * len(arms) * len(scenarios)
    group_summary, paired = [], []
    for key, group in groups.items():
        seed, scenario, budget, arm = key
        group['array'] = np.array(group.pop('values'), dtype=np.float64)
        assert np.isfinite(group['array']).all()
        assert group['seen'] == protocol['splits'][scenario]
        execution = read(f'seed-{seed}/{scenario}-{budget}-{arm}-execution.json')
        assert execution['all_four_outputs'] and execution['budget_violations'] == 0
        assert set(execution['output_sha256']) == set(NAMES)
        if group['encoded'] != execution['encoded_examples']:
            issues.append('encoder example count mismatch: ' + repr(key))
        calls = {name: sum(modality == name for _, modality in group['call_groups']) for name in NAMES}
        if calls != execution['encoder_calls']:
            issues.append('encoder call count mismatch: ' + repr(key))
        group_summary.append({'seed': seed, 'scenario': scenario, 'budget': budget, 'arm': arm,
                              'worlds': group['seen'], 'depth_counts': group['depth'],
                              'mean_loss': float(group['array'][:, index['loss']].mean()),
                              'cvar90': float(cv90(group['array'][:, index['loss']])),
                              'mean_quality': float(group['array'][:, index['quality']].mean()),
                              'mean_linear_macs': float(group['array'][:, index['linear_macs']].mean())})
    for seed in seeds:
        for scenario in scenarios:
            digests = {groups[seed, scenario, budget, arm]['ids'].hexdigest() for budget in budgets for arm in arms}
            assert len(digests) == 1
            paired.append({'seed': seed, 'scenario': scenario, 'ordered_world_id_and_truth_sha256': digests.pop(),
                           'arms_and_budgets_checked': len(arms) * len(budgets)})
    if any(trace_failures.values()):
        issues.append('trace or per-world consistency failures: ' + repr(dict(trace_failures)))

    def arrays(arm, metric):
        return np.stack([groups[seed, 'test_iid', 12, arm]['array'][:, index[metric]] for seed in seeds])

    candidate, baseline = arrays('joint_ndu', 'loss'), arrays('supervised_static', 'loss')
    endpoint = paired_interval(candidate, baseline, cv90)
    quality = paired_interval(arrays('joint_ndu', 'quality'), arrays('supervised_static', 'quality'), np.mean)
    ratio = float(arrays('joint_ndu', 'linear_macs').mean() / arrays('supervised_static', 'linear_macs').mean())
    audits = read('audits.json')
    expected_audits = {(seed, arm) for seed in seeds for arm in arms if not arm.endswith('_static')}
    assert {(a['seed'], a['arm']) for a in audits} == expected_audits and len(audits) == 15
    oracle_passed = all(a['states'] == 14298 and a['passed'] and a['max_value_error'] <= 1e-10
                        and a['action_portfolio_depth_mismatches'] == 0 for a in audits)
    gates = {'cvar_reduction_at_least_0_02': endpoint['estimate'] <= -0.02,
             'cvar_ci_upper_below_zero': endpoint['ci_high'] < 0,
             'quality_noninferiority_point_margin_0_02': quality['estimate'] >= -0.02,
             'linear_mac_ratio_at_most_1_05': ratio <= 1.05,
             'three_registered_seeds': seeds == [17, 29, 43],
             'independent_oracle_parity': oracle_passed,
             'output_and_budget_contracts': not any(trace_failures.values())}
    # Read reported results only after deriving the primary comparison independently.
    reported = read('results.json')
    comparison_errors = {key: abs(endpoint[key] - reported['primary']['loss_cvar90'][key]) for key in ('estimate', 'ci_low', 'ci_high')}
    comparison_errors.update({'quality_' + key: abs(quality[key] - reported['primary']['quality_mean'][key]) for key in ('estimate', 'ci_low', 'ci_high')})
    comparison_errors['linear_mac_ratio'] = abs(ratio - reported['primary']['mean_linear_mac_ratio'])
    if max(comparison_errors.values()) > 1e-10 or gates != reported['gates'] or all(gates.values()) != reported['primary_passed']:
        issues.append('primary result or gate mismatch')
    training, replays = [], []
    targets = prototypes()
    for seed in seeds:
        left, right = read(f'seed-{seed}/joint-training.json'), read(f'seed-{seed}/supervised-training.json')
        checkpoints = {name: torch.load(RUN / f'seed-{seed}/{name}-model.pt', map_location='cpu', weights_only=True)
                       for name in ('warmup', 'supervised', 'joint')}
        for name, checkpoint in checkpoints.items():
            assert checkpoint_hashes(checkpoint['state_dict']) == checkpoint['weight_sha256']
            assert checkpoint['dimensions'] == DIMS
        assert left['initial_hashes'] == right['initial_hashes'] == checkpoints['warmup']['weight_sha256']
        assert left['final_hashes'] == checkpoints['joint']['weight_sha256']
        assert right['final_hashes'] == checkpoints['supervised']['weight_sha256']
        assert left['optimizer_steps'] == right['optimizer_steps'] == 40
        assert left['forward_linear_macs'] == right['forward_linear_macs']
        depth_work = 8 * 64 + 3 * 2 * 64 * 64 + 4 * sum(64 * 64 + 64 * DIMS[name] for name in NAMES)
        assert left['forward_linear_macs'] == 40 * (len(grids[seed]) + 8) * depth_work
        assert left['initial_hashes']['encoders'] == left['final_hashes']['encoders'] == right['final_hashes']['encoders']
        assert left['calibration_sha256'] == right['calibration_sha256']
        joint_table = np.load(RUN / f'seed-{seed}/calibration.npz')['joint']
        assert hashlib.sha256(joint_table.tobytes()).hexdigest() == left['calibration_sha256']
        gradients = []
        for entry in left['gradient_evidence']:
            utility, anchor = entry['negative_utility_gradient_l2'], entry['unweighted_anchor_gradient_l2']
            assert all(np.isfinite(value) and value >= 0 for value in utility.values())
            assert entry['excludes_optimizer_weight_decay'] and entry['frozen_encoders_not_differentiated']
            gradients.append({'step': entry['step'], 'utility_gradient_l2': utility,
                              'anchor_gradient_l2': anchor})
        reached = [{'step': e['step'], 'root_action_probabilities': e['root_action_probabilities'],
                    'depth_probabilities': e['reached_commitment_depth_probabilities'],
                    'expected_evidence_acquisitions': e['expected_evidence_acquisitions']} for e in left['selected_policy_evidence']]
        assert [e['step'] for e in gradients] == [1, 40]
        training.append({'seed': seed, 'identical_initial_checkpoint': True, 'optimizer_updates_each': 40,
                         'forward_linear_macs_each': left['forward_linear_macs'], 'encoders_unchanged': True,
                         'calibration_unchanged': True, 'lifetime_compute_matched': False,
                         'gradient_attribution': gradients, 'physical_probability_policy_distribution': reached})
        offline = read(f'seed-{seed}/offline-costs.json')
        for name in ('supervised', 'joint'):
            assert offline['candidate_tables'][name]['two_actual_all_depth_forwards_charged']
            assert offline['candidate_tables'][name]['forward_linear_macs'] == 2 * len(grids[seed]) * depth_work
        for stage in ('calibration', 'validation'):
            measured = offline[stage]
            independent_work = sum(measured['encoded_examples'][name] * (DIMS[name] * 64 + 64 * 8) for name in NAMES)
            assert measured['forward_linear_macs'] == independent_work
        for arm, model_name in [('joint_ndu', 'joint'), ('supervised_static', 'supervised')]:
            matrix = groups[seed, 'test_iid', 12, arm]['array']
            depth = matrix[:, index['depth']].astype(np.int64)
            choices = matrix[:, index['portfolio_index']].astype(np.int64)
            outputs = replay(checkpoints[model_name]['state_dict'], grids[seed][choices], depth)
            output_hashes = {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in outputs.items()}
            recorded_hashes = read(f'seed-{seed}/test_iid-12-{arm}-execution.json')['output_sha256']
            if output_hashes != recorded_hashes:
                issues.append('direct primary generation replay hash mismatch: ' + str(seed) + ':' + arm)
            scores = independent_scores(outputs, matrix[:, index['truth']].astype(np.int64), targets)
            differences = {name: float(np.max(np.abs(values - matrix[:, index[name]]))) for name, values in scores.items()}
            if max(differences.values()) > 1e-10:
                issues.append('independent primary scorer mismatch: ' + str(seed) + ':' + arm)
            replays.append({'seed': seed, 'arm': arm, 'worlds': len(depth), 'all_four_output_hashes_match': output_hashes == recorded_hashes,
                            'max_abs_metric_differences': differences})
    progress = [json.loads(line) for line in (RUN / 'progress.jsonl').read_text().splitlines()]
    selection = []
    for seed in seeds:
        events = [(i, e) for i, e in enumerate(progress) if e.get('seed') == seed]
        frozen = [(i, e) for i, e in events if e['event'] == 'policy_selection_frozen_before_new_worlds']
        assert len(frozen) == 1
        actual_hash = sha(RUN / f'seed-{seed}/validation-selection.json')
        assert actual_hash == frozen[0][1]['selection_sha256']
        assert all(i > frozen[0][0] for i, e in events if e['event'] == 'scenario_complete')
        selection.append({'seed': seed, 'frozen_selection_sha256': actual_hash,
                          'unchanged_at_end': True, 'logged_before_all_scenario_completion_events': True})
    result = {
        'schema': 'hepta.controlled-generation.independent-confirmation-review.v1',
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'reviewer_role': 'separate collaborating agent; independent calculations, not external signed attestation',
        'run_directory_at_review': str(RUN), 'source_commit': SOURCE,
        'audit_script_sha256': sha(Path(__file__)),
        'audit_script_path': 'experiments/multimodal_output_portfolio/v2/evidence/audit_confirmation.py',
        'review_execution_cost': {'wall_seconds': time.perf_counter() - AUDIT_WALL_START,
                                 'process_cpu_seconds': time.process_time() - AUDIT_CPU_START,
                                 'scope': 'Separate post-run audit including NumPy/Torch imports; excludes final review JSON serialization. Not part of original experiment training or inference cost.'},
        'scope': 'Read-only completed evidence audit. No training, policy reselection, empirical tuning, source edit, or heldout rerun.',
        'source_integrity': {'manifest_files': len(source_files), 'combined_sha256': combined,
                             'source_frozen_at_execution': True, 'commit_and_current_bytes_checked': True,
                             'artifact_files': len(artifact), 'unmanifested_artifacts': extra,
                             'old_experiment_modified_or_deleted_paths': old_changes.splitlines(),
                             'current_old_experiment_modified_or_deleted_paths': current_old_changes.splitlines()},
        'execution_scope': {'tier': runtime['tier'], 'smoke_only': False, 'source_unchanged_receipt': completion['source_unchanged'],
                            'world_evaluations': total, 'distinct_seed_scenario_worlds': sum(protocol['splits'][s] for s in scenarios) * len(seeds),
                            'groups': len(groups), 'dedicated_execution_verified': False},
        'paired_evidence': paired, 'per_world_trace_and_cost_failures': dict(trace_failures),
        'independent_primary': {'definition': 'mean across seeds of within-seed upper-tail CVaR90(candidate) minus CVaR90(baseline)',
                                'scenario': 'test_iid', 'budget': 12, 'candidate': 'joint_ndu', 'baseline': 'supervised_static',
                                'cvar90': endpoint, 'quality_mean': quality, 'mean_linear_mac_ratio': ratio,
                                'gates': gates, 'primary_passed': all(gates.values()),
                                'reported_result_absolute_differences': comparison_errors,
                                'method': 'CSV-only aligned arrays; ascending weighted-tail estimator and separately implemented paired seed/world percentile bootstrap. Experiment metrics/reporting modules were not imported.'},
        'all_oracle_receipts': audits, 'training_fairness_and_credit': training,
        'primary_saved_weight_and_metric_replays': replays,
        'selection_freeze_receipts': selection,
        'all_observed_depth_distributions': group_summary,
        'limitations': ['Only three training seeds; percentile intervals provide limited training-variability evidence.',
                       'All 15 oracle receipts are checked; this review does not rerun the oracle computation.',
                       'Exact saved-weight generation and independent metric replay cover the two primary arms at budget12, all three seeds; every row receives trace, cost and paired-ID checks.',
                       'Selection ordering is established from frozen source control flow and retained log/hash evidence, not an external trusted timestamp service.',
                       'Linear MAC matching is not backward, optimizer, controller, wall-time or lifecycle compute equivalence.',
                       'Utility gradient evidence at updates1and40 does not prove nonzero credit in every group at every update.',
                       'Native HEPTA runtime, general stochastic FBSDE, learned identified preference, latent-dependent refinement feedback, natural-data foundation-model performance and dedicated execution remain separate gates.'],
        'integrity_issues': issues, 'integrity_review_passed': not issues,
        'scientific_disposition': 'Passes the preregistered bounded primary gate.' if all(gates.values()) else 'Does not pass the preregistered bounded primary gate; retain the result without retuning or substituting secondary endpoints.'}
    with DESTINATION.open('x') as destination:
        json.dump(result, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write('\n')
    print(json.dumps({'review': str(DESTINATION), 'sha256': sha(DESTINATION),
                      'primary': result['independent_primary'], 'integrity_issues': issues,
                      'world_evaluations': total, 'oracle_count': len(audits)}, sort_keys=True))


if __name__ == '__main__':
    main()
