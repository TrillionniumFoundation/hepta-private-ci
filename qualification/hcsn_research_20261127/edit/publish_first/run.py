"""Run all independent fits, seal every selected model, then cold-evaluate."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

P=Path(__file__).resolve().parent
METHODS=('keep','direct','wronglabel','unconditional','bp')
SEEDS=(107,211,431)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--parents',type=Path,required=True);ap.add_argument('--jobs',type=int,default=2)
    args=ap.parse_args();args.output.mkdir(exist_ok=True,parents=True)
    log=args.output/'logs';log.mkdir(exist_ok=True)
    items=[(s,m) for s in SEEDS for m in METHODS]
    def run(spec):
        mode,s,m=spec;folder=args.output/str(s)/m
        if (folder/('fit.json' if mode=='fit' else 'test.json')).is_file():
            return f'reuse {mode} {s} {m}'
        cmd=[sys.executable,str(P/'experiment.py'),mode,'--seed',str(s),'--method',m,'--input',str(args.input),'--output',str(args.output),'--parents',str(args.parents)]
        with (log/f'{mode}-{s}-{m}.txt').open('w') as f:
            stamp=time.perf_counter();finished=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
            if finished.returncode:raise RuntimeError(f'{s}/{m} failed at {mode} rc {finished.returncode}')
            (log/f'{mode}-{s}-{m}.json').write_text(json.dumps({'cold_process_wall_s':time.perf_counter()-stamp,'exit':finished.returncode})+'\n')
        return f'{mode} {s} {m} done'
    if (args.output/'seal.json').is_file():
        seal=json.loads((args.output/'seal.json').read_text())
    else:
        with ThreadPoolExecutor(args.jobs) as pool:
            for msg in pool.map(run,[('fit',s,m) for s,m in items]):print(msg,flush=True)
        seal={'models':{str(s)+'/'+m:sha(args.output/str(s)/m/'selected.pt') for s,m in items},
              'fit_records':{str(s)+'/'+m:sha(args.output/str(s)/m/'fit.json') for s,m in items},
              'source':sha(P/'experiment.py'),'protocol':sha(P/'PROTOCOL.md'),'dataset':sha(args.input/'dataset.json')}
        (args.output/'seal.json').write_text(json.dumps(seal,indent=2,sort_keys=True)+'\n')
        print('sealed',sha(args.output/'seal.json'),flush=True)
    for s,m in items:assert seal['models'][str(s)+'/'+m]==sha(args.output/str(s)/m/'selected.pt')
    with ThreadPoolExecutor(args.jobs) as pool:
        for msg in pool.map(run,[('eval',s,m) for s,m in items]):print(msg,flush=True)


if __name__=='__main__':main()
