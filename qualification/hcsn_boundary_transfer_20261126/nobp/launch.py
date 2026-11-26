"""Run each arm in its own CPU process. Seal every trained model before confirmation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
ARMS = ('hcsn_frozen', 'hcsn_bp', 'gru_frozen', 'gru_bp', 'flat')
SEEDS = (107, 211, 431)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh(path, data):
    with path.open('x') as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')


def run(arg, job):
    arm, seed = job
    key = f'{arm}-{seed}'
    receipt = arg.out/(f'{arg.phase}-{key}-process.json')
    if receipt.is_file():
        prior = json.loads(receipt.read_text())
        if prior['exit'] == 0:
            return
        raise RuntimeError(f'Previous failure for {key}. Use new output path.')
    start = time.perf_counter()
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', OMP_NUM_THREADS='1')
    completed = subprocess.run([sys.executable, str(ROOT/'study.py'), arg.phase, arm, str(seed),
                                str(arg.data), str(arg.out)], env=env, text=True, capture_output=True)
    seconds = time.perf_counter()-start
    fresh(receipt, dict(arm=arm, seed=seed, phase=arg.phase, wall_seconds=seconds,
                        exit=completed.returncode, stdout=completed.stdout, stderr=completed.stderr))
    print(arg.phase, key, round(seconds, 3), 'status', completed.returncode, flush=True)
    if completed.returncode:
        raise RuntimeError(f'{key} {completed.stderr}')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('phase', choices=('train','test'));p.add_argument('data', type=Path);p.add_argument('out', type=Path)
    p.add_argument('--workers', type=int, default=3)
    args=p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs=[(arm, seed) for i, seed in enumerate(SEEDS) for arm in (ARMS[i:]+ARMS[:i])]
    source = json.loads((ROOT/'SOURCE.json').read_text())
    import importlib.util
    model_root = Path(importlib.util.find_spec('qualification.hcsn_smallnet_20261124.model').origin).parents[2]
    assert all(sha(model_root/key)==value for key,value in source['encoder_modules'].items())
    if args.phase=='test' and not (args.out/'seal.json').exists():
        raise FileNotFoundError('Unsealed training')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda job:run(args,job),jobs))
    if args.phase=='train':
        roster={}
        for arm,seed in jobs:
            key=f'{arm}-{seed}';folder=args.out/key
            fit=json.loads((folder/'fit.json').read_text())
            assert fit['program']==sha(ROOT/'study.py') and fit['protocol']==sha(ROOT/'PROTOCOL.md')
            assert fit['selected_file']==sha(folder/'selected.pt') and fit['initial_file']==sha(folder/'initial.pt')
            roster[key]=dict(weights=fit['selected_file'], initialization=fit['initial_file'], fit=sha(folder/'fit.json'))
        for seed in SEEDS:
            for model in ('hcsn','gru'):
                pair=[json.loads((args.out/f'{model}_{variant}-{seed}'/'fit.json').read_text()) for variant in ('bp','frozen')]
                assert pair[0]['initial_state']==pair[1]['initial_state']==pair[1]['final_state']
                assert pair[0]['final_state']!=pair[0]['initial_state']
        fresh(args.out/'seal.json', dict(roster=roster, program=sha(ROOT/'study.py'), protocol=sha(ROOT/'PROTOCOL.md'),
                                         launcher=sha(Path(__file__)), source=sha(ROOT/'SOURCE.json')))
        print('seal',sha(args.out/'seal.json'),flush=True)


if __name__ == '__main__':
    main()
