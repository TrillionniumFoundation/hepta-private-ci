"""Full actor-disjoint CREMA-D retrieval using predeclared aggressively quantized inputs."""
import hashlib
import io
import json
import lzma
from pathlib import Path
import time
import zipfile

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from hcsn_temporal import Phys, Attention, Law

SEEDS=(137,311,557)
ARMS=('literal','smooth','lif','sdpa')
ENDPOINTS=('updates78','time12')
DEVICE='cuda'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_time():
    torch.cuda.synchronize()
    return time.perf_counter()


class StudyData:
    def __init__(self,root):
        meta=json.loads((root/'data_identity.json').read_text())
        assert digest(root/'all.xz')==meta['sha']
        with np.load(io.BytesIO(lzma.decompress((root/'all.xz').read_bytes())),allow_pickle=False) as a:
            q={k:a[k] for k in a}
        for k,a in q.items():assert hashlib.sha256(a.tobytes()).hexdigest()==meta['arrays'][k]['sha']
        p=q['nibbles']
        codes=np.stack((p>>4,p&15),axis=-1).reshape(len(p),4,8)
        self.splits=[np.flatnonzero(q['split']==i) for i in range(3)]
        train=self.splits[0]
        feat=q['levels'][np.arange(8)[None,None,:],codes]
        mu=feat[train].mean((0,1),dtype='float64').astype('float32')
        sd=feat[train].std((0,1),dtype='float64').clip(.001).astype('float32')
        feat=(feat-mu)/sd
        self.x=torch.from_numpy(feat).to(DEVICE);self.y=torch.from_numpy(q['labels']).long().to(DEVICE)
        self.tokens=torch.from_numpy(q['tokens']).long().to(DEVICE)
        self.ids=q['ids'];self.actor=np.array([s.split('_')[0] for s in self.ids])
        actors=[set(self.actor[idx]) for idx in self.splits]
        assert sum(map(len,actors))==len(set.union(*actors))
        assert self.tokens.shape==(72,12) and list(map(len,self.splits))==[4984,1147,1311]
        self.meta=meta
    def get(self,rows,av=None):
        if av is None:return self.x[rows]
        v,a=av
        return torch.cat((self.x[v,: ,:4],self.x[a,:,4:]),dim=-1)


class Encoder(nn.Module):
    def __init__(self,arm,seed,words,law):
        super().__init__()
        w=32
        torch.manual_seed(seed)
        self.face=nn.Linear(4,w);self.sound=nn.Linear(4,w)
        self.words=nn.Embedding(words,w,padding_idx=0)
        self.pos=nn.Parameter(torch.randn(4,w)*.015);self.type_code=nn.Parameter(torch.randn(2,w)*.015)
        self.n1=nn.ModuleList(nn.LayerNorm(w) for _ in range(2));self.n2=nn.ModuleList(nn.LayerNorm(w) for _ in range(2))
        self.ff=nn.ModuleList(nn.Sequential(nn.Linear(w,4*w),nn.GELU(),nn.Linear(4*w,w)) for _ in range(2))
        self.out=nn.Sequential(nn.LayerNorm(w),nn.Linear(w,32,bias=False))
        torch.manual_seed(seed+21019)
        self.mix=nn.ModuleList(Attention(w) if arm=='sdpa' else Phys(arm,w,4,j>0) for j in range(2))
        self.law=Law(law)
    def av(self,x):
        return self.face(x[:,:,:4])+self.sound(x[:,:,4:])+self.pos+self.type_code[0]
    def text(self,t):
        return self.words(t).reshape(t.shape[0],4,3,32).mean(2)+self.pos+self.type_code[1]
    def encode(self,h):
        mark=None
        for m,n1,n2,ff in zip(self.mix,self.n1,self.n2,self.ff):
            y,mark,_=m(n1(h),mark,self.law)
            h=h+y;h=h+ff(n2(h))
        return F.normalize(self.out(h[:,-1]),dim=-1)
    def logits(self,x,t):
        h=self.encode(torch.cat((self.av(x),self.text(t))))
        return 12.*(h[:len(x)]@h[len(x):].T)


def clipped_score(logits,y):
    z=np.asarray(logits,dtype=np.float64)
    loss=np.logaddexp.reduce(z,axis=1)-z[np.arange(len(y)),y]
    pred=z.argmax(1)
    return {'nll':float(loss.mean()),'top1':float((pred==y).mean())},loss,pred


@torch.no_grad()
def infer(model,data,rows,donors=None):
    model.eval()
    txt=model.encode(model.text(data.tokens))
    outputs=[]
    for start in range(0,len(rows),192):
        ids=rows[start:start+192]
        av=None if donors is None else [ids if v is None else v[start:start+192] for v in donors]
        outputs.append(12*(model.encode(model.av(data.get(ids,av)))@txt.T))
    z=torch.cat(outputs).cpu().numpy()
    assert z.shape==(len(rows),72) and np.isfinite(z).all()
    return z


def train_arm(folder,arm,seed,data):
    begin=wait_time()
    model=Encoder(arm,seed,int(data.tokens.max())+1,folder/'law4.npz').to(DEVICE)
    opt=torch.optim.AdamW(model.parameters(),lr=.0008,weight_decay=.01,foreach=False)
    rng=np.random.default_rng(seed+7369)
    train=data.splits[0];init=wait_time()-begin
    active=0.;steps=0;samples=0;saved={};last=0.;batches=iter(());first_grad=None
    while len(saved)<2:
        start=wait_time()
        rows=next(batches,None)
        if rows is None:
            order=rng.permutation(train);batches=iter(order[i:i+128] for i in range(0,len(train),128))
            rows=next(batches)
        model.train();opt.zero_grad(set_to_none=True)
        logits=model.logits(data.get(rows),data.tokens)
        loss=F.cross_entropy(logits,data.y[rows])
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
        opt.step();last=float(loss)
        duration=wait_time()-start
        if first_grad is None:
            first_grad=sum(int(torch.count_nonzero(p.grad)) for p in model.parameters() if p.grad is not None)
        active+=duration;steps+=1;samples+=len(rows)
        assigned=[]
        if steps==78:assigned.append('updates78')
        if active>=12 and 'time12' not in saved:assigned.append('time12')
        for tag in assigned:
            save_start=wait_time();name=f'{arm}-{seed}-{tag}.pt'
            torch.save({k:v.detach().cpu() for k,v in model.state_dict().items()},folder/name)
            summ,_,_=clipped_score(infer(model,data,data.splits[1]),data.y[data.splits[1]].cpu().numpy())
            saved[tag]={'file':name,'sha256':digest(folder/name),'steps':steps,'samples':samples,'train_seconds':active,
                        'development':summ,'save_dev_seconds':wait_time()-save_start}
    return {'parameters':sum(p.numel() for p in model.parameters()),'first_nonzero_grad_elements':first_grad,'init_s':init,'last_loss':last,
            'fit_save_dev_s':wait_time()-begin,'checkpoints':saved}


def ridge(data):
    start=wait_time()
    x=data.x.flatten(1).double()
    tr,dev,_=data.splits
    y=data.y; xm=x[tr].mean(0);xd=x[tr].std(0,unbiased=False).clamp_min(.01)
    x=(x-xm)/xd
    target=F.one_hot(y[tr],72).double();ym=target.mean(0);target-=ym
    gram=x[tr].T@x[tr]/len(tr); rhs=x[tr].T@target/len(tr)
    best=None;rows=[]
    for lam in (.0001,.01,.1,1.):
        w=torch.linalg.solve(gram+lam*torch.eye(gram.shape[0],device=DEVICE,dtype=gram.dtype),rhs)
        for scale in (4.,16.,64.,128.):
            z=scale*(x[dev]@w+ym)
            loss=float(F.cross_entropy(z,y[dev]))
            rows.append([lam,scale,loss])
            if best is None or loss<best[0]:best=(loss,lam,scale,w.detach().clone())
    loss,lam,scale,w=best
    def logits(features):
        return (scale*(((features.flatten(1).double()-xm)/xd)@w+ym)).float().cpu().numpy()
    return logits,{'regularization':lam,'scale':scale,'development_nll':loss,'fit_dev_s':wait_time()-start,'candidates':rows}


def derange(rows,seed):
    order=np.random.default_rng(seed).permutation(len(rows))
    ix=np.arange(len(rows));ix[order]=np.roll(order,1)
    assert np.all(ix!=np.arange(len(rows)))
    return rows[ix]


def clustered(delta,actor):
    who=np.unique(actor)
    counts=np.array([(actor==w).sum() for w in who])
    ag=np.array([delta[actor==w].sum() for w in who])
    draws=np.random.default_rng(66541).integers(len(who),size=(4000,len(who)))
    samples=ag[draws].sum(1)/counts[draws].sum(1)
    return {'delta':float(delta.mean()),'actor_cluster_ci95':np.quantile(samples,[.025,.975]).tolist(),'actors':len(who)}


def analyze(scores,actor):
    result={}
    for tag in ENDPOINTS:
        for oth in ('smooth','lif','sdpa','ridge'):
            delta=np.mean([scores[f'literal-{seed}-{tag}-normal']-scores[
                f'{oth}-{seed}-{tag}-normal' if oth!='ridge' else 'ridge-normal'] for seed in SEEDS],axis=0)
            result[f'{tag}:literal-minus-{oth}']=clustered(delta,actor)
        for arm in ARMS:
            for cond in (('perm_audio','perm_vision','no_wire') if arm=='literal' else ('perm_audio','perm_vision')):
                delta=np.mean([scores[f'{arm}-{seed}-{tag}-{cond}']-scores[f'{arm}-{seed}-{tag}-normal'] for seed in SEEDS],axis=0)
                result[f'{tag}:{arm}:{cond}-minus-normal']=clustered(delta,actor)
    return result


def run(folder,result,arrays,weights):
    assert torch.cuda.is_available() and 'T4' in torch.cuda.get_device_name()
    torch.set_num_threads(1);begin=wait_time()
    probe=torch.arange(8,dtype=torch.float32,device='cuda');assert float(probe@probe)==140
    prep=wait_time();data=StudyData(folder);prep=wait_time()-prep
    report={'device':torch.cuda.get_device_name(),'torch':str(torch.__version__),'cuda':torch.version.cuda,'dot':140,
            'source_data':data.meta,'split':list(map(len,data.splits)),'actor_counts':[len(set(data.actor[q])) for q in data.splits],
            'data_setup_s':prep,'fits':{},'terminal':False}
    for i,seed in enumerate(SEEDS):
        for arm in ARMS[i:]+ARMS[:i]:
            report['fits'][f'{arm}-{seed}']=train_arm(folder,arm,seed,data)
            result.write_text(json.dumps(report,allow_nan=False))
    ridge_score,report['ridge']=ridge(data)
    seal=folder/'seal.json';seal.write_text(json.dumps({'fits':report['fits'],'ridge':report['ridge']},sort_keys=True,allow_nan=False))
    report['seal_sha256']=digest(seal)
    with zipfile.ZipFile(weights,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for f in sorted(folder.glob('*.pt')):z.write(f,f.name)
        z.write(seal,seal.name)
    report['weights_sha256']=digest(weights)
    test=data.splits[2];y=data.y[test].cpu().numpy();actor=data.actor[test]
    da,dv=derange(test,202611281),derange(test,202611282)
    archive={'ids':data.ids[test],'y':y,'actor':actor,'audio_donor_global':da,'vision_donor_global':dv,'global_indices':test}
    losses={};report['cold']={}
    def record(key,z):
        row,loss,pred=clipped_score(z,y)
        report['cold'][key]=row
        losses[key]=loss;archive[key+'__loss']=loss;archive[key+'__prediction']=pred.astype('uint8')
        if key.endswith('-normal'):archive[key+'__logits']=z.astype('float32')
    start=wait_time()
    for arm in ARMS:
        for seed in SEEDS:
            model=Encoder(arm,seed,int(data.tokens.max())+1,folder/'law4.npz').to(DEVICE)
            for tag in ENDPOINTS:
                fit=report['fits'][f'{arm}-{seed}']['checkpoints'][tag]
                p=folder/fit['file'];assert digest(p)==fit['sha256']
                model.load_state_dict(torch.load(p,map_location=DEVICE,weights_only=True))
                for cond,swap in (('normal',None),('perm_audio',(None,da)),('perm_vision',(dv,None))):
                    record(f'{arm}-{seed}-{tag}-{cond}',infer(model,data,test,swap))
                if arm=='literal':
                    model.mix[1].kind='no_wire'
                    record(f'{arm}-{seed}-{tag}-no_wire',infer(model,data,test))
                    model.mix[1].kind='literal'
    for cond,swap in (('normal',None),('perm_audio',(test,da)),('perm_vision',(dv,test))):
        record('ridge-'+cond,ridge_score(data.get(test,swap)))
    report['all_cold_s']=wait_time()-start
    report['paired']=analyze(losses,actor)
    np.savez_compressed(arrays,**archive)
    report.update(terminal=True,arrays_sha256=digest(arrays),array_keys=len(archive),total_s=wait_time()-begin)
    result.write_text(json.dumps(report,allow_nan=False,indent=1)+'\n')
