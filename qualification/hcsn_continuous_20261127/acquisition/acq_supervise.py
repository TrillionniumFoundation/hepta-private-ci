"""One-shot acquisition study. Run one worker at a time on this host; retained folds can resume."""
import os,sys,subprocess,pathlib,json,time
ROOT=pathlib.Path(__file__).resolve().parent
env={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONUNBUFFERED':'1'}
deps=ROOT/'cpu_deps';deps.mkdir(exist_ok=True)
env['PYTHONPATH']=str(deps)
possible=[str(pathlib.Path.home()/'.venvs/rocm10/bin/python'),'/usr/bin/python3','/usr/local/bin/python']
def module_test(py,code):
    result=subprocess.run([py,'-c',code],capture_output=True,text=True,env=env)
    return result.returncode==0,result.stdout.strip()
def select_py():
    test="import numpy,scipy,sklearn;from sklearn.ensemble import HistGradientBoostingRegressor;print(numpy.__version__,scipy.__version__,sklearn.__version__)"
    for p in possible:
        if os.path.isfile(p):
            ok,version=module_test(p,test)
            if ok:print(p,version,flush=True);return p
    for k,p in enumerate(possible):
        if not os.path.isfile(p):continue
        target=ROOT/('cpu-deps-'+str(k));target.mkdir(exist_ok=True)
        ok,_=module_test(p,"import pip")
        if not ok:continue
        proc=subprocess.run([p,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--target',str(target),'scikit-learn==1.8.0'],env=env)
        if proc.returncode==0:
            env['PYTHONPATH']=str(target)
            ok,ver=module_test(p,test)
            if ok:print(p,ver,flush=True);return p
    raise RuntimeError('compatible private scientific environment unavailable')
def run():
    py=select_py()
    started=time.time()
    subprocess.run([py,str(ROOT/'acq_prepare.py')],check=True,env=env,cwd=ROOT)
    for ds in ['daphnet','mhealth']:
        for subject in range(1,11):
            fold=ROOT/'acq_inputs'/ds/'results'/('p%02d'%subject)
            if fold.with_suffix('.json').exists() and fold.with_suffix('.npz').exists():continue
            subprocess.run([py,str(ROOT/'acq_study.py'),ds,str(subject)],check=True,env=env,cwd=ROOT)
    subprocess.run([py,str(ROOT/'acq_score.py')],check=True,env=env,cwd=ROOT)
    print('downstream wall',time.time()-started,flush=True)
if __name__=='__main__':run()
