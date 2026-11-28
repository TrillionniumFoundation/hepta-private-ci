"""Two writable affine maps surrounding two recurrent literal or slope-matched smooth cells."""
import numpy as np
from scipy.special import expit
from receiver import Cell, fitted_parent

def smooth_law(original, target):
    with np.load(original) as f:
        fields,center,du,dm,k=(f[x].astype(np.float64) for x in ('fields','center','du','dm','k'))
    u=np.linspace(-1,1,len(fields))[:,None,None]
    x=np.linspace(0,1.2,fields.shape[1])[None,:,None]
    upper=np.maximum(fields.max((0,1)),center*1.01)
    upper[2:]=[1,1.2]
    frac=center/upper
    slope=upper*frac*(1-frac)
    v=upper*expit(np.log(frac/(1-frac))+(u*du+(x-.18)*dm)/slope)
    np.savez_compressed(target,fields=v.astype(np.float32),center=center,du=du,dm=dm,k=k)

def standardized(x,parent):return np.clip((x-parent['xm'])/parent['xs'],-6,6)
def forward(x, mats, parent, law, tape=False):
    sender, r1=law.run(x@mats[0],tape)
    keys=(sender[...,0]-parent['km'])/parent['ks']
    recv,r2=law.run(keys@mats[1],tape)
    logits=(recv.reshape(len(x),-1)-parent['hm'])@parent['head']+parent['bias']
    return logits,(r1,r2,keys)

def grad(x,mats,parent,law,y):
    z,(r1,r2,k)=forward(x,mats,parent,law,tape=True)
    dz=2*(z-y)/(len(x)*z.shape[1])
    drecv=(dz@parent['head'].T).reshape(len(x),x.shape[1],mats[1].shape[1],4)
    dd2=law.reverse(drecv,r2)
    gw2=k.reshape(-1,k.shape[-1]).T@dd2.reshape(-1,dd2.shape[-1])
    dkey=(dd2@mats[1].T)/parent['ks']
    dsender=np.zeros_like(drecv)
    dsender[...,0]=dkey
    dd1=law.reverse(dsender,r1)
    gw1=x.reshape(-1,x.shape[-1]).T@dd1.reshape(-1,dd1.shape[-1])
    return [gw1,gw2]

def load_panel(path):
    with np.load(path,allow_pickle=False) as f:return {k:v for k,v in f.items()}

def balanced(panel,seed):
    rng=np.random.default_rng(seed);y=panel['y'];s=panel['speaker'];who=np.unique(s)
    idx=[]
    for digit in range(10):
        for speaker in who:
            rows=np.flatnonzero((s==speaker)&(y==digit))
            idx.extend(rng.choice(rows,12//len(who),replace=False))
    idx=np.sort(idx); assert len(idx)==120
    return {k:v[idx] for k,v in panel.items()}

def checks(parent, law):
    rng=np.random.default_rng(7979);x=rng.normal(size=(4,6,16));y=rng.normal(size=(4,10))
    mats=[parent['encoder'],parent['W']];gs=grad(x,mats,parent,law,y);ret=[]
    for i in range(2):
        for _ in range(4):
            d=rng.normal(size=mats[i].shape);d/=np.linalg.norm(d);h=1.e-6
            vals=[]
            for sign in [-1,1]:
                m=mats.copy();m[i]=m[i]+sign*h*d
                vals.append(np.mean((forward(x,m,parent,law)[0]-y)**2))
            numeric=(vals[1]-vals[0])/(2*h);exact=np.sum(gs[i]*d)
            ret.append({'which':i,'exact':exact,'central':numeric,'abs':abs(numeric-exact)})
    assert max(c['abs'] for c in ret)<2.e-5,ret
    return ret
