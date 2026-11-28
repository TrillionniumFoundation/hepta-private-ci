"""Forward impulse-response derivatives for coupled finite-dimensional transmitter and receiver."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from fit_model import (Cell, Expired, Track, balanced, clock, dump, fields, forward, grad,
                       load_panel, sha, since, standardized, stats)
from model import fitted_parent

def impulses(tape, law, boundary_only):
    """A local response maps six drive impulses to each physical observation time."""
    steps=len(tape);shape=(*tape[0][0].shape,steps)
    mass=np.zeros(shape);last_boundary=np.zeros(shape);feedback=np.zeros(shape);rows=[]
    for time,(u,fu,fx,h) in enumerate(tape):
        total=feedback.copy();total[...,time]+=1
        du=(1-u*u)[...,None]*total
        db=law.k/(1+law.k*u)[...,None]*du
        dx=mass+last_boundary-db
        df=fu[...,None]*du[...,None,:]+fx[...,None]*dx[...,None,:]
        obs=db if boundary_only else np.concatenate((db[...,None,:],df[...,:3,:]),axis=-2)
        rows.append(obs)
        feedback=.15*np.einsum('nuc,nucv->nuv',1-h*h,df[...,:2,:])
        mass=df[...,3,:];last_boundary=db
    return np.stack(rows,axis=1)

def response(x, mats, p, law, both):
    sender,trace1=law.run(x@mats[0],both)
    keys=(sender[...,0]-p['km'])/p['ks']
    receiver,trace2=law.run(keys@mats[1],True)
    z=(receiver.reshape(len(x),-1)-p['hm'])@p['head']+p['bias']
    H=p['head'].reshape(x.shape[1],mats[1].shape[1],4,-1)
    R2=np.einsum('ntjcv,tjco->nvjo',impulses(trace2,law,False),H,optimize=True)
    j2=np.einsum('nvjo,nvi->noij',R2,keys,optimize=True).reshape(len(x),z.shape[1],-1)
    if not both:return z,j2
    S1=impulses(trace1,law,True)
    R1=np.einsum('nvjo,ij->nvio',R2,mats[1],optimize=True)/p['ks'][None,None,:,None]
    dkey=np.einsum('ntiv,nvq->ntiq',S1,x,optimize=True)
    j1=np.einsum('ntio,ntiq->noqi',R1,dkey,optimize=True).reshape(len(x),z.shape[1],-1)
    return z,np.concatenate((j1,j2),axis=-1)

def check(p,law):
    rng=np.random.default_rng(40301);x=rng.normal(size=(5,6,16));m=[p['encoder'],p['W']]
    y=rng.normal(size=(5,10));z,J=response(x,m,p,law,True)
    exact=np.einsum('no,nop->p',2*(z-y)/z.size,J)
    reverse=np.concatenate([g.ravel() for g in grad(x,m,p,law,y)])
    out={'max_reverse':float(abs(exact-reverse).max()),'max_logits':float(abs(z-forward(x,m,p,law)[0]).max()),'directions':[]}
    for unused in range(8):
        dv=[rng.normal(size=q.shape) for q in m];norm=np.sqrt(sum((q*q).sum() for q in dv));dv=[q/norm for q in dv]
        h=1e-6
        low=forward(x,[q-h*d for q,d in zip(m,dv)],p,law)[0]
        hi=forward(x,[q+h*d for q,d in zip(m,dv)],p,law)[0]
        output=np.einsum('nop,p->no',J,np.concatenate([d.ravel() for d in dv]))
        out['directions'].append(float(abs(output-(hi-low)/(2*h)).max()))
    assert out['max_reverse']<1e-9 and max(out['directions'])<3e-5,out
    return out

def released_update(track,x,y,both):
    dampings=(.002,.02,.2);mats=[[v.copy() for v in track.original] for _ in dampings]
    iteration=0
    while True:
        for c,damping in enumerate(dampings):
            track.check();current=mats[c]
            z,S=response(x,current,track.p,track.law,both)
            J=S.reshape(z.size,-1);cov=J.T@J/z.size;rhs=J.T@(y-z).ravel()/z.size
            scale=damping*np.trace(cov)/len(cov)+1.e-9
            d=np.linalg.solve(cov+scale*np.eye(len(cov)),rhs);d*=min(1,1.5/max(1.e-12,np.linalg.norm(d)))
            cut=current[0].size
            dd=[d[:cut].reshape(current[0].shape),d[cut:].reshape(current[1].shape)] if both else [np.zeros_like(current[0]),d.reshape(current[1].shape)]
            best=current;bl=np.mean((z-y)**2)
            for frac in (.25,.5,1):
                option=[q+frac*delq for q,delq in zip(current,dd)]
                track.consider(option,{'iter':iteration,'damping':damping,'fraction':frac,'jac_frob2':float(np.trace(cov)*z.size)})
                loss=np.mean((forward(x,option,track.p,track.law)[0]-y)**2)
                if loss<bl:best=option;bl=loss
            mats[c]=best
        iteration+=1

def lbfgs(track,x,y):
    scales=(1,.25,4);flat=np.concatenate([m.ravel() for m in track.original]);arr=[flat.copy()/s for s in scales];cnt=0
    def unflatten(q):
        n=track.original[0].size
        return [q[:n].reshape(track.original[0].shape),q[n:].reshape(track.original[1].shape)]
    while True:
        for i,scale in enumerate(scales):
            def obj(v):
                track.check();m=unflatten(scale*v)
                z,(r1,r2,keys)=forward(x,m,track.p,track.law,True)
                residual=z-y;dz=2*residual/residual.size
                drecv=(dz@track.p['head'].T).reshape(len(x),x.shape[1],m[1].shape[1],4)
                rec=track.law.reverse(drecv,r2);g2=keys.reshape(-1,keys.shape[-1]).T@rec.reshape(-1,rec.shape[-1])
                dsend=np.zeros_like(drecv);dsend[...,0]=(rec@m[1].T)/track.p['ks']
                dg=track.law.reverse(dsend,r1);g1=x.reshape(-1,x.shape[-1]).T@dg.reshape(-1,dg.shape[-1])
                return np.mean(residual**2),scale*np.concatenate([g1.ravel(),g2.ravel()])
            def accepted(v):
                track.consider(unflatten(scale*v),{'round':cnt,'parameter_scale':scale})
            res=minimize(obj,arr[i],jac=True,method='L-BFGS-B',callback=accepted,
                         options={'maxiter':4,'maxls':20,'ftol':1.e-13,'gtol':1.e-12})
            arr[i]=res.x
        cnt+=1

def main(a):
    d=a.models/f'{a.arch}_{a.seed}';p=fields(d/'parent.npz');law=Cell(d/'smooth.npz' if a.arch=='smooth' else a.law)
    ck=check(p,law);dump(d/'sensitivity_check.json',ck)
    cal={};dev={}
    for name in ('new','old'):
        c=balanced(load_panel(a.data/(name+'_cal.npz')),17319);cal[name]=(standardized(c['x'],p),c['y'])
        v=load_panel(a.data/(name+'_dev.npz'));dev[name]=(standardized(v['x'],p),v['y'])
    xx=np.concatenate([cal['new'][0],cal['old'][0]]);mats=[p['encoder'],p['W']]
    y=np.vstack((np.eye(10)[cal['new'][1]],forward(cal['old'][0],mats,p,law)[0]))
    base={k:stats(forward(x,mats,p,law)[0],labels) for k,(x,labels) in dev.items()}
    methods=['lm_joint','lm_receiver','lbfgs']; offset=(271,577,911).index(a.seed)+(a.arch=='smooth');methods=methods[offset:]+methods[:offset]
    for method in methods:
        if (d/(method+'.json')).exists():continue
        print(a.arch,a.seed,method,flush=True);tr=Track(method,a.seed,p,law,dev,d,base,mats)
        try:
            if method=='lbfgs':lbfgs(tr,xx,y)
            else:released_update(tr,xx,y,method=='lm_joint')
        except Expired:tr.save()
if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ('data','models','law'):ap.add_argument('--'+name,required=True,type=Path)
    ap.add_argument('--arch',required=True);ap.add_argument('--seed',required=True,type=int);main(ap.parse_args())
