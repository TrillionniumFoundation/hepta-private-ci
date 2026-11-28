from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os,sys,subprocess
root=Path(__file__).resolve().parents[1]
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
def jobs(slot):
    for j,seed in enumerate((137,311,557)):
        k=('hxcurve','bilinear','smoothwall')[(slot+j)%3]
        logfile=root/'curved'/'results'/f'{k}-{seed}.log'
        with logfile.open('x') as out:
            subprocess.run(['taskset','-c',str(1+slot),sys.executable,'curved/run.py','.',k,str(seed)],cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
with ThreadPoolExecutor(3) as pool:list(pool.map(jobs,range(3)))
