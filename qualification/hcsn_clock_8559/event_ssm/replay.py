"""Replay the authors' frozen Event-SSM on raw SHD and a duration-preserving timing control."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from zipfile import ZipFile
import h5py
import numpy as np
from scipy.special import logsumexp
import yaml
import jax
import jax.numpy as jnp
from flax.serialization import msgpack_restore
def hash_file(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def init(src,zipfile):
    sys.path.insert(0,str(src.resolve()))
    from event_ssm.ssm import init_S5SSM
    from event_ssm.seq_model import BatchClassificationModel
    with ZipFile(zipfile) as archive:state=msgpack_restore(archive.read('SHD/checkpoint'))
    conf=yaml.safe_load((src/'configs/model/shd/medium.yaml').read_text())['model']
    model=BatchClassificationModel(ssm=init_S5SSM(**conf['ssm_init']),num_classes=20,num_embeddings=700,**conf['ssm'])
    variables={'params':state['params'],**state['model_state']}
    return jax.jit(lambda x,t,l:model.apply(variables,x,t,l,False)),sum(np.size(a) for a in jax.tree_util.tree_leaves(state['params']))
def derive(f,rows,B):
    events=[];ts=[]
    for i in rows:
        times=f['spikes/times'][int(i)]*1.e6
        times=times.astype(np.int64,copy=False)
        delta=np.diff(times).astype(np.float32)/1000.
        assert (delta>=0).all()
        ts.append(delta);events.append(f['spikes/units'][int(i)][:-1].astype(np.int32))
    lens=np.array([len(e) for e in events],dtype=np.int32);L=(int(lens.max())//8192+1)*8192
    x=-np.ones((B,L),dtype=np.int32);t=np.zeros((B,L),dtype=np.float32);c=t.copy()
    for j,(v,d) in enumerate(zip(events,ts)):
        x[j,:len(v)]=v;t[j,:len(d)]=d;c[j,:len(d)]=np.float32(np.sum(d,dtype=np.float64)/len(d))
    return x,t,c,np.pad(lens,(0,B-len(lens)),mode='edge')
def aggregate(y,z,sp):
    p=z.argmax(1);l=z.astype(float);l-=logsumexp(l,axis=1,keepdims=True)
    per={int(s):float((p[sp==s]==y[sp==s]).mean()) for s in np.unique(sp)}
    return dict(accuracy=float(np.mean(p==y)),speaker_macro=float(np.mean(list(per.values()))),per_speaker=per,
                new_speaker_macro=float((per[4]+per[5])/2),nll=float((-l[np.arange(len(y)),y]).mean()))
def run(src,weights,h5,out,B):
    src=src.resolve();out.mkdir(exist_ok=True,parents=True)
    t0=time.perf_counter()
    assert hash_file(h5)=='47d8621a092cb483bea9448a93c0a3375a6726d370045090c2f7a77f70f95df3'
    runner,nparams=init(src,weights)
    source_s=time.perf_counter()-t0
    with h5py.File(h5) as f:
        y=f['labels'][:].astype(int);sp=f['extra/speaker'][:].astype(int)
        lengths=np.array([len(f['spikes/units'][i])-1 for i in range(len(y))])
        result=np.zeros((2,len(y),20),dtype=np.float32);completed=np.zeros(len(y),bool)
        blocks=out/'parts';blocks.mkdir(exist_ok=True)
        # Group equal padding lengths. Official model uses layer normalization and no batch mixing during evaluation.
        for size in np.unique(lengths//8192):
            ids=np.flatnonzero(lengths//8192==size)
            for j in range(0,len(ids),B):
                ix=ids[j:j+B];path=blocks/f'{size}-{j}.npz'
                if not path.exists():
                    start=time.perf_counter();x,dt,c,lens=derive(f,ix,B)
                    zs=np.stack([np.asarray(runner(jnp.asarray(x),jnp.asarray(times),jnp.asarray(lens)))[:len(ix)] for times in (dt,c)])
                    assert zs.shape==(2,len(ix),20) and np.isfinite(zs).all()
                    tmp=path.with_suffix('.partial')
                    with tmp.open('wb') as h:np.savez_compressed(h,rows=ix,logits=zs,wall=time.perf_counter()-start)
                    os.replace(tmp,path)
                    if j%(B*12)==0:print('bucket',size,'through',j+len(ix),'of',len(ids),flush=True)
                with np.load(path) as z:
                    assert np.array_equal(ix,z['rows']);result[:,ix]=z['logits']
                completed[ix]=True
        assert completed.all()
        p=out/'all.npz';np.savez_compressed(p,natural=result[0],equal_intervals=result[1],y=y,speaker=sp,rows=np.arange(len(y)),events_after_final_drop=lengths)
    outcome=dict(model='Official Schöne et al. Event-SSM medium',source='a12766788413665cd3dcf8eaa010d551d8841eb7',
                 external_published_accuracy=.959,checkpoint_sha256=hash_file(weights),test_sha256=hash_file(h5),
                 score_sha256=hash_file(p),parameters=nparams,records=len(y),elapsed_this_invocation=time.perf_counter()-t0,
                 summed_process_block_wall=sum(float(np.load(p)['wall']) for p in blocks.glob('*.npz')),
                 setup_s=source_s,jax_version=jax.__version__,jax_devices=[str(d) for d in jax.devices()],
                 published_training_config_validate_on_test=True,views={k:aggregate(y,v,sp) for k,v in zip(('natural','equal_intervals'),result)})
    (out/'REPLAY.json').write_text(json.dumps(outcome,indent=1)+'\n')
    print(json.dumps(outcome),flush=True)
if __name__=='__main__':
    pa=argparse.ArgumentParser()
    for k in ('src','checkpoint','h5','out'):pa.add_argument(k,type=Path)
    pa.add_argument('--batch',type=int,default=2);a=pa.parse_args();run(a.src,a.checkpoint,a.h5,a.out,a.batch)
