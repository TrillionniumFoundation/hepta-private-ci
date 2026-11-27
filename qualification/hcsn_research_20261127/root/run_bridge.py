"""Seal all development choices before any confirmation worker starts."""
from pathlib import Path
import argparse, concurrent.futures, hashlib, json, os, subprocess, sys, time
ROOT=Path(__file__).resolve().parent
ARMS=('physical','smooth','gru','lif','attention','linear','identity','procrustes')
SEEDS=(27,117,207)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def worker(task):
    mode,arm,seed,out=task
    name=f'{arm}-{seed}'
    loc=out/name
    loc.mkdir(exist_ok=True)
    marker=loc/('fit.json' if mode=='fit' else 'test.json')
    if marker.exists():
        data=json.loads(marker.read_bytes())
        if mode=='fit' and data['state_sha256']!=sha(loc/'selected.pt'):
            raise ValueError(name+' checkpoint mismatch')
        if mode=='test' and data['ranks_sha256']!=sha(loc/'ranks.npz'):
            raise ValueError(name+' rank mismatch')
        return
    with (loc/f'{mode}.log').open('a') as log:
        sub=subprocess.run([sys.executable,'-u',str(ROOT/'bridge.py'),mode,arm,str(seed),'--out',str(out)],cwd=ROOT,stderr=subprocess.STDOUT,stdout=log)
    if sub.returncode or not marker.is_file():
        raise RuntimeError(f'{name}/{mode}: {sub.returncode}, see {log.name}')
    print(mode,name,flush=True)
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--out',type=Path,default=ROOT/'retrieval')
    args=p.parse_args()
    out=args.out.resolve()
    out.mkdir(exist_ok=True,parents=True)
    slots=[(a,s) for a in ARMS for s in ((27,) if a in ('identity','procrustes') else SEEDS)]
    slots.sort(key=lambda x:hashlib.sha256(str(x).encode()).hexdigest())
    for mode in ['fit','test']:
        if mode=='test':
            seal={'states':{f'{a}-{s}':sha(out/f'{a}-{s}'/'selected.pt') for a,s in slots},
                  'sources':{f:sha(ROOT/f) for f in ('bridge.py','BRIDGE_PROTOCOL.md','PROTOCOL.md','encode.py','run_bridge.py')}}
            if (out/'seal.json').is_file():
                if json.loads((out/'seal.json').read_bytes())!=seal:
                    raise ValueError('seal changed')
            else:
                (out/'seal.json').write_text(json.dumps(seal,indent=1))
        with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
            futures=[ex.submit(worker,(mode,a,s,out)) for a,s in slots]
            failures=[]
            for f in concurrent.futures.as_completed(futures):
                try: f.result()
                except Exception as e: failures.append(str(e))
            if failures:
                raise RuntimeError(str(failures))
    subprocess.run([sys.executable,str(ROOT/'summarize_bridge.py'),'--out',str(out)],check=True)
if __name__=='__main__':
    main()
