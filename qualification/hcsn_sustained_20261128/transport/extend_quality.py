"""Prospective follow-up on the previously censored Optical Digits development threshold."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
CAP=96
THRESHOLD=.80


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,obj):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n');temp.replace(path)


def write_state(torch,model,path):
    tmp=path.with_suffix('.tmp');torch.save(model.state_dict(),tmp);tmp.replace(path)
    return sha(path)


def worker(args):
    import numpy as np
    import torch
    import train_digits as base
    from qualify_native import patched_module
    torch.set_num_threads(1);torch.manual_seed(args.seed)
    x,y,(train,dev,test)=base.dataset()
    dest=args.dest/f'{args.k}-{args.seed}-{args.mode}';dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        module=patched_module(HERE/'upstream',Path(t))
        model=module.ContinuousSpikingNetwork(8,3,2,atoms=args.k,port='priced').double()
        model.first.matrix_free=model.second.matrix_free=args.mode=='fft'
        x=torch.tensor(x,dtype=torch.float64).transpose(0,1);y=torch.tensor(y,dtype=torch.long)
        def evaluate(rows):
            with torch.no_grad():
                scores=torch.cat([model(x[:,group])[0][-1] for group in np.array_split(rows,int(np.ceil(len(rows)/8)))])
                truth=y[rows];pred=scores.argmax(-1)
                acc=[float((pred[truth==i]==i).double().mean()) for i in (0,1)]
                return {'balanced_accuracy':sum(acc)/2,'ce':float(torch.nn.functional.cross_entropy(scores,truth))}
        if args.phase=='cold':
            seal=json.loads((args.dest/'development_seal.json').read_text())
            row=seal['cells'][dest.name];cold={}
            for name,h in row['states'].items():
                p=dest/f'{name}.pt'
                if sha(p)!=h:raise ValueError('state hash')
                before=time.perf_counter();model.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'))
                cold[name]={**evaluate(test),'state_sha256':h,'load_and_inference_seconds':time.perf_counter()-before}
            save(dest/'cold.json',cold);return
        schedule=np.random.default_rng(args.seed).choice(train,(CAP,8))
        opt=torch.optim.AdamW(model.parameters(),lr=.016,weight_decay=.001)
        steps=[];first=None;states={};cold_to_dev=None;cold_to_saved=None
        for j in range(CAP+1):
            if j%4==0:
                metrics=evaluate(dev);elapsed=time.perf_counter()-args.spawn
                steps.append({'updates':j,'cold_elapsed_s':elapsed,**metrics})
                if first is None and metrics['balanced_accuracy']>=THRESHOLD:
                    first=j;cold_to_dev=elapsed;states['gate']=write_state(torch,model,dest/'gate.pt')
                    cold_to_saved=time.perf_counter()-args.spawn
            if j==CAP:break
            ix=schedule[j];opt.zero_grad(set_to_none=True)
            logits=model(x[:,ix])[0][-1];torch.nn.functional.cross_entropy(logits,y[ix]).backward();opt.step()
        states['terminal']=write_state(torch,model,dest/'terminal.pt')
        save(dest/'development.json',{'seed':args.seed,'atoms':args.k,'mode':args.mode,'first_dev_gate_step':first,
            'cold_time_to_dev_gate_s':cold_to_dev,'cold_time_to_saved_gate_s':cold_to_saved,'dev_checks':steps,
            'train_prefix_16_sha256':hashlib.sha256(schedule[:16].astype('<i8').tobytes()).hexdigest(),
            'all_train_indices_sha256':hashlib.sha256(schedule.astype('<i8').tobytes()).hexdigest(),
            'states':states,'device':'cpu','torch':str(torch.__version__),'platform':platform.platform(),
            'terminal_fit_and_dev_wall_s':time.perf_counter()-args.spawn})


def supervisor(dest):
    dest.mkdir(exist_ok=True)
    cells={}
    identities=[]
    for i,k in enumerate((12,128)):
        for j,seed in enumerate((314,159)):
            for mode in (('dense','fft') if (i+j)%2==0 else ('fft','dense')):
                name=f'{k}-{seed}-{mode}';identities.append((name,k,seed,mode));cell=dest/name
                f=cell/'development.json'
                if not f.is_file():
                    stamp=time.perf_counter()
                    subprocess.run([sys.executable,__file__,'--dest',str(dest),'--phase','train','--k',str(k),
                      '--seed',str(seed),'--mode',mode,'--spawn',str(stamp)],check=True)
                cells[name]=json.loads(f.read_text());print('development',name,cells[name]['first_dev_gate_step'],flush=True)
    sealed={'source_sha256':sha(HERE/'extend_quality.py'),'protocol_sha256':sha(HERE/'EXTENSION_PROTOCOL.md'),
            'score_threshold':THRESHOLD,'cap':CAP,'selection':'fixed development gate after 16-update censoring, same cohort','cells':cells}
    seal=dest/'development_seal.json'
    if seal.exists() and json.loads(seal.read_text())!=sealed:raise ValueError('seal changed')
    if not seal.exists():save(seal,sealed)
    cold={}
    for name,k,seed,mode in identities:
        cell=dest/name;f=cell/'cold.json'
        if not f.is_file():
            subprocess.run([sys.executable,__file__,'--dest',str(dest),'--phase','cold','--k',str(k),'--seed',
                            str(seed),'--mode',mode],check=True)
        cold[name]=json.loads(f.read_text())
    pairs=[]
    for k in (12,128):
        for seed in (314,159):
            a,b=(f'{k}-{seed}-{m}' for m in ('dense','fft'))
            x,y=cells[a],cells[b]
            if x['first_dev_gate_step']!=y['first_dev_gate_step'] or x['all_train_indices_sha256']!=y['all_train_indices_sha256']:
                raise ValueError('paired inputs / crossing differ')
            row={'atoms':k,'seed':seed,'first_dev_gate_step':x['first_dev_gate_step'],
                 'terminal_test_accuracy_dense':cold[a]['terminal']['balanced_accuracy'],
                 'terminal_test_accuracy_fft':cold[b]['terminal']['balanced_accuracy']}
            if x['first_dev_gate_step'] is not None:
                row.update({'to_dev_gate_s_dense':x['cold_time_to_dev_gate_s'],'to_dev_gate_s_fft':y['cold_time_to_dev_gate_s'],
                            'cold_to_dev_gate_ratio':x['cold_time_to_dev_gate_s']/y['cold_time_to_dev_gate_s'],
                            'test_at_gate_dense':cold[a]['gate'],'test_at_gate_fft':cold[b]['gate']})
            pairs.append(row)
    save(dest/'extended_cold.json',{'source_sha256':sealed['source_sha256'],'development_seal_sha256':sha(seal),
            'pairs':pairs,'heldout':cold,'threshold':THRESHOLD,'cap':CAP,'terminal':True})


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=['train','cold']);p.add_argument('--seed',type=int);p.add_argument('--mode')
    p.add_argument('--k',type=int);p.add_argument('--spawn',type=float)
    p.add_argument('--dest',type=Path,default=HERE/'recovery')
    args=p.parse_args();(worker(args) if args.phase else supervisor(args.dest.resolve()))
