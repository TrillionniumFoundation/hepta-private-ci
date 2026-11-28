"""Cold replay with independently implemented NumPy field interpolation and inference."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np


SEEDS=(157,281,509)
BUDGETS=(30,120,600,1800)
METHODS={'literal':('boundary','fp','bp','rf','wrong','raw'),'smooth':('boundary','fp','bp','rf','wrong','raw'),
         'dense':('fp','bp','rf','raw')}


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def source_signature(a):
    result={}
    for arch,methods in METHODS.items():
        for seed in SEEDS:
            for method in methods:
                ident=f'{arch}-{seed}-{method}';d=a.fits/ident
                report=json.loads((d/'result.json').read_text());assert report['law']==sha(a.law)
                picks={}
                for b in BUDGETS:
                    rec=report['picks'][str(b)]['choice']
                    if rec is not None:
                        assert sha(d/rec['file'])==rec['sha']
                    picks[str(b)]=None if rec is None else [rec['file'],rec['sha']]
                result[ident]=dict(report=sha(d/'result.json'),picks=picks)
    meta=json.loads((a.data/'data.json').read_text())
    for group in ('train','dev','test'):
        assert sha(a.data/(group+'_pixels.npy'))==meta['splits'][group]['pixels']
        assert sha(a.data/(group+'_targets.npz'))==meta['splits'][group]['targets']
    root=Path(__file__).parent
    return dict(models=result,law=sha(a.law),source=sha(a.data/'data.json'),protocol=sha(root/'PROTOCOL.md'),
                programs={n:sha(root/n) for n in ('data.py','cifar_net.py','cifar_local.py','train.py','cold.py','score.py')})


def prepare_lookup(file,arch):
    with np.load(file) as law:
        tab=law['fields'].astype('float64')
        c=law['center'].astype('float64');k=float(law['k'])
        scale=np.array([.5*k,*np.maximum(tab[24:137,:192,:3].reshape(-1,3).std(0),.001)],'float32')
        if arch=='smooth':
            maximum=np.maximum(tab.max(axis=(0,1)),c*1.01);maximum[2:]=[1,1.2]
            frac=c/maximum;slope=maximum*frac*(1-frac)
            grid=np.linspace(0,1.2,tab.shape[1])[None,:,None]
            drive=np.linspace(-1,1,len(tab))[:,None,None]
            z=np.log(frac/(1-frac))+(drive*law['du']+(grid-.18)*law['dm'])/slope
            tab=maximum/(1+np.exp(-z.clip(-100,100)))
        return tab.astype('float32'),np.array([0,*c[:3]],'float32'),scale,k


def channels(d,arch,law):
    if arch=='dense':
        return np.stack([np.maximum(d,0),np.maximum(-d,0),np.maximum(d-1,0),np.maximum(-d-1,0)],axis=-1).reshape(d.shape[:2]+(-1,))
    tab,ref,scale,k=law
    mass=np.full((len(d),d.shape[-1]),.18,'float32');old=np.zeros_like(mass);feedback=old.copy();outputs=[]
    for drive in d.transpose(1,0,2):
        u=np.tanh(drive+feedback)
        bound=np.log1p(k*u)
        pos=np.clip(mass+old-bound,0,1.2)
        loc=(u+1)*((len(tab)-1)/2);r=pos*((tab.shape[1]-1)/1.2)
        ix=loc.astype('int32').clip(0,tab.shape[0]-2);iy=r.astype('int32').clip(0,tab.shape[1]-2)
        ax=(loc-ix).astype('float32')[...,None];ay=(r-iy).astype('float32')[...,None]
        fields=(tab[ix,iy]*(1-ay)+tab[ix,iy+1]*ay)*(1-ax)+(tab[ix+1,iy]*(1-ay)+tab[ix+1,iy+1]*ay)*ax
        signal=np.concatenate((bound[...,None],fields[...,:3]),axis=-1)
        outputs.append(np.clip((signal-ref)/scale,-6,6).reshape(len(d),-1))
        mass=fields[...,3];old=bound
        feedback=.15*np.tanh(fields[...,:2]-ref[1:3]).sum(-1)
    return np.stack(outputs,axis=1)


def evaluate(pixels,weights,arch,law,mean):
    z=[]
    for start in range(0,len(pixels),64):
        rgb=(pixels[start:start+64].astype('float32')/255-mean)*4
        b=len(rgb);h=rgb.reshape(b,4,8,4,8,3).transpose(0,1,3,2,4,5).reshape(b,16,192)
        if 'raw' in weights:
            features=h.reshape(b,4,4,2,4,2,4,3).mean((4,6)).reshape(b,-1);head=weights['raw']
        else:
            for site in ('w0','w1','w2'):
                w=weights[site];h=channels(h@w[:-1]+w[-1],arch,law)
            features=h.reshape(b,2,2,2,2,-1).mean((2,4)).reshape(b,-1);head=weights['head']
        z.append((features@head[:-1]+head[-1])*weights['temperature'])
    return np.concatenate(z)


def main(a):
    a.work.mkdir(parents=True,exist_ok=True);s=a.work/'seal.json'
    registered=source_signature(a)
    if a.mode=='seal':
        if s.exists():raise FileExistsError(s)
        s.write_text(json.dumps(registered,indent=1)+'\n');return
    assert registered==json.loads(s.read_text())
    meta=json.loads((a.data/'data.json').read_text());mu=np.array(meta['train_rgb_mean'],'float32')
    pixels=np.load(a.data/'test_pixels.npy',mmap_mode='r')
    with np.load(a.data/'test_targets.npz') as f:y,c=f['fine'],f['coarse'];identity=f['rgb_sha']
    mapping=np.zeros((100,20),'float32');mapping[y,c]=1;assert np.all(mapping.sum(1)==1)
    for arch,methods in METHODS.items():
        law=prepare_lookup(a.law,arch)
        for method in methods:
            key=f'{arch}-{a.seed}-{method}';d=a.fits/key;dest=a.work/key;dest.mkdir(exist_ok=True)
            unique={tuple(v) for v in registered['models'][key]['picks'].values() if v is not None}
            for filename,h in sorted(unique):
                target=dest/(h+'.npz');timing=dest/(h+'.json')
                if target.exists() and timing.exists() and sha(target)==json.loads(timing.read_text())['evidence']:continue
                start=time.perf_counter();cpu=time.process_time()
                assert sha(d/filename)==h
                with np.load(d/filename) as w:z=evaluate(pixels,w,arch,law,mu)
                exp=np.exp(z-z.max(-1,keepdims=True));probs=exp/exp.sum(-1,keepdims=True)
                coarse=(probs@mapping).argmax(-1)
                nll=np.log(exp.sum(-1))+z.max(-1)-z[np.arange(len(z)),y]
                wall=time.perf_counter()-start;clock=time.process_time()-cpu
                np.savez_compressed(target,fine=z.argmax(-1).astype('uint8'),coarse=coarse.astype('uint8'),nll=nll,
                                     excerpt=z[:32],ids=identity[:32])
                receipt=dict(wall=wall,cpu=clock,evidence=sha(target),full_logits_sha256=hashlib.sha256(z.tobytes()).hexdigest())
                timing.write_text(json.dumps(receipt)+'\n')
            (dest/'complete.json').write_text(json.dumps({'seal':sha(s),'selected_unique':len(unique),'target':meta['splits']['test']['targets']})+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('seal','cold'))
    for n in ('data','law','fits','work'):p.add_argument(n,type=Path)
    p.add_argument('--seed',type=int,choices=SEEDS)
    main(p.parse_args())
