"""Pooled free-boundary trajectories. Edit actual W2 with black-box probes or BP/LoRA."""
import argparse, collections
from core import *

def shuffled_labels(y,sp,seed):
    rng=np.random.default_rng(seed+3344);out=y.copy()
    groups=[np.flatnonzero(sp==u) for u in sorted(set(sp))]
    for ids in groups:out[ids]=y[rng.permutation(ids)]
    within=float(np.mean(y!=out));switched=within<.2
    if switched:
        lengths=collections.defaultdict(list)
        for ids in groups:lengths[len(ids)].append(ids)
        for n,sg in lengths.items():
            perm=rng.permutation(len(sg));ordered=[sg[j] for j in perm]
            for i,dst in enumerate(ordered):out[dst]=y[ordered[(i+1)%len(ordered)]]
    assert np.array_equal(np.bincount(y),np.bincount(out))
    return out,{'within_fraction_changed':within,'group_derangement_used':switched,'fitted_fraction_changed':float(np.mean(out!=y))}

def balanced_keys(a):return a.reshape(-1,a.shape[-1]).astype('f8')
def axes(new,old,mode,seed):
    if mode=='random':
        q=np.linalg.qr(np.random.default_rng(seed+811).normal(size=(32*16,32)))[0].T
        return q.reshape(-1,32,16).astype('f4')*4
    x=balanced_keys(new);on,oa=map(balanced_keys,old)
    sn=x.T@x/len(x);so=(on.T@on/len(on)+oa.T@oa/len(oa))/2
    so+=.1*np.trace(so)/len(so)*np.eye(len(so))
    if mode=='protected':e,v=eigh(sn,so);out=v[:,np.argsort(e)[::-1]].T
    else:
        e,v=eigh(sn);out=(v[:,np.argsort(e)[::-1]]/(np.sqrt(np.maximum(e[np.argsort(e)[::-1]],1e-7)))[None,:]).T
    return (out[:16]/np.maximum(np.linalg.norm(out[:16],axis=1,keepdims=True),1e-12)).astype('f4')

def grouped(h,s,L,w,q):
    drive=h@w+s['b2'];eps=.06;head=s['head'].reshape(T,H,2,OUT)
    grads=[];residual=[];actual_recompose=[]
    for k,vec in enumerate(q):
        if vec.ndim==1:
            dv=(h@vec)[...,None]
            plus=upper(drive+eps*dv,L);minus=upper(drive-eps*dv,L)
            # No coupling between different receivers. Separate only after full time propagation.
            g=np.einsum('ntjh,tjhc->ncj',(plus-minus)/(2*eps),head,optimize=True)
            if k==0:
                m=np.broadcast_to(vec[:,None],w.shape)
                chk=(logits(h[:4],s,L,w+eps*m)-logits(h[:4],s,L,w-eps*m))/(2*eps)
                actual_recompose.append(float(np.abs(g[:4].sum(2)-chk).max()))
        else:
            g=((logits(h,s,L,w+eps*vec)-logits(h,s,L,w-eps*vec))/(2*eps))[...,None]
        grads.append(g)
    return np.concatenate(grads,axis=-1),actual_recompose

def proposal(new,olds,y,parent_z,state,w,L,Q,mode):
    jnew,er=grouped(new,state,L,w,Q); jold=[];checks=er.copy()
    for h in olds:
        g,e=grouped(h,state,L,w,Q);jold.append(g);checks+=e
    current=logits(new,state,L,w);p=softmax(current.astype('f8'),axis=1);target=np.eye(10)[y]-p
    js=[]
    for J in jold:
        J=J.astype('f8');J-=J.mean(1,keepdims=True);js.append(J)
    J=jnew.astype('f8');J-=np.einsum('nc,nck->nk',p,J)[:,None]
    newF=(J*np.sqrt(p/len(p))[...,None]).reshape(-1,J.shape[-1]);Hn=newF.T@newF;g=(J*target[...,None]).sum((0,1))/len(J)
    Ho=np.zeros_like(Hn);oldg=np.zeros_like(g)
    for J,h,teacher in zip(js,olds,parent_z):
        mat=J.reshape(-1,J.shape[-1]);Ho+=mat.T@mat/(len(mat)*2.)
        delta=teacher-logits(h,state,L,w);delta-=delta.mean(1,keepdims=True)
        oldg+=(J*delta[...,None]).sum((0,1))/(len(mat)*2.)
    width=1 if mode=='random' else H
    for count in ((32,) if mode=='random' else (4,8,16)):
        k=count*width
        for protect in (.5,2.,8.):
            G=Hn[:k,:k]+protect*Ho[:k,:k]
            G.flat[::k+1]+=.10*np.trace(G)/len(G)+1e-5
            from scipy.linalg import solve
            sol=solve(G,g[:k]+protect*oldg[:k],assume_a='pos',check_finite=False)
            dw=np.einsum('k,kij->ij',sol,Q[:count]) if mode=='random' else Q[:count].T@sol.reshape(count,H)
            dw/=max(1.,np.linalg.norm(dw)/2.)
            for scale in (.5,1.):
                yield w+scale*dw.astype('f4'),dict(k=count,protect=protect,fraction=scale,probe_recomposition_error=max(checks,default=0.))

def bp_updates(cache,tri,state,L,seed,arm):
    import torch
    import torch.nn.functional as FF
    from parent import torch_upper
    l=torch.from_numpy(L);head=torch.from_numpy(state['head']);bias=torch.from_numpy(state['bias']);W=torch.from_numpy(state['w2']);b=torch.from_numpy(state['b2'])
    h={k:torch.from_numpy(cache[k]) for k in cache};y=torch.from_numpy(tri['gsc'][1]);fwd=lambda x,d:torch_upper(x,W+d,b,l).flatten(1)@head+bias
    with torch.no_grad(): old={k:fwd(h[k],0.) for k in ('fsdd','arabic')}
    for protect in (.5,2.,8.):
        for lr in (.001,.005,.02):
            rng=np.random.default_rng(seed+831);torch.manual_seed(seed+11)
            if arm=='LoRA':
                a=torch.nn.Parameter(torch.randn(32,4)/np.sqrt(32));v=torch.nn.Parameter(torch.zeros(4,16));params=(a,v)
                def delta():return a@v
            else:
                dd=torch.nn.Parameter(torch.zeros_like(W));params=(dd,)
                def delta():return dd
            opt=torch.optim.Adam(params,lr=lr)
            for step in range(1,193):
                ids=rng.integers(len(y),size=48);d=delta();z=fwd(h['gsc'][ids],d);loss=FF.cross_entropy(z,y[ids])
                for name in ('fsdd','arabic'):
                    indices=rng.integers(len(h[name]),size=24);zo=fwd(h[name][indices],d);diff=zo-old[name][indices];diff=diff-diff.mean(dim=1,keepdim=True)
                    loss+=.5*protect*diff.square().mean()
                opt.zero_grad();loss.backward();opt.step()
                if step in (12,48,96,192):yield (W+delta()).detach().numpy().copy(),dict(lr=lr,step=step,protect=protect)

def run(out,seed,arm):
    par=out/'parent.npz';s=dict(np.load(par));tr=splits('train');dv=splits('dev');L=table();cache={k:lower(x[0],s,L) for k,x in tr.items()};dev={k:lower(x[0],s,L) for k,x in dv.items()}
    def stats(w):return {k:summarize(logits(dev[k],s,L,w),dv[k]) for k in dv}
    W=s['w2'];base=stats(W);modes=['point','confidence'];best={k:base for k in modes};bestw={k:W.copy() for k in modes};front=[];choice={k:'KEEP' for k in modes}
    def consider(w,identity):
        met=stats(w);pt,co,bounds=retention(met,base);record={'candidate':identity,'dev':small(met),'retained_point':pt,'retained_confidence':co,'retention_lower_90':bounds,'elapsed_s':use()['wall_s']};front.append(record)
        for name,viable in zip(modes,(pt,co)):
            if viable and selectkey(met)>selectkey(best[name]):best[name]=met;bestw[name]=w.copy();choice[name]=identity
    consider(W,'KEEP');count=0;shuf={};probecount=0
    if arm in ('LoRA','Adam'):
        for w,id in bp_updates(cache,tr,s,L,seed,arm):consider(w,id);count+=1
    elif arm!='KEEP':
        new=cache['gsc'];olds=[cache[k] for k in ('fsdd','arabic')];parent_z=[logits(h,s,L,W) for h in olds];y=tr['gsc'][1]
        if arm=='shuffled':y,shuf=shuffled_labels(y,tr['gsc'][2],seed)
        mode={'shuffled':'protected','gen':'protected','white':'white','random':'random'}[arm]
        Q=axes(new,olds,mode,seed);cur=W.copy()
        for epoch in (1,2):
            probecount+=2*len(Q)*sum(len(h) for h in [new,*olds])
            for w,id in proposal(new,olds,y,parent_z,s,cur,L,Q,mode):
                consider(w,{'refresh':epoch,**id});count+=1
            cur=bestw['point'].copy()
    d=out/arm;d.mkdir(exist_ok=True)
    ck={}
    for k in modes:
        p=d/(k+'.npz');np.savez(p,w2=bestw[k]);ck[k]=sha(p)
    names=['fsdd','arabic','gsc'];no={k:int(np.count_nonzero(bestw[k]!=W)) for k in modes}
    info=dict(seed=seed,arm=arm,parent_sha256=sha(par),candidates=count+1,selected=choice,front=front,dev={k:small(v) for k,v in best.items()},hidden_weights_changed=no,checkpoints=ck,shuffle=shuf,
        grouped_probe_upper_forward_examples=probecount,baseline_train_forward_examples=(9*192*96 if arm in ('Adam','LoRA') else 0),baseline_train_backward_examples=(9*192*96 if arm in ('Adam','LoRA') else 0),train_rows={k:len(tr[k][1]) for k in names},dev_rows={k:len(dv[k][1]) for k in names},test_opened=False,**use())
    dump(d/'fit.json',info);print(seed,arm,choice,info['wall_s'],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--seed',type=int,required=True);ap.add_argument('--arm',required=True,choices=['KEEP','random','gen','white','shuffled','Adam','LoRA']);arg=ap.parse_args();run(arg.out,arg.seed,arg.arm)
