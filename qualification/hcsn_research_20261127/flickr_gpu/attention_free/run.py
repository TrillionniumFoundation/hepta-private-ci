"""Single-CPU serial runner and fixed-gallery analysis of attention-free token mixing."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

SRC=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('HEPTA_FLICKR_ROOT',SRC.parents[1]))
BASE=ROOT/'attention_free'
RESULT=BASE/'results'
ARMS=('hcsn','no_wire','smooth','lif','diagonal_ssm','attention_sdpa')
SEEDS=(17011,24203,39827)


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(p,obj):
    tmp=p.with_name(p.name+'.part');tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False));tmp.replace(p)


def sources():
    return {f:sha(SRC/f) for f in ('PROTOCOL.md','free_boundary_decoder.py','study.py','cohort.py','qualify.py','run.py')}


def process(args):
    tick=time.monotonic();r=resource.getrusage(resource.RUSAGE_CHILDREN)
    env=dict(os.environ,HEPTA_FLICKR_ROOT=str(ROOT),OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONUNBUFFERED='1')
    with (BASE/'worker.log').open('a') as log:
        z=subprocess.run([sys.executable,*args],env=env,cwd=SRC,stdout=log,stderr=subprocess.STDOUT)
    v=resource.getrusage(resource.RUSAGE_CHILDREN)
    with (BASE/'costs.jsonl').open('a') as f:
        f.write(json.dumps(dict(args=args,exit=z.returncode,whole_child_wall=time.monotonic()-tick,
            whole_child_cpu=v.ru_utime+v.ru_stime-r.ru_utime-r.ru_stime,finished=datetime.datetime.now(datetime.timezone.utc).isoformat()))+'\n')
    if z.returncode:raise RuntimeError(args)


def wait_for(p,seconds):
    deadline=time.monotonic()+seconds
    while not p.exists():
        if time.monotonic()>deadline:raise TimeoutError(p.name)
        time.sleep(25)


def first_below(history,target):
    before=0.
    for r in history:
        if not r['eligible']:continue
        if r['nll']<=target:return dict(first_observed=r['observed'],previous_observation=before,
            optimizer_steps=r['steps'],tokens=r['tokens'])
        before=r['observed']
    return dict(right_censored_at_last_observation=before)


def summarize():
    import numpy as np
    n=None;ids=None;draws=None
    groups={};losses={}
    for arm in ARMS:
        sl=[];ss=[];details=[]
        for seed in SEEDS:
            sub=RESULT/f'{arm}-{seed}';f=json.loads((sub/'fit.json').read_text());t=json.loads((sub/'test.json').read_text())
            assert sha(sub/'external.npz')==t['scores'] and sha(sub/'selected.pt')==f['selected']==t['selected']
            with np.load(sub/'external.npz') as z:
                if ids is None:
                    n=z['counts'];ids=z['ids'];draws=np.random.default_rng(9500331).integers(len(ids),size=(4000,len(ids)))
                assert np.array_equal(z['counts'],n) and np.array_equal(z['ids'],ids)
                sl.append(z['paired']);ss.append(z['shifted'])
            details.append(dict(seed=seed,params=f['params'],step=f['final_steps'],tokens=f['final_tokens'],
                best_step=f['best_step'],best_development=f['best_nll'],test_nll=t['nll'],shift_penalty=t['shift_penalty'],
                setup=f['setup_seconds'],train_seconds=f['train_seconds'],selection_total_seconds=f['combined_wall'],
                child_fit_wall=f['child_wall_seconds'],child_fit_cpu=f['child_cpu_seconds'],child_test_wall=t['child_wall_seconds'],
                child_test_cpu=t['child_cpu_seconds'],peak_fit_rss=f['peak_rss_kib'],
                time_to_development={str(level):first_below(f['history'],level) for level in (5.,4.,3.5)}))
        l=np.mean(sl,axis=0);s=np.mean(ss,axis=0);losses[arm]=l
        b=(s-l)[draws].sum(1)/n[draws].sum(1)
        groups[arm]=dict(seeds=details,external_nll=float(l.sum()/n.sum()),condition_penalty=float((s-l).sum()/n.sum()),
                condition_penalty95=np.quantile(b,[.025,.975]).tolist(),
                mean_best_development=float(np.mean([x['best_development'] for x in details])))
    strongest=min(('smooth','lif','diagonal_ssm','attention_sdpa'),key=lambda k:groups[k]['mean_best_development'])
    for arm in ARMS:
        diff=losses['hcsn']-losses[arm];b=diff[draws].sum(1)/n[draws].sum(1)
        groups[arm]['hcsn_minus_external_nll']=float(diff.sum()/n.sum())
        groups[arm]['hcsn_minus_95']=np.quantile(b,[.025,.975]).tolist()
    ext=json.loads((BASE/'external/manifest.json').read_text())
    write(BASE/'summary.json',dict(groups=groups,strongest_conventional_on_development=strongest,images=len(ids),tokens=int(n.sum()),
        unknown_fraction_lexical=ext['unknown']/ext['lexical_tokens'],excluded_external=len(ext['excluded']),
        source=sources(),qualification=sha(BASE/'qualification.json'),seal=sha(RESULT/'seal.json'),
        evidence_scope='Held-out COCO images absent from historical 1,600 and complete Flickr cohort subject to raw/dHash screen; 3 fixed seeds. Paired intervals condition on gallery. Single CPU comparison, two blocks, no coverage of large-scale pretraining.'))


def main():
    BASE.mkdir(exist_ok=True);lock=(BASE/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    RESULT.mkdir(exist_ok=True)
    if (BASE/'summary.json').exists():return
    if not (BASE/'qualification.json').exists():process(['qualify.py'])
    # Reserve one CPU worker for the concurrent scientific studies; no extra GPU use.
    wait_for(ROOT/'tied_edit/summary.json',33000)
    schedule=[(arm,seed) for i,seed in enumerate(SEEDS) for arm in ARMS[i:]+ARMS[:i]]
    for arm,seed in schedule:
        if not (RESULT/f'{arm}-{seed}'/'fit.json').exists():process(['study.py','fit',arm,str(seed)])
    wait_for(BASE/'external/manifest.json',7200)
    states={}
    for seed in SEEDS:
        common=set()
        for arm in ARMS:
            name=f'{arm}-{seed}';sub=RESULT/name;f=json.loads((sub/'fit.json').read_text())
            assert f['source']==sources() and f['selected']==sha(sub/'selected.pt')
            common.add(f['common_initial']);states[name]=f['selected']
        assert len(common)==1
    seal=dict(source=sources(),states=states,external_manifest=sha(BASE/'external/manifest.json'),
        flickr_manifest=sha(ROOT/'data/manifest.json'),qualification=sha(BASE/'qualification.json'))
    if (RESULT/'seal.json').exists():assert json.loads((RESULT/'seal.json').read_text())==seal
    else:write(RESULT/'seal.json',seal)
    for arm,seed in schedule:
        if not (RESULT/f'{arm}-{seed}'/'test.json').exists():process(['study.py','test',arm,str(seed)])
    summarize()
    print('completed eighteen mixed-modal candidates',flush=True)


if __name__=='__main__':main()
