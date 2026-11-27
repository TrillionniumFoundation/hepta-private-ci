"""Replay the sealed full training search with the same exact specialization for BP and direct."""
import argparse,hashlib,json,resource,sys,time
from pathlib import Path
ENTRY=time.perf_counter();CPU=time.process_time()
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import torch
import experiment as core
import exact
def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['fit','eval']);ap.add_argument('--seed',type=int,required=True)
    ap.add_argument('--method',choices=['direct','bp'],required=True)
    for k in ('input','parents','output'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();a.root_id='8b538954e3db0763b9eb24b6159d17b80f286f26'
    torch.set_num_threads(1);core.trace=exact.trace;core.score=exact.score
    (core.fit if a.mode=='fit' else core.evaluate)(a)
    root=a.output/str(a.seed)/a.method
    info=dict(elapsed_s=time.perf_counter()-ENTRY,cpu_s=time.process_time()-CPU,maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              threads=torch.get_num_threads(),torch=str(torch.__version__),source=core.sha((HERE/'exact.py').read_bytes()),
              costing_protocol=core.sha((HERE/'COST_PROTOCOL.md').read_bytes()))
    core.write(root/(a.mode+'_process_resource.json'),info)
if __name__=='__main__':main()
