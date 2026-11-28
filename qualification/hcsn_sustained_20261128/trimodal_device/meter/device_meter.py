"""Clock synchronized real training and autoregressive batch-one inference on the same native APU."""
from pathlib import Path
import gc
from hashlib import sha256
import json
import statistics
import threading
import time
import numpy as np
import torch
from setup_native import inputs

HERE=Path(__file__).resolve().parent
TRIALS=4
BUDGET=5.
REST=3.
def sysfloat(path,scale=1.):
    try:return float(path.read_text())/scale
    except (OSError,ValueError):return None


class Recorder:
    def __init__(self):
        self.hw=next(p for p in Path('/sys/class/hwmon').glob('hwmon*') if (p/'name').read_text().strip()=='amdgpu')
        self.busy=next(Path('/sys/class/drm').glob('card*/device/gpu_busy_percent'))
        self.rows=[];self.stopflag=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        while not self.stopflag.is_set():
            st=np.fromstring(Path('/proc/stat').read_text().splitlines()[0][4:],sep=' ')
            self.rows.append([time.perf_counter(),sysfloat(self.hw/'power1_average',1e6),
                              sysfloat(self.busy),sysfloat(self.hw/'temp1_input',1000),
                              sum(st[:8]), st[3]+st[4]])
            self.stopflag.wait(.10)
    def start(self):
        self.thread.start()
    def close(self):
        self.stopflag.set();self.thread.join()
    def interval(self,t0,t1):
        v=np.asarray(self.rows,dtype=float)
        use=v[(v[:,0]>=t0)&(v[:,0]<=t1)]
        dt=use[-1,0]-use[0,0]
        J=float(np.trapezoid(use[:,1],x=use[:,0]))
        return dict(seconds=t1-t0,sample_n=len(use),sample_span_s=float(dt),sampled_joules=J,
                    mean_ppt_w=J/dt,mean_gpu_busy=float(np.mean(use[:,2])),
                    cpu_busy_frac=float(1-(use[-1,5]-use[0,5])/(use[-1,4]-use[0,4])),
                    temp_range_c=[float(np.min(use[:,3])),float(np.max(use[:,3]))])


def main():
    data=inputs()
    from network import architecture
    from data import START,PAD,EOS
    from train import BATCH
    assert torch.cuda.is_available() and torch.version.hip
    torch.set_num_threads(1)
    x,y,(tr,dev,held),_,modes,vocab,_=data
    x=x.to('cuda');y=y.to('cuda')
    truth=json.loads((HERE/'result.json').read_text())
    sdir=HERE/'tri_private_scores'
    samples={};records=[];idle=[]
    record=Recorder();record.start()
    def rest(label):
        a=time.perf_counter();time.sleep(REST);b=time.perf_counter()
        idle.append(dict(label=label,**record.interval(a,b)))
    def load(arm):
        report=next(q for q in truth['rows'] if q['arm']==arm)
        f=next(r for r in report['rows'] if 'epoch1' in r['labels'])
        path=sdir/f['weights'];assert sha256(path.read_bytes()).hexdigest()==f['weights_sha256']
        net,_,_=architecture(vocab,arm,137)
        with np.load(path) as W:net.load_state_dict({k:torch.from_numpy(v) for k,v in W.items()})
        return net.to('cuda')
    def go(arm,mode,rep):
        model=load(arm);tridx=torch.as_tensor(tr,device='cuda')
        order=np.random.default_rng(23673+rep).permutation(len(tr))
        batches=[torch.as_tensor(q,device='cuda') for q in np.array_split(order[:96*(len(order)//96)],len(order)//96)]
        h=np.random.default_rng(92637+rep).permutation(held)
        opt=torch.optim.AdamW(model.parameters(),lr=.002,weight_decay=.01)
        def train_step(i):
            ix=tridx[batches[i%len(batches)]]
            z=model(x[ix])[:,START:];t=y[ix]
            loss=torch.nn.functional.cross_entropy(z.reshape(-1,vocab),t.flatten(),ignore_index=-100)
            opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            opt.step()
            return 96
        def stream_step(i):
            with torch.no_grad():
                obs=x[h[i%len(h)]:h[i%len(h)]+1].clone()
                # Input includes both conditioning streams and the target marker, with no target suffix.
                obs[:,START+1:]=PAD;done=torch.zeros(1,dtype=torch.bool,device='cuda')
                for t in range(17):
                    nxt=model(obs[:,:START+t+1])[:,-1].argmax(-1)
                    nxt=torch.where(done,PAD,nxt);done|=nxt==EOS
                    if t<16:obs[:,START+t+1]=nxt
                return 17
        run=train_step if mode=='train_96' else stream_step
        model.train(mode=='train_96')
        for i in range(3):run(i)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        lat=[];units=0
        start=time.perf_counter();t=start
        while t-start<BUDGET:
            a=time.perf_counter();units+=run(len(lat));torch.cuda.synchronize()
            t=time.perf_counter();lat.append(t-a)
        q=record.interval(start,t)
        q.update(arm=arm,mode=mode,repeat=rep,units=units,throughput=units/(t-start),
                 repetitions=len(lat),latency_median_ms=1000*float(np.median(lat)),
                 latency_p95_ms=1000*float(np.quantile(lat,.95)),peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                 peak_reserved_bytes=torch.cuda.max_memory_reserved())
        key=arm+'_'+mode+'_'+str(rep);samples[key]=np.array(lat)
        records.append(q);print(key,q['throughput'],q['mean_ppt_w'],flush=True)
        del opt,model;gc.collect();torch.cuda.empty_cache()
    rest('initial')
    schedule=[('train_96',False),('stream_1',True),('stream_1',False),('train_96',True)]
    for rep in range(TRIALS):
        block=schedule[rep:]+schedule[:rep]
        # One train and one stream pair per repetition, counterbalanced order.
        used=set()
        for mode,rev in block:
            if mode in used:continue
            used.add(mode)
            arms=['financial','sdpa_matched']
            if bool((rep%2) ^ (mode=='stream_1')):arms.reverse()
            rest(mode+'_'+str(rep)+'_before')
            for arm in arms:go(arm,mode,rep)
            rest(mode+'_'+str(rep)+'_after')
    record.close()
    trace=HERE/'device_meter_raw.npz'
    np.savez_compressed(trace,telemetry=np.asarray(record.rows),**samples)
    out=dict(hardware=torch.cuda.get_device_name(0),torch=str(torch.__version__),hip=torch.version.hip,
             source_checkpoint='epoch1',timing='device synchronized at batch/utterance boundaries',
             train_units='examples, batch=96',stream_units='17 unmasked autoregressive forward steps per utterance from two observed streams, batch=1, prefix recomputation',
             raw_sha256=sha256(trace.read_bytes()).hexdigest(),sampling_columns=['monotonic_s','APU_PPT_W','gpu_busy_percent','gpu_edge_C','cpu_total_ticks','cpu_idle_ticks'],
             meter_label=(record.hw/'power1_label').read_text().strip(),idle=idle,rows=records)
    (HERE/'device_meter.json').write_text(json.dumps(out,indent=2)+'\n')
if __name__=='__main__':main()
