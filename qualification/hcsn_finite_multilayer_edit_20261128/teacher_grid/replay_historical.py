"""Read both original RAVDESS candidate sets and independently recompute full CPU HCSN outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import torch


def run(root,out):
    sys.path.insert(0,str(root/'source'))
    raw=root/'unpacked'/'speech_v2'
    spec=importlib.util.spec_from_file_location('published_model',raw/'semantic_executor.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    torch.set_num_threads(1)
    training=mod.raw(raw,'train');mu=training[0].mean((0,1,2));sd=np.maximum(training[0].std((0,1,2)),.001)
    scale=np.float32(max(training[1][:,-1].std(),.001));results=[]
    for version in ('cu121','cu130'):
        d=root/'unpacked'/('results-'+version);report=json.loads((d/'eval.json').read_text());seal=json.loads((d/'weights.json').read_text())
        for seed,t in report['seeds'].items():
            for arm in ('keep','direct','exact','weak'):
                f=d/f'centered_{seed}_{arm}.pt';assert hashlib.sha256(f.read_bytes()).hexdigest()==seal[f.name]
                net=mod.Hybrid('centered');net.load_state_dict(torch.load(f,map_location='cpu',weights_only=True));net.eval()
                record={}
                with torch.inference_mode():
                    for part in ('dev','test','retain'):
                        x,base,labels,_=mod.raw(raw,part)
                        z=net(torch.tensor((x-mu)/sd),torch.tensor(base[:,-1]/scale))
                        margin=(z[:,1]-z[:,0]).detach().numpy()
                        saved=np.array(t[arm][part]['margins'])
                        correct=int(((margin>0)==labels).sum())
                        tolerance=float(np.max(abs(margin-saved)))
                        assert correct==t[arm][part]['correct'] and tolerance<.0001
                        record[part]=dict(n=len(margin),correct=correct,max_margin_difference=tolerance)
                results.append(dict(version=version,seed=seed,arm=arm,sha=seal[f.name],cold=record))
    out.write_text(json.dumps(results,indent=1)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();run(a.root,a.out)
