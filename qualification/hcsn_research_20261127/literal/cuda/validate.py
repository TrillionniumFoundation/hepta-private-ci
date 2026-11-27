"""Compare the compiled GPU operator in both precisions to independent tensor autodiff."""
import json,sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cell import Published
ROOT=Path(__file__).resolve().parent
def main():
    w=np.loadtxt(ROOT/'witness.csv',delimiter=',')
    records={}
    law=Published()
    for dtype in [4,8]:
        raw=w[w[:,0]==dtype]
        x,p=(torch.tensor(raw[:,j],dtype=torch.double,requires_grad=True) for j in (2,3))
        a,f=law.values(x,p);b=(law.boundary(p)/law.B0).log();m=law.move_mean(x)
        outputs=[]
        for v in (a,f,b,m):
            gx,gp=torch.autograd.grad(v.sum(),(x,p),retain_graph=True,allow_unused=True)
            outputs.extend(q.detach().numpy() if q is not None else np.zeros(len(x)) for q in (v,gx,gp))
        ref=np.column_stack(outputs)
        err=np.abs(raw[:,4:]-ref)
        records[str(dtype)]={'points':len(x),'max_abs_by_operator':{k:list(map(float,q.max(axis=0))) for k,q in zip(('equity','hit_probability','log_boundary','next_margin'),np.split(err,4,axis=1))},'max_abs':float(err.max())}
    timings={}
    for row in (json.loads(x) for x in (ROOT/'results.jsonl').read_text().splitlines()):
        key=f"{row['n']}/{row['dtype_bytes']}"
        timings.setdefault(key,{})[row['kind']]={'kernel_ms_median':float(np.median(row['kernel_ms'])),'p10':float(np.quantile(row['kernel_ms'],.1)),'p90':float(np.quantile(row['kernel_ms'],.9)),'host_input_s':row['allocate_and_input_s'],'first_launch_s':row['first_launch_s'],'output_copy_s':row['output_copy_s']}
    for v in timings.values():v['literal_over_ordinary']=v['literal']['kernel_ms_median']/v['ordinary']['kernel_ms_median']
    assert records['8']['max_abs']<1e-8 and records['4']['max_abs']<.02
    (ROOT/'validation.json').write_text(json.dumps({'accuracy':records,'times':timings},indent=1));print(records,[(k,round(v['literal_over_ordinary'],2)) for k,v in timings.items()],flush=True)
if __name__=='__main__':main()
