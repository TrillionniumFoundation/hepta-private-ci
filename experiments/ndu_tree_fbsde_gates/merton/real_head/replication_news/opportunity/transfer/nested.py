"""Nested record exclusion for learning-curve forecasts; retrospective research only."""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
import time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
NEWS = HERE.parent.parent
for p in (HERE.parent, NEWS):
    sys.path.insert(0, str(p))
from belief import Planner, BATCHES, STEPS
from material_news import encode, loads, original, sha, write
from trial_news import design, probabilities

POSTURE = 'RESEARCH_ONLY_DENY_ALL'
FILES = ('nested.py', 'audit_nested.py', 'test_nested.py', 'protocol.json', 'README.md')
WORKER_KEYS = {'fit_x','fit_y','fit_ids','cal_x','cal_y','cal_ids','cal_hashes','eval_x','eval_ids'}


def config():
    return loads((HERE/'protocol.json').read_bytes())


def sources():
    paths = {n: HERE/n for n in FILES}
    paths.update({'../belief.py': HERE.parent/'belief.py', '../review.py': HERE.parent/'review.py',
                  '../../material_news.py': NEWS/'material_news.py', '../../trial_news.py': NEWS/'trial_news.py'})
    return {n: sha(p.read_bytes()) for n,p in paths.items()}


def groups(ids, n, domain):
    if n not in (3,4) or len(ids) % n or len(set(ids)) != len(ids):
        raise ValueError('invalid disjoint partition')
    if domain not in ('outer','inner') or any(type(i) is not str for i in ids):
        raise ValueError('invalid identity or partition domain')
    order = sorted(range(len(ids)), key=lambda i: hashlib.sha256(
        ('hepta-nested-'+domain+'-v1:'+ids[i]).encode()).hexdigest())
    return [order[j::n] for j in range(n)]


def prepare(archive: Path, output: Path):
    c0,w0=time.process_time_ns(),time.perf_counter_ns()
    rows,x,parts=original(archive)
    train,cal=parts['train'],parts['calibration']
    ids=[rows[i]['case_id'] for i in train]
    output.mkdir(parents=True,exist_ok=False)
    manifests=[]
    for fold,indices in enumerate(groups(ids,4,'outer')):
        evaluation=[train[i] for i in indices]
        fitted=[train[i] for i in range(64) if i not in indices]
        path=output/f'fold-{fold}';path.mkdir()
        a={'fit_x':x[fitted], 'fit_y':np.array([rows[i]['label'] for i in fitted]),
           'fit_ids':np.array([rows[i]['case_id'] for i in fitted]),
           'cal_x':x[cal], 'cal_y':np.array([rows[i]['label'] for i in cal]),
           'cal_ids':np.array([rows[i]['case_id'] for i in cal]),
           'cal_hashes':np.array([sha(rows[i]['text'].encode()) for i in cal]),
           'eval_x':x[evaluation], 'eval_ids':np.array([rows[i]['case_id'] for i in evaluation])}
        with (path/'worker.npz').open('xb') as f: np.savez(f,**a)
        # The producer receives only worker.npz and its expected digest, never this file.
        write(path/'labels.json',{rows[i]['case_id']:rows[i]['label'] for i in evaluation})
        manifests.append({'fold':fold,'worker_sha256':sha((path/'worker.npz').read_bytes()),
                          'labels_sha256':sha((path/'labels.json').read_bytes()),
                          'fit_ids':a['fit_ids'].tolist(),'eval_ids':a['eval_ids'].tolist()})
    write(output/'manifest.json',{'schema':'hepta.nested-material.v1','posture':POSTURE,
          'protocol_sha256':sha((HERE/'protocol.json').read_bytes()),'archive_sha256':config()['archive_sha256'],
          'excluded_original_holdout_ids':[rows[i]['case_id'] for i in parts['holdout']],
          'folds':manifests,'cpu_ns':time.process_time_ns()-c0,'wall_ns':time.perf_counter_ns()-w0})


def read_worker(path, expected_sha):
    if sha(path.read_bytes())!=expected_sha: raise ValueError('worker digest drift')
    with np.load(path,allow_pickle=False) as z:
        if set(z.files)!=WORKER_KEYS: raise ValueError('unexpected field or evaluation-label leak')
        a={k:z[k].copy() for k in z.files}
    all_ids=[]
    for kind,n in (('fit',48),('cal',32),('eval',16)):
        if a[kind+'_x'].shape!=(n,384) or not np.isfinite(a[kind+'_x']).all():
            raise ValueError('invalid feature shape or nonfinite feature')
        ids=a[kind+'_ids']
        if ids.shape!=(n,) or ids.dtype.kind not in 'US': raise ValueError('invalid identity array')
        all_ids+=ids.tolist()
        if kind!='eval':
            y=a[kind+'_y']
            if y.shape!=(n,) or y.dtype.kind not in 'iu' or np.any((y<0)|(y>3)):
                raise ValueError('invalid permitted labels')
    if len(all_ids)!=len(set(all_ids)): raise ValueError('cross-role overlap')
    if a['cal_hashes'].shape!=(32,) or len(set(a['cal_hashes'].tolist()))!=32:
        raise ValueError('invalid calibration order')
    return a


class Head:
    """New size-qualified trainer; inherited hard64 trainer is not changed."""
    def __init__(self, raw, labels, budget=128):
        if raw.ndim!=2 or raw.shape[1]!=384 or len(raw) not in (32,48):
            raise ValueError('only nested32/48 training sizes admitted')
        if not np.isfinite(raw).all() or labels.shape!=(len(raw),) or labels.dtype.kind not in 'iu':
            raise ValueError('invalid training arrays')
        if np.any((labels<0)|(labels>3)) or type(budget) is not int or not 0<=budget<=128:
            raise ValueError('invalid labels or hard budget')
        raw=raw.astype(np.float64)
        self.mean=raw.mean(axis=0)
        self.scale=np.maximum(np.sqrt(np.mean((raw-self.mean)**2,axis=0)),1e-6)
        self.x=design(raw,self.mean,self.scale);self.y=labels.copy();self.budget=budget
        self.w=np.zeros((385,4));self.updates=0;self.losses=[]
        self.snapshots={0:self.w.copy()}

    def step(self):
        if self.updates>=self.budget:raise ValueError('unaffordable update')
        n=len(self.y);p=probabilities(self.x,self.w)
        self.losses.append(float(-np.log(p[np.arange(n),self.y]).mean()+.0005*np.sum(self.w[:-1]**2)))
        p[np.arange(n),self.y]-=1
        gradient=self.x.T@p/n;gradient[:-1]+=.001*self.w[:-1]
        self.w-=.1*gradient;self.updates+=1
        if not np.isfinite(self.w).all():raise ValueError('nonfinite Head update')
        if self.updates in STEPS:self.snapshots[self.updates]=self.w.copy()

    def advance(self, target):
        if type(target) is not int or target not in STEPS or not self.updates<target<=self.budget:
            raise ValueError('invalid training target')
        while self.updates<target:self.step()

    def predict(self,raw,step=None):
        step=self.updates if step is None else step
        if step not in self.snapshots:raise ValueError('unexecuted checkpoint')
        return probabilities(design(raw,self.mean,self.scale),self.snapshots[step])

    def record(self):
        return {'mean':self.mean.tolist(),'scale':self.scale.tolist(),
                'checkpoints':{str(k):v.tolist() for k,v in self.snapshots.items()},
                'losses':self.losses,'actual_updates':self.updates}


def fit_prior(a):
    start=time.process_time_ns();wall=time.perf_counter_ns();curves=[];fits=[]
    ids=a['fit_ids'].tolist()
    for f,valid in enumerate(groups(ids,3,'inner')):
        train=[i for i in range(48) if i not in valid]
        h=Head(a['fit_x'][train],a['fit_y'][train]);counts=[]
        for t in STEPS:
            if t:h.advance(t)
            counts.append(int(np.sum(h.predict(a['fit_x'][valid]).argmax(axis=1)==a['fit_y'][valid])))
        curves.append(counts)
        fits.append({'fold':f,'train_ids':a['fit_ids'][train].tolist(),
                     'valid_ids':a['fit_ids'][valid].tolist(),'counts':counts,**h.record()})
    return {'curves':curves,'fits':fits,'actual_updates':384,'scoring_calls':12,
            'cpu_ns':time.process_time_ns()-start,'wall_ns':time.perf_counter_ns()-wall}


def journal(path,event):
    with path.open('ab') as f:
        f.write(encode(event)+b'\n');f.flush();os.fsync(f.fileno())


def lifecycle(a,prior,arm,scenario,emit):
    if arm not in config()['arms'] or scenario not in config()['scenarios']:
        raise ValueError('unregistered policy or scenario')
    c0,w0=time.process_time_ns(),time.perf_counter_ns()
    h=Head(a['fit_x'],a['fit_y'],scenario['budget']);history=[];events=[]
    planner=Planner(prior['curves'],scenario,arm[7:]) if arm.startswith('belief_') else None
    def log(e):events.append(e);emit(e)
    log({'kind':'start','fit_ids':a['fit_ids'].tolist()})
    order=np.argsort(a['cal_hashes'],kind='stable')
    while True:
        if planner:
            command=planner.decision(history)
        else:
            target=int(arm[5:]);take=target>h.updates and target<=scenario['budget']
            command={'action':'continue' if take else 'stop','to_step':target if take else None,
                     'selected_steps':h.updates,'reason':'fixed_schedule'}
        log({'kind':'decision','history':list(history),**command})
        if command['action']=='stop':selected=command['selected_steps'];break
        target=command['to_step'];log({'kind':'train_start','from_step':h.updates,'to_step':target})
        h.advance(target)
        log({'kind':'train_done','step':h.updates,'weights_sha256':sha(encode(h.w.tolist()))})
        if planner:
            j=len(history);start=sum(BATCHES[:j]);idx=order[start:start+BATCHES[j]]
            count=int(np.sum(h.predict(a['cal_x'][idx]).argmax(axis=1)==a['cal_y'][idx]))
            history.append(count)
            log({'kind':'observation','step':target,'count':count,'ids':a['cal_ids'][idx].tolist()})
    prediction=h.predict(a['eval_x'],selected)
    log({'kind':'success','actual_updates':h.updates,'selected_steps':selected})
    return {'arm':arm,'scenario':scenario['name'],'history':history,'selected_steps':selected,
            'evaluation_ids':a['eval_ids'].tolist(),'probabilities':prediction.tolist(),
            'events':events,'calibration_calls':len(history),**h.record(),
            'cpu_ns':time.process_time_ns()-c0,'wall_ns':time.perf_counter_ns()-w0}


def run(worker,worker_sha,output):
    a=read_worker(worker,worker_sha);output.mkdir(parents=True,exist_ok=False)
    journal_path=output/'journal.jsonl'
    journal(journal_path,{'phase':'prior','kind':'start'})
    try:
        prior=fit_prior(a)
        write(output/'prior.json',prior)
        journal(journal_path,{'phase':'prior','kind':'success','updates':prior['actual_updates']})
        forecasts={str(t):[(c[j]+1)/18 for c in prior['curves']] for j,t in enumerate(STEPS)}
        # Forecast is sealed before ANY target Head training or target label scoring.
        write(output/'forecast.json',{'prior_rates':forecasts,'eval_ids':a['eval_ids'].tolist(),
              'target_labels_loaded':False,'worker_sha256':worker_sha})
        rows=[]
        for scenario in config()['scenarios']:
            for arm in config()['arms']:
                def emit(e):journal(journal_path,{'phase':'policy','arm':arm,'scenario':scenario['name'],**e})
                row=lifecycle(a,prior,arm,scenario,emit)
                rows.append(row);write(output/(arm+'.json'),row)
        # Separate diagnostic is paid even though policies may have stopped at8.
        journal(journal_path,{'phase':'diagnostic','kind':'start'})
        c,w=time.process_time_ns(),time.perf_counter_ns()
        h=Head(a['fit_x'],a['fit_y']);h.advance(128)
        diagnostic={**h.record(),'probabilities':{str(t):h.predict(a['eval_x'],t).tolist() for t in STEPS},
                    'cpu_ns':time.process_time_ns()-c,'wall_ns':time.perf_counter_ns()-w}
        write(output/'diagnostic.json',diagnostic)
        journal(journal_path,{'phase':'diagnostic','kind':'success','updates':128})
        seal={'schema':'hepta.nested-transfer.seal.v1','posture':POSTURE,'source_sha256':sources(),
              'worker_sha256':worker_sha,'forecast_sha256':sha((output/'forecast.json').read_bytes()),
              'prior_sha256':sha((output/'prior.json').read_bytes()),
              'diagnostic_sha256':sha((output/'diagnostic.json').read_bytes()),
              'journal_sha256':sha(journal_path.read_bytes()),'rows':rows,
              'prior_updates':384,'diagnostic_updates':128,'policy_updates':sum(r['actual_updates'] for r in rows),
              'target_labels_loaded':False,'original_holdout_used':False,'new_sources':0,
              'runtime':{'python':platform.python_version(),'numpy':np.__version__}}
        write(output/'sealed.json',seal)
        print(encode({'policy_rows':len(rows),'total_updates':512+seal['policy_updates']}).decode())
    except Exception as exc:
        journal(journal_path,{'phase':'run','kind':'failure','error':type(exc).__name__})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('prepare');q.add_argument('--archive',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('--worker',type=Path,required=True);q.add_argument('--worker-sha',required=True);q.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.archive,a.output)
    else:run(a.worker,a.worker_sha,a.output)
