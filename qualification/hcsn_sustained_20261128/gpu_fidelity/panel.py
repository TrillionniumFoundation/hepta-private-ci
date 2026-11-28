"""Run the four original encoders on the largest byte-identical completed tier."""
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from encoder import AVText, pair_loss
from reference import stages


def clock():torch.cuda.synchronize();return time.perf_counter()


def run(root,ingress):
    tiers=[j for j,v in enumerate(ingress.get('tiers',())) if v['verified']]
    if not tiers:return {'qualified_tier':None,'models':{}},{}
    t=max(tiers)
    with np.load(root/'meta.npz',allow_pickle=False) as a:
        ix=stages(a['split'])[t];ids=a['ids'][ix];tokens=torch.from_numpy(a['tokens']).long().cuda();y=torch.from_numpy(a['labels'][ix]).long().cuda();fold=a['split'][ix]
    v=[];a=[]
    for name in ids:
        with np.load(root/'data/clips'/(str(name)+'.npz'),allow_pickle=False) as d:v.append(d['video']);a.append(d['audio'])
    tr,dev,test=[np.flatnonzero(fold==j) for j in range(3)]
    v=torch.from_numpy(np.stack(v)).cuda();a=np.stack(a)
    mu=a[tr].mean((0,1),dtype='float64').astype('float32');sd=a[tr].std((0,1),dtype='float64').clip(.01).astype('float32');a=torch.from_numpy((a-mu)/sd).cuda()
    scores={'ids':ids[test],'test_y':y[test].cpu().numpy(),'development_ids':ids[dev]}
    result={'qualified_tier':len(ix),'split':list(map(len,(tr,dev,test))),'models':{}}
    for arm in ('literal','smooth','lif','sdpa'):
        net=AVText(arm,96,137,int(tokens.max())+1,root/'law4.npz').cuda();opt=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=.01,foreach=False)
        rng=np.random.default_rng(137+7369);start=clock();s=[]
        for _ in range(12):
            rows=rng.choice(tr,len(tr) if len(tr)<24 else 24,replace=False);opt.zero_grad(set_to_none=True)
            zv,zt=net(v[rows],a[rows],tokens[y[rows]]);loss=pair_loss(zv,zt,y[rows]);loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True);opt.step();s.append(float(loss))
        elapsed=clock()-start
        report={'train_steps':12,'train_examples':12*min(len(tr),24),'train_s':elapsed,'train_last_loss':s[-1],'params':sum(p.numel() for p in net.parameters())}
        with torch.no_grad():
            net.eval();txt=net.encode(net.text(tokens))
            for tag,rows in [('development',dev),('cold',test)]:
                zz=[]
                for k in range(0,len(rows),64):
                    rr=rows[k:k+64];zz.append(12*net.encode(net.front(v[rr],a[rr]))@txt.T)
                z=torch.cat(zz);assert z.shape==(len(rows),72) and torch.isfinite(z).all()
                scores[arm+'_'+tag]=z.cpu().numpy();report[tag]={'nll':float(F.cross_entropy(z.double(),y[rows])),'top1':float((z.argmax(1)==y[rows]).double().mean())}
        result['models'][arm]=report
    return result,scores
