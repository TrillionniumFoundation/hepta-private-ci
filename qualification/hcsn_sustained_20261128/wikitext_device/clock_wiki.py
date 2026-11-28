"""Four paired native GPU measurements of real prefill plus full-vocabulary autoregressive decoding."""
import hashlib
import json
from pathlib import Path
import sys,time
import numpy as np
import torch
from evaluate_wiki import load
from stream_wiki import State,log_probs
HERE=Path(__file__).resolve().parent


@torch.inference_mode()
def decode(ids,net,kind,capacity):
    torch.cuda.synchronize()
    t0=time.perf_counter()
    carry=State(net,kind,1,capacity)
    hidden=carry.append(ids)[:,-1]
    first=log_probs(net.head,hidden).argmax(-1)
    first_ready=torch.cuda.Event(enable_timing=True);first_ready.record()
    word=first
    for step in range(15):
        h=carry.append(word[:,None])[:,-1]
        word=log_probs(net.head,h).argmax(-1)
    last=torch.cuda.Event(enable_timing=True);last.record();last.synchronize()
    elapsed=time.perf_counter()-t0
    return elapsed,first_ready.elapsed_time(last)/1000,carry.live_state_bytes()


def main(root):
    torch.set_num_threads(1)
    ids,nets,_=load(root)
    metrics=[];raw={}
    for W in (128,512,2048):
        for rep in range(4):
            arms=['hx','sdpa'] if rep%2==0 else ['sdpa','hx']
            starts=np.random.default_rng(296812+rep).integers(0,len(ids)-W,8192)
            # Aligned prompt windows within a pair; source tokens come from the original official split.
            for arm in arms:
                net=nets[arm]
                for s in starts[:3]:decode(ids[int(s):int(s)+W-15][None,:],net,arm,W)
                torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
                resident=torch.cuda.memory_allocated()
                t0=time.perf_counter();dts=[];suffix=[]
                while time.perf_counter()-t0<4.:
                    s=int(starts[len(dts)])
                    dt,step,carry=decode(ids[s:s+W-15][None,:],net,arm,W)
                    dts.append(dt);suffix.append(step)
                t=time.perf_counter()-t0
                key=f'{arm}_{W}_{rep}';raw[key+'_host_s']=np.asarray(dts);raw[key+'_last15_device_s']=np.asarray(suffix)
                row=dict(window=W,prefill=W-15,seed=887,kind=arm,repeat=rep,original_prompts=len(dts),
                         predicted_words=16*len(dts),cadence_words_s=16*len(dts)/t,
                         full_16_words_median_ms=1000*float(np.median(dts)),
                         full_16_words_p95_ms=1000*float(np.quantile(dts,.95)),
                         last15_ms_per_word=1000*float(np.median(suffix))/15,
                         state_bytes=carry,prior_live_bytes=resident,
                         peak_live_bytes=torch.cuda.max_memory_allocated(),
                         peak_incremental_bytes=torch.cuda.max_memory_allocated()-resident)
                metrics.append(row);print(key,row['cadence_words_s'],row['last15_ms_per_word'],flush=True)
    rawdest=HERE/'wikitext_times.npz';np.savez_compressed(rawdest,**raw)
    (HERE/'wikitext_clock.json').write_text(json.dumps(dict(device=torch.cuda.get_device_name(),
         torch=str(torch.__version__),rocm=torch.version.hip,seed=887,rows=metrics,
         raw_sha256=hashlib.sha256(rawdest.read_bytes()).hexdigest()),indent=2)+'\n')
if __name__=='__main__':main(Path(sys.argv[1]))
