"""Six-frame two-phase boundary communication and participant-level metrics."""
import hashlib, json, os, resource, sys, time
from pathlib import Path
import numpy as np
from scipy.special import softmax
from scipy.linalg import eigh

HERE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('HEPTA_MULTILINGUAL_INPUT','/workspace/scratch/c8894b6d9760/work/edit/input'))
H=16;T=6;OUT=10;KAPPA=.29352408221793214
START=(time.perf_counter(),time.process_time())
def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def use(): return {'wall_s':time.perf_counter()-START[0],'cpu_s':time.process_time()-START[1],'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
def table():
    sys.path.insert(0,str(HERE.parent/'uji'))
    from verify import law
    grid=np.linspace(-12.,12.,16385);arr=law(grid)-law(0.)
    return arr.astype('f4')
def interp(z,lut):
    j=np.clip((z+12.)*(16384/24.),0,16384.);low=j.astype('i4');high=np.minimum(low+1,16384)
    return lut[low]+(j-low)[...,None].astype('f4')*(lut[high]-lut[low])
def feedback(values):return .4*(np.tanh(values[...,0])+np.tanh(values[...,1]))
def boundary(z):return np.log1p(KAPPA*np.tanh(z))/KAPPA
def lower(x,s,lut):
    drive=x@s['w1']+s['b1'];out=[];fb=0.
    for i in range(T):
        u=drive[:,i]+fb;a=interp(u,lut);fb=feedback(a)
        out.append(np.concatenate([boundary(u),boundary(drive[:,i]+fb)],axis=-1))
    return np.stack(out,axis=1)
def upper(drive,lut):
    pieces=[];fb=0.
    for i in range(T):
        u=drive[:,i]+fb;a=interp(u,lut);fb=feedback(a);pieces.append(a)
    return np.stack(pieces,axis=1)
def logits(h,s,lut,w=None):
    a=upper(h@(s['w2'] if w is None else w)+s['b2'],lut)
    return a.reshape(len(h),-1)@s['head']+s['bias']
def splits(part):
    old=dict(np.load(DATA/f'{part}.npz'));cmd=dict(np.load(DATA/'command'/f'{part}.npz'))
    oldmeta=json.loads((DATA/'dataset.json').read_text());cmdmeta=json.loads((DATA/'command'/'dataset.json').read_text())
    assert sha(DATA/f'{part}.npz')==oldmeta['parts'][part]['sha256']
    assert sha(DATA/'command'/f'{part}.npz')==cmdmeta['actual_parts'][part]['sha256']
    train=np.load(DATA/'train.npz')['ar_train_x'];mu=train.mean((0,1));sig=train.std((0,1)).clip(1e-7)
    out={}
    for prefix,name in [('eng','fsdd'),('ar','arabic')]:
        X=old[f'{prefix}_{part}_x'];y=old[f'{prefix}_{part}_y'];ids=old[f'{prefix}_{part}_id']
        if name=='arabic':
            X=np.clip((X-mu)/sig,-5,5);people=np.array(['ar-'+part[0]+'-'+str(int(k)%(220 if part=='test' else 660)//10) for k in ids])
        else:people=np.array([x.split('_')[1] for x in ids])
        out[name]=(X.astype('f4'),y.astype('i8'),people,ids.astype(str))
    out['gsc']=(cmd['x'].astype('f4'),cmd['y'].astype('i8'),cmd['people'],cmd['id'])
    return out
def summarize(z,rows):
    _,y,people,_=rows;p=softmax(z.astype('f8'),axis=1);good=z.argmax(1)==y
    speaker={k:float(good[people==k].mean()) for k in sorted(set(people.tolist()))}
    br=np.sum(p*p,axis=1)-2*p[np.arange(len(y)),y]+1
    return {'n':len(y),'acc':float(good.mean()),'macro':float(np.mean(list(speaker.values()))),'brier':float(np.mean(br)),'by_speaker':speaker}
def small(m):return {k:{j:v[j] for j in ('n','acc','macro','brier')} for k,v in m.items()}
def selectkey(m):return (m['gsc']['macro'],-sum(v['brier'] for v in m.values()))
def retention(dev,base):
    pt=True;cons=True;bounds={}
    for name in ('arabic','fsdd'):
        a=dev[name]['by_speaker'];b=base[name]['by_speaker'];ids=sorted(a);g=np.array([a[k]-b[k] for k in ids]);
        rand=np.random.default_rng(20261127);indices=rand.integers(len(g),size=(1500,len(g)));lower=float(np.quantile(g[indices].mean(1),.10))
        bounds[name]=lower;pt=pt and g.mean()>=-.0200000001;cons=cons and lower>=-.0200000001
    return bool(pt),bool(cons),bounds
