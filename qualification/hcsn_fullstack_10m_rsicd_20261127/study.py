"""One genuine fit, all immutable seals, and held-out scoring for raw-input captioning."""
import argparse,contextlib,hashlib,json,os,resource,sys,time
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from model import ARMS,Captioner

ROOT=Path(os.environ['FULLSTACK_DATA']);SEEDS=(109,271,463);BUDGETS=(60,180,300);STEPS=(4,16)
torch.set_num_threads(1)

def write(p,obj):
    tmp=p.with_suffix('.partial');tmp.write_text(json.dumps(obj,indent=1,allow_nan=False));tmp.replace(p)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class Data:
    def __init__(self):
        self.meta=json.loads((ROOT/'data.json').read_text());self.p=np.load(self.meta['pixels'],mmap_mode='r');z=np.load(ROOT/'data.npz');self.x=z['inputs'];self.y=z['targets'];self.index={k:z[k] for k in ('train','development','test')};z.close()
    def batch(self,ix,images=None):
        return (torch.from_numpy(self.p[ix if images is None else images]),torch.from_numpy(self.x[ix].astype(np.int64)),torch.from_numpy(self.y[ix].astype(np.int64)))
def net(kind,seed,d):return Captioner(kind,seed,d.meta['vocab_size'],ROOT/'law4.npz')
def eval_rows(model,d,rows,images=None):
    model.eval();losses=[];counts=[]
    with torch.no_grad():
        for j in range(0,len(rows),8):
            pix,t,y=d.batch(rows[j:j+8],None if images is None else images[j:j+8]);logits=model(pix,t);l=F.cross_entropy(logits.transpose(1,2),y,ignore_index=0,reduction='none');losses.extend(l.double().sum(1).tolist());counts.extend((y!=0).sum(1).tolist())
    return np.array(losses),np.array(counts)
def fit(arm,seed):
    tick=time.perf_counter();out=ROOT/'runs'/f'{arm}-{seed}';out.mkdir(exist_ok=True,parents=True)
    if (out/'done.json').exists():return
    if (out/'history.json').exists():
        raise RuntimeError(f'incomplete cell needs explicit recovery preserving failed attempt: {out}')
    d=Data();model=net(arm,seed,d);opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01,foreach=False);rng=np.random.default_rng(seed)
    count=sum(p.numel() for p in model.parameters());assert count>=10_000_000
    w=time.perf_counter();c=time.process_time();hw=[];tokens=0;step=0;thresholds={k:[35,125,225] for k in ('wall','cpu')}
    def elapsed():return {'wall':time.perf_counter()-w,'cpu':time.process_time()-c}
    def observe(tags):
        losses,ns=eval_rows(model,d,d.index['development']);nll=float(losses.sum()/ns.sum());state=out/f's{step}.pt'
        new_record=not hw or nll<min(x['nll'] for x in hw);save=(step in STEPS or new_record)
        if save:tmp=state.with_suffix('.tmp');torch.save(model.state_dict(),tmp);tmp.replace(state)
        digest=sha(state) if save else None
        entry={'step':step,'train_tokens':tokens,'nll':nll,'validation_tokens':int(ns.sum()),'state':state.name if save else None,'sha':digest,'tags':tags,**elapsed()};hw.append(entry);write(out/'history.json',hw)
        print(arm,seed,step,round(entry['cpu'],1),round(nll,5),flush=True)
    observe(['initial']);batches=[]
    while min(elapsed().values())<300:
        model.train();ix=rng.choice(d.index['train'],size=8,replace=False);pix,t,y=d.batch(ix);tok=int((y!=0).sum());batches.append(hashlib.sha256(ix.astype('<i8').tobytes()).hexdigest())
        opt.zero_grad(set_to_none=True);pred=model(pix,t);loss=F.cross_entropy(pred.flatten(0,1),y.flatten(),ignore_index=0);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step();step+=1;tokens+=tok
        tags=[];e=elapsed()
        for clock,levels in thresholds.items():
            while levels and e[clock]>=levels[0]:tags.append(clock+str(levels.pop(0)))
        if step in STEPS:tags.append(f'step{step}')
        if tags:observe(tags)
    duration=elapsed();write(out/'done.json',{'arm':arm,'seed':seed,'parameters':count,'setup_s':w-tick,'elapsed':duration,'steps':step,'tokens':tokens,'affinity':list(os.sched_getaffinity(0)),'rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'batch_roster_sha':hashlib.sha256(''.join(batches).encode()).hexdigest()})
def seal():
    rows={}
    for arm in ARMS:
        for s in SEEDS:
            out=ROOT/'runs'/f'{arm}-{s}';assert (out/'done.json').is_file();h=json.loads((out/'history.json').read_text());selected={}
            for clock in ('cpu','wall'):
                for budget in BUDGETS:
                    eligible=[r for r in h if r[clock]<=budget];selected[clock+str(budget)]=min(eligible,key=lambda r:(r['nll'],r[clock])) if eligible else None
            for step in STEPS:selected['steps'+str(step)]=next((r for r in h if r['step']==step),None)
            for label,r in selected.items():
                if r:assert r['state'] and sha(out/r['state'])==r['sha']
            rows[f'{arm}-{s}']=selected
    write(ROOT/'seal.json',rows)
def confirm():
    d=Data();selection=json.loads((ROOT/'seal.json').read_text());raw=ROOT/'cold';raw.mkdir(exist_ok=True)
    ids=d.index['test'];perm=np.roll(ids,1)
    for arm in ARMS:
        for s in SEEDS:
            ident=f'{arm}-{s}';out=ROOT/'runs'/ident;model=net(arm,s,d)
            for mode,rec in selection[ident].items():
                if rec is None:continue
                key=rec['sha'];path=raw/(key+'.npz')
                if path.exists():continue
                assert sha(out/rec['state'])==key;model.load_state_dict(torch.load(out/rec['state'],weights_only=True,map_location='cpu'))
                t=time.perf_counter();a,n=eval_rows(model,d,ids);b,k=eval_rows(model,d,ids,perm);assert np.array_equal(n,k)
                tmp=raw/(key+'.tmp.npz');np.savez_compressed(tmp,matched=a,shifted=b,counts=n,rows=ids,seconds=time.perf_counter()-t);tmp.replace(path)
            print('cold',ident,flush=True)
    write(ROOT/'cold_manifest.json',{f.name:sha(f) for f in raw.glob('*.npz')})
if __name__=='__main__':
    a=sys.argv
    if a[1]=='fit':fit(a[2],int(a[3]))
    elif a[1]=='seal':seal()
    elif a[1]=='confirm':confirm()
