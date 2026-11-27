"""Forward-only construction of both hidden cross-modal boundary layers and final train-only alignment."""
from pathlib import Path
import time,json,sys,hashlib
import numpy as np
from common import ROOT,setup_data,lex,CCA,store_model,load_model,gallery,score
from lawtable import propagate
def chunks(ix,n=320):
    for i in range(0,len(ix),n):yield ix[i:i+n]
def randomize(m,X,Y,seed):
    g=np.random.default_rng(seed)
    for side,a in [('x',X),('y',Y)]:
        old=getattr(m,'w'+side);w=g.standard_normal(old.shape,dtype=np.float32)
        projected=(a-getattr(m,'m'+side))@w
        setattr(m,'w'+side,w/np.maximum(projected.std(0),1e-5))
def projected_prefix(X,m,w):
    """Unseen row/time groups stay at the training mean."""
    centered=(X-m).reshape(len(X),4,-1)
    W=w.reshape(4,-1,w.shape[1]);parts=np.einsum('ntd,tdr->ntr',centered,W,optimize=True)
    return parts.cumsum(1)
def raw_drive(V,T,first,side):
    if side=='x':return projected_prefix(V,first.mx,first.wx)
    return np.stack([first.transform(lex(T,t),'y') for t in [4,8,12,16]],axis=1)
def first_out(V,T,first,side,z,kind):
    q=raw_drive(V,T,first,side)
    return propagate(q,z,kind)[:,:,:,0].reshape(len(q),-1)
def deeper(a,second,side,z,kind):
    m,w=(second.mx,second.wx) if side=='x' else (second.my,second.wy)
    steps=projected_prefix(a,m,w);return propagate(steps,z,kind).reshape(len(a),-1)
def fit(V,d,tr,kind,width,ridge,seed,z):
    X=np.array(V[tr]);Y=lex(d['tokens'][tr]);first=CCA().fit(X,Y,width,ridge)
    if kind=='linear':return {'first':first}
    if kind=='random':randomize(first,X,Y,seed)
    del X,Y
    def enc1(side):
        return np.concatenate([first_out(V[ii],d['tokens'][ii],first,side,z,kind) for ii in chunks(tr)])
    a,b=enc1('x'),enc1('y')
    second=CCA().fit(a,b,width,ridge)
    if kind=='random':randomize(second,a,b,seed+211)
    def enc2(v,side):
        return np.concatenate([deeper(v[j:j+320],second,side,z,kind) for j in range(0,len(v),320)])
    x=enc2(a,'x');del a
    y=enc2(b,'y');del b
    head=CCA().fit(x,y,width,ridge)
    return {'first':first,'second':second,'head':head}
def encode(V,d,ix,models,kind,z):
    embeds=[]
    for side in ['x','y']:
        output=[]
        for ii in chunks(ix):
            if kind=='linear':last=models['first'].transform(V[ii] if side=='x' else lex(d['tokens'][ii]),side)
            else:
                a=first_out(V[ii],d['tokens'][ii],models['first'],side,z,kind)
                last=models['head'].transform(deeper(a,models['second'],side,z,kind),side)
            output.append(last)
        embeds.append(np.concatenate(output))
    return embeds
def run(kind,width,ridge,seed):
    start=time.monotonic();d,V=setup_data();tr=np.flatnonzero(d['split']==0);dv=gallery(d,1)
    with np.load(ROOT/'law.npz') as f:z=dict(f)
    dest=ROOT/'fitted';dest.mkdir(exist_ok=True)
    stem=dest/f'{kind}-w{width}-r{ridge}-s{seed}';mark=Path(str(stem)+'.json')
    if mark.exists():return
    models=fit(V,d,tr,kind,width,ridge,seed,z)
    ftime=time.monotonic();I,T=encode(V,d,dv,models,kind,z)
    metrics,ranks=score(I,T,d,dv)
    p=Path(str(stem)+'.npz');store_model(p,models,{'kind':np.array(kind)})
    rec={'kind':kind,'width':width,'ridge':ridge,'seed':seed,'development':metrics,'fit_s':ftime-start,'fit_validate_save_s':time.monotonic()-start,'weights_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'training_count':len(tr),'dev_count':len(dv)}
    mark.write_text(json.dumps(rec));print(rec,flush=True)
if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),int(sys.argv[4]))
