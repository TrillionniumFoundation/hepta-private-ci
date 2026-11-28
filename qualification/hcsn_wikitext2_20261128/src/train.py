"""Fixed context-128 next-word benchmark. Every adjacent official-split target is scored."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import torch
from model import LanguageModel


class Windows:
    def __init__(self,path):
        a=torch.from_numpy(np.load(path)).long()
        self.count=len(a)-1
        n=math.ceil(self.count/128);pad=128*n-self.count
        self.x=torch.nn.functional.pad(a[:-1],(0,pad)).view(n,128)
        self.y=torch.nn.functional.pad(a[1:],(0,pad),value=-1).view(n,128)


def evaluate(model,data,batch,device,cut=False):
    model.eval()
    total=0.;count=0
    with torch.inference_mode():
        for k in range(0,len(data.x),batch):
            loss=model.losses(data.x[k:k+batch].to(device),data.y[k:k+batch].to(device),cut)
            total+=loss.double().sum().item();count+=loss.numel()
    if count!=data.count:raise ArithmeticError('Target coverage')
    return dict(targets=count,nll=total/count,ppl=math.exp(total/count))


def run(args):
    torch.set_num_threads(args.threads);torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed)
    dev=torch.device(args.device)
    if dev.type=='cuda':torch.cuda.manual_seed_all(args.seed)
    data=json.loads((args.root/'data.json').read_text())
    train,valid,test=[Windows(args.root/(s+'.npy')) for s in ('train','valid','test')]
    model=LanguageModel(data['vocab'],args.kind).to(dev)
    opt=torch.optim.AdamW(model.parameters(),lr=.003,weight_decay=.01,foreach=False)
    order=torch.Generator().manual_seed(args.seed+500)
    metadata=dict(kind=args.kind,seed=args.seed,threads=args.threads,device=str(dev),
         device_name=torch.cuda.get_device_name(0) if dev.type=='cuda' else platform.machine(),torch=str(torch.__version__),
         parameter_count=sum(p.numel() for p in model.parameters()),float_dtype='float32',
         vocab=data['vocab'],context=128,batch=args.batch,learning_rate=.003,weight_decay=.01)
    epochs=[];timed=[];elapsed=0.;process=0.;tokens=0;steps=0
    clocks=[15,45,120,300,600];clock_idx=0;start=time.time()
    prefix=f'{args.kind}-{args.seed}'
    dest=args.root/'results';dest.mkdir(exist_ok=True)
    best_loss=math.inf;best_state=None;best_epoch=None
    def synchronize():
        if dev.type=='cuda':torch.cuda.synchronize()
    def cpu_state():
        return {k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    for epoch in range(1,args.epochs+1):
        perm=torch.randperm(len(train.x),generator=order)
        n0=tokens;epoch_nll=0.;t0=elapsed
        model.train()
        for k in range(0,len(train.x),args.batch):
            synchronize();t=time.perf_counter();pc=time.process_time()
            ii=perm[k:k+args.batch]
            x=train.x[ii].to(dev);y=train.y[ii].to(dev)
            opt.zero_grad(set_to_none=True)
            losses=model.losses(x,y);objective=losses.mean()
            objective.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            opt.step();synchronize()
            elapsed+=time.perf_counter()-t;process+=time.process_time()-pc
            n=losses.numel();tokens+=n;steps+=1;epoch_nll+=objective.item()*n
            if clock_idx<len(clocks) and elapsed>=clocks[clock_idx]:
                while clock_idx<len(clocks) and elapsed>=clocks[clock_idx]:
                    timed.append(dict(clock=clocks[clock_idx],actual_seconds=elapsed,tokens=tokens,step=steps))
                    torch.save(cpu_state(),dest/(prefix+f'-clock{clocks[clock_idx]}.pt'))
                    clock_idx+=1
            if steps%100==0:print(prefix,epoch,steps,tokens,round(elapsed,2),flush=True)
            if args.smoke and steps>=args.smoke:
                print('SMOKE',metadata,elapsed,flush=True);return
        if tokens-n0!=train.count:raise ArithmeticError('Training target coverage')
        val=evaluate(model,valid,args.batch,dev)
        row=dict(epoch=epoch,cumulative_targets=tokens,train_nll=epoch_nll/(tokens-n0),valid=val,
                train_seconds=elapsed-t0,cumulative_train_seconds=elapsed)
        epochs.append(row)
        if val['nll']<best_loss:
            best_loss=val['nll'];best_epoch=epoch;best_state=cpu_state()
        print(prefix,'EPOCH',row,flush=True)
    model.load_state_dict(best_state)
    torch.save(best_state,dest/(prefix+'-best.pt'))
    scores=evaluate(model,test,args.batch,dev);cut=evaluate(model,test,args.batch,dev,cut=True)
    for row in timed:
        path=dest/(prefix+f'-clock{row["clock"]}.pt')
        model.load_state_dict(torch.load(path,map_location=dev,weights_only=True))
        row['valid']=evaluate(model,valid,args.batch,dev)
        row['test']=evaluate(model,test,args.batch,dev)
    out=dict(metadata=metadata,epochs=epochs,selected_epoch=best_epoch,test=scores,cut_test=cut,
             timed=timed,total_training_seconds=elapsed,total_process_training_seconds=process,
             tok_per_training_second=tokens/elapsed,overall_seconds=time.time()-start,
             model_sha256=hashlib.sha256((dest/(prefix+'-best.pt')).read_bytes()).hexdigest())
    tmp=dest/(prefix+'.json.tmp');tmp.write_text(json.dumps(out,indent=2)+'\n');tmp.replace(dest/(prefix+'.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('kind',choices=['hx','sdpa','smooth','lif'])
    p.add_argument('seed',type=int);p.add_argument('--epochs',type=int,default=2);p.add_argument('--threads',type=int,default=1)
    p.add_argument('--batch',type=int,default=32);p.add_argument('--device',default='cpu');p.add_argument('--smoke',type=int)
    run(p.parse_args())
