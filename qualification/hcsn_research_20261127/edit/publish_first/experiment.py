"""Write the actual physical sending layer of a pretrained nonlinear HCSN."""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

ENTRY=time.perf_counter()
import numpy as np
import torch
from torch.nn import functional as F
from qualification.hcsn_boundary_transfer_20261126.nobp import study

DIGESTS={107:'6e28f1b516ba5cb302d0c889d30d682ae7eae4d5aa310b22f82d1b76e0e3a8ea',
         211:'0ebe8e87b3bf10e26454844a416a3ff0d79df0e8f11ba1dc0840a4776b665eb2',
         431:'21c9479061ab7ff7c9bf17649b5413f486a78aff83f5a1bcd02c38c1b9c17124'}
SITES={'input_drive.weight','input_drive.bias'}
METHODS=('keep','direct','wronglabel','unconditional','bp')
BASE=Path(__file__).resolve().parent


def sha(b): return hashlib.sha256(b).hexdigest()


def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')


def read_parent(args):
    path=args.parents/'evidence'/f'hcsn_bp-{args.seed}.zip'
    assert sha(path.read_bytes())==DIGESTS[args.seed]
    with zipfile.ZipFile(path) as z: raw=z.read(f'hcsn_bp-{args.seed}/selected.pt')
    c=torch.load(io.BytesIO(raw),weights_only=True,map_location='cpu')
    model=study.make('hcsn_bp',args.seed)
    model.load_state_dict(c['model'],strict=True)
    for k,p in model.named_parameters():p.requires_grad_(k in SITES)
    return model,c,sha(raw)


def physical_map(model):
    return torch.cat((model.input_drive.weight.detach(),model.input_drive.bias.detach()[:,None]),1).double().T.clone()


@torch.no_grad()
def install(model,w):
    model.input_drive.weight.copy_(w[:-1].T)
    model.input_drive.bias.copy_(w[-1])


def loads(args,split,c):
    f=args.input/(split+'.npz')
    receipt=json.loads((args.input/'dataset.json').read_text())['parts'][split]['sha256']
    assert sha(f.read_bytes())==receipt
    out={}
    with np.load(f,allow_pickle=False) as ar:
        for lang in ['eng','ar']:
            x=torch.from_numpy(ar[lang+'_'+split+'_x'])
            if lang=='ar':x=((x-c['input_mean'])/c['input_scale']).clamp(-5,5).float()
            out[lang]=(x,torch.from_numpy(ar[lang+'_'+split+'_y']),ar[lang+'_'+split+'_id'].copy())
    return out


def score(model,ridge,x):
    z=study.features(model,x).double()
    return ((z-ridge['mean'])/ridge['scale'])@ridge['weight']+ridge['bias']


@torch.no_grad()
def scores(model,c,x):
    return torch.cat([score(model,c['ridge'],b) for b in x.split(24)])


def metric(s,y):
    p=s.softmax(1)
    return {'n':len(y),'acc':(s.argmax(1)==y).double().mean().item(),
            'brier':(p-F.one_hot(y,10)).square().sum(1).mean().item()}


def score_parts(model,c,part):
    return {k:metric(scores(model,c,x),y) for k,(x,y,_) in part.items()}


@torch.no_grad()
def trace(model,x):
    """Measure the nonlinear drifts; retain the recurrent offset needed in inversion."""
    all_values={'keys':[], 'drift':[], 'preactivation':[]}
    c=model.config
    for batch in x.split(24):
        vals={k:[] for k in all_values}
        def observe(m,frame,control,raw,message,step):
            if step%c.slow_every: return
            assert c.message_mode=='full'
            channels=frame.new_ones(3)
            rec=F.linear((message.to(frame)*channels[None,:,None]).flatten(1),m.recurrent.weight*m.synaptic_mask)[:,:c.neurons//2]
            pre=F.linear(control,m.input_drive.weight,m.input_drive.bias)+rec
            vals['keys'].append(torch.cat((control,torch.ones(len(frame),1,dtype=frame.dtype)),dim=1))
            vals['preactivation'].append(pre)
            vals['drift'].append(c.base_drift+c.drift_scale*pre.tanh())
        model.observer=observe
        try:
            _,_,state=model(batch.transpose(0,1),return_features=True)
        finally:model.observer=None
        # The final frame holds the preceding update's physical sender drift.
        assert torch.allclose(state.population.drift[:,:c.neurons//2],vals['drift'][-1].double(),rtol=2e-6,atol=1e-7)
        for k in vals:all_values[k].append(torch.stack(vals[k],1))
    return {k:torch.cat(v).double() for k,v in all_values.items()}


def solve(model,traces,train,kind):
    uk,old=traces['eng'],traces['ar']
    ynew=train['eng'][1];yold=train['ar'][1]
    d=torch.stack([old['drift'][yold==j].mean(0) for j in range(10)])
    if kind=='direct': target=d[ynew]
    elif kind=='wronglabel': target=d[(ynew+1)%10]
    else:target=old['drift'].mean(0,keepdim=True).expand(len(ynew),-1,-1)
    c=model.config
    desired=((target-c.base_drift)/c.drift_scale).clamp(-1+1e-8,1-1e-8).atanh()
    design=uk['keys'].flatten(0,1)
    delta=(desired-uk['preactivation']).flatten(0,1)
    keep=old['keys'].flatten(0,1)
    A=design.T@design/len(design)+.25*(keep.T@keep/len(keep))+.02*torch.eye(design.shape[1],dtype=torch.double)
    return torch.linalg.solve(A,(design.T@delta)/len(design)),{'target_rms_drift':float(target.square().mean().sqrt()),
          'current_rms_drift':float(uk['drift'].square().mean().sqrt()),'condition':float(torch.linalg.cond(A))}


def gradient_fit(model,c,base,train,old_predict,seed):
    out={}
    for lr in (.002,.01):
        install(model,base)
        opt=torch.optim.Adam([p for p in model.parameters() if p.requires_grad],lr=lr)
        g=torch.Generator().manual_seed(23000+seed)
        for i in range(1,49):
            new_ids=torch.randperm(len(train['eng'][1]),generator=g)[:16]
            old_ids=torch.randperm(len(train['ar'][1]),generator=g)[:16]
            opt.zero_grad(set_to_none=True)
            for lang,ids,weight in [('eng',new_ids,1.),('ar',old_ids,.25)]:
                for sub in ids.split(4):
                    predictions=score(model,c['ridge'],train[lang][0][sub])
                    target=F.one_hot(train[lang][1][sub],10) if lang=='eng' else old_predict[sub]
                    loss=weight*(predictions-target).square().mean()*len(sub)/len(ids)
                    loss.backward()
            if not torch.isfinite(torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],2.)):raise RuntimeError('Non-finite BP')
            opt.step()
            if i in (12,48):out[f'lr{lr}_steps{i}']=physical_map(model)
    return out


def fit(args):
    model,c,source_sha=read_parent(args)
    base=physical_map(model); train=loads(args,'train',c);dev=loads(args,'dev',c)
    root=args.output/str(args.seed)/args.method;root.mkdir(exist_ok=False,parents=True)
    m=args.method; started=time.perf_counter()
    if m in ('direct','wronglabel','unconditional'):
        tr={k:trace(model,data[0]) for k,data in train.items()}
        delta,details=solve(model,tr,train,m)
        cand={'scale'+str(a):base+a*delta for a in [.125,.25,.5,1.]}
    elif m=='bp':
        old=scores(model,c,train['ar'][0])
        cand=gradient_fit(model,c,base,train,old,args.seed);details={}
    else:cand={};details={}
    fitted=time.perf_counter()
    roster={}; candidates={'keep':base,**cand}
    for name,w in candidates.items():
        install(model,w)
        roster[name]={'dev':score_parts(model,c,dev),'dw':float((physical_map(model)-base).norm())}
    keep_acc=roster['keep']['dev']['ar']['acc']
    allowed=[k for k,d in roster.items() if d['dev']['ar']['acc']>=keep_acc-.03-1e-12]
    best=min(allowed,key=lambda k:(-roster[k]['dev']['eng']['acc'],roster[k]['dev']['eng']['brier'],roster[k]['dw']))
    install(model,candidates[best])
    selected=physical_map(model)
    unchanged=[k for k,v in model.state_dict().items() if k not in SITES and not torch.equal(c['model'][k],v)]
    assert not unchanged
    np.savez_compressed(root/'weights.npz',**{k:w.numpy() for k,w in candidates.items()})
    full={**c,'model':model.state_dict()}
    torch.save(full,root/'selected.pt')
    write(root/'fit.json',{'method':m,'seed':args.seed,'source_parent_sha256':source_sha,
          'upstream_zip_sha256':DIGESTS[args.seed],'writable_parameters':224,'candidates':roster,'selected':best,
          'root':args.root_id,'code':sha(Path(__file__).read_bytes()),'protocol':sha((BASE/'PROTOCOL.md').read_bytes()),
          'old_constraints_pass':allowed,'physical_map_delta_norm':float((selected-base).norm()),'changed_other_tensors':unchanged,
          'candidate_weights_sha256':sha((root/'weights.npz').read_bytes()),'selected_sha256':sha((root/'selected.pt').read_bytes()),
          'time_s':{'cold_total_to_save':time.perf_counter()-ENTRY,'fit_search':fitted-started,'dev_and_serialize':time.perf_counter()-fitted},
          'details':details,'runtime':str(torch.__version__)})
    print(args.seed,args.method,best,roster[best]['dev'],round(time.perf_counter()-ENTRY,2),flush=True)


def evaluate(args):
    root=args.output/str(args.seed)/args.method
    seal=json.loads((args.output/'seal.json').read_text())
    rec=json.loads((root/'fit.json').read_text())
    assert sha((root/'selected.pt').read_bytes())==seal['models'][str(args.seed)+'/'+args.method]
    model,c,_=read_parent(args)
    saved=torch.load(root/'selected.pt',weights_only=True,map_location='cpu')
    for k,v in c['ridge'].items():assert torch.equal(saved['ridge'][k],v)
    model.load_state_dict(saved['model'],strict=True)
    test=loads(args,'test',c); met={}; arrays={}
    for lang,(x,y,ids) in test.items():
        s=scores(model,c,x);met[lang]=metric(s,y)
        arrays[lang+'_scores']=s.float().numpy()
        arrays[lang+'_class']=s.argmax(1).numpy()
        arrays[lang+'_y']=y.numpy();arrays[lang+'_id']=ids
        if lang=='eng':
            speakers=np.array([i.split('_')[1] for i in ids])
            met['by_speaker']={key:metric(s[speakers==key],y[speakers==key]) for key in sorted(set(speakers))}
            heldout=trace(model,x[:20]);arrays['example_drift']=heldout['drift'].float().numpy()
    np.savez_compressed(root/'predictions.npz',**arrays)
    write(root/'test.json',{'seed':args.seed,'method':args.method,'selected':rec['selected'],'scores':met,'prediction_sha256':sha((root/'predictions.npz').read_bytes()),
          'cold_eval_s':time.perf_counter()-ENTRY,'parent_and_fit_cost_s':rec['time_s']['cold_total_to_save']})
    print(args.seed,args.method,met,round(time.perf_counter()-ENTRY,2),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['fit','eval']);ap.add_argument('--seed',type=int,choices=tuple(DIGESTS),required=True)
    ap.add_argument('--method',choices=METHODS,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--input',type=Path,required=True);ap.add_argument('--parents',type=Path,required=True);ap.add_argument('--root-id',default='8b538954e3db0763b9eb24b6159d17b80f286f26')
    args=ap.parse_args();torch.set_num_threads(1)
    (fit if args.mode=='fit' else evaluate)(args)
