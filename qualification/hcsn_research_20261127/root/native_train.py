"""Run a pinned COCO bridge campaign on the machine that extracted its inputs."""
import argparse, concurrent.futures, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
RAW='https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/'
UP='8b538954e3db0763b9eb24b6159d17b80f286f26'
FOLDER='qualification/hcsn_research_20261127/root/'
def fetch(item):
    url,path,hash_expected=item
    path.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(4):
        try:
            req=Request(url,headers={'User-Agent':'Hepta vision language qualification'})
            with urlopen(req,timeout=90) as f: data=f.read()
            if hash_expected and hashlib.sha256(data).hexdigest()!=hash_expected:
                raise ValueError(path.name+' digest')
            path.write_bytes(data)
            return
        except Exception:
            if attempt==3:raise
            time.sleep(attempt+1)
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--ref',required=True)
    p.add_argument('--workers',type=int,default=3)
    args=p.parse_args()
    root=args.root.resolve()
    src=root/'physics'
    with concurrent.futures.ThreadPoolExecutor(5) as pool:
        list(pool.map(fetch,[(RAW+args.ref+'/'+FOLDER+f,root/f,None) for f in ('PROTOCOL.md','BRIDGE_PROTOCOL.md','bridge.py','run_bridge.py','summarize_bridge.py','bridge_upstream.json')]))
        manifest=json.loads((root/'bridge_upstream.json').read_bytes())
        list(pool.map(fetch,[(RAW+UP+'/'+f,src/f,d) for f,d in manifest.items()]))
    # Top-level definitions read only. Train/test use their fixed inputs and local output directory.
    env={**os.environ,'PYTHONPATH':str(src),'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    subprocess.run([sys.executable,'-c','import torch,numpy;from bridge import Bridge; x=torch.zeros(6,2,32); print("source check",torch.__version__,Bridge("physical").layers[0].core(x).shape,flush=True)'],cwd=root,check=True,env=env)
    print('physics sources verified; waiting for canonical local features',flush=True)
    while not all((root/'features'/f'{mod}-{sp}.json').is_file() for mod in ('vision','text') for sp in ('train','val','test')):
        time.sleep(20)
    subprocess.run([sys.executable,'-u','run_bridge.py','--workers',str(args.workers)],cwd=root,env=env,check=True)
if __name__=='__main__':main()
