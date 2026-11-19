"""Reproducible three-layer continuous latent/NDU experiment entry point."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import subprocess
import sys
import time

import numpy as np
import torch

from codec import semantic_metrics
from data import make_worlds, render
from evaluate import baseline_specs, choose_baseline, core_specs, evaluate, spec
from train import load_checkpoint, train_seed


ROOT = Path(__file__).resolve().parent
SCENARIOS = {'iid': 'iid', 'missing': 'ood_missing', 'correlated_shift': 'ood_correlated'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = list(ROOT.glob('*.py')) + list((ROOT / 'oracle').glob('*.py')) + list((ROOT / 'review').glob('*.py'))
    paths += [ROOT / 'protocol.json']
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def numerical_audits(output):
    # Local runtime may reuse an existing CPU Torch environment plus a read-only
    # SciPy installation. Cloud uses its strictly pinned single environment.
    try:
        import scipy
    except ImportError:
        extra = os.environ.get('NDU_SCIPY_SITE_PACKAGES')
        if not extra:
            raise
        sys.path.append(extra)
        import scipy
    receipt = {'scipy': scipy.__version__, 'scipy_path': scipy.__file__}
    scripts = [('oracle/benchmark.py', 'oracle.json'),
               ('oracle/local_control_audit.py', 'local_control_audit.json'),
               ('review/codec_audit.py', 'codec_audit.json')]
    for script, target in scripts:
        saved_args = sys.argv[:]
        saved_path = sys.path[:]
        saved_threads = torch.get_num_threads()
        sys.path.insert(0, str((ROOT / script).parent))
        sys.argv = [str(ROOT / script), '--output', str(output / target)]
        try:
            runpy.run_path(str(ROOT / script), run_name='__main__')
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(f'{script} failed with exit {exc.code}') from exc
        finally:
            sys.argv = saved_args
            sys.path[:] = saved_path
            torch.set_num_threads(saved_threads)
    write(output / 'audit-runtime.json', receipt)


def prepare(output, config):
    numerical_audits(output)
    for seed in config['seeds']:
        destination = output / 'seeds' / str(seed)
        destination.mkdir(parents=True, exist_ok=False)
        print(f'seed={seed} stage=training started={now()}', flush=True)
        worlds = make_worlds(config['train_worlds'], config['split_seed_offsets']['train'] + seed)
        decoder, models, training = train_seed(worlds, seed, config, destination)
        write(destination / 'training.json', training)
        validation = make_worlds(config['validation_worlds'], config['split_seed_offsets']['validation'] + seed)
        # True-latent capability admits the shared codec; never a controller.
        with torch.no_grad():
            decoded = decoder(torch.cat((validation['facts'], validation['style']), -1))
            ceiling = semantic_metrics(decoded, validation['facts'])
        ceiling_report = {k: float(v.float().mean()) for k, v in ceiling.items()
                          if not k.startswith('raw_facts') and k != 'modality_loss'}
        capability = {key: ceiling_report[key] >= minimum
                      for key, minimum in config['codec_capability_minima'].items()}
        ceiling_report['capability_gates'] = capability
        write(destination / 'codec_ceiling.json', ceiling_report)
        if not config['development_only'] and not all(capability.values()):
            raise RuntimeError(f'Shared codec capability failed for seed {seed}; preserve attempt, no heldout')
        primary = spec('ndu_trained', 'ndu', config['primary_steps'])
        reference, reference_arrays = evaluate(decoder, models, validation, primary, config,
                                               6100000 + seed, timing_repeats=3)
        np.savez_compressed(destination / 'validation__primary.npz', **reference_arrays)
        candidates = []
        for choice in baseline_specs(config):
            report, arrays = evaluate(decoder, models, validation, choice, config,
                                      6100000 + seed, timing_repeats=3)
            candidates.append(report)
            np.savez_compressed(destination / f'validation__{choice["name"]}.npz', **arrays)
        selection = choose_baseline(candidates, reference, config)
        selection.update({'selected_at': now(), 'heldout_generated': False,
                          'validation_facts_sha256': digest(destination / 'validation__primary.npz')})
        write(destination / 'validation.json', {'primary': reference, 'candidates': candidates})
        write(destination / 'selection.json', selection)
        print(f'seed={seed} stage=validation selected={selection["choice"]["name"]} fairness={selection["fairness_gate"]}', flush=True)
    if not config['development_only']:
        if json.loads((output / 'source-freeze.json').read_text())['files'] != sources():
            raise RuntimeError('Source changed during preparation')
    selection_hashes = {str(seed): {name: digest(output / 'seeds' / str(seed) / name)
                                   for name in ('selection.json', 'checkpoint.pt', 'training.json', 'validation.json')}
                        for seed in config['seeds']}
    write(output / 'selection-lock.json', {'frozen_at': now(), 'seeds': selection_hashes,
                                          'source_manifest': sources(), 'heldout_generated': False})


def heldout(output, config):
    lock = json.loads((output / 'selection-lock.json').read_text())
    if lock['source_manifest'] != sources():
        raise RuntimeError('Source changed after validation selection; preserve run and register amendment')
    if not config['development_only'] and json.loads((output / 'source-freeze.json').read_text())['files'] != sources():
        raise RuntimeError('Heldout source differs from published freeze')
    for seed in config['seeds']:
        for name, sha in lock['seeds'][str(seed)].items():
            if digest(output / 'seeds' / str(seed) / name) != sha:
                raise RuntimeError('Prepared checkpoint or selection evidence changed after lock')
    write(output / 'heldout-start.json', {'started_at': now(), 'selection_lock_sha256': digest(output / 'selection-lock.json')})
    for seed in config['seeds']:
        destination = output / 'seeds' / str(seed)
        decoder, models = load_checkpoint(destination / 'checkpoint.pt')
        selection = json.loads((destination / 'selection.json').read_text())
        choices = core_specs(config) + [selection['choice']]
        choices += [spec(v, a, count) for count in config['secondary_steps']
                    for v, a in [('flow_trained', 'flow'), ('ndu_trained', 'ndu'),
                                 ('free_trained', 'free_joint')]]
        choices = list({choice['name']: choice for choice in choices}.values())
        reports = []
        for index, (scenario, count) in enumerate(config['heldout_worlds'].items()):
            world_seed = config['split_seed_offsets']['test'] + 10000 * index + seed
            worlds = make_worlds(count, world_seed, SCENARIOS[scenario])
            # Facts are retained exclusively for scorer/replay, outside inference.
            np.savez_compressed(destination / f'{scenario}__worlds.npz',
                                facts=worlds['facts'].numpy(), style=worlds['style'].numpy())
            for choice in choices:
                report, arrays = evaluate(decoder, models, worlds, choice, config, 7100000 + 10000 * index + seed)
                report.update({'scenario': scenario, 'world_seed': world_seed})
                reports.append(report)
                np.savez_compressed(destination / f'{scenario}__{choice["name"]}.npz', **arrays)
            write(destination / 'evaluation.json', reports)
            print(f'seed={seed} stage=heldout scenario={scenario} worlds={count} arms={len(choices)}', flush=True)
    from analysis import analyze_run
    result = analyze_run(output, config)
    write(output / 'summary.json', result)
    print(json.dumps({'scientific_success': result.get('scientific_success'), 'summary': str(output / 'summary.json')}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execution-tier', choices=['local-preflight', 'dedicated-cloud'], default='local-preflight')
    parser.add_argument('--stage', choices=['all', 'prepare', 'evaluate'], default='all')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args()
    if args.smoke and args.development:
        parser.error('Use only one development mode')
    dedicated = args.execution_tier == 'dedicated-cloud'
    if dedicated:
        expected = {'HEPTA_DEDICATED_RUNNER_VERIFIED': '1', 'GITHUB_ACTIONS': 'true',
                    'GITHUB_REPOSITORY': 'TrillionniumFoundation/hepta-private-ci',
                    'GITHUB_REF': 'refs/heads/research/ndu-latent-riccati-20261021',
                    'RUNNER_NAME': 'desktop', 'RUNNER_ENVIRONMENT': 'self-hosted',
                    'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}
        if any(os.environ.get(k) != v for k, v in expected.items()):
            raise RuntimeError('Dedicated cloud identity requires matching verified launcher fields')
        actual_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if actual_sha != os.environ.get('HEPTA_EXPERIMENT_EXPECTED_SHA'):
            raise RuntimeError('Dedicated source SHA differs from the assigned workflow')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    config = json.loads((ROOT / 'protocol.json').read_text())
    config['development_only'] = bool(args.smoke or args.development)
    if config['development_only']:
        config['seeds'] = [config['development_seed']]
        config['heldout_worlds'] = {'iid': 64, 'missing': 32, 'correlated_shift': 32}
    if args.smoke:
        config.update({'train_worlds': 256, 'validation_worlds': 16, 'decoder_updates': 20,
                       'foundation_updates': 20, 'continued_updates': 4,
                       'baseline_candidate_steps': [8], 'guidance_strengths': [2.0],
                       'secondary_steps': [], 'batch_size': 16})
        config['heldout_worlds'] = {'iid': 16, 'missing': 8, 'correlated_shift': 8}
        config['free_controller_compute_match']['maximum_updates'] = 40
        config['primary']['paired_hierarchical_bootstrap_replicates'] = 50
    output = args.output.resolve()
    if args.stage != 'evaluate':
        output.mkdir(parents=True, exist_ok=False)
        if not config['development_only']:
            freeze = json.loads((ROOT / 'SOURCE_FREEZE.json').read_text())
            if freeze['files'] != sources():
                raise RuntimeError('Implementation does not match published source freeze')
            write(output / 'source-freeze.json', freeze)
        write(output / 'protocol.json', config)
    else:
        stored = json.loads((output / 'protocol.json').read_text())
        if stored != config:
            raise RuntimeError('Evaluation protocol differs from prepared protocol')
        if (output / 'heldout-start.json').exists():
            raise RuntimeError('Heldout attempt already exists; it must not be overwritten')
        prepared_runtime = json.loads((output / 'runtime-prepare.json').read_text())
        if prepared_runtime['execution_tier'] != args.execution_tier:
            raise RuntimeError('Prepared and evaluated execution tiers differ')
    runtime = {'started_at': now(), 'execution_tier': args.execution_tier,
               'dedicated_runner_verified': dedicated,
               'python': sys.version, 'python_executable': sys.executable, 'torch': torch.__version__,
               'numpy': np.__version__, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
               'torch_threads': torch.get_num_threads(), 'argv': sys.argv, 'development_only': config['development_only'],
               'source_manifest': sources(), 'github_run_id': os.environ.get('GITHUB_RUN_ID'),
               'source_commit_asserted_by_launcher': os.environ.get('HEPTA_EXPERIMENT_EXPECTED_SHA')}
    write(output / f'runtime-{args.stage}.json', runtime)
    started = time.perf_counter()
    if args.stage in ('all', 'prepare'):
        prepare(output, config)
    if args.stage in ('all', 'evaluate'):
        heldout(output, config)
    write(output / f'completion-{args.stage}.json', {'finished_at': now(), 'seconds': time.perf_counter() - started,
                                                  'process_success': True, 'scientific_success_separate': True})
    manifest = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    write(output / 'manifest.json', manifest)


if __name__ == '__main__':
    main()
