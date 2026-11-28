"""One CUDA allocator-isolated dimension/precision/transport measurement."""
import argparse
import json
import math
from pathlib import Path
import statistics
import time

import numpy as np
import torch
from fft_transport import transported_mass
from population import BoundaryPopulation, ContinuousSpikingNetwork
from telemetry import BoardMeter


def physical_grid(atoms, dtype, mode):
    layer=BoundaryPopulation(1,1,atoms).to(device='cuda',dtype=dtype)
    batch=4
    ix=torch.arange(batch,device='cuda',dtype=dtype)[:,None]
    x=layer.grid[None,:]
    mass=(.2+torch.cos(2+ix/9+6*x).square())*torch.exp(-((x-.17-.13*ix)/.42).square())
    mass=(mass/mass.sum(-1,keepdim=True)).detach().requires_grad_()
    shift=x.new_tensor([.023,-.031,.123,-.171]).requires_grad_()
    principal=x.new_tensor([50.5,60.25,69.75,74.5]).requires_grad_()
    coefficients=x.new_tensor([.35,.08,-.11,.15])
    query=torch.sin(4*x)
    def step():
        if mode=='dense':
            survival,hits=layer.kernels(layer.grid+shift[:,None])
            moved=(mass[:,:,None]*survival).sum(-2)
            flow=(mass*hits).sum(-1)
        else:
            moved,flow=transported_mass(mass,shift,layer.grid,sigma=layer.prices.p.sigma,
                                       a=layer.prices.a,dt=layer.dt)
        equity,shortage=layer.priced_channels(principal)
        outputs=torch.stack((flow,(moved*equity).sum(-1),(moved*shortage).sum(-1),(moved*query).sum(-1)),dim=-1)
        loss=(outputs*coefficients).sum()+.05*moved.square().sum()
        dm,ds,dp=torch.autograd.grad(loss,(mass,shift,principal))
        return {'mass':moved,'flow':flow,'prices_equity_loss':outputs[:,1:3],
                'probe':outputs[:,3],'grad_mass':dm,'grad_shift':ds,'grad_principal':dp,
                'balance':moved.sum(-1)+flow}
    return step


def network_grid(atoms,dtype,mode):
    torch.manual_seed(7632)
    model=ContinuousSpikingNetwork(2,2,2,atoms,port='priced',matrix_free=mode=='fft').to(device='cuda',dtype=dtype)
    frames=torch.tensor([[[.3,-.6]],[[1.,.4]],[[-.4,.8]]],device='cuda',dtype=dtype,requires_grad=True)
    def step():
        output,((m1,f1,b1,p1),(m2,f2,b2,p2))=model(frames)
        loss=output.square().sum()+.05*(p2.square().sum()+m1.square().sum())
        grad=torch.autograd.grad(loss,(*model.parameters(),frames))
        return {'network_output':output,'mass1':m1,'mass2':m2,'flow1':f1,'flow2':f2,'b1':b1,'b2':b2,
                'prices1':p1,'prices2':p2,
                'network_grad':torch.cat([g.flatten() for g in grad])}
    return step


def timed(step):
    begin=torch.cuda.Event(enable_timing=True)
    end=torch.cuda.Event(enable_timing=True)
    start=time.perf_counter()
    begin.record()
    ans=step()
    end.record()
    torch.cuda.synchronize()
    wall=time.perf_counter()-start
    return wall,begin.elapsed_time(end)/1000,ans


def run(args):
    torch.cuda.set_per_process_memory_fraction(.75,0)
    torch.set_num_threads(1)
    dt={'float32':torch.float32,'float64':torch.float64}[args.dtype]
    tag=f'{args.kind}_{args.dtype}_{args.atoms}_{args.mode}'
    report={'kind':args.kind,'dtype':args.dtype,'atoms':args.atoms,'mode':args.mode,
            'gpu':torch.cuda.get_device_name(),'torch':str(torch.__version__),
            'allocator_fraction':.75,'status':'initial'}
    try:
        make=physical_grid if args.kind=='operator' else network_grid
        step=make(args.atoms,dt,args.mode)
        warm=[]
        for _ in range(3):
            wall,_,out=timed(step)
            warm.append(wall)
            del out
        # Per-call reported metrics divide by the actual number of complete forwards and reverses.
        n=max(3,min(384,math.ceil(2.0/statistics.median(warm))))
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        base=torch.cuda.memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        walls=[];events=[]
        with BoardMeter() as meter:
            for i in range(n):
                tw,te,ans=timed(step)
                walls.append(tw);events.append(te)
                if i+1<n:del ans
        peak=torch.cuda.max_memory_allocated()
        traces={name:v.detach().cpu().numpy() for name,v in ans.items()}
        np.savez_compressed(args.folder/(tag+'.npz'),**traces)
        if not all(np.isfinite(v).all() for v in traces.values()):raise ValueError('nonfinite scientific output')
        energy=meter.result
        energy['scope']='whole GPU board during synchronized repeated warmed calls, including Python loop and NVML samples'
        report.update(status='ok',repetitions=n,warmup_wall_s=warm,wall_s=walls,cuda_event_s=events,
                      wall_median_s=statistics.median(walls),cuda_event_median_s=statistics.median(events),
                      base_allocated_bytes=base,peak_allocated_bytes=peak,
                      incremental_peak_bytes=peak-base,peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                      energy=energy,joules_per_call=energy['board_counter_joules']/n if energy['board_counter_joules'] is not None else None)
    except torch.cuda.OutOfMemoryError as exc:
        report.update(status='oom',error=str(exc)[:900],peak_allocated_bytes=torch.cuda.max_memory_allocated())
    (args.folder/(tag+'.json')).write_text(json.dumps(report,allow_nan=False))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--dtype',choices=('float32','float64'),required=True)
    p.add_argument('--mode',choices=('dense','fft'),required=True)
    p.add_argument('--atoms',type=int,required=True)
    p.add_argument('--kind',choices=('operator','network'),required=True)
    run(p.parse_args())
