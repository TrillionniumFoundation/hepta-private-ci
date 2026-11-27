import time
ENTRY=time.perf_counter();ENTRY_CPU=time.process_time()
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.linalg import eigh
from model import ARMS,SEEDS,RUNGS,WIDTH,Cell,clone,gradient,hidden,macro,parent,predict,prep,raw_features,read_batches,ridge,sha


def ortho_keys(k,y):
    pooled=k.mean(1);mu=pooled.mean(0)
    means=np.stack([pooled[y==c].mean(0) for c in np.unique(y)])-mu
    a=pooled-mu;cov=a.T@a/len(a)
    _,dirs=eigh(means.T@means/len(means)+.0001*np.eye(len(cov)),cov+.05*max(np.trace(cov)/len(cov),.001)*np.eye(len(cov)))
    dirs=dirs[:,::-1];return dirs/np.linalg.norm(dirs,axis=0)


def fit(a):
    x,y,_,ids=read_batches(a.archive,range(1,6));xv,yv,bv,v_ids=read_batches(a.archive,(6,7))
    p0={'mean':(np.sign(x)*np.log1p(abs(x))).mean(0),'sd':np.maximum((np.sign(x)*np.log1p(abs(x))).std(0),1.e-6)}
    if a.arm not in ('raw','fourier'):
        law=Cell(a.law);p0=parent(x,a.seed,law)
    else:law=None
    t=prep(x,p0);v=prep(xv,p0)
    tY=np.eye(6)[y];rng=np.random.default_rng(30109+a.seed)
    status={'seed':a.seed,'arm':a.arm,'archive_sha256':sha(a.archive),'law_sha256':sha(a.law),'n_train':len(y),'n_dev':len(yv),'train_dev_duplicate_feature_ids':len(set(ids)&set(v_ids)),'common_process_wall':time.perf_counter()-ENTRY,'common_process_cpu':time.process_time()-ENTRY_CPU}
    p=clone(p0);wall=time.perf_counter();cpu=time.process_time()
    elapsed=lambda:time.process_time()-cpu
    hist=[];saved={r:None for r in RUNGS};best={r:None for r in RUNGS}
    def consider(q,detail,z=None):
        if elapsed()>max(RUNGS):return
        if z is None:z=predict(v,q,law)
        m=macro(z,yv,bv);mse=np.mean((z-np.eye(6)[yv])**2)
        rank=(m,-mse);c=elapsed();w=time.perf_counter()-wall
        record={**detail,'dev_macro':m,'dev_mse':float(mse),'fit_cpu':c,'fit_wall':w}
        hist.append(record)
        for r in RUNGS:
            if c<=r and (best[r] is None or rank>best[r]):
                best[r]=rank;saved[r]=(clone(q),dict(record))

    if a.arm in ('raw','fourier','frozen'):
        configs=(.5,1.,2.) if a.arm=='fourier' else (1.,)
        if a.arm=='fourier':
            # Characteristic scale and directions from training data only.
            xx=t.reshape(len(t),-1)[rng.choice(len(t),384,False)]
            dz=xx-xx[rng.permutation(len(xx))]
            bw=max(np.sqrt(np.median((dz*dz).sum(1))),1e-3)
            p['rff_w']=rng.normal(0,1/bw,size=(128,256));p['rff_b']=rng.uniform(0,2*np.pi,256)
        for scale in configs:
            p['width_scale']=np.array(scale)
            if a.arm=='frozen':
                H=hidden(t,p,law)[0];D=hidden(v,p,law)[0]
            else:
                H=raw_features(t,a.arm,p);D=raw_features(v,a.arm,p)
            for reg in (.001,.03,.3):
                p['w3']=ridge(H,tY,reg);consider(p,{'penalty':reg,'bandwidth_scale':scale,'hidden_updates':[0,0]},D@p['w3'])
    elif a.arm=='forward':
        # Charge data-dependent target extraction, covariance ranking and full forward probes.
        calib=np.concatenate([rng.choice(np.flatnonzero(y==j),min(48,int((y==j).sum())),False) for j in range(6)])
        tt=t[calib];ct=tY[calib];cy=y[calib];updates=[0,0];loop=0
        # Common ridge readout on training data gives the zero-hidden-update candidate.
        p['w3']=ridge(hidden(t,p,law)[0],tY,.03);consider(p,{'round':0,'hidden_updates':updates.copy()})
        while elapsed()<max(RUNGS):
            for layer in range(2):
                if elapsed()>=max(RUNGS):break
                key='w1' if layer==0 else 'w2'
                inputs=tt if layer==0 else hidden(tt,p,law)[1]
                dirs=ortho_keys(inputs,cy)
                basis=[dirs[:,loop%min(4,dirs.shape[1])],dirs[:,(loop+1)%min(4,dirs.shape[1])],rng.standard_normal(dirs.shape[0])]
                basis[-1]/=np.linalg.norm(basis[-1]);outputs=[(2*loop+j)%WIDTH for j in range(4)]
                init=predict(tt,p,law);columns=[];directions=[];w=p[key].copy()
                for d in basis:
                    for j in outputs:
                        if elapsed()>=max(RUNGS):break
                        dW=np.zeros_like(w);dW[:,j]=d
                        p[key]=w+.015*dW;z1=predict(tt,p,law)
                        p[key]=w-.015*dW;z0=predict(tt,p,law)
                        directions.append(dW);columns.append(((z1-z0)/.03).ravel())
                    if elapsed()>=max(RUNGS):break
                p[key]=w
                if len(columns)!=12 or elapsed()>=max(RUNGS):break
                J=np.stack(columns,axis=1);G=J.T@J/len(J)
                C=np.linalg.solve(G+np.eye(len(G))*(.03*np.trace(G)/len(G)+1e-8),J.T@(ct-init).ravel()/len(J))
                delta=np.einsum('i,ijk->jk',C,np.stack(directions));delta*=min(1.,1.5/max(np.linalg.norm(delta),1e-12))
                best_loss=float(np.mean((init-ct)**2));best_w=w
                for rate in (.25,.5,1.):
                    p[key]=w+rate*delta;loss=float(np.mean((predict(tt,p,law)-ct)**2))
                    if loss<best_loss:best_loss=loss;best_w=p[key]
                p[key]=best_w;updates[layer]+=int(np.any(w!=best_w))
            if elapsed()>=max(RUNGS):break
            p['w3']=ridge(hidden(t,p,law)[0],tY,.03);loop+=1
            consider(p,{'round':loop,'hidden_updates':updates.copy()})
    else:
        states=[]
        for lr in (.001,.01):
            q=clone(p0)
            if a.arm=='hybrid_bp':q['w3']=ridge(hidden(t,q,law)[0],tY,.03)
            states.append([lr,q,[(np.zeros_like(q[k]),np.zeros_like(q[k])) for k in ('w1','w2','w3')]])
        for lr,q,_ in states:consider(q,{'lr':lr,'step':0,'hidden_updates':[0,0]})
        step=0
        while elapsed()<max(RUNGS):
            step+=1;idx=rng.choice(len(t),64,False)
            for lr,q,st in states:
                if elapsed()>=max(RUNGS):break
                grads=gradient(t[idx],tY[idx],q,law)
                for j,key in enumerate(('w1','w2','w3')):
                    if key=='w3' and a.arm=='hybrid_bp':continue
                    m,ss=st[j];g=grads[j]
                    m*=.9;m+=.1*g;ss*=.999;ss+=.001*g*g
                    q[key]-=lr*(m/(1-.9**step))/(np.sqrt(ss/(1-.999**step))+1e-8)
                if step in (1,4,12) or step%24==0:
                    if a.arm=='hybrid_bp':q['w3']=ridge(hidden(t,q,law)[0],tY,.03)
                    consider(q,{'lr':lr,'step':step,'hidden_updates':[step,step]})
    dest=a.out;dest.mkdir(exist_ok=True,parents=True)
    status.update({'fit_wall':time.perf_counter()-wall,'fit_cpu':elapsed(),'history':hist,'selected':{}})
    for r,tracked in saved.items():
        if tracked is None:status['selected'][r]=None;continue
        q,row=tracked
        change=[float(np.linalg.norm(q[k]-p0[k])) for k in ('w1','w2') if k in p0]
        file=dest/f'{a.arm}_{a.seed}_{r}.npz';np.savez_compressed(file,**q)
        status['selected'][r]={**row,'sha256':sha(file),'hidden_deltas':change}
    (dest/f'{a.arm}_{a.seed}.json').write_text(json.dumps(status,indent=1)+'\n')
    print(a.arm,a.seed,len(hist),flush=True)


if __name__=='__main__':
    q=argparse.ArgumentParser()
    for n in ('archive','law','out'):q.add_argument(n,type=Path)
    q.add_argument('arm',choices=ARMS);q.add_argument('seed',type=int,choices=SEEDS)
    fit(q.parse_args())
