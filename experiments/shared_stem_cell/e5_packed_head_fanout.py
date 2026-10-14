#!/usr/bin/env python3
"""Real CPU *packed* (not independent Python modules) 9,744-param Heads.

Synthetic feature only; no pretrained Encoder or production Worker. An exact
batch-size>1 Head matrix and a zero-stride shared feature view are executed.
"""
from __future__ import annotations
import argparse, hashlib, json, math, resource, time
from pathlib import Path

class Invalid(ValueError): pass
SCALES=(64,256,1024,4096)
PER_HEAD=9744


def parameterize(torch, count, seed):
    torch.manual_seed(seed)
    def draw(shape, fan_in):
        x=torch.empty(shape,dtype=torch.float32)
        torch.nn.init.uniform_(x, -1/(fan_in**.5), 1/(fan_in**.5))
        return x
    tensors={
       'down.weight':draw((count,8,384),384),
       'gate.weight':draw((count,8,64),64),
       'gate.bias':draw((count,8),64),
       'up.weight':torch.zeros((count,384,8),dtype=torch.float32),
       'output.weight':draw((count,8,384),384),
       'output.bias':draw((count,8),384),
    }
    if sum(v.numel() for v in tensors.values())!=count*PER_HEAD:raise Invalid('Head count')
    return tensors


def packed_forward(torch, weights, feature, state):
    n=state.shape[0]
    if feature.shape!=(n,384) or state.shape!=(n,64):raise Invalid('feature/state shape')
    for tag,shape in (('down.weight',(n,8,384)),('gate.weight',(n,8,64)),
                      ('gate.bias',(n,8)),('up.weight',(n,384,8)),
                      ('output.weight',(n,8,384)),('output.bias',(n,8))):
        if weights[tag].shape!=shape:raise Invalid('weight shape drift '+tag)
    down=torch.bmm(weights['down.weight'],feature.unsqueeze(-1)).squeeze(-1)
    gate=torch.bmm(weights['gate.weight'],state.unsqueeze(-1)).squeeze(-1)+weights['gate.bias']
    hidden=torch.nn.functional.silu(down)*torch.sigmoid(gate)
    residual=torch.bmm(weights['up.weight'],hidden.unsqueeze(-1)).squeeze(-1)
    logits=torch.bmm(weights['output.weight'],(feature+residual).unsqueeze(-1)).squeeze(-1)+weights['output.bias']
    return logits


def run(logical_cells=4096, active_cells=409, seed=20261014, repeats=15):
    if logical_cells not in SCALES or type(active_cells) is not int or not 1<=active_cells<=logical_cells or type(seed) is not int or type(repeats) is not int or not 2<=repeats<=100:
        raise Invalid('invalid packed cohort')
    import torch,psutil
    torch.set_num_threads(1)
    start=time.perf_counter_ns();started_cpu=time.process_time_ns();proc=psutil.Process()
    all_weights=parameterize(torch,logical_cells,seed)
    weights={k:v[:active_cells] for k,v in all_weights.items()}
    common=torch.round(torch.linspace(-1,1,384,dtype=torch.float32)*(1<<24))/(1<<24)
    expanded=common.reshape(1,-1).expand(active_cells,-1)
    states=((torch.arange(active_cells,dtype=torch.float32)%23-11)/20).reshape(-1,1).expand(-1,64)
    if expanded.untyped_storage().data_ptr()!=common.untyped_storage().data_ptr() or expanded.stride(0)!=0:
        raise Invalid('not a shared physical feature buffer')
    rss_ready=proc.memory_info().rss
    hashes=hashlib.sha256(b'hepta.e5.packed-batch-outputs.v1')
    times=[]
    with torch.inference_mode():
        first=packed_forward(torch,weights,expanded,states)
        if first.shape!=(active_cells,8) or not bool(torch.isfinite(first).all()):raise Invalid('invalid batched output')
        for _ in range(repeats):
            tick=time.perf_counter_ns()
            out=packed_forward(torch,weights,expanded,states)
            times.append((time.perf_counter_ns()-tick)/1e6)
            hashes.update(out.contiguous().numpy().tobytes())
    if min(times)<=0:raise Invalid('unmeasured physical execution')
    return {'schema':'hepta.e5.packed-physical-cpu-head-v1','authority':'DENY_ALL',
            'production_promotion_permitted':False,'real_cpu_pytorch_batched_forward':True,
            'pretrained_encoder_executed':False,'production_worker_verified':False,
            'synthetic_feature_and_state':True,'independent_future_ndu':False,
            'logical_cells':logical_cells,'active_cells':active_cells,'seed':seed,'batch_repeats':repeats,
            'complete_head_parameters':sum(v.numel() for v in all_weights.values()),
            'physical_head_weight_tensors':len(all_weights),
            'physical_input_feature_buffers':1,
            'physical_input_feature_payload_bytes':common.numel()*common.element_size(),
            'reported_batch_forward_p50_ms':sorted(times)[len(times)//2],
            'reported_batch_forward_p95_ms':sorted(times)[math.ceil(.95*len(times))-1],
            'reported_batch_forward_p99_ms':sorted(times)[math.ceil(.99*len(times))-1],
            'batch_forward_samples':len(times),'p99_independently_qualified':False,
            'per_cell_equivalent_loop_ms_mean':sum(times)/len(times)/active_cells,
            'measured_wall_ms':(time.perf_counter_ns()-start)/1e6,
            'measured_cpu_ms':(time.process_time_ns()-started_cpu)/1e6,
            'measured_rss_ready_bytes':rss_ready,
            'measured_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'sampled_output_sha256':hashes.hexdigest(),
            'power_or_gpu_evidence':None}


def main():
    p=argparse.ArgumentParser();p.add_argument('--cells',type=int,required=True)
    p.add_argument('--active',type=int,required=True)
    p.add_argument('--repeats',type=int,default=15)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('create-only output')
    result=run(a.cells,a.active,repeats=a.repeats)
    with a.output.open('x',encoding='utf8') as h:json.dump(result,h,indent=2,sort_keys=True,allow_nan=False);h.write('\n')
if __name__=='__main__':main()
