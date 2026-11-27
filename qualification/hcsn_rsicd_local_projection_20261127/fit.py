"""One sealed case of forward-only local construction, including all completed/deadline costs."""
import time
ENTRY=time.perf_counter();ENTRYCPU=time.process_time()
import argparse
import resource
from construct import *


@torch.inference_mode()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('work',type=Path);ap.add_argument('arm',choices=ARMS);ap.add_argument('seed',type=int,choices=SEEDS);a=ap.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    def reject_backward(*args,**kwargs):
        raise RuntimeError('Local forward arms cannot call automatic differentiation')
    torch.Tensor.backward=reject_backward;torch.autograd.grad=reject_backward;torch.autograd.backward=reject_backward
    d=FitData(a.work)
    out=a.work/'fits'/f'{a.arm}-{a.seed}';out.mkdir(exist_ok=True,parents=True)
    if (out/'done.json').exists():raise FileExistsError(out/'done.json')
    if (out/'history.json').exists():raise RuntimeError('incomplete development history must be preserved before a retry')
    m=original(a.seed,d);tick=time.perf_counter();cpu=time.process_time();setup=tick-ENTRY;setupcpu=cpu-ENTRYCPU
    hist=[];rows=[]
    def record(step,nll,state,digest,info,roster,nt):
        e={'prefix':step,'dev_token_nll':float(nll),'state':state,'state_sha':digest,'train_tokens':nt,
          'batch_digests':roster,'candidate_parts':info,'wall_s':time.perf_counter()-tick,'cpu_s':time.process_time()-cpu}
        assert e['wall_s']>=e['cpu_s']*.80
        hist.append(e);write(out/'history.json',hist);print(a.arm,a.seed,step,round(e['wall_s'],2),round(e['cpu_s'],2),round(nll,5),flush=True)
    t=time.perf_counter();l,c=eval_rows(m,d,d.index['development']);assert c.sum()==1291
    path=out/'p0.pt';h=save_recipe(path,{'writes':{}})
    record(0,l.sum()/c.sum(),path.name,h,{'evaluation_wall':time.perf_counter()-t},[],0)
    for step in PREFIXES:
        if min(time.perf_counter()-tick,time.process_time()-cpu)>=max(TIMES):break
        p,x,y,ids,roster=sampled_data(d,a.seed,step);nt=int((y!=0).sum())
        t=time.perf_counter();base=original(a.seed,d)
        recipe,diag=construct(base,p,x,y,ids,a.arm,a.seed)
        fitwall=time.perf_counter()-t
        learned=Probe(base,recipe['probe']) if 'probe' in recipe else base
        t=time.perf_counter();l,c=eval_rows(learned,d,d.index['development']);assert c.sum()==1291 and np.isfinite(l).all()
        devwall=time.perf_counter()-t;t=time.perf_counter();path=out/f'p{step}.pt'
        digest=save_recipe(path,recipe);write(out/f'p{step}-design.json',diag)
        modelhash={k:tensor_sha(v) for k,v in base.named_parameters()}
        if 'probe' in recipe:modelhash['independent_probe.weight']=tensor_sha(recipe['probe'])
        write(out/f'p{step}-parameters.json',modelhash)
        record(step,l.sum()/c.sum(),path.name,digest,{'fit_and_all_feature_pass_wall':fitwall,'evaluation_wall':devwall,
          'serialization_and_parameter_hashes_wall':time.perf_counter()-t,'roster_sha256':hashlib.sha256(''.join(roster).encode()).hexdigest(),
          'distinct_images_in_prefix':len(set(ids)),'parameter_record':f'p{step}-parameters.json','design_record':f'p{step}-design.json'},roster,nt)
        del recipe,diag,base,learned
    endwall=time.perf_counter()-tick;endcpu=time.process_time()-cpu
    modes={}
    for clock in ('wall_s','cpu_s'):
        for b in TIMES:
            eligible=[r for r in hist if r[clock]<=b]
            modes[clock+str(b)]=min(eligible,key=lambda q:(q['dev_token_nll'],q[clock])) if eligible else None
    for step in (0,4,16):modes['step'+str(step)]=next((r for r in hist if r['prefix']==step),None)
    write(out/'done.json',{'arm':a.arm,'seed':a.seed,'setup_process_wall':setup,'setup_process_cpu':setupcpu,
        'fit_development_save_total_wall':endwall,'fit_development_save_total_cpu':endcpu,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'autograd_backward_and_grad_guard':True,'core':sorted(os.sched_getaffinity(0)),'history_sha256':sha(out/'history.json'),'selected':modes})


if __name__=='__main__':main()
