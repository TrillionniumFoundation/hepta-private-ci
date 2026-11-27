"""Replay a declared sensitivity granting a clock restart after both CNN initial evaluations."""
import json
from pathlib import Path
import numpy as np
import torch
from study import ROOT,SEEDS,setup_data,gallery,score,sha,atomic
from neural import Conventional,Inputs

def main():
    torch.set_num_threads(1)
    out=ROOT/'startup_sensitivity';out.mkdir(exist_ok=True)
    base=ROOT/'short';d,V=setup_data();te=gallery(d,2);inputs=Inputs('conv',d,V,'cpu')
    selection={}
    for seed in SEEDS:
        root=base/f'conventional-{seed}';hist=json.loads((root/'history.json').read_text())
        clock=max(r['time'] for r in hist if r['step']==0)
        q=[r for r in hist if r['state'] and r['time']<=12+clock]
        row=max(q,key=lambda r:(r['dev_r1'],r['dev_r5'],-r['time']));assert sha(root/row['state'])==row['hash']
        selection[str(seed)]={'waived_s':clock,'row':row}
    atomic(out/'seal.json',selection)
    ranks={};metrics={}
    with np.load(base/'cold_ranks.npz') as old:
        for seed in SEEDS:
            row=selection[str(seed)]['row'];net=Conventional(int(d['tokens'].max())+1,24)
            net.load_state_dict(torch.load(base/f'conventional-{seed}'/row['state'],map_location='cpu',weights_only=True));net.eval()
            I=[];T=[]
            with torch.no_grad():
                for j in range(0,len(te),128):
                    a,b=net(*inputs.batch(te[j:j+128]));I.append(a.numpy());T.append(b.numpy())
            m,rs=score(np.concatenate(I),np.concatenate(T),d,te);ranks[str(seed)]=np.stack(list(rs.values())).astype(np.int16);metrics[str(seed)]=m
        deltas=np.mean([((old[f'literal/{s}/12'][:,:,0]==1).astype(float)-(ranks[str(s)][:,:,0]==1)).mean(0) for s in SEEDS],0)
    g=np.random.default_rng(220711);b=np.concatenate([deltas[g.integers(len(te),size=(100,len(te)))].mean(1) for _ in range(80)])
    np.savez_compressed(out/'ranks.npz',**ranks)
    atomic(out/'result.json',dict(selection=selection,metrics=metrics,mean_conventional=float(np.mean([m['strict_R1'] for m in metrics.values()])),literal_minus_conventional=float(np.mean(deltas)),paired95=np.quantile(b,[.025,.975]).tolist(),notes='Within-family sensitivity after original scores were known. No model updates. CNN receives extra measured time equal to complete model startup and both zero-step development evaluations.'))
if __name__=='__main__':main()
