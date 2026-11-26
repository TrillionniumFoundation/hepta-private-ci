"""Independent WISDM cohort with person-disjoint confirmation and a sealed parent/candidate."""
import argparse
import hashlib
from pathlib import Path
import json
import sys
import time

start_import=time.perf_counter()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import har_utility as h
import numpy as np
import torch
load_seconds=time.perf_counter()-start_import

LABELS='ABCDEFGHIJKLMOPQRS'
MANIFEST=json.loads(Path(__file__).with_name('SOURCE.json').read_text())
IDS={int(Path(r['path']).name.split('_')[1]):r for r in MANIFEST['files']}
ALIASES=(1611,1612,1613,1615,1616,1617)
if any(IDS[alias]['sha'] != IDS[1610]['sha'] for alias in ALIASES):
    raise ValueError('Alias identity does not match the frozen inventory')
ORDER=sorted(set(IDS)-set(ALIASES),key=lambda p:hashlib.sha256(f'hcsn-wisdm-20261126-v1:{p}'.encode()).hexdigest())
GROUPS=(ORDER[:11],ORDER[11:17],ORDER[17:23],ORDER[23:])
ARMS=('KEEP','inverse','same_BP','wide_BP','ridge')


def read(data,people):
    tables=[]; ys=[]; ids=[]; missing=0
    for person in people:
        rec=IDS[person]; path=data/Path(rec['path']).name
        raw=path.read_bytes()
        git=hashlib.sha1(f'blob {len(raw)}'.encode()+bytes([0])+raw).hexdigest()
        if git!=rec['sha']:raise ValueError(f'Changed public file: {person}')
        text=raw.decode().split('@data',1)
        names=[ln.split('"')[1] for ln in text[0].splitlines() if ln.startswith('@attribute "')]
        rows=[line.strip().split(',') for line in text[1].splitlines() if line.strip() and not line.lstrip().startswith('%')]
        if names[0]!='ACTIVITY' or names[-1]!='class':raise ValueError(names)
        if any(int(r[-1])!=person for r in rows):raise ValueError('Row subject differs')
        labels=[LABELS.index(r[0].strip()) for r in rows]
        vals=np.array([[np.nan if c.strip()=='?' else float(c) for c in r[1:-1]] for r in rows])
        if vals.shape[1]!=len(names)-2:raise ValueError('Unexpected width')
        missing+=int((~np.isfinite(vals)).sum())
        vals[~np.isfinite(vals)]=0.
        # Put cheap columns at index 0 and 3 for the common frozen HAR feature interface.
        features=names[1:-1]
        columns=list(range(len(features)))
        for dst,name in ((0,'XAVG'),(3,'XSTANDDEV')):
            src=columns.index(features.index(name));columns[dst],columns[src]=columns[src],columns[dst]
        tables.append(vals[:,columns]);ys.extend(labels);ids.extend([person]*len(rows))
    return np.vstack(tables),np.array(ys),np.array(ids),missing


def fitted(x,y):
    truth=np.eye(len(LABELS))[y]
    return dict(cheap=h.fit_ridge(x[:,[0,3]],truth,2.),full=h.fit_ridge(x,truth,20.))


def context(x,y,ids,fit,ref=None):
    cheap=h.ridge_pred(fit['cheap'],x[:,[0,3]])
    paid=h.ridge_pred(fit['full'],x)
    top=np.sort(cheap,axis=1)
    conf=top[:,-1]-top[:,-2]
    if ref is None:ref=np.sort(conf)
    rank=np.searchsorted(ref,conf,side='right')/len(ref)
    cheap2=np.clip((x[:,[0,3]]-fit['cheap']['mean'])/fit['cheap']['scale'],-3.,3.)
    phi=np.column_stack([cheap2,rank-.5,(cheap.argmax(1)-8.5)/8.5]);u=phi@h.DRIVE
    b=h.core(h.tensor(u),h.tensor(0.)).detach().numpy()
    ok0=(cheap.argmax(1)==y).astype(float)
    return dict(phi=phi,z=b+.022*(rank-.5),u=u,ok0=ok0,gain=(paid.argmax(1)==y).astype(float)-ok0,
                ids=ids,persons=np.unique(ids)),ref


def select_arm(arm,a,d,parent):
    n=0
    if arm=='KEEP':pool=[]
    elif arm=='inverse':
        inv,n=h.sweep(a,h.NEW,parent);pool=[inv]
    elif arm in ('same_BP','wide_BP'):
        pool=h.bp(a,parent,arm=='wide_BP')
    else:
        pool=[dict(kind='ridge',head=h.fit_ridge(a['phi'],a['gain'],pen),threshold=h.NEW+off)
              for pen in (.1,1.,10.) for off in (-.1,0.,.1)]
    return h.select(d,parent,pool),len(pool),n


def train(data,out,replay=None):
    start=time.perf_counter()
    rows=[read(data,p) for p in GROUPS[:3]]
    fit=fitted(rows[0][0],rows[0][1])
    base,ref=context(*rows[0][:3],fit)
    parent,nparent=h.sweep(base,h.OLD)
    a,_=context(*rows[1][:3],fit,ref);d,_=context(*rows[2][:3],fit,ref)
    common=time.perf_counter()-start
    metrics={};selected={}
    for arm in ((replay,) if replay else ARMS):
        stamp=time.perf_counter();pol,n,c=select_arm(arm,a,d,parent)
        seconds=time.perf_counter()-stamp
        selected[arm]=pol
        if replay:
            frozen=json.loads((out/'seal.json').read_text())['policies'][arm]
            if frozen!=pol:raise ValueError('Fresh process changed policy')
            return dict(arm=arm,fit_select_seconds=seconds,common_seconds=common,identical_to_original=True)
        metrics[arm]=dict(pool=n,scanned_thresholds=c,seconds=seconds,selected_keep=pol==parent,
                          dev=h.summary(d,h.decision(d,pol),h.decision(d,parent)))
    h.store(out/'seal.json',dict(policies=selected,confidence_reference=ref.tolist(),parent=parent,experts=fit))
    h.store(out/'train.json',dict(sealed_sha256=h.digest(out/'seal.json'),protocol=h.digest(Path(__file__).with_name('PROTOCOL.md')),
             source=h.digest(Path(__file__)),base_source=h.digest(Path(h.__file__)),groups=GROUPS,
             windows=[len(r[1]) for r in rows],nonfinite=[r[3] for r in rows],import_seconds=load_seconds,
             common_training_seconds=common,parent_thresholds=nparent,arms=metrics,torch=torch.__version__,numpy=np.__version__))
    print('sealed',h.digest(out/'seal.json'),flush=True)


def test(data,out):
    start=time.perf_counter()
    tr=json.loads((out/'train.json').read_text())
    if h.digest(out/'seal.json')!=tr['sealed_sha256'] or tr['source']!=h.digest(Path(__file__)) or tr['base_source']!=h.digest(Path(h.__file__)):
        raise ValueError('Changed seal or executable')
    seal=json.loads((out/'seal.json').read_text())
    x,y,ids,nonfinite=read(data,GROUPS[3])
    d,_=context(x,y,ids,seal['experts'],np.array(seal['confidence_reference']))
    parent=h.decision(d,seal['parent'])
    rows={};actions={}
    for arm,pol in seal['policies'].items():
        stamp=time.perf_counter()
        buy=h.decision(d,pol);s=h.summary(d,buy,parent)
        s['scoring_seconds']=time.perf_counter()-stamp
        s['verify_36_original_forward']=h.check_forward(d,pol)
        rows[arm]=s;actions[arm]=buy.astype(np.uint8)
    np.savez_compressed(out/'predictions.npz',subjects=ids,labels=y,free_correct=d['ok0'],paid_correct=d['ok0']+d['gain'],**actions)
    paid=h.by_person(d,d['ok0']+d['gain'])
    r=dict(test_n=len(y),test_groups=d['persons'].tolist(),nonfinite=nonfinite,arms=rows,import_seconds=load_seconds,
           time_seconds=time.perf_counter()-start,free_accuracy=float(h.by_person(d,d['ok0']).mean()),
           paid_accuracy=float(paid.mean()),always_paid_new=float(paid.mean()-h.NEW),
           oracle_new=float(h.by_person(d,d['ok0']+np.maximum(d['gain']-h.NEW,0)).mean()),
           sealed_sha256=tr['sealed_sha256'],predictions_sha256=h.digest(out/'predictions.npz'))
    h.store(out/'test.json',r)
    print({k:[v['new_delta'],v['worst_old'],v['pass_all']] for k,v in rows.items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['train','test','cold'])
    p.add_argument('data',type=Path);p.add_argument('out',type=Path);p.add_argument('--arm',choices=ARMS)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if args.phase=='cold':
        if not args.arm:raise ValueError('Cold phase requires an arm')
        print(json.dumps(train(args.data,args.out,args.arm)),flush=True)
    elif (args.out/(args.phase+'.json')).exists():raise FileExistsError('Existing result')
    else:(train if args.phase=='train' else test)(args.data,args.out)
