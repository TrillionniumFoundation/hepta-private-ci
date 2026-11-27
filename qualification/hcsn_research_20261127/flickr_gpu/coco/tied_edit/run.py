"""Run the one-time tied-weight experiment in isolated CPU processes and summarize it."""
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import os
import resource
import subprocess
import sys
import time

ROOT = Path(os.environ.get('HEPTA_FLICKR_ROOT', Path(__file__).resolve().parents[2]))
SRC = Path(__file__).resolve().parent
BASE = ROOT/'tied_edit'
RESULT = BASE/'results'
ARMS = ('hcsn', 'dense')
ORIGINS = ('random','flickr20')
SEEDS = (17011,24203,39827)
METHODS = ('fixed','untied_edit16','tied_edit16','tied_gradient','full_gradient')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write(p, x):
    t=p.with_name(p.name+'.part')
    t.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False))
    t.replace(p)


def execute(args):
    start=time.monotonic()
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONUNBUFFERED='1')
    with (BASE/'worker.log').open('a') as log:
        q=subprocess.run([sys.executable,*args],cwd=SRC,env=env,stdout=log,stderr=subprocess.STDOUT)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    with (BASE/'costs.jsonl').open('a') as f:
        f.write(json.dumps(dict(args=[str(a) for a in args], exit=q.returncode, wall=time.monotonic()-start,
            cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            completed=datetime.datetime.now(datetime.timezone.utc).isoformat()))+'\n')
    if q.returncode:raise RuntimeError((args,q.returncode))


def summarize():
    import numpy as np
    out={}
    ids=None
    counts=None
    rng=np.random.default_rng(745033)
    draws=None
    for arm in ARMS:
        for origin in ORIGINS:
            key=f'{arm}-{origin}'
            obs={}
            records={}
            for method in METHODS:
                paired=[];shifted=[];rows=[]
                for seed in SEEDS:
                    path=RESULT/f'{arm}-{seed}-{origin}'
                    selected=json.loads((path/'fit.json').read_text())
                    test=json.loads((path/method/'test.json').read_text())
                    assert selected['selected'][method]['sha256']==test['selected']
                    assert sha(path/method/'scores.npz')==test['scores_sha256']
                    with np.load(path/method/'scores.npz') as z:
                        if ids is None:
                            ids=z['ids'];counts=z['tokens']
                            draws=rng.integers(len(ids),size=(4000,len(ids)))
                        assert np.array_equal(z['ids'],ids) and np.array_equal(z['tokens'],counts)
                        paired.append(z['paired']);shifted.append(z['shifted'])
                    selection=selected['selected'][method]
                    candidates=selected['candidates'][method]
                    cpu=sum(q['development']['cpu']+q['update']['cpu'] for q in candidates)
                    wall=sum(q['development']['wall']+q['update']['wall'] for q in candidates)
                    if method.endswith('edit16'):
                        ext=selected['closed_form']
                        cpu+=ext['extraction']['cpu']+ext['solve']['cpu']
                        wall+=ext['extraction']['wall']+ext['solve']['wall']
                    rows.append(dict(seed=seed,dev_nll=selection['dev_nll'],tuning=selection['tuning'],
                        nll=test['nll'],shift_penalty=test['shifted_penalty'],standalone_recorded_wall=wall,
                        standalone_recorded_cpu=cpu,cold_test_wall=test['process_elapsed_wall'],cold_test_cpu=test['process_cpu']))
                obs[method]=(np.mean(paired,axis=0),np.mean(shifted,axis=0))
                records[method]=dict(seeds=rows,mean_nll=float(obs[method][0].sum()/counts.sum()),
                    mean_shift_penalty=float((obs[method][1]-obs[method][0]).sum()/counts.sum()),
                    standalone_recorded_wall=float(np.mean([q['standalone_recorded_wall'] for q in rows])),
                    standalone_recorded_cpu=float(np.mean([q['standalone_recorded_cpu'] for q in rows])))
            cmp={}
            for method in METHODS:
                diff=obs['tied_edit16'][0]-obs[method][0]
                v=diff[draws].sum(1)/counts[draws].sum(1)
                cmp[method]=dict(nll_difference=float(diff.sum()/counts.sum()),interval95=np.quantile(v,[.025,.975]).tolist())
            out[key]=dict(treatments=records,tied_closed_minus_comparator=cmp)
    write(BASE/'summary.json',dict(panels=out,images=len(ids),tokens=int(counts.sum()),
        data=json.loads((BASE/'data/manifest.json').read_text()),seal_sha256=sha(RESULT/'seal.json'),
        cost_definition='Standalone update plus all validation candidate costs, with extraction and solve charged in full to each closed-form treatment. Excludes shared setup, independent cold tests and file I/O not inside these timers. See whole-process cost ledger.',
        uncertainty='4000 paired photo-cluster resamples of mean three-seed token loss sums; fixed gallery, seeds and protocol, unadjusted across comparisons.'))


def main():
    BASE.mkdir(exist_ok=True)
    lock=(BASE/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (BASE/'summary.json').exists():return
    RESULT.mkdir(exist_ok=True)
    deadline=time.monotonic()+32000
    required=[ROOT/'coco_restored/verification.json',ROOT/'caption_external20/seal.json',ROOT/'coco_timed/results/summary.json']
    while not all(p.is_file() for p in required):
        if time.monotonic()>deadline:raise RuntimeError('No preceding single-CPU study completed before the resource reservation elapsed')
        time.sleep(20)
    if not (BASE/'data/manifest.json').exists():execute([str(SRC/'prepare.py')])
    blocks=[(a,s,o) for s in SEEDS for o in ORIGINS for a in (ARMS if s!=SEEDS[1] else ARMS[::-1])]
    for a,s,o in blocks:
        if not (RESULT/f'{a}-{s}-{o}'/'fit.json').exists():
            execute([str(SRC/'study.py'),'fit',a,str(s),o])
    states={}
    for a,s,o in blocks:
        path=RESULT/f'{a}-{s}-{o}'
        j=json.loads((path/'fit.json').read_text())
        for m in METHODS:
            h=sha(path/m/'selected.pt')
            assert h==j['selected'][m]['sha256']
            states[f'{path.name}/{m}']=h
    assert len(states)==60
    seal={'states':states,'source':sha(SRC/'study.py'),'data':sha(BASE/'data/manifest.json'),'protocol':sha(SRC/'PROTOCOL.md')}
    if (RESULT/'seal.json').exists():assert json.loads((RESULT/'seal.json').read_text())==seal
    else:write(RESULT/'seal.json',seal)
    for a,s,o in blocks:
        for m in METHODS:
            if not (RESULT/f'{a}-{s}-{o}'/m/'test.json').exists():
                execute([str(SRC/'study.py'),'test',a,str(s),o,m])
    summarize()
    print('completed all sixty independently scored selected states',flush=True)


if __name__=='__main__':
    main()
