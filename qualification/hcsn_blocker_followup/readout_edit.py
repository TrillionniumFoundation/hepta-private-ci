"""Conditional purchase-head edits under a common norm and observed loss."""
import argparse
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog

from . import experiment as ex, metrics, selector

RADII=(0.,.25,1.,4.)
MARGIN=.10
EPS=1.e-5
HERE=Path(__file__).parent


def matrix(data, base):
    x=((ex.features(data)-base['mean'])/base['std']).clip(-5,5)
    return np.column_stack((x,np.ones(len(x))))


def variables(data, base):
    m=matrix(data, base)
    w=np.r_[base['beta'],base['bias']]
    correct=selector.target(data)-selector.PRICE
    sign=np.sign(correct)
    importance=selector.source_mass(data['group'])*np.abs(correct)
    return m, w, sign, importance


def loss(m,w,s,a,delta):
    return float(a@np.maximum(0., MARGIN-s*(m@(w+delta)-selector.PRICE))+EPS*np.abs(delta).sum())


def direct(m,w,s,a,radius):
    d=len(w); n=len(s)
    common=np.hstack((-s[:,None]*m,np.zeros((n,d)),-np.eye(n)))
    box=np.block([[np.eye(d),-np.eye(d),np.zeros((d,n))],[-np.eye(d),-np.eye(d),np.zeros((d,n))]])
    cap=np.r_[np.zeros(d),np.ones(d),np.zeros(n)]
    A=np.vstack((common,box,cap));b=np.r_[s*(m@w-selector.PRICE)-MARGIN,np.zeros(2*d),radius]
    c=np.r_[np.zeros(d),np.full(d,EPS),a]
    opt=linprog(c,A_ub=A,b_ub=b,bounds=[(None,None)]*d+[(0,None)]*(n+d),method='highs')
    if not opt.success:raise ValueError(opt.message)
    delta=opt.x[:d]; actual=loss(m,w,s,a,delta)
    # Nonnegative variables have lower bound zero; the free variables have no bounds.
    dual=float(b@opt.ineqlin.marginals)
    if max(abs(actual-opt.fun),abs(dual-opt.fun),np.max(A@opt.x-b))>1.e-7:
        raise ValueError('primal-dual or recovered objective mismatch')
    return delta,{'objective':actual,'dual':dual,'max_primal_residual':max(0.,float(np.max(A@opt.x-b)))}


def project(delta,r):
    z=abs(delta)
    if z.sum()<=r:return delta
    u=np.sort(z)[::-1]
    cutoff=(np.cumsum(u)-r)/np.arange(1,len(z)+1)
    k=np.flatnonzero(u>cutoff)[-1]
    return np.sign(delta)*np.maximum(z-cutoff[k],0.)


def gradient(m,w,s,a,radius):
    x=np.zeros_like(w); best=x.copy(); value=loss(m,w,s,a,best)
    for i in range(1,65):
        active=s*(m@(w+x)-selector.PRICE)<MARGIN
        grad=-(m.T@(s*a*active))+EPS*np.sign(x)
        x=project(x-(.25/math.sqrt(i))*grad,radius)
        now=loss(m,w,s,a,x)
        if now<value:
            best,value=x.copy(),now
    return best,{'objective':value,'steps':64}


def capacity(m,w,s):
    d=len(w);n=len(s);zero=np.zeros(d)
    A=np.block([[-s[:,None]*m,np.zeros((n,d))],[np.eye(d),-np.eye(d)],[-np.eye(d),-np.eye(d)]])
    b=np.r_[s*(m@w-selector.PRICE)-MARGIN,np.zeros(2*d)]
    opt=linprog(np.r_[zero,np.ones(d)],A_ub=A,b_ub=b,bounds=[(None,None)]*d+[(0,None)]*d,method='highs')
    if opt.status==2:return {'feasible':False,'required_margin':MARGIN}
    if not opt.success:raise ValueError(opt.message)
    delta=opt.x[:d]
    minimum=float(np.min(s*(m@(w+delta)-selector.PRICE)))
    if minimum<MARGIN-1e-7 or abs(opt.fun-np.abs(delta).sum())>1e-6:raise ValueError('invalid witness')
    return {'feasible':True,'required_margin':MARGIN,'min_realized_margin':minimum,'min_l1_displacement':float(opt.fun)}


def assess(data,base,delta):
    value=matrix(data,base)@(np.r_[base['beta'],base['bias']]+delta)
    return metrics.evaluate(data,value>selector.PRICE,value)


def fit(args):
    root,old,out=args.root,args.old,args.output
    train,_=ex.panel(root,old,'train');dev,_=ex.panel(root,old,'dev');base=ex.read(out/'fit.json')['full-svd-.1']
    m,w,s,a=variables(train,base)
    rows={}; selected={}
    for name,solver in [('lp',direct),('gradient',gradient)]:
        candidates={}
        for r in RADII:
            start=time.perf_counter()
            delta,qa=solver(m,w,s,a,r) if r else (np.zeros(len(w)),{'objective':loss(m,w,s,a,np.zeros(len(w)))})
            if np.abs(delta).sum()>r+1.e-7:raise ValueError('edit exceeds common radius')
            candidates[str(r)]={'delta':delta.tolist(),'check':qa,'elapsed':time.perf_counter()-start,
                                'train':assess(train,base,delta),'dev':assess(dev,base,delta)}
        rows[name]=candidates
        selected[name]=max(candidates,key=lambda r:(round(candidates[r]['dev']['utility'],12),
                                                       round(candidates[r]['dev']['worst_delta_free'],12),-float(r)))
    for r in RADII:
        if rows['lp'][str(r)]['check']['objective']>rows['gradient'][str(r)]['check']['objective']+1.e-8:
            raise ValueError('gradient improved on exact optimum')
    ex.write(out/'edit_seal.json',{'model_seal':ex.digest(out/'seal.json'),'protocol':ex.digest(HERE/'readout_protocol.json'),
             'script':ex.digest(Path(__file__)),'heldout_opened':False,'rows':rows,'selected':selected})


def confirm(args):
    root,old,out=args.root,args.old,args.output
    seal=ex.read(out/'edit_seal.json')
    if (not args.expected_seal or args.expected_seal!=ex.digest(out/'edit_seal.json')
            or seal['model_seal']!=ex.digest(out/'seal.json') or seal['script']!=ex.digest(Path(__file__))):
        raise ValueError('changed edit or source')
    base=ex.read(out/'fit.json')['full-svd-.1'];test,b=ex.panel(root,old,'test')
    if b!=ex.read(out/'test.json')['test_inputs']:raise ValueError('unregistered test panel')
    rows={name:{r:assess(test,base,np.array(opt['delta'])) for r,opt in grid.items()} for name,grid in seal['rows'].items()}
    caps={}
    for split in ('train','dev','test'):
        data,_=ex.panel(root,old,split);m,w,s,_=variables(data,base);caps[split]=capacity(m,w,s)
    ex.write(out/'edit_test.json',{'rows':rows,'selected':seal['selected'],'edit_seal':args.expected_seal,
                                   'retrospective_labeled_capacity':caps})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['fit','confirm'])
    for k in ('root','old','output'):p.add_argument(k,type=Path)
    p.add_argument('--expected-seal');args=p.parse_args()
    (fit if args.phase=='fit' else confirm)(args)
