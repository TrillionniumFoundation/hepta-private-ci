"""Exercise the registered training function's write order using a tiny deterministic model and two synthetic clocks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import numpy as np
import torch

class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w=torch.nn.Parameter(torch.tensor(0.75))
    def forward(self,v,a,t):
        return self.w*v,t

def main(path):
    sys.path.insert(0,str(path))
    import train
    torch.set_num_threads(1)
    sys.modules['network']=SimpleNamespace(make_model=lambda *a:Tiny())
    sys.modules['encoder']=SimpleNamespace(pair_loss=lambda av,txt,y:(av-txt).square().mean())
    def infer(model,data,rows):
        v=model.w.expand(len(rows));return torch.stack([v,-v],dim=1)
    sys.modules['study']=SimpleNamespace(inference=infer)
    tr=np.arange(48)
    data=SimpleNamespace(train=tr,dev=tr[:2],v=torch.ones(48),audio=torch.ones(48),tokens=torch.tensor([0.,1.]),y=torch.zeros(48,dtype=torch.long))
    train.RUNGS=(3.,6.,15.)
    def set_clock(delta):
        ticks=iter(np.arange(0,20000*delta,delta))
        train.time=SimpleNamespace(perf_counter=lambda:float(next(ticks)),process_time=lambda:0.,time=lambda:0.)
    original=train.write
    def interrupted(path,val):
        if path.name=="resume.pt":
            raise InterruptedError("registered first result exists and cursor does not")
        original(path,val)
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);out=root/'run';out.mkdir();cell=out/'stationary-137'
        set_clock(1.)
        train.write=interrupted
        try:train.one_stage(root,out,data,'stationary',137,3.)
        except InterruptedError:pass
        prior=sorted(f.name for f in cell.iterdir())
        assert prior==['step3-dev.npz','step3.pt']
        orig={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in cell.iterdir()}
        train.write=original;set_clock(2.)
        train.one_stage(root,out,data,'stationary',137,3.)
        restored=json.loads((cell/'progress.json').read_text())['history']['time3']
        assert restored['step']==2 and (cell/'step3.pt').exists()
        print(json.dumps({'first_attempt_time_threshold_step':3,'surviving_original_files_before_restart':prior,'original_sha256':orig,'restart_recorded_threshold_step':restored['step'],'step3_in_restart_history':False,'setup':'Only the test clock tick is changed. The registered one_stage writes weights and development scores before checkpoint cursor/progress.'},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source_dir',type=Path)
    main(p.parse_args().source_dir)
