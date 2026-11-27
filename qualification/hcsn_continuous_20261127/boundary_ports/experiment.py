"""Train the registered exact dual-price population encoders and raw/feature-matched controls on FordA."""
from pathlib import Path
import time,os,sys,json,hashlib,copy
import numpy as np,torch
from torch import nn
from torch.nn import functional as F
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'core'))
sys.path.insert(0,str(HERE.parent/'paired_catalog'))
from population import ContinuousSpikingNetwork
from affine_ports import copy_reference
from adam import Adam
sys.path.insert(0,str(HERE))
from prepare import ROOT
torch.set_num_threads(1)
ARMS=['boundary','priced','augmented','boundary_basis','gru','conv']
SEEDS=[419,1097]
class PortNet(nn.Module):
    def __init__(self,arm):
        super().__init__();self.arm=arm
        if arm=='gru':
            self.gru=nn.GRU(7,12,batch_first=True,dtype=torch.float64);self.head=nn.Linear(24,2,dtype=torch.float64)
        elif arm=='conv':
            self.conv=nn.Sequential(nn.Conv1d(1,24,9,padding=4),nn.GroupNorm(4,24),nn.GELU(),nn.Conv1d(24,32,7,padding=3),nn.GroupNorm(4,32),nn.GELU(),nn.MaxPool1d(4),nn.Conv1d(32,32,7,padding=3),nn.GELU(),nn.AdaptiveAvgPool1d(1));self.head=nn.Linear(32,2)
        else:
            self.net=ContinuousSpikingNetwork(7,4,2,atoms=7,port='augmented' if arm=='boundary_basis' else arm)
            self.net.first=copy_reference(self.net.first);self.net.second=copy_reference(self.net.second)
    def forward(self,x,raw):
        if self.arm=='gru':
            o,_=self.gru(x.double());return self.head(torch.cat([o.mean(1),o[:,-1]],1))
        if self.arm=='conv':return self.head(self.conv(raw[:,None,:]).squeeze(-1))
        if self.arm=='boundary_basis':
            send,_=self.net.first(x.transpose(0,1));b=send[...,0]
            # Same interface width as augmented, all eight functions depend on one scalar only.
            feats=torch.stack([b,b*b,b*b*b,torch.tanh(2*b),torch.sin(2*b),torch.cos(2*b),torch.tanh(4*b),torch.sin(4*b)],-1)
            rec,_=self.net.second(feats.flatten(-2));return self.net.head(rec.flatten(-2)).mean(0)
        return self.net(x.transpose(0,1))[0].mean(0)
def data(name):
    with np.load(ROOT/name) as z:return {k:torch.from_numpy(z[k]) if k in ['feat','raw','y'] else z[k] for k in z.files}
def pred(net,d,idx):
    net.eval()
    with torch.no_grad():return np.concatenate([net(d['feat'][i],d['raw'][i]).softmax(-1)[:,1].numpy() for i in np.array_split(idx,max(1,(len(idx)+47)//48))])
def train(arm,seed):
    start=time.monotonic();dst=HERE/'fits';dst.mkdir(exist_ok=True);path=dst/f'{arm}-{seed}';mark=path.with_suffix('.json')
    if mark.exists():return
    d=data('train.npz');torch.manual_seed(seed);net=PortNet(arm);opt=Adam(net.parameters(),.004,weight_decay=.001)
    rng=np.random.default_rng(seed);best=np.inf;history=[];active=0
    for step in range(193):
        if step in [0,48,96,192]:
            ix=d['val'];p=pred(net,d,ix);y=d['y'][ix].numpy()
            brier=float(((p-y)**2).mean());history.append([step,brier,active])
            if brier<best:
                best=brier;chosen=step;torch.save(net.state_dict(),path.with_suffix('.pt'))
            if step==192:break
        t=time.perf_counter();net.train();idx=rng.choice(d['train'],24,replace=False);opt.zero_grad()
        obj=F.cross_entropy(net(d['feat'][idx],d['raw'][idx]),d['y'][idx]);obj.backward();opt.step();active+=time.perf_counter()-t
    doc={'arm':arm,'seed':seed,'chosen':chosen,'development':history,'parameters':sum(p.numel() for p in net.parameters()),'fit_cold_s':time.monotonic()-start,'weights':hashlib.sha256(path.with_suffix('.pt').read_bytes()).hexdigest()};mark.write_text(json.dumps(doc));print(arm,seed,best,active,flush=True)
def seal():
    ob={}
    for s in SEEDS:
        for a in ARMS:
            p=HERE/'fits'/f'{a}-{s}.json';r=json.loads(p.read_bytes());assert hashlib.sha256(p.with_suffix('.pt').read_bytes()).hexdigest()==r['weights'];ob[p.stem]=r
    q=HERE/'SEAL.json';payload=json.dumps(ob,indent=1)
    if q.exists():assert q.read_text()==payload
    else:q.write_text(payload)
def score():
    s=json.loads((HERE/'SEAL.json').read_bytes());d=data('sealed.npz');idx=np.arange(len(d['y']));y=d['y'].numpy()
    out=HERE/'confirmed';out.mkdir(exist_ok=True);rows={};rng=np.random.default_rng(7381)
    ix=rng.integers(len(y),size=(4000,len(y)))
    byarm={}
    for arm in ARMS:
        probs=[]
        for seed in SEEDS:
            key=f'{arm}-{seed}';p=HERE/'fits'/(key+'.pt');assert hashlib.sha256(p.read_bytes()).hexdigest()==s[key]['weights']
            net=PortNet(arm);net.load_state_dict(torch.load(p,map_location='cpu',weights_only=True))
            probs.append(pred(net,d,idx))
        v=np.asarray(probs);byarm[arm]=((v-y[None,:])**2).mean(0)
        rows[arm]={'brier':float(byarm[arm].mean()),'accuracy':float(((v>.5)==y[None,:]).mean()),'brier_by_seed':((v-y[None,:])**2).mean(1).tolist()}
        np.savez_compressed(out/(arm+'.npz'),p=v,target=y,ident=d['ident'])
    contrasts={}
    for arm in ARMS:
        v=byarm['augmented']-byarm[arm];contrasts[arm]={'delta':float(v.mean()),'paired_row95':np.quantile(v[ix].mean(1),[.025,.975]).tolist()}
    obj={'heldout_rows':len(y),'scores':rows,'augmented_minus':contrasts,'predeclared_pass':all(contrasts[a]['paired_row95'][1]<0 for a in ['boundary','boundary_basis'])}
    (HERE/'RESULTS.json').write_text(json.dumps(obj,indent=1));print(obj,flush=True)
if __name__=='__main__':
    if sys.argv[1]=='fit':train(sys.argv[2],int(sys.argv[3]))
    elif sys.argv[1]=='seal':seal()
    elif sys.argv[1]=='score':score()
