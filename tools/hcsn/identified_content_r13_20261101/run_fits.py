"""Independent full-process fits; confirmation freeze is a separate audited step."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from launch import ROOT, run_child

PROTOCOL = json.loads((ROOT/'PROTOCOL.json').read_text())


def run_one(job):
    seed, core, seconds, output = job
    path = output/'fits'/f'{seed}_{core}.json'
    receipt = run_child([ROOT/'training.py', '--seed', seed, '--core', core,
                         '--seconds', seconds, '--output', path],
                        output/'logs'/f'{seed}_{core}.txt',
                        output/'receipts'/f'{seed}_{core}.json')
    fit = json.loads(path.read_text())
    print(json.dumps({'seed': seed, 'core': core, 'updates': fit['updates'],
        'selected': fit['selected_update'], 'validation': fit['selected_validation'],
        'whole_process_cpu_seconds': receipt['whole_process_cpu_seconds']}), flush=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'evidence')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args()
    seeds = [PROTOCOL['development_seed']] if args.development else PROTOCOL['seeds']
    seconds = 3.0 if args.development else PROTOCOL['fit_cpu_seconds_per_core']
    jobs = [(s, c, seconds, args.output) for s in seeds for c in PROTOCOL['cores']]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_one, jobs))
