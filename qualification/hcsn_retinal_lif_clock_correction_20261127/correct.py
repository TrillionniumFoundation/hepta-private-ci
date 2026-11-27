"""Re-estimate only the corrected LIF clock. Independent phases for fit and confirmation."""
import argparse
import ctypes
import gzip
import json
import time
from pathlib import Path
import numpy as np
from scipy.special import expit
from sklearn.metrics import average_precision_score
from retinal_io import bce,logistic,make_trial,sha

HERE=Path(__file__).resolve().parent


def dump(p,v):p.write_text(json.dumps(v,indent=1,sort_keys=True,allow_nan=False)+'\n')


def signatures():
    return {p:sha(HERE/p) for p in ('PROTOCOL.md','lif.cpp','retinal_io.py','correct.py')}


def features(trials,scale,mu,sd,lib,dt):
    xy=[]
    for trial in trials:
        x=np.ascontiguousarray((trial['features']-mu)/sd*scale)
        h=np.zeros((len(x),x.shape[1],4))
        lib.lif(len(x),x.shape[1],dt,x,h)
        xy.append(h[trial['indices']].reshape(len(trial['indices']),-1))
    return np.concatenate(xy)


def init(p):
    lib=ctypes.CDLL(str(p.resolve()));dp=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.lif.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_double,dp,dp];lib.lif.restype=None;return lib


def fit(a):
    if a.seal.exists():raise FileExistsError(a.seal)
    clock=time.perf_counter();lib=init(a.lib);trials=[make_trial(a.data,i) for i in range(1,56,2)]
    base=np.vstack([t['features'] for t in trials if t['id']<=43]);mu=base.mean(0);sd=base.std(0).clip(1e-7)
    ids=np.concatenate([np.repeat(t['id'],len(t['y'])) for t in trials]);y=np.concatenate([t['y'] for t in trials])
    train=ids<=43;dev=ids>=45;records=[]
    raw=json.loads(gzip.decompress((a.legacy/'seal.json.gz').read_bytes()))
    assert all(t['input_sha']==raw['input_hashes'][str(t['id'])] for t in trials)
    for scale in (.6,1.3):
        x=features(trials,scale,mu,sd,lib,1.)
        for ridge in (.01,.0001):
            p,coeff=logistic(x,y,train,ridge);records.append({'scale':scale,'ridge':ridge,'dev_bce':float(bce(p[dev],y[dev]).mean()),'readout':coeff})
    dump(a.seal,{'dt_ms':1,'selection':'minimum pooled dev BCE, earliest in fixed order','selected':int(np.argmin([r['dev_bce'] for r in records])),'candidates':records,'source_sha256':signatures(),'lib_sha256':sha(a.lib),'legacy_seal_gzip_sha256':sha(a.legacy/'seal.json.gz'),'training_event_count':int(train.sum()),'dev_event_count':int(dev.sum()),'raw_sha':{t['id']:t['input_sha'] for t in trials},'mu':mu.tolist(),'sd':sd.tolist(),'fit_wall':time.perf_counter()-clock})


def eval_readout(x,fit):
    z=(x-np.array(fit['mean']))/np.array(fit['sd'])
    z=np.column_stack([np.ones(len(x)),z]);return expit(z@np.array(fit['params'])).clip(1e-10,1-1e-10)


def confirm(a):
    if (a.out/'cold.npz').exists():raise FileExistsError(a.out/'cold.npz')
    a.out.mkdir(parents=True,exist_ok=True);s=json.loads(a.seal.read_bytes());assert s['source_sha256']==signatures() and s['lib_sha256']==sha(a.lib)
    clock=time.perf_counter();lib=init(a.lib);trials=[make_trial(a.data,i) for i in range(57,76,2)]
    mu=np.array(s['mu']);sd=np.array(s['sd']);rec=s['candidates'][s['selected']]
    y=np.concatenate([t['y'] for t in trials]);rep=np.concatenate([np.repeat(t['id'],len(t['y'])) for t in trials]);ts=np.concatenate([t['indices'] for t in trials])
    new=eval_readout(features(trials,rec['scale'],mu,sd,lib,1.),rec['readout'])
    # Read archived results only after new independent predictive vector is fully evaluated.
    assert sha(a.legacy/'seal.json.gz')==s['legacy_seal_gzip_sha256']
    raw=json.loads(gzip.decompress((a.legacy/'seal.json.gz').read_bytes()))
    assert all(t['input_sha']==raw['input_hashes'][str(t['id'])] for t in trials)
    old=raw['all_fits']['lif'][raw['model_selection']['lif']]
    legacy=eval_readout(features(trials,old['scale'],mu,sd,lib,2.),old['fit'])
    pred_path=a.legacy/'cold.npz'
    with np.load(pred_path) as f:
        assert np.array_equal(y,f['y']) and np.array_equal(rep,f['repeat']) and np.array_equal(ts,f['time_ms'])
        named={k:f[k] for k in f.files if k not in ('time_ms','y','repeat')}
    gap=float(np.max(abs(legacy-named['lif'])));assert gap<1e-12,gap
    np.savez_compressed(a.out/'cold.npz',y=y,repeat=rep,time_ms=ts,corrected_lif=new,legacy_replay=legacy)
    groups=np.unique(rep);draw=np.random.default_rng(30588).integers(0,len(groups),(6000,len(groups)))
    def pooled(v):
        each=np.array([v[rep==g].mean() for g in groups])
        return {'pooled':float(v.mean()),'balanced':float(each.mean()),'ci95':np.quantile(each[draw].mean(1),[.025,.975]).tolist(),'repeats':each.tolist()}
    loss=bce(new,y);new_stats={'log_loss':pooled(loss),'brier':pooled((new-y)**2),'ap':float(average_precision_score(y,new)),'calibration':pooled(new-y),'bits_per_event_vs_rate':pooled((bce(named['rate'],y)-loss)/np.log(2))}
    dif={k:pooled(loss-bce(other,y)) for k,other in named.items()}
    dump(a.out/'RESULTS.json',{'events':len(y),'repeat_count':len(groups),'positive':int(y.sum()),'legacy_max_abs_probability_error':gap,'original_cold_sha256':sha(pred_path),'corrected_cold_sha256':sha(a.out/'cold.npz'),'seal_sha256':sha(a.seal),'selected':{k:rec[k] for k in ('scale','ridge','dev_bce')},'corrected':new_stats,'corrected_minus_archived_loss':dif,'cold_wall_s':time.perf_counter()-clock})
    print(new_stats['log_loss']['balanced'],dif['lif']['balanced'],gap)


if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('command',choices=('fit','confirm'))
    for k in ('data','lib','legacy','seal','out'):q.add_argument(k,type=Path)
    a=q.parse_args();(fit if a.command=='fit' else confirm)(a)
