"""Verify causal equivalence on every held condition before measuring balanced cached generation."""
from hashlib import sha256
from pathlib import Path
import json
import time
import numpy as np
import torch
from setup_native import inputs
from stream import StreamingDecoder
from device_meter import Recorder
ROOT=Path(__file__).resolve().parent


def main():
    x,y,(tr,dev,held),actors,modes,V,_=inputs()
    from data import START,PAD,EOS,LENGTH
    from network import architecture
    x=x.to('cuda')
    torch.set_num_threads(1)
    trial=json.loads((ROOT/'result.json').read_text())
    nets={}
    for z in trial['rows']:
        cp=next(r for r in z['rows'] if 'epoch1' in r['labels'])
        path=ROOT/'tri_private_scores'/cp['weights']
        assert sha256(path.read_bytes()).hexdigest()==cp['weights_sha256']
        net,d,_=architecture(V,z['arm'],137)
        with np.load(path) as w:net.load_state_dict({k:torch.from_numpy(v) for k,v in w.items()})
        nets[z['arm']]=net.to('cuda').eval()
    with torch.inference_mode():
        parity={}
        for arm,net in nets.items():
            maxerr=n=diff=0
            for group in np.array_split(held,int(np.ceil(len(held)/48))):
                obs=x[group];ref=net(obs)
                cache=StreamingDecoder(net,len(obs),LENGTH)
                # Compare irregular block boundaries and sixteen consecutive single-token appends.
                pieces=[cache.append(obs[:,:1]),cache.append(obs[:,1:9]),cache.append(obs[:,9:34])]
                pieces += [cache.append(obs[:,i:i+1]) for i in range(34,LENGTH)]
                scores=torch.cat(pieces,dim=1)
                maxerr=max(maxerr,float((scores-ref).abs().max()))
                diff+=int((scores.argmax(-1)!=ref.argmax(-1)).sum());n+=scores.numel()
            assert maxerr<5.e-4
            parity[arm]=dict(max_absolute_logit_error=maxerr,differing_argmax=diff,logits=n,
                             observed_conditions=len(held),full_sequence_length=LENGTH)
        telemetry=Recorder();telemetry.start()
        def rest(label):
            start=time.perf_counter();time.sleep(2.5)
            return dict(label=label,**telemetry.interval(start,time.perf_counter()))
        idle=[];rows=[];trace={}
        for rep in range(4):
            for b in ([1,16] if rep%2==0 else [16,1]):
                idle.append(rest(f'{b}_{rep}_before'))
                arms=list(nets)
                if bool((rep%2)^(b==16)):arms.reverse()
                order=np.random.default_rng(81836+rep).permutation(held)
                for arm in arms:
                    net=nets[arm];token=[];times=[]
                    def run_once(idx):
                        cursor=(idx*b)%(len(order)-b)
                        obs=x[order[cursor:cursor+b],:START+1]
                        torch.cuda.synchronize();begin=time.perf_counter()
                        cache=StreamingDecoder(net,b,LENGTH)
                        logits=cache.append(obs)[:,-1]
                        done=torch.zeros(b,dtype=torch.bool,device='cuda')
                        previous=logits.argmax(-1);done|=previous==EOS
                        pre=torch.cuda.Event(enable_timing=True)
                        pre.record()
                        for t in range(16):
                            score=cache.append(previous[:,None])[:,-1]
                            previous=torch.where(done,PAD,score.argmax(-1));done|=previous==EOS
                        end=torch.cuda.Event(enable_timing=True);end.record();end.synchronize()
                        wall=time.perf_counter()-begin
                        return wall,pre.elapsed_time(end)/1000.,cache.state_bytes
                    for i in range(3):run_once(i)
                    torch.cuda.reset_peak_memory_stats();begin=time.perf_counter()
                    while time.perf_counter()-begin<5:
                        wall,dispatch,cache_bytes=run_once(len(times))
                        times.append(wall);token.append(dispatch)
                    end=time.perf_counter();z=telemetry.interval(begin,end)
                    key=f'{arm}_{b}_{rep}'
                    z.update(arm=arm,batch=b,repeat=rep,utterances=len(times)*b,
                             generated_tokens=len(times)*17*b,tokens_s=len(times)*17*b/(end-begin),
                             utterance_batch_median_ms=1000*float(np.median(times)),
                             utterance_batch_p95_ms=1000*float(np.quantile(times,.95)),
                             post_prefill_gpu_ms_per_step=1000*float(np.median(token))/16,
                             carry_or_kv_bytes=cache_bytes,peak_allocated_bytes=torch.cuda.max_memory_allocated())
                    rows.append(z);trace[key+'_host_s']=np.asarray(times);trace[key+'_device_suffix_s']=np.asarray(token)
                    print(key,z['tokens_s'],z['carry_or_kv_bytes'],flush=True)
                idle.append(rest(f'{b}_{rep}_after'))
        telemetry.close()
        raw=ROOT/'stream_raw.npz'
        np.savez_compressed(raw,samples=np.asarray(telemetry.rows),**trace)
        report=dict(device=torch.cuda.get_device_name(0),torch=str(torch.__version__),parity=parity,
                    prefill_tokens=34,greedy_outputs_per_condition=17,post_prefill_updates=16,
                    raw_sha256=sha256(raw.read_bytes()).hexdigest(),idle=idle,rows=rows)
        (ROOT/'stream_result.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
