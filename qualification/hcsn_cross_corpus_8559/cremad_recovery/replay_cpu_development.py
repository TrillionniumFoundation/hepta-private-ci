"""Load the 4.07 GB immutable 1B checkpoint into a fresh process and replay all development logits."""
import argparse,hashlib,json,sys,time
from pathlib import Path
import numpy as np
import torch

from cpu_quality import Data,build,scores,sha,write


def main(parent,out):
    sys.path.insert(0,str(parent/'src'));torch.set_num_threads(1)
    p=out/'fits/literal';obs=json.loads((p/'observations.json').read_text())
    meta=next(x for x in obs if x['step']==4);weights=p/'weights-4.pt';assert sha(weights)==meta['weights_sha256']
    gt=p/'panel-4.npz';assert sha(gt)==meta['panel_sha256'];d=Data(parent);net=build(parent,'literal',d.n);t=time.perf_counter()
    model=torch.load(weights,map_location='cpu',weights_only=True,mmap=True);net.load_state_dict(model,strict=True);loaded=sum(q.numel() for q in net.parameters());assert loaded==1016475200
    del model;load=time.perf_counter()-t
    observed,latency=scores(net,d,d.panel,parent)
    with np.load(gt) as z:
        assert np.array_equal(d.names[d.panel],z['ids']);err=np.abs(observed['aligned']-z['aligned'])
        report=dict(checkpoint_sha256=meta['weights_sha256'],checkpoint_bytes=weights.stat().st_size,parameters_loaded=loaded,parameter_tensors=sum(1 for _ in net.parameters()),panel_rows=len(d.panel),classes=int(z['aligned'].shape[1]),n_logits=int(err.size),max_abs_error=float(err.max()),bytewise_equal=bool(np.array_equal(observed['aligned'],z['aligned'])),load_wall_s=load,inference=latency)
    write(out/'INDEPENDENT_DEVELOPMENT_REPLAY.json',report);print(report,flush=True)
    assert report['max_abs_error']<=1e-6


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('parent',type=Path);a.add_argument('out',type=Path);v=a.parse_args();main(v.parent.resolve(),v.out.resolve())
