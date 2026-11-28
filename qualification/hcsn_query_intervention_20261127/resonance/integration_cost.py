"""Fixed-law specialization accuracy and timings against the repository's native positive-premium path."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time
import numpy as np
import torch
from compatibility import native_cls
from resonance import StablePublished,StationaryLaw,replace_published

def sample(fn,n):
    fn();w=[];cpu=[]
    for _ in range(n):
        tic=time.perf_counter();c=time.process_time();fn();cpu.append(time.process_time()-c);w.append(time.perf_counter()-tic)
    return dict(wall_seconds=w,cpu_seconds=cpu,median_wall=float(np.median(w)),median_cpu=float(np.median(cpu)))
def run(legacy,records):
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(855977)
    raw=json.loads(records.read_text())['cases'];masks={};maxerr=np.zeros(4);models={}
    for row in raw:
        k=row['m'],row['sigma'],row['premium']
        if k not in models:models[k]=StablePublished(replace(StationaryLaw(),m=k[0],sigma=k[1],premium=k[2]))
        module=models[k];c=module.channels(row['margin'],61.68);price=np.array([float(v) for v in c]);maxerr=np.maximum(maxerr,abs(price-np.array(row['quad'])))
    cls=native_cls(legacy);old=cls.Published();stable=StablePublished(validate_args=False)
    m=torch.linspace(.001,.8,384,dtype=torch.float64).reshape(32,12);P=torch.linspace(55.,75.,384,dtype=torch.float64).reshape(32,12)
    q=torch.full_like(P,.01)
    times={'native_fixed_values':sample(lambda:old.values(m,P),21),'stable_fixed_values':sample(lambda:stable.values(m,P),21),
           'stable_dynamic_values':sample(lambda:stable.values(m,P,premium=q),21)}
    c1=cls.LiteralCell();from copy import deepcopy
    c2=replace_published(deepcopy(c1),validate_args=False);drive=torch.randn(15,4,6,dtype=torch.float64)
    def trainstep(model):
        model.zero_grad(set_to_none=True);y=model(drive);y.square().sum().backward()
    times['native_15_step_backward']=sample(lambda:trainstep(c1),7);times['stable_15_step_backward']=sample(lambda:trainstep(c2),7)
    return dict(validation='80 fixed-law cases against independent adaptive quadrature',fixed_max_abs_error_by_B_E_F_G=maxerr.tolist(),
          positive_premium=.01,torch=torch.__version__,cpu_threads=torch.get_num_threads(),batch_shape=[32,12],timings=times)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('legacy','reference','out'):p.add_argument(k,type=Path)
    a=p.parse_args();a.out.write_text(json.dumps(run(a.legacy,a.reference),indent=1,allow_nan=False)+'\n')
