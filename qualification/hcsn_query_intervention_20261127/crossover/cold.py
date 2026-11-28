"""Score each equal-phase paired intervention under frozen senders."""
import argparse
import gzip
import json
from pathlib import Path
import pickle
import time
import numpy as np
from threadpoolctl import threadpool_limits
from fit import MODELS,Y_COLD,get,prob,metrics,digest,dump
from features import PHASE

def evaluate_condition(probability,events):
    return metrics(probability.ravel(),events.ravel())
def difference(p1,p0,y1,y0):
    # The commanded condition arrays are replicate x within-episode cycle x phase x forecast horizon.
    pred=(p1.mean(1)-p0.mean(1)).mean(0,dtype=float)
    observation=y1.mean(1)-y0.mean(1)
    ordinary=float(np.mean((pred-observation.mean(0))**2))
    cross=float(np.mean((pred-observation[0])*(pred-observation[1])))
    split_noise=float(np.mean((observation[0]-observation[1])**2)/4)
    return [ordinary,cross,split_noise,float(pred.mean()),float(observation.mean())]
def cold(data,cache,models,out):
    out.mkdir(exist_ok=True,parents=True);m=json.loads((models/'SEAL.json').read_text())
    assert digest(Path(__file__).with_name('features.py'))==m['constructor_sha']
    if digest(models/'boost.pkl.gz')!=m['boost']['sha']:raise ValueError('booster SHA')
    with gzip.open(models/'boost.pkl.gz','rb') as buf:boost=pickle.load(buf)
    names=list(MODELS)+['boost'];donor={};cost={n:0. for n in names};qa={}
    for sid in m['test']:
        org=data/f'{sid}.npz';assert digest(org)==m['raw_test'][str(sid)]
        receipt=json.loads((cache/f'{sid}.json').read_text())
        assert receipt['source']==digest(org) and m['table_sha']==receipt['table_sha']
        qa[str(sid)]=receipt['input_qa']
        cube={};y={}
        for typ in ('1','2'):
            for rep in (0,1):
                x,target=get(data,cache,sid,typ,rep,(1,2,3),Y_COLD)
                shape=(3,3,len(PHASE),len(Y_COLD));y[typ,rep]=target.reshape(shape)
                arrays={}
                for n in names:
                    tic=time.monotonic();pp=prob(x,n,boost if n=='boost' else m['weights'][n]).reshape(shape)
                    cost[n]+=time.monotonic()-tic;arrays[n]=pp;cube[n,typ,rep]=pp
                path=out/f'{sid}_{typ}_{rep}.npz'
                # Identical commands imply identical predictions across repeats.
                if rep==0 or not receipt['input_qa'][typ]['repeats_identical']:
                    np.savez_compressed(path,**arrays)
                else:
                    if not all(np.array_equal(cube[n,typ,0],cube[n,typ,1]) for n in names):raise ValueError('unexpected FP32 mismatch between identical drives')
        outcomes={typ:np.stack([y[typ,k] for k in (0,1)]) for typ in ('1','2')}
        cell={}
        for n in names:
            pulses={typ:np.stack([cube[n,typ,k] for k in (0,1)]) for typ in ('1','2')}
            pp=pulses['2'];yy=outcomes['2']
            cell[n]=dict(primary=difference(pp[:,2],pp[:,1],yy[:,2],yy[:,1]),
                      secondary=difference(pp[:,2],pulses['1'][:,2],yy[:,2],outcomes['1'][:,2]),
                      high_noise2=evaluate_condition(pp[:,2],yy[:,2]).tolist(),
                      mid_noise2=evaluate_condition(pp[:,1],yy[:,1]).tolist())
        donor[str(sid)]=cell
        print('scored',len(donor),sid,flush=True)
    rng=np.random.default_rng(855949);ix=rng.integers(0,len(donor),(10000,len(donor)));outvals={};compare={}
    for field in ('primary','secondary','high_noise2','mid_noise2'):
        v={n:np.stack([row[n][field] for row in donor.values()]) for n in names}
        outvals[field]={n:a.mean(0).tolist() for n,a in v.items()};compare[field]={}
        for n in names:
            dd=v['moving']-v[n]
            compare[field][n]=dict(delta=dd.mean(0).tolist(),ci95=np.quantile(dd[ix].mean(1),[.025,.975],axis=0).tolist(),donors_lower_first=int((dd[:,0]<0).sum()))
    gate=all(compare['primary'][n]['ci95'][1][0]<0 and compare['high_noise2'][n]['delta'][1]<=0 for n in ('fixed','tangent','smooth','boost'))
    dump(out/'results.json',dict(seal_sha=digest(models/'SEAL.json'),donors=donor,means=outvals,contrasts=compare,gate=gate,sender_readout_seconds=cost,input_qa=qa))
    print('gate',gate,'primary',outvals['primary'],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','cache','models','out'):p.add_argument('--'+k,required=True,type=Path)
    a=p.parse_args()
    with threadpool_limits(limits=1):cold(a.data,a.cache,a.models,a.out)
