"""Stream one recording at a time; fit the identical panel on disk-backed feature columns."""
import argparse
import gc
import json
from pathlib import Path
import time
import numpy as np
from scipy.special import expit
import estimate as e
from stream_fit import newton,eqcheck,checkpoint

class Columns:
    def __init__(self,bank,keys):
        self.bank=bank;self.keys=keys;self.shape=(len(bank),len(keys))
    def __getitem__(self,idx):return self.bank[idx][:,self.keys]

def sweep(data,cache,sid,tag,physical):
    f=cache/f'{sid}-{tag}.npz';r=json.loads((cache/f'{sid}.json').read_text());raw=data/f'{sid}.npz'
    assert r['source_sha256']==e.digest(raw) and r['sweeps'][tag]['sha256']==e.digest(f)
    with np.load(f) as comp,np.load(raw) as src:
        a=comp['anchors'];y=src['y'+tag];s=np.r_[0,np.cumsum(y,dtype=int)]
        d={'anchors':a,'binary':y[a].astype(np.float32),'base_full':comp['base'],'future':np.stack([s[a+h]-s[a]>0 for h in e.HORIZONS],1).astype(np.float32),
           'free':comp['free'][a]}
        if physical:
            d['phys']={law+str(i):comp[law+str(i)][a] for law in ('fixed','tangent','literal') for i in range(3)}
        return d

def alloc(mount,name,shape,dtype=np.float32):
    return np.lib.format.open_memmap(mount/(name+'.npy'),mode='w+',dtype=dtype,shape=shape)
def reload(mount,name):return np.load(mount/(name+'.npy'),mmap_mode='r')
def stages(data,cache,ids,root,pre=None):
    src=[(sid,typ+'_'+rep) for sid in ids for typ in ('1','2') for rep in ('0','1')]
    size=[]
    for sid,tag in src:
        with np.load(cache/f'{sid}-{tag}.npz') as z:size.append(len(z['anchors']))
    tot=sum(size);h=len(e.IDX_SUP);avg=tot/len(size);root.mkdir(parents=True,exist_ok=True)
    bnames=['h','haz0','haz1','haz2','free0','free1','free2']+[law+str(i) for law in ('fixed','tangent','literal') for i in range(3)]
    if pre is None:
        bb=alloc(root,'base',(tot,18));ff=alloc(root,'free',(tot*h,16));yb=alloc(root,'yb',(tot,),float);wb=alloc(root,'wb',(tot,),float)
    else:bank=alloc(root,'bank',(tot*h,len(bnames)))
    yf=alloc(root,'yf',(tot*h,),float);wf=alloc(root,'wf',(tot*h,),float);idx=0
    for (sid,tag),n in zip(src,size):
        r=sweep(data,cache,sid,tag,pre is not None);s=slice(idx,idx+n);hs=slice(idx*h,(idx+n)*h)
        if pre is None:
            bb[s]=r['base_full'][r['anchors']];ff[hs]=e.free_design(r)[:,e.IDX_SUP].reshape(-1,16)
            yb[s]=r['binary'];wb[s]=avg/n
        else:
            e.add_base_features([r],pre)
            vals=[e.hfeature(r)]+[r['hazard'][str(p)] for p in e.PENALTIES]+[r['learned_free'][str(p)] for p in e.PENALTIES]
            vals += [e.safest(r['phys'][law+str(i)]) for law in ('fixed','tangent','literal') for i in range(3)]
            for k,v in enumerate(vals):bank[hs,k]=v[:,e.IDX_SUP].ravel()
        yf[hs]=r['future'][:,e.IDX_SUP].ravel();wf[hs]=avg/n;idx+=n
    return src,size,bnames

def dev_metrics(bank,truth,sol,src,size):
    sacs={};i=0;h=len(e.IDX_SUP)
    for (sid,tag),n in zip(src,size):
        s=slice(i,i+n*h);z=bank[s];w=np.array(sol['w']);p=expit((z-sol['mean'])/sol['std']@w[1:]+w[0]).astype(np.float32)
        ll,b=e.score(p,truth[s]);sacs.setdefault(sid,[]).append([ll.mean(),b.mean()]);i+=n*h
    return np.mean([np.mean(x,axis=0) for x in sacs.values()],axis=0).tolist()

def train(data,cache,out):
    tic=time.monotonic();out.mkdir(parents=True,exist_ok=True);ck=out/'candidate';ck.mkdir(exist_ok=True)
    err=eqcheck();ids=json.loads((data/'roster.json').read_text())['cells'];assert len(ids)==24
    a=out/'pre_inputs';t=out/'train_inputs';v=out/'dev_inputs';pre={}
    pre_file=ck/'pre.json'
    if pre_file.exists():pre=json.loads(pre_file.read_text())
    else:
        stages(data,cache,ids[:12],a)
        for pen in e.PENALTIES:
            pair={}
            for name,xkey,y,w in [('hazard','base','yb','wb'),('free','free','yf','wf')]:
                path=ck/f'pre_{name}_{pen}.json'
                if not path.exists():
                    fit=newton(reload(a,xkey),reload(a,y),pen,reload(a,w));checkpoint(path,fit)
                pair[name]=json.loads(path.read_text());print('pre',pen,name,flush=True)
            pre[str(pen)]=pair
        checkpoint(pre_file,pre)
    _,_,names=stages(data,cache,ids[:12],t,pre);source,ns,_=stages(data,cache,ids[12:16],v,pre);gc.collect()
    trainbank=reload(t,'bank');truth=reload(t,'yf');weights=reload(t,'wf');valid=reload(v,'bank');vy=reload(v,'yf')
    selected={};scores={}
    for name in ('hazard','hazard+free','fixed','tangent','literal','hazard+fixed','hazard+tangent','hazard+literal'):
        choices=[]
        for ip,pen in enumerate(e.PENALTIES):
            for si in ([0] if name in ('hazard','hazard+free') else range(3)):
                path=ck/f'{name}_{pen}_{si}.json'
                if path.exists():choice=json.loads(path.read_text())
                else:
                    tic1=time.monotonic();cols=['h']
                    if name.startswith('hazard'):cols.append('haz'+str(ip))
                    if name=='hazard+free':cols.append('free'+str(ip))
                    if name not in ('hazard','hazard+free'):cols.append(name.split('+')[-1]+str(si))
                    ix=[names.index(k) for k in cols]
                    sol=newton(Columns(trainbank,ix),truth,pen,weights)
                    ll,br=dev_metrics(Columns(valid,ix),vy,sol,source,ns)
                    choice=dict(calibrator=sol,penalty=pen,scale_index=si,dev_nll=ll,dev_brier=br,wall_seconds=time.monotonic()-tic1)
                    checkpoint(path,choice)
                choices.append(choice)
        selected[name]=min(choices,key=lambda row:row['dev_nll'])
        scores[name]=[{k:v for k,v in row.items() if k!='calibrator'} for row in choices];print(name,selected[name]['dev_nll'],flush=True)
    checkpoint(out/'SEAL.json',dict(ids=ids,roster_sha256=e.digest(data/'roster.json'),source_sha256={str(i):e.digest(data/f'{i}.npz') for i in ids},
            features_sha256={str(i):e.digest(cache/f'{i}.json') for i in ids},pre=pre,selected=selected,all_dev=scores,
            total_fit_wall_s=time.monotonic()-tic,chunk_equivalence_max_logit_error=err))
if __name__=='__main__':
    cli=argparse.ArgumentParser()
    for k in ('data','cache','out'):cli.add_argument('--'+k,type=Path,required=True)
    args=cli.parse_args();train(args.data,args.cache,args.out)
