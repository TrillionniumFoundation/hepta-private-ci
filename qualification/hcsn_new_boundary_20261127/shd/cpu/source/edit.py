"""Hidden-only German updates with a frozen English parent and explicit KEEP candidate."""
import argparse
from pathlib import Path
import numpy as np
from scipy.special import softmax
from common import numpy_gate,pool,gate_features,indices,sha,record,usage,score_batches


def scored(h,w,b,head,head_bias,table):
    return pool(gate_features(h,w,b,table))@head+head_bias


def data(root,parent,cap=12):
    x=(np.load(root/'x_train.npy')-parent['center'])/parent['scale']
    y=np.load(root/'labels_train.npy');people=np.load(root/'people_train.npy');dev=np.load(root/'devmask.npy')
    inputs={}
    for lang,mask in [('old',y<10),('new',y>=10)]:
        tr=np.flatnonzero(mask & ~dev)
        ids=np.concatenate([np.flatnonzero(mask & ~dev & (people==p)&(y==label))[:cap]
                            for p in np.unique(people[tr]) for label in np.unique(y[tr])])
        for key,which in [('tr',np.sort(ids)),('dv',np.flatnonzero(mask&dev))]:
            inputs[lang+key]=(x[which],y[which]%10,people[which],which)
    return inputs


def direct(cache,state,tbl,ynew,seed):
    rng=np.random.default_rng(seed+7183)
    w=state['w2'];b=state['b2'];head=state['head'];bias=state['head_bias']
    q=np.linalg.qr(rng.normal(size=(w.size,32)))[0].T
    q=(q.reshape(32,*w.shape)*np.sqrt(w.shape[1])).astype('f4')
    def run(h,w):return scored(h,w,b,head,bias,tbl)
    p=softmax(run(cache['newtr'],w).astype('f8'),axis=-1)
    residual=np.eye(p.shape[1])[ynew]-p
    jn=[];jo=[]
    for u in q:
        plus=w+.10*u;minus=w-.10*u
        for ls,name in [(jn,'newtr'),(jo,'oldtr')]:
            ls.append(((run(cache[name],plus)-run(cache[name],minus))/.20).astype('f8'))
    # Each response tensor has axes sample, class, direction.
    jn=np.stack(jn,axis=-1);jo=np.stack(jo,axis=-1)
    for k in (12,32):
        j=jn[:,:,:k];jold=jo[:,:,:k]
        avg=(p[...,None]*j).sum(axis=1,keepdims=True)
        centered=j-avg
        hess=np.einsum('nck,ncl->kl',centered*(p/len(p))[...,None],centered)
        hess+=np.einsum('nck,ncl->kl',jold,jold)/(jold.shape[0]*jold.shape[1])
        g=np.einsum('nck,nc->k',j,residual)/len(j)
        hess+=np.eye(k)*(.01*np.trace(hess)/k+1e-6)
        sol=np.linalg.solve(hess,g)
        sol/=max(1.,np.linalg.norm(sol))
        step=np.einsum('k,kij->ij',sol,q[:k]).astype('f4')
        for scale in (.25,.5,1.):
            yield {'rank':k,'scale':scale,'coordinate_norm':float(np.linalg.norm(sol))},w+scale*step


def late_bp(cache,state,tbl,ynew,seed,kind):
    import torch
    from torch.nn import functional as F
    from bp import Table
    from adam import Adam
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    gate=Table(tbl['lut'])
    hnew=torch.from_numpy(cache['newtr']);hold=torch.from_numpy(cache['oldtr'])
    original=torch.from_numpy(state['w2']);b=torch.from_numpy(state['b2'])
    read=torch.from_numpy(state['head']);bias=torch.from_numpy(state['head_bias'])
    labels=torch.from_numpy(ynew)
    def forward(h,delta):
        z=gate(h@(original+delta)+b)
        return z.reshape(len(z),6,2,-1).mean(2).flatten(1)@read+bias
    with torch.no_grad():targetold=forward(hold,0)
    for lr in (.001,.005,.02):
        torch.manual_seed(seed+555)
        if kind=='lora':
            a=torch.nn.Parameter(torch.randn(original.shape[0],4)/np.sqrt(original.shape[0]))
            bfac=torch.nn.Parameter(torch.zeros(4,original.shape[1]))
            params=(a,bfac)
            def delta():return a@bfac
        else:
            dd=torch.nn.Parameter(torch.zeros_like(original));params=(dd,)
            def delta():return dd
        opt=Adam(params,lr=lr)
        rng=np.random.default_rng(seed+93877)
        for i in range(1,97):
            newrows=rng.integers(0,len(hnew),size=96);oldrows=rng.integers(0,len(hold),size=96)
            upd=delta();ln=forward(hnew[newrows],upd);lo=forward(hold[oldrows],upd)
            loss=F.cross_entropy(ln,labels[newrows])+.5*F.mse_loss(lo,targetold[oldrows]);opt.zero_grad()
            loss.backward();opt.step()
            if i in (12,48,96):
                yield dict(lr=lr,step=i), (original+delta()).detach().cpu().numpy().copy()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--parents',type=Path,required=True);ap.add_argument('--data',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--arm',choices=['keep','direct','shuffle','lora','adam'],required=True)
    ap.add_argument('--seed',type=int,required=True);args=ap.parse_args()
    parentfile=args.parents/f'english-{args.seed}'/'selected.npz'
    with np.load(parentfile) as arr:state=dict(arr)
    tbl=dict(np.load(args.data/'law.npz'))
    data_by_task=data(args.data,state)
    hidden={k:gate_features(v[0],state['w1'],state['b1'],tbl) for k,v in data_by_task.items()}
    tr_y=data_by_task['newtr'][1].copy()
    if args.arm=='shuffle':
        rg=np.random.default_rng(args.seed+71173)
        ppl=data_by_task['newtr'][2]
        for person in np.unique(ppl):
            ix=np.flatnonzero(ppl==person)
            tr_y[ix]=tr_y[rg.permutation(ix)]
    temp=float(state['temperature'])
    def evaluation(w):
        d={}
        for name in ['olddv','newdv']:
            scores=scored(hidden[name],w,state['b2'],state['head'],state['head_bias'],tbl)
            _,y,p,_=data_by_task[name]
            d[name]=indices(scores,y,p,temp)
        return d
    parent_scores=evaluation(state['w2'])
    def selection(v):
        return (v['newdv']['speaker_acc'],-v['newdv']['brier']-v['olddv']['brier'])
    best=parent_scores;chosen={'choice':'keep','norm':0.,'dev':parent_scores,'viable':True}
    history=[chosen];selected_w=state['w2']
    if args.arm in ('direct','shuffle'):gen=direct(hidden,state,tbl,tr_y,args.seed)
    elif args.arm in ('lora','adam'):gen=late_bp(hidden,state,tbl,tr_y,args.seed,args.arm)
    else:gen=iter(())
    for identity,weights in gen:
        metrics=evaluation(weights)
        viable=metrics['olddv']['speaker_acc']>=parent_scores['olddv']['speaker_acc']-.02-1e-12
        item=dict(choice=identity,dev=metrics,norm=float(np.linalg.norm(weights-state['w2'])),viable=viable)
        history.append(item)
        if viable and selection(metrics)>selection(best):
            selected_w=weights.copy();best=metrics;chosen=item
    args.out.mkdir(parents=True,exist_ok=True);dest=args.out/'selected.npz'
    changed=int(np.count_nonzero(selected_w!=state['w2']))
    np.savez_compressed(dest,**{**state,'w2':selected_w})
    receipt=dict(parent=sha(parentfile),checkpoint=sha(dest),arm=args.arm,seed=args.seed,best=chosen,roster=history,
                 n={k:len(z[0]) for k,z in data_by_task.items()},new_train_labels_shuffled=args.arm=='shuffle',
                 hidden_changed=changed,test_label_access=False,**usage())
    record(args.out/'fit.json',receipt);print(args.arm,args.seed,chosen['choice'],flush=True)
if __name__=='__main__':main()
