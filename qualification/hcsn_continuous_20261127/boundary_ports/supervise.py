from pathlib import Path
import os,sys,subprocess,time,json
HERE=Path(__file__).resolve().parent
def main():
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    for seed in [419,1097]:
        for kind in ['boundary','priced','augmented','boundary_basis','gru','conv']:
            r=subprocess.run([sys.executable,str(HERE/'experiment.py'),'fit',kind,str(seed)],env=env)
            if r.returncode:raise SystemExit(r.returncode)
    for cmd in ['seal','score']:subprocess.run([sys.executable,str(HERE/'experiment.py'),cmd],env=env,check=True)
if __name__=='__main__':main()
