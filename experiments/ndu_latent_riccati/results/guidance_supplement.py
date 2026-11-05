"""Post-primary guidance coverage using only original validation selection."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data import make_worlds
from evaluate import evaluate
from run_experiment import SCENARIOS, sources
from train import load_checkpoint


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run, output = args.run.resolve(), args.output.resolve()
    if output.is_relative_to(run):
        raise ValueError('Do not modify the original sealed run')
    if not (run / 'completion-all.json').exists():
        raise ValueError('This supplement follows the completed primary experiment')
    plan_path = Path(__file__).with_name('GUIDANCE_SUPPLEMENT_PROTOCOL.json')
    plan = json.loads(plan_path.read_text())
    config = json.loads((run / 'protocol.json').read_text())
    lock = json.loads((run / 'selection-lock.json').read_text())
    if sources() != lock['source_manifest']:
        raise ValueError('Critical source changed')
    if sha(run / 'summary.json') != plan['original_primary_summary_sha256']:
        raise ValueError('Original primary result changed')
    for selected in plan['per_seed']:
        folder = run / 'seeds' / str(selected['seed'])
        for name in ('checkpoint.pt', 'validation.json'):
            if sha(folder / name) != lock['seeds'][str(selected['seed'])][name]:
                raise ValueError('Original checkpoint or validation evidence changed')
        validation = json.loads((folder / 'validation.json').read_text())
        for item in selected['choices']:
            eligible = [row for row in validation['candidates']
                        if row['choice']['arm'] == 'guidance'
                        and row['choice']['variant'] == item['choice']['variant']
                        and row['cpu_seconds_per_world'] <= selected['validation_cpu_cap']]
            best = min(eligible, key=lambda row: (row['world_cvar90'], row['cpu_seconds_per_world']))
            if best['choice'] != item['choice']:
                raise ValueError('Supplement choice differs from frozen validation winner')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'protocol.json', plan)
    started = time.perf_counter()
    all_reports = []
    for selected in plan['per_seed']:
        seed = selected['seed']
        folder = output / str(seed)
        folder.mkdir()
        decoder, models = load_checkpoint(run / 'seeds' / str(seed) / 'checkpoint.pt')
        original = json.loads((run / 'seeds' / str(seed) / 'evaluation.json').read_text())
        for index, (scenario, count) in enumerate(config['heldout_worlds'].items()):
            world_seed = config['split_seed_offsets']['test'] + 10000 * index + seed
            worlds = make_worlds(count, world_seed, SCENARIOS[scenario])
            reference = next(row for row in original if row['scenario'] == scenario
                             and row['choice']['name'] == 'ndu_trained__ndu__n8')
            for item in selected['choices']:
                report, arrays = evaluate(decoder, models, worlds, item['choice'], config,
                                          7100000 + 10000 * index + seed)
                if any(report[key] != reference[key] for key in ('facts_sha256', 'noise_sha256')):
                    raise ValueError('Supplement pairing differs from original evidence')
                report.update({'seed': seed, 'scenario': scenario, 'world_seed': world_seed,
                               'original_ndu_cpu_ratio': report['cpu_seconds_per_world'] / reference['cpu_seconds_per_world'],
                               'inferential_status': 'post-primary descriptive coverage'})
                np.savez_compressed(folder / f'{scenario}__{item["choice"]["name"]}.npz', **arrays)
                all_reports.append(report)
        print(f'guidance supplement seed={seed} complete', flush=True)
    write(output / 'evaluation.json', all_reports)
    write(output / 'completion.json', {
        'finished_at': datetime.now(timezone.utc).isoformat(), 'seconds': time.perf_counter() - started,
        'process_success': True, 'primary_unchanged': sha(run / 'summary.json') == plan['original_primary_summary_sha256'],
        'critical_source_unchanged': sources() == lock['source_manifest'],
        'python': sys.version, 'torch': torch.__version__, 'numpy': np.__version__,
        'plan_sha256': sha(plan_path), 'script_sha256': sha(Path(__file__)),
        'execution_tier': 'local-preflight', 'dedicated_runner_verified': False,
    })
    write(output / 'manifest.json', {str(path.relative_to(output)): sha(path)
                                   for path in output.rglob('*') if path.is_file()})


if __name__ == '__main__':
    main()
