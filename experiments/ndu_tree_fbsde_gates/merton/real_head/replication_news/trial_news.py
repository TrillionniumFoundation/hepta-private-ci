"""Real multiclass Head training on archived frozen features. Never loads test labels."""
from __future__ import annotations
import argparse
import os
import platform
import time
from fractions import Fraction as Q
from pathlib import Path
import numpy as np
from material_news import ROOT, PROTOCOL_SHA, encode, packet, sha, spec, write

SEARCH = ('neutral','fixed_risk','ndu_discrete','augmented_same_profile')
FILES = ('protocol.json','material_news.py','trial_news.py','audit_news.py','test_news.py','README.md')

def source_hashes(): return {n:sha((ROOT/n).read_bytes()) for n in FILES}

def design(x: np.ndarray, mean: np.ndarray, scale: np.ndarray):
    return np.column_stack(((x.astype(np.float64)-mean)/scale,np.ones(len(x))))

def probabilities(x: np.ndarray, weights: np.ndarray):
    z=x@weights;z-=z.max(axis=1,keepdims=True)
    p=np.exp(z);return p/p.sum(axis=1,keepdims=True)

def fit(x: np.ndarray, y: np.ndarray, stops: tuple[int,...]):
    if not stops or any(type(s) is not int or s not in (0,8,32,128) for s in stops):
        raise ValueError('unsupported optimizer budget')
    if x.shape != (64,385) or y.shape != (64,) or not np.isfinite(x).all():
        raise ValueError('invalid training data')
    w=np.zeros((385,4),dtype=np.float64);snapshots={};losses=[]
    if 0 in stops:snapshots[0]=w.copy()
    for step in range(1,max(stops)+1):
        p=probabilities(x,w)
        loss=float(-np.log(p[np.arange(64),y]).mean()+0.0005*np.sum(w[:-1]**2))
        losses.append(loss)
        p[np.arange(64),y]-=1
        gradient=x.T@p/64
        gradient[:-1]+=0.001*w[:-1]
        w-=0.1*gradient
        if not np.isfinite(w).all():raise ValueError('nonfinite parameters')
        if step in stops:snapshots[step]=w.copy()
    return snapshots,losses

def block_counts(prediction, labels, order):
    correct=np.asarray(prediction)==labels
    return [int(correct[order[j:j+8]].sum()) for j in range(0,32,8)]

def preference(counts):
    p=Q(1,4);trace=[p]
    for count in counts:
        p=min(Q(1,2),max(Q(0),p+(1-2*Q(count,8))/8));trace.append(p)
    return trace

def choose(counts: dict[int,list[int]], arm: str, alpha: Q):
    if arm not in SEARCH:raise ValueError('unknown selector')
    a=Q(0) if arm=='neutral' else Q(1,4) if arm=='fixed_risk' else alpha
    values={s:(1-a)*Q(sum(c),32)+a*Q(min(c),8) for s,c in counts.items()}
    if arm=='augmented_same_profile':
        selected=min(values)
        for s in sorted(values):
            if values[s]>values[selected]:selected=s
    else:selected=max(sorted(values),key=lambda s:values[s])
    return selected,{str(s):str(v) for s,v in values.items()}

def measure(fn):
    c,w=time.process_time_ns(),time.perf_counter_ns();value=fn()
    return value,{'cpu_ns':time.process_time_ns()-c,'wall_ns':time.perf_counter_ns()-w}

def event(path: Path, row: dict):
    with path.open('ab') as f:f.write(encode(row)+b'\n');f.flush();os.fsync(f.fileno())

def run(material: Path, output: Path):
    cfg=spec();a,receipt=packet(material/'worker.npz')
    output.mkdir(parents=True,exist_ok=False)
    write(output/'protocol.json',cfg)
    def setup():
        mean=a['x_train'].astype(np.float64).mean(axis=0)
        scale=np.maximum(np.sqrt(np.mean((a['x_train']-mean)**2,axis=0)),1e-6)
        return mean,scale,{s:design(a['x_'+s],mean,scale) for s in ('train','cal','holdout')}
    (mean,scale,x),common=measure(setup)
    order=np.argsort(a['cal_hashes'],kind='stable');rows=[]
    for repeat in range(cfg['repeats']):
        arms=cfg['arms'][repeat:]+cfg['arms'][:repeat]
        for arm in arms:
            event(output/'attempts.jsonl',{'repeat':repeat,'arm':arm,'status':'start'})
            try:
                c0,w0=time.process_time_ns(),time.perf_counter_ns()
                phases={};cal={};values={};snapshots={};losses=[];trace=[]
                majority=int(np.bincount(a['y_train'],minlength=4).argmax())
                if arm in SEARCH:
                    (snapshots,losses),phases['fit']=measure(lambda:fit(x['train'],a['y_train'],(0,8,32,128)))
                    def calibrate():
                        counts={s:block_counts(probabilities(x['cal'],w).argmax(axis=1),a['y_cal'],order)
                                for s,w in snapshots.items()}
                        baseline=block_counts(np.full(32,majority),a['y_cal'],order)
                        tr=preference(baseline)
                        sel,v=choose(counts,arm,tr[-1])
                        return counts,tr,sel,v
                    (cal,trace,selected,values),phases['calibration_and_selection']=measure(calibrate)
                    weights=snapshots[selected];steps=128
                else:
                    selected=int(arm[5:]) if arm.startswith('fixed') else 0
                    (snapshots,losses),phases['fit']=measure(lambda:fit(x['train'],a['y_train'],(selected,)))
                    weights=snapshots[selected];steps=selected
                def infer():
                    if arm=='train_majority':
                        p=np.zeros((32,4));p[:,majority]=1;return p
                    return probabilities(x['holdout'],weights)
                predicted,phases['prediction']=measure(infer)
                cpu,wall=time.process_time_ns()-c0,time.perf_counter_ns()-w0
                row={'repeat':repeat,'arm':arm,'selected_steps':selected,'actual_steps':steps,
                    'majority_class':majority,'weights':weights.tolist(),
                    'checkpoints':{str(s):w.tolist() for s,w in snapshots.items()},'losses':losses,
                    'calibration_blocks':{str(s):v for s,v in cal.items()},
                    'preference_trace':[str(v) for v in trace],'selection_values':values,
                    'holdout_ids':a['holdout_ids'].tolist(),'probabilities':predicted.tolist(),
                    'phases':phases,'cpu_ns':cpu,'wall_ns':wall}
                rows.append(row);write(output/f'{repeat}-{arm}.json',row)
                event(output/'attempts.jsonl',{'repeat':repeat,'arm':arm,'status':'success'})
            except Exception as exc:
                event(output/'attempts.jsonl',{'repeat':repeat,'arm':arm,'status':'failure','error':type(exc).__name__})
                raise
    report={'schema':'hepta.merton.news-seal.v1','posture':'RESEARCH_ONLY_DENY_ALL',
        'protocol_sha256':PROTOCOL_SHA,'worker_sha256':receipt['worker_sha256'],
        'archive_sha256':cfg['archive_sha256'],'source_sha256':source_hashes(),
        'attempts_sha256':sha((output/'attempts.jsonl').read_bytes()),
        'mean':mean.tolist(),'scale':scale.tolist(),'common_preparation_cost':common,
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.platform()},
        'fresh_encoder_calls':0,'heldout_labels_loaded':False,'rows':rows}
    write(output/'sealed.json',report)
    print(encode({'lifecycles':len(rows),'actual_updates':sum(r['actual_steps'] for r in rows),
                  'sealed_sha256':sha((output/'sealed.json').read_bytes())}).decode())

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--material',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.material,a.output)
