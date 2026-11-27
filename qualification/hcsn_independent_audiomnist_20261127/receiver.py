"""Double-precision evaluation and exact reverse derivatives of the catalog's piecewise bilinear law."""
import numpy as np


class Cell:
    def __init__(self, path):
        with np.load(path) as data:
            self.f = data['fields'].astype('float64')
            self.c = data['center'].astype('float64')
            self.k = float(data['k'])
        self.ns=(self.f.shape[0]-1)/2
        self.ms=(self.f.shape[1]-1)/1.2

    def run(self, drive, tape=False):
        zero=np.zeros_like(drive[:,0]);m=zero+.18;bprev=zero;fb=zero
        out=[];saved=[]
        for step in range(drive.shape[1]):
            u=np.tanh(drive[:,step]+fb)
            b=np.log1p(self.k*u)
            live=m+bprev-b
            sx=(u+1)*self.ns
            sy=np.clip(live,0,1.2)*self.ms
            i=np.minimum(sx.astype(int),self.f.shape[0]-2)
            j=np.minimum(sy.astype(int),self.f.shape[1]-2)
            a=(sx-i)[...,None];r=(sy-j)[...,None]
            f00=self.f[i,j];f01=self.f[i,j+1]
            f10=self.f[i+1,j];f11=self.f[i+1,j+1]
            low=f00+r*(f01-f00);high=f10+r*(f11-f10)
            v=low+a*(high-low)
            h=np.tanh(v[...,:2]-self.c[:2])
            if tape:
                fu=self.ns*(high-low)
                fx=self.ms*((1-a)*(f01-f00)+a*(f11-f10))*((live>0)&(live<1.2))[...,None]
                saved.append((u,fu,fx,h))
            fb=.15*h.sum(-1);bprev=b;m=v[...,3]
            out.append(np.stack([b,v[...,0],v[...,1],v[...,2]],axis=-1))
        return np.stack(out,axis=1),saved

    def reverse(self, dout, saved):
        steps=dout.shape[1]; gdrive=np.empty(dout.shape[:-1])
        zero=np.zeros_like(dout[:,0,:,0])
        gb=zero;gm=zero;gf=zero
        for i in reversed(range(steps)):
            u,fu,fx,h=saved[i]
            dv=np.empty_like(fu)
            dv[...,:3]=dout[:,i,:,1:]
            dv[...,:2]+=.15*gf[...,None]*(1-h*h)
            dv[...,3]=gm
            gx=np.sum(dv*fx,axis=-1)
            bt=dout[:,i,:,0]+gb-gx
            gu=np.sum(dv*fu,axis=-1)+bt*self.k/(1+self.k*u)
            gf=gu*(1-u*u)
            gb=gx;gm=gx
            gdrive[:,i]=gf
        return gdrive


def encode(x,parent,law):
    x=np.clip((x-parent['xm'])/parent['xs'],-6,6)
    h,_=law.run(x@parent['encoder'])
    return (h[...,0]-parent['km'])/parent['ks']


def fitted_parent(x,y,seed,law):
    rng=np.random.default_rng(seed)
    p={'xm':x.mean((0,1)), 'xs':np.maximum(x.std((0,1)),1e-4),
       'encoder':rng.standard_normal((x.shape[-1],12))/np.sqrt(x.shape[-1]),
       'W':rng.standard_normal((12,12))/np.sqrt(12)}
    z=law.run(np.clip((x-p['xm'])/p['xs'],-6,6)@p['encoder'])[0][...,0]
    p['km']=z.mean((0,1));p['ks']=np.maximum(z.std((0,1)),1e-4)
    keys=(z-p['km'])/p['ks']
    h=law.run(keys@p['W'])[0].reshape(len(y),-1)
    p['hm']=h.mean(0);sd=np.maximum(h.std(0),1e-5)
    z=(h-p['hm'])/sd
    t=np.eye(10)[y];p['bias']=t.mean(0)
    cov=z.T@z/len(z)
    p['head']=np.linalg.solve(cov+.03*np.eye(len(cov)),z.T@(t-p['bias'])/len(z))/sd[:,None]
    return p


def scores(k,w,p,law,reverse=False):
    h,t=law.run(k@w,reverse)
    return (h.reshape(len(h),-1)-p['hm'])@p['head']+p['bias'],t


def delta_grad(k,w,p,law,target):
    z,trace=scores(k,w,p,law,True)
    residual=(z-target)
    dh=(2*residual@p['head'].T/residual.size).reshape(len(k),k.shape[1],w.shape[1],4)
    ddrive=law.reverse(dh,trace)
    return k.reshape(-1,k.shape[-1]).T@ddrive.reshape(-1,w.shape[1])


def brier(z,y):
    # The original regression scores fit one-hot labels. A fixed, shared scale produces
    # probabilities for reporting. Model selection primarily uses classification accuracy.
    a=np.exp(5*(z-z.max(1,keepdims=True)));pr=a/a.sum(1,keepdims=True)
    return np.sum((pr-np.eye(10)[y])**2,axis=1)
