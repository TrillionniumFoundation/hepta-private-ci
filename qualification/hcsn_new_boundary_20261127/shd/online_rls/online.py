"""Causal real-speaker stream; weight-only recursive writes with measured latent information cost."""
import argparse,hashlib,json,time,sys
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
from scipy.special import softmax
HERE=Path(__file__).resolve().parent;CROSS=HERE.parent/'multilingual';sys.path.insert(0,str(CROSS))
from core import table,lower,upper,logits,interp,feedback,sha,splits,summarize,small,selectkey,dump,use,H,T,OUT
def hashed(s):return hashlib.sha256(s.encode()).hexdigest()
def stream(rows,seed):
    _,y,sp,ids=rows;order=sorted(set(sp),key=lambda s:(hashed('hepta-online-rsv1/'+str(seed)+'/'+s),s));seq=[];ends=[]
    for s in order:
        ix=np.flatnonzero(sp==s);seq+=list(ix[np.argsort(ids[ix])])
        if len(ends)<3 and len(seq)>=(len(ends)+1)*120:ends.append(len(seq))
    ends.append(len(seq));return np.array(seq),ends
def basis(hold,kind,rank):
    S=sum(h.reshape(-1,32).astype('f8').T@h.reshape(-1,32)/h.reshape(-1,32).shape[0] for h in hold)/2
    if kind=='orth':
        e,V=np.linalg.eigh(S);P=V[:,:rank]
    else:P=np.eye(32);e=np.linalg.eigvalsh(S)
    leak=float(np.trace(P.T@S@P)/np.trace(S))
    return S,P,leak
def latent(keys,w,s,L,y):
    # 12 forward trajectories produce dlogits/d(current six drives x 16 receivers).
    drive=keys@w+s['b2'];head=s['head'].reshape(T,16,2,10).astype('f8');eps=.05
    perturb=np.eye(T,dtype='f4')[:,:,None]*eps
    trans=upper(np.concatenate([drive[None]+perturb,drive[None]-perturb]),L)
    deriv=(trans[:T]-trans[T:])/(2*eps)
    J=np.einsum('ptja,tjac->cpj',deriv,head,optimize=True).reshape(10,T*16)
    J-=J.mean(0);state=upper(drive[None],L);z=state.reshape(1,-1)@s['head']+s['bias'];p=softmax(z[0].astype('f8'))
    rhs=np.eye(10)[y]-p;Gram=J@J.T;ridge=.1*max(1.,np.trace(Gram)/10);a=cho_solve(cho_factor(Gram+ridge*np.eye(10),check_finite=False),rhs,check_finite=False)
    target=(J.T@a).reshape(T,16);target/=max(1.,np.linalg.norm(target)/2)
    return target
def gradient(keys,w,s,L,y=None,teacher=None):
    # Exact adjoint of the piecewise-linear table and the six-step feedback recurrence.
    head=s['head'].reshape(T,16,2,10);drive=keys@w+s['b2'];A=[];S=[];prev=0.
    for i in range(T):
        u=drive[i]+prev;q=np.clip((u+12.)*(16384./24.),0,16384.);k=q.astype('i4')
        dx=L[np.minimum(k+1,16384)]-L[k]
        aa=L[k]+(q-k)[...,None]*dx;S.append(dx*(16384./24.)*((u>-12)&(u<12))[:,None]);A.append(aa);prev=feedback(aa)
    aa=np.array(A);z=aa.ravel()@s['head']+s['bias']
    if y is None:
        e=(z-teacher);e=(e-e.mean())/10
    else:
        e=softmax(z.astype('f8'));e[y]-=1.
    response=np.einsum('tjac,c->tja',head,e);later=np.zeros(16);dv=np.zeros((T,16))
    for t in range(T-1,-1,-1):
        da=response[t]+later[:,None]*.4*(1-np.tanh(aa[t])**2)
        later=(da*S[t]).sum(1);dv[t]=later
    return keys.T@dv
def adam(v,mom,var,grad,t,lr):
    mom*=.9;mom+=.1*grad;var*=.999;var+=.001*grad**2
    v-=lr*(mom/(1-.9**t))/(np.sqrt(var/(1-.999**t))+1e-8)
def path(arm,s,h,tr,L,seed,order,ends,cfg,all_dev,old_tensor):
    start=time.perf_counter();rng=np.random.default_rng(seed+311)
    keys=h['gsc'];y=tr['gsc'][1].copy();old_ix={k:(np.arange(1,len(order)+1)*31+seed)%len(h[k]) for k in ('fsdd','arabic')};hold=[h[k][old_ix[k]] for k in ('fsdd','arabic')];W0=s['w2'].astype('f8')
    if arm=='shuffled':
        yy=y.copy()
        for g in sorted(set(tr['gsc'][2])):
            i=np.flatnonzero(tr['gsc'][2]==g);yy[i]=y[rng.permutation(i)]
        if np.mean(yy!=y)<.2:
            groups={}
            for k in sorted(set(tr['gsc'][2])):
                ii=np.flatnonzero(tr['gsc'][2]==k);groups.setdefault(len(ii),[]).append(ii)
            for ls in groups.values():
                ll=[ls[i] for i in rng.permutation(len(ls))]
                for j,ix in enumerate(ll):yy[ix]=y[ll[(j+1)%len(ll)]]
        y=yy
    S,P,leak=basis(hold,'orth' if arm=='orth' else 'full',cfg.get('rank',32));E=P.shape[1];reg=cfg.get('anchor',0.);tar=cfg.get('trust',1.)
    I=np.eye(E);A0=60*cfg.get('tau',.1)*max(1e-6,np.trace(S)/32)*I+120*reg*(P.T@S@P)+1e-6*I
    G=cho_solve(cho_factor(A0),I);Q=np.zeros((E,16));AA=A0.copy();BB=np.zeros_like(Q)
    bp=arm in ('Adam','LoRA');D=np.zeros_like(W0);left=rng.normal(size=(32,4))*.15;right=np.zeros((4,16))
    params=[D] if arm=='Adam' else [left,right];M=[np.zeros_like(p) for p in params];V=[np.zeros_like(p) for p in params];saved=[];wc=W0.copy()
    for j,idx in enumerate(order,1):
        key=keys[idx].astype('f8')
        if bp:
            g=gradient(key,wc,s,L,y=y[idx])
            for n,nm in enumerate(('fsdd','arabic')):
                ii=(j*31+seed)%len(h[nm]);g+=reg*.5*gradient(h[nm][ii],wc,s,L,teacher=old_tensor[nm][ii])
            gg=[g] if arm=='Adam' else [g@right.T,left.T@g]
            for p,m,v,grad in zip(params,M,V,gg):adam(p,m,v,grad,j,cfg['lr'])
            wc=W0+(D if arm=='Adam' else left@right)
        else:
            d=tar*latent(key,wc,s,L,int(y[idx]));K=key@P;value=K@Q+d
            if arm=='feedback':
                Q+=cfg['rate']*(K.T@d-reg*.04*(P.T@S@P)@Q)/(1.+np.sum(K*K))
            else:
                # Six-row Woodbury gain; targets are frozen as they arrive.
                F=G@K.T;B=I[:T,:T]+K@F;fac=cho_factor(B,check_finite=False)
                gain=cho_solve(fac,F.T,check_finite=False).T;Q+=gain@(value-K@Q);G-=gain@F.T;G=(G+G.T)*.5
                AA+=K.T@K;BB+=K.T@value
            wc=W0+P@Q
        if j in ends:
            dev=all_dev(wc.astype('f4'));early=order[:ends[0]];holdz=logits(keys[early],s,L,wc.astype('f4'));em=summarize(holdz,tuple(v[early] for v in tr['gsc']))
            saved.append({'n':j,'new_previously_seen_first_cohort':em['macro'],'dev':small(dev),'elapsed':time.perf_counter()-start})
    err=0. if bp or arm=='feedback' else float(abs(cho_solve(cho_factor(AA),BB)-Q).max())
    return wc.astype('f4'),saved,{'relative_old_key_energy':leak,'orthogonality':float(abs(P.T@P-I).max()),'online_vs_batch_coordinate_max':err,'new_recordings':len(order),'old_anchor_record_exposures':2*len(order),'old_gradient_exposures':(2*len(order) if bp else 0),'new_backward_examples':len(order) if bp else 0,'forward_latent_trajectories':0 if bp else 13*len(order),'working_rls_matrix_dim':0 if bp or arm=='feedback' else E,'stream_s':time.perf_counter()-start}
def grid(arm):
    if arm in ('Adam','LoRA'):return [dict(lr=lr,anchor=r) for lr in (.001,.005,.02) for r in (.5,2.,8.)]
    if arm=='feedback':return [dict(rate=g,trust=t,anchor=a) for g in (.15,.75) for t in (.25,1.) for a in (.5,2.,8.)]
    return [dict(tau=t,trust=d,anchor=r,rank=k) for t in (.1,1.) for d in (.25,1.) for r in ((0.,) if arm=='noanchor' else (.5,2.,8.)) for k in ((8,16) if arm=='orth' else (32,))]
def main(seed,arm):
    start=time.perf_counter();s=dict(np.load(CROSS/'fits'/str(seed)/'parent.npz'));L=table();tr=splits('train');dv=splits('dev');h={k:lower(v[0],s,L) for k,v in tr.items()};hv={k:lower(v[0],s,L) for k,v in dv.items()};ot={k:logits(h[k],s,L) for k in ('arabic','fsdd')};order,ends=stream(tr['gsc'],seed)
    def evaluate(w):return {k:summarize(logits(v,s,L,w),dv[k]) for k,v in hv.items()}
    base=evaluate(s['w2']);best=base;chosen='KEEP';ww=s['w2'].copy();front=[];bestst=[]
    for cfg in ([] if arm=='KEEP' else grid(arm)):
        w,history,stats=path(arm,s,h,tr,L,seed,order,ends,cfg,evaluate,ot);m=evaluate(w);ok=all(m[k]['macro']>=base[k]['macro']-.0200001 for k in ('fsdd','arabic'))
        front.append(dict(cfg=cfg,retained=ok,stages=history,terminal=small(m),audited=stats,elapsed_s=time.perf_counter()-start))
        if ok and selectkey(m)>selectkey(best):best=m;chosen=cfg;ww=w.copy();bestst=history
    out=HERE/'fits'/str(seed)/arm;out.mkdir(parents=True,exist_ok=True);np.save(out/'W2.npy',ww)
    dump(out/'fit.json',dict(seed=seed,arm=arm,selected=chosen,baseline=small(base),terminal=small(best),history=bestst,order_sha=hashlib.sha256(order.tobytes()).hexdigest(),cohort_ends=ends,front=front,checkpoint=sha(out/'W2.npy'),elapsed_s=time.perf_counter()-start,**use()))
    print(seed,arm,chosen,round(time.perf_counter()-start,2),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('seed',type=int);p.add_argument('arm');a=p.parse_args();main(a.seed,a.arm)
