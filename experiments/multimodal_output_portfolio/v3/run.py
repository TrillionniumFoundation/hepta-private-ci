"""Frozen-source v3 mechanism runner; all failed directories are retained."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path[:0] = [str(HERE), str(PARENT)]

import numpy as np
import torch

from feedback_control import audit_policy, choose_static_depth, compile_policy
from feedback_evaluation import rollout_feedback, score_feedback
from feedback_model import train_feedback_denoiser, weight_hashes
from feedback_training import train_pair
from model import load_model
from native_bridge import NativeBridge
from preference import (evaluate_preference, fit_preference, identifiability_report,
                        randomized_lottery_pairs, simulate_choices)
from reporting import feedback_report
from risk import binomial_entropic_step, gaussian_entropic_bsde
from source_control import run_sources
from world import canonical, render


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    def scalar(item):
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError('unsupported evidence value: ' + type(item).__name__)
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False, default=scalar)
        stream.write('\n')


def source_receipt(smoke):
    repo = HERE.parents[2]
    files = [*HERE.glob('*.py'), HERE / 'protocol.json',
             *(PARENT / name for name in ('model.py', 'world.py', 'control.py', 'metrics.py', 'controlled_model.py')),
             *sorted((repo / 'codex-rs/hepta-ndu/src').glob('feedback_generation*.rs')),
             repo / 'codex-rs/hepta-ndu/src/lib.rs',
             repo / 'codex-rs/hepta-ndu/src/bin/ndu-feedback-generation.rs',
             repo / 'codex-rs/hepta-ndu/Cargo.toml', repo / 'codex-rs/hepta-ndu/BUILD.bazel',
             repo / 'codex-rs/Cargo.lock', HERE / 'evidence/native_build_final.json']
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    manifest, dirty = {}, []
    for path in files:
        relative = str(path.relative_to(repo))
        manifest[relative] = digest(path)
        committed = subprocess.run(['git', 'show', 'HEAD:' + relative], cwd=repo, capture_output=True)
        if committed.returncode or hashlib.sha256(committed.stdout).hexdigest() != manifest[relative]:
            dirty.append(relative)
    if dirty and not smoke:
        raise RuntimeError('confirmation requires committed byte-identical sources: ' + repr(dirty))
    return {'implementation_commit': sha, 'source_sha256': manifest,
            'all_source_bytes_committed': not dirty, 'development_dirty_files': dirty}


def preference_study(seed, settings, smoke):
    size = 256 if smoke else settings['train_pairs']
    holdout = 128 if smoke else settings['heldout_pairs']
    rows = []
    for index, gamma in enumerate(settings['profiles']):
        pairs = randomized_lottery_pairs(size, 1600000 + 100 * seed + index)
        choices = simulate_choices(pairs, gamma, 1700000 + 100 * seed + index)
        fitted = fit_preference(pairs, choices, settings['temperature'], settings['bounds'])
        new_pairs = randomized_lottery_pairs(holdout, 1800000 + 100 * seed + index)
        new_choices = simulate_choices(new_pairs, gamma, 1900000 + 100 * seed + index)
        rows.append({'true_synthetic_gamma': gamma, 'fit': asdict(fitted),
            'absolute_error': abs(fitted.gamma - gamma),
            'identified': identifiability_report(pairs, fitted.gamma),
            'heldout': evaluate_preference(new_pairs, new_choices, fitted.gamma),
            'fixed_gamma2_heldout': evaluate_preference(new_pairs, new_choices, 2.),
            'train_pairs_sha256': hashlib.sha256(pairs.tobytes()).hexdigest(),
            'test_pairs_sha256': hashlib.sha256(new_pairs.tobytes()).hexdigest()})
    return rows


def execute(output, source_run, native_binary, smoke):
    if np.__version__ != '1.26.4' or torch.__version__.split('+')[0] != '2.5.1':
        raise RuntimeError('registered NumPy1.26.4 / Torch2.5.1 runtime required')
    torch.set_num_threads(4)
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / 'protocol.json').read_text())
    write(output / 'protocol.json', protocol)
    source = source_receipt(smoke)
    build = json.loads((HERE / 'evidence/native_build_final.json').read_text())
    if digest(native_binary) != build['binary_sha256']:
        raise RuntimeError('native binary does not match final source build receipt')
    for path, expected in build['source_sha256'].items():
        if digest(HERE.parents[2] / path) != expected:
            raise RuntimeError('native build source changed: ' + path)
    runtime = {'smoke': smoke, 'tier': 'local-cpu', 'dedicated_runner_verified': False,
               'python': platform.python_version(), 'numpy': np.__version__, 'torch': torch.__version__,
               'device': 'cpu', 'threads': torch.get_num_threads(), **source}
    runtime['native_build_receipt_sha256'] = digest(HERE / 'evidence/native_build_final.json')
    write(output / 'runtime-start.json', runtime)
    started, started_cpu = time.perf_counter(), time.process_time()
    def progress(event, **data):
        row = {'event': event, 'elapsed_seconds': time.perf_counter() - started, **data}
        with (output / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
    targets = canonical()
    settings = dict(protocol['feedback'])
    sources = dict(protocol['robust_sources'])
    if smoke:
        settings.update(supervised_warmup_steps=6, matched_supervised_steps=2, ndu_steps=2,
                        heldout_worlds_per_seed_per_scenario=24)
        sources.update(calibration_worlds_per_regime=64, heldout_worlds_per_scenario=24)
    seeds = [protocol['development_seed']] if smoke else protocol['seeds']
    namespace = protocol['rng_namespace'] + ('-development' if smoke else '-confirmation')
    summary, source_summary, preferences, audits, costs = [], [], [], [], []
    retained = {}
    with gzip.open(output / 'feedback-worlds.jsonl.gz', 'wt') as world_log, \
            gzip.open(output / 'source-worlds.jsonl.gz', 'wt') as source_log, \
            gzip.open(output / 'native-transcript.tsv.gz', 'wt') as transcript:
        native = NativeBridge(native_binary, transcript)
        for seed in seeds:
            source_seed = protocol['seeds'][0] if smoke else seed
            checkpoint = source_run / protocol['source_checkpoints'][str(source_seed)]['path']
            if digest(checkpoint) != protocol['source_checkpoints'][str(source_seed)]['sha256']:
                raise RuntimeError('frozen source checkpoint digest mismatch')
            directory = output / f'seed-{seed}'
            directory.mkdir()
            save = lambda name, value: write(directory / name, value)
            progress('seed_start', seed=seed, source_seed=source_seed)
            base = load_model(checkpoint)
            warm, warm_receipt = train_feedback_denoiser(base, targets, seed,
                steps=settings['supervised_warmup_steps'], batch_size=settings['batch_size'],
                noise_scale=settings['noise_scale'], learning_rate=settings['learning_rate'],
                max_refinements=settings['maximum_refinements'])
            save('warmup.json', warm_receipt)
            models, training = train_pair(warm, targets, seed, settings)
            for name, receipt in training.items():
                save(name + '-training.json', receipt)
                torch.save({'dimensions': base.dimensions, 'max_refinements': settings['maximum_refinements'],
                            'state_dict': models[name].state_dict(), 'weight_sha256': weight_hashes(models[name])},
                           directory / (name + '-model.pt'))
            costs.append({'seed': seed, 'warmup': warm_receipt, 'training': training})
            progress('matched_training_complete', seed=seed)
            policies = {}
            for name, mode in [('supervised_feedback', 'feedback'), ('ndu_feedback', 'feedback'),
                               ('ndu_myopic', 'myopic'), ('ndu_robust', 'robust')]:
                model = models['supervised' if name.startswith('supervised') else 'ndu']
                policies[name] = compile_policy(model, targets, seed, settings['gamma'],
                    settings['cost_penalty_per_refinement'], settings['noise_scale'],
                    settings['nominal_branch_probabilities'], settings['ambiguity_rows'], mode)
                audit = {'seed': seed, 'arm': name, **audit_policy(policies[name])}
                audits.append(audit)
            static = {key: choose_static_depth(policies[key + '_feedback']) for key in ('supervised', 'ndu')}
            save('static-selection.json', static)
            save('compiled-policies.json', {key: value.receipt for key, value in policies.items()})
            fits = preference_study(seed, protocol['preference'], smoke)
            for result in fits:
                fitted_policy = compile_policy(models['ndu'], targets, seed, result['fit']['gamma'],
                    settings['cost_penalty_per_refinement'], settings['noise_scale'])
                result['compiled_policy'] = fitted_policy.receipt
                result['changed_actions_vs_fixed_gamma2'] = sum(int(np.count_nonzero(a != b)) for a, b in
                    zip(fitted_policy.actions, policies['ndu_feedback'].actions))
            preferences.append({'seed': seed, 'profiles': fits})
            save('preference.json', fits)
            progress('policies_frozen_before_new_worlds', seed=seed, static=static)
            for scenario_index, scenario in enumerate(settings['scenarios']):
                count = settings['heldout_worlds_per_seed_per_scenario']
                seed_offset = 9000000 if smoke else 0
                label_seed = 1400000 + seed_offset + 100 * seed + scenario_index
                labels = np.random.default_rng(label_seed).integers(8, size=count)
                raw = render(labels, label_seed + 400000, nuisance=True)
                probabilities = settings['nominal_branch_probabilities' if scenario == 'nominal_noise'
                                         else 'shift_branch_probabilities']
                for arm in settings['arms']:
                    model_name = 'supervised' if arm.startswith('matched_supervised') else 'ndu'
                    key = model_name + '_feedback'
                    if arm in ('ndu_myopic', 'ndu_robust'):
                        key = arm
                    depth = static[model_name]['depth'] if arm.endswith('_static') else None
                    if arm in ('ndu_no_refine', 'clean_no_disturbance_reference'):
                        depth = 0
                    outputs, receipts, execution = rollout_feedback(models[model_name], raw['text'],
                        policies[key], targets, label_seed + 200000, probabilities, arm, depth, native)
                    scores, statistics = score_feedback(outputs, receipts, labels, targets)
                    summary.append({'seed': seed, 'scenario': scenario, 'arm': arm, **execution, **statistics})
                    retained.setdefault((scenario, arm), []).append(scores)
                    for row, receipt in enumerate(receipts):
                        world_log.write(json.dumps({'seed': seed, 'scenario': scenario, 'arm': arm,
                            'world_id': f'{namespace}:{seed}:{scenario}:{row}', 'truth': int(labels[row]),
                            **receipt, **{name: float(value[row]) for name, value in scores.items()}}) + '\n')
                    progress('feedback_arm_complete', seed=seed, scenario=scenario, arm=arm,
                             mean_loss=statistics['mean_loss'], depth_counts=execution['depth_counts'])
            source_rows, records = run_sources(base, targets, seed, sources, namespace, save)
            source_summary.extend(source_rows)
            for record in records:
                source_log.write(json.dumps(record) + '\n')
            progress('source_study_complete', seed=seed)
        write(output / 'native-execution.json', native.close())
    results = feedback_report(retained, summary, preferences, source_summary, costs, protocol, smoke)
    write(output / 'results.json', results)
    write(output / 'feedback-summaries.json', summary)
    write(output / 'source-summaries.json', source_summary)
    write(output / 'preference-results.json', preferences)
    write(output / 'oracle-audits.json', audits)
    exact_u, exact_z = gaussian_entropic_bsde(0., 0., sigma=.7, gamma=2.)
    bsde = {'scope': 'analytic Gaussian entropic BSDE only; not neural learned/general FBSDE',
            'exact_U0': exact_u, 'exact_Z': exact_z, 'mesh': []}
    for n in (8, 32, 128, 512):
        dt = 1 / n
        step = binomial_entropic_step(-.7 * np.sqrt(dt), .7 * np.sqrt(dt), dt, 2.)
        bsde['mesh'].append({'steps': n, 'U0': n * step.utility, 'Z': step.z,
                             'absolute_error': abs(n * step.utility - exact_u)})
    write(output / 'bsde-special-case.json', bsde)
    after = source_receipt(smoke)
    if after['source_sha256'] != source['source_sha256']:
        raise RuntimeError('source changed during execution')
    completion = {'completed': True, 'wall_seconds': time.perf_counter() - started,
                  'process_cpu_seconds': time.process_time() - started_cpu,
                  'source_unchanged': True, 'smoke': smoke, 'seeds': seeds,
                  'primary_pass': results['primary']['pass']}
    write(output / 'completion.json', completion)
    progress('complete', **completion)
    files = {str(p.relative_to(output)): {'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(output.rglob('*')) if p.is_file()}
    write(output / 'artifact-manifest.json', files)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-run', required=True, type=Path)
    parser.add_argument('--native-binary', required=True, type=Path)
    parser.add_argument('--smoke', action='store_true')
    arguments = parser.parse_args()
    try:
        execute(arguments.output, arguments.source_run, arguments.native_binary, arguments.smoke)
    except Exception as error:
        if arguments.output.exists() and not (arguments.output / 'failure.json').exists():
            write(arguments.output / 'failure.json', {'type': type(error).__name__, 'error': str(error)})
        raise
