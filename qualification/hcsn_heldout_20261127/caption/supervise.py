"""Bound allocator lifetime to one matched cell and resume the registered panel."""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cell',nargs=3);p.add_argument('--device',default='cpu')
    p.add_argument('--threads',type=int,default=1)
    a=p.parse_args();root=a.out.resolve();data=a.data.resolve();src=Path(__file__).resolve().parent
    if a.cell:
        import hashlib
        import numpy as np
        import panel
        arm,seed,budget=a.cell
        device=panel.runtime(a)
        manifest=json.loads((data/'manifest.json').read_text())
        env=json.loads((root/'environment.json').read_text())
        assert env['dataset']==panel.sha(data/'manifest.json') and env['device']==str(device)
        assert all(panel.sha(src/f)==s for f,s in env['source'].items())
        train=panel.Samples(data,'train',manifest);valid=panel.Samples(data,'validation',manifest)
        ids=np.asarray(sorted(range(len(valid.pix)),key=lambda i: hashlib.sha256(b'flickr-caption-prereg-128'+bytes(valid.ids[i])).digest())[:128])
        panel.run_cell(arm,int(seed),int(budget),root,manifest,train,valid,ids,device)
        return
    # Match the order from panel.py. Only cell boundaries and failure accounting change.
    import ast
    module=ast.parse((src/'panel.py').read_text());network=ast.parse((src/'model.py').read_text())
    def constant(tree,key):
        return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(k,ast.Name) and k.id==key for k in n.targets))
    budgets=constant(module,'BUDGET');seeds=constant(module,'SEEDS');arms=constant(network,'ARMS')
    env=dict(os.environ,MALLOC_ARENA_MAX='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    common=['--data',str(data),'--out',str(root),'--device',a.device,'--threads',str(a.threads)]
    log=root/'controller.jsonl'
    for budget in budgets:
        for i,seed in enumerate(seeds):
            for arm in arms[i:]+arms[:i]:
                config=root/f'{arm}-{seed}'/'fit.json'
                if config.is_file() and json.loads(config.read_text())['exposure_s']>=budget:continue
                for attempt in range(3):
                    start=time.monotonic()
                    result=subprocess.run([sys.executable,str(src/'supervise.py'),*common,'--cell',arm,str(seed),str(budget)],env=env)
                    row={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'arm':arm,'seed':seed,'nominal_s':budget,'attempt':attempt+1,'child_exit':result.returncode,'whole_child_seconds':time.monotonic()-start}
                    with log.open('a') as f:f.write(json.dumps(row)+'\n')
                    if result.returncode==0:break
                else:raise RuntimeError(f'cell requires review {arm} {seed} {budget}')
    # panel.fit verifies the same 15 cells, then seals and evaluates them in independent cold processes.
    subprocess.run([sys.executable,str(src/'panel.py'),'fit',*common],check=True,env=env)

if __name__=='__main__':main()
