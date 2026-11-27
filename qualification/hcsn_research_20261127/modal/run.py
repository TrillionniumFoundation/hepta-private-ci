"""Launch frozen fits, globally seal all states, then evaluate from cold starts."""
import argparse
import concurrent.futures
import hashlib
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARMS = ('qvi_joint', 'qvi_boundary', 'smooth', 'gru', 'lif', 'attention', 'ridge')
SLOTS = list(itertools.product(['A','B'], ARMS, [1729,2718]))


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--workers', type=int, default=2)
    a = p.parse_args()
    a.out.mkdir(exist_ok=True, parents=True)
    a.data, a.out = a.data.resolve(), a.out.resolve()
    all_source = {name:digest(ROOT / name) for name in ('PROTOCOL.md','RUNTIME_AMENDMENT.md','experiment.py','prepare.py','run.py')}
    inputs = list(SLOTS)
    inputs.sort(key=lambda k: hashlib.sha256(str(k).encode()).digest())
    def job(slot, mode):
        fold, arm, seed = slot
        out = a.out / f'{fold}-{arm}-{seed}'
        key = mode + '_cold.json'
        if (out/key).exists():
            return
        begin = time.perf_counter()
        cmd = [sys.executable,str(ROOT/'experiment.py'),mode,'--data',str(a.data),'--output',str(out),
               '--fold',fold,'--arm',arm,'--seed',str(seed)]
        log = a.out / f'{out.name}.{mode}.log'
        with log.open('w') as sink:
            result = subprocess.run(cmd,stdout=sink,stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - begin
        if result.returncode:
            print(f'{mode}: {out.name} ERROR {result.returncode} ({log})',flush=True)
            raise RuntimeError(out.name)
        with (out/key).open('x') as f:
            json.dump({'wall':elapsed,'returncode':result.returncode,'workers':a.workers},f)
        print(f'{mode}: {out.name} {elapsed:.2f}s',flush=True)
    with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:
        list(pool.map(lambda s:job(s,'train'), inputs))
    seal = {'source':all_source,'states':{f'{fold}-{arm}-{seed}':digest(a.out/f'{fold}-{arm}-{seed}'/'states.pt')
                for fold,arm,seed in inputs}}
    if (a.out/'seal.json').exists():
        assert json.loads((a.out/'seal.json').read_text())==seal
    else:
        with (a.out/'seal.json').open('x') as f: json.dump(seal,f,indent=2)
    with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:
        list(pool.map(lambda s:job(s,'evaluate'), inputs))


if __name__ == '__main__':
    main()
