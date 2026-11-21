"""One frozen, finite study of compiled fixed-law transport on real checkpoints."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from qualification.hcsn_currentstate.differentiable import Work
from qualification.hcsn_network.benchmark_data import training_data
from qualification.hcsn_network.benchmark_models import make_model
from qualification.hcsn_network.checkpoint import state_to_record, state_from_record
from specialize import compile_flow, apply_flow, readout_features

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write('\n')


def flatten(value, prefix='root'):
    tensors, metadata = {}, {}
    def walk(obj, key):
        if isinstance(obj, torch.Tensor):
            tensors[key] = obj.detach().cpu().numpy()
        elif isinstance(obj, dict):
            for name in sorted(obj):
                walk(obj[name], key+'.'+name)
        elif isinstance(obj, (list, tuple)):
            metadata[key+'.length'] = len(obj)
            for index, item in enumerate(obj):
                walk(item, key+f'.{index}')
        else:
            metadata[key] = obj
    walk(value, prefix)
    return tensors, metadata


def compare(out, name, left, right, protocol):
    la, lm = flatten(left); ra, rm = flatten(right)
    if lm != rm or la.keys() != ra.keys():
        raise ValueError(('state structure mismatch', name))
    arrays = {}; rows = []
    for key in la:
        a, b = la[key], ra[key]
        if a.shape != b.shape or a.dtype != b.dtype or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError(('array contract', name, key))
        delta = np.abs(a-b)
        bound = protocol['absolute_tolerance'] + protocol['relative_tolerance']*np.abs(a)
        bitdiff = np.count_nonzero(a.view(np.uint64) != b.view(np.uint64))
        rows.append(dict(key=key, shape=list(a.shape), coordinates=a.size,
                         max_abs=float(delta.max(initial=0)), bitwise_mismatches=int(bitdiff),
                         passed=bool(np.all(delta <= bound))))
        arrays['reference::'+key] = a; arrays['specialized::'+key] = b
    np.savez_compressed(out/(name+'.npz'), **arrays)
    save_json(out/(name+'.json'),dict(metadata=lm, rows=rows, passed=all(r['passed'] for r in rows)))
    return dict(name=name, arrays=len(rows), coordinates=sum(r['coordinates'] for r in rows),
                max_abs=max((r['max_abs'] for r in rows),default=0),
                bitwise_mismatches=sum(r['bitwise_mismatches'] for r in rows),
                passed=all(r['passed'] for r in rows))


def timed(fn):
    cpu, wall = time.process_time(), time.perf_counter()
    result = fn()
    return result, {'cpu_seconds':time.process_time()-cpu,'wall_seconds':time.perf_counter()-wall}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    args = parser.parse_args(); out = Path(args.output); out.mkdir(exist_ok=False)
    protocol = json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
    for entry in protocol['sources']:
        if sha(ROOT/entry['path']) != entry['sha256']:
            raise ValueError(('frozen source changed',entry['path']))
    resource.setrlimit(resource.RLIMIT_CPU, (protocol['cpu_limit_seconds'],protocol['cpu_limit_seconds']+2))
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    if torch.__version__ != '2.8.0+cpu':
        raise ValueError('pinned Torch version required')
    started_cpu, started_wall = time.process_time(),time.perf_counter()
    tx, _, _, _, indexes, _ = training_data(ROOT/'originals/data')
    input_train = tx[:64].transpose(0,1).contiguous()
    generator = torch.Generator().manual_seed(protocol['synthetic_input_seed'])
    synthetic = torch.randn(20,8,2,dtype=torch.float64,generator=generator)*0.4
    inputs = [('training64',input_train), ('synthetic1',synthetic[:10,:1].clone()),
              ('synthetic20',synthetic)]
    np.savez_compressed(out/'inputs.npz',train=input_train.numpy(),synthetic=synthetic.numpy(),
                        training_original_indexes=indexes[:64])
    results, rejections, compile_costs = [], [], []
    counters = {'reference_forward':0,'compiled_forward':0,'original_classifier_forward':0,
                'reference_exponentials':0,'compile_exponentials':0,'continuation_steps':0,
                'gradient_backward':0,'optimizer_calls':0,'checkpoint_writes':0}
    for arm in protocol['arms']:
        for seed in protocol['seeds']:
            fit = f'{arm}-s{seed}'; folder=out/fit;folder.mkdir()
            checkpoint = ROOT/'originals/campaign/fits'/fit/'selected.pt'
            before = sha(checkpoint)
            selected = torch.load(checkpoint,map_location='cpu',weights_only=True)
            model = make_model(arm);model.load_state_dict(selected['model'],strict=True);model.eval()
            with torch.no_grad():
                episode, physics_cost = timed(model.episode)
            physics = (episode.physics,episode.physics)
            compilers = {}
            for steps in (10,20):
                compiled, cost = timed(lambda:compile_flow(model.flow,physics,steps))
                compilers[steps]=compiled;counters['compile_exponentials']+=compiled.exponentials
                compile_costs.append(dict(fit=fit,steps=steps,**cost,
                                          exponentials=compiled.exponentials,
                                          bytes=compiled.tensor_bytes(),physics_cost=physics_cost,
                                          kernel_sha256=compiled.kernel_sha256))
            # Authenticate full original source execution separately from frozen-physics timings.
            model.capture_state=True
            with torch.no_grad():
                original_logits=model(input_train.transpose(0,1));counters['original_classifier_forward']+=1
                original_state=state_to_record(model.last_state)
                _, specialized_state=apply_flow(compilers[10],model.flow,input_train,physics)
                specialized_logits=model.readout(readout_features(specialized_state,64,8))
                counters['compiled_forward']+=1
            results.append(dict(fit=fit,case='original_source_parity',**compare(folder,'original-source',
                {'logits':original_logits,'state':original_state},
                {'logits':specialized_logits,'state':state_to_record(specialized_state)},protocol)))
            model.capture_state=False;model.last_state=None
            for case, x in inputs:
                compiled=compilers[len(x)]
                def reference(seq=x):
                    work=Work()
                    emissions,state=model.flow(seq,physics,work=work)
                    logits=model.readout(readout_features(state,seq.shape[1],8))
                    counters['reference_forward']+=1;counters['reference_exponentials']+=work.exponentials
                    return emissions,state,logits
                def optimized(seq=x):
                    emissions,state=apply_flow(compiled,model.flow,seq,physics)
                    logits=model.readout(readout_features(state,seq.shape[1],8))
                    counters['compiled_forward']+=1
                    return emissions,state,logits
                with torch.no_grad():
                    (re,rs,rl),ref_first=timed(reference)
                    (ce,cs,cl),opt_first=timed(optimized)
                    evidence=compare(folder,case+'-full',
                        {'emissions':re,'state':state_to_record(rs),'logits':rl},
                        {'emissions':ce,'state':state_to_record(cs),'logits':cl},protocol)
                    same_class=bool(torch.equal(rl.argmax(1),cl.argmax(1)))
                    # Cold reconstruction discards previous AD graph on both paths.
                    rr=state_from_record(state_to_record(rs));cr=state_from_record(state_to_record(cs))
                    next_input=x[-1].clone()*0.25
                    rw,cw=Work(),Work()
                    ro,rnext=model.flow.step(next_input,rr,physics,rw)
                    co,cnext=model.flow.step(next_input,cr,physics,cw)
                    counters['continuation_steps']+=2
                    counters['reference_exponentials']+=rw.exponentials+cw.exponentials
                    continuation=compare(folder,case+'-cold',
                        {'emission':ro,'state':state_to_record(rnext)},
                        {'emission':co,'state':state_to_record(cnext)},protocol)
                    timing=[]
                    for repeat in range(protocol['timing_repeats']):
                        order=(('reference',reference),('specialized',optimized)) if repeat%2==0 else (('specialized',optimized),('reference',reference))
                        for label,fn in order:
                            _,cost=timed(fn);timing.append(dict(repeat=repeat,path=label,**cost))
                # Only writers/readout/input remain differentiable. Physics cache is constant.
                gradients=[]
                for fn in (reference,optimized):
                    model.zero_grad(set_to_none=True)
                    gx=x.detach().clone().requires_grad_()
                    em,st,logits=fn(gx)
                    weights=torch.arange(1,11,dtype=torch.float64)/10
                    loss=(logits*weights).sum()/gx.shape[1]+0.01*em.square().sum()/gx.numel()
                    loss.backward();counters['gradient_backward']+=1
                    grad={'input':gx.grad.clone()}
                    for name,param in model.named_parameters():
                        if name=='raw_cost':
                            if param.grad is not None:raise ValueError('frozen physics unexpectedly has gradient')
                        else:
                            if param.grad is None:raise ValueError(('missing trainable gradient',name))
                            grad[name]=param.grad.clone()
                    gradients.append(grad)
                gradient=compare(folder,case+'-gradients',gradients[0],gradients[1],protocol)
                results.append(dict(fit=fit,case=case,full=evidence,cold=continuation,gradient=gradient,
                                    same_argmax=same_class,reference_first=ref_first,specialized_first=opt_first,
                                    timings=timing,full_state_bytes=rs.tensor_bytes(),
                                    specialized_full_state_bytes=cs.tensor_bytes()))
            # Operational faults must reject. They do not evaluate scientific outcomes.
            compiled=compilers[10]
            faults=[('horizon',lambda:apply_flow(compiled,model.flow,input_train[:9],physics)),
                    ('physics',lambda:apply_flow(compiled,model.flow,input_train,
                      (replace(physics[0],discount=physics[0].discount+0.01),physics[1]))),
                    ('physics_gradient',lambda:apply_flow(compiled,model.flow,input_train,
                      (replace(physics[0],discount=physics[0].discount.clone().requires_grad_()),physics[1])))]
            for name,fn in faults:
                try:fn()
                except ValueError as exc:rejections.append(dict(fit=fit,fault=name,rejected=True,reason=str(exc)))
                else:raise ValueError(('failed rejection',name))
            model.flow.rate_drive=True
            try:apply_flow(compiled,model.flow,input_train,physics)
            except ValueError as exc:rejections.append(dict(fit=fit,fault='rate_drive',rejected=True,reason=str(exc)))
            else:raise ValueError('failed rate-drive rejection')
            model.flow.rate_drive=False
            with torch.no_grad():compiled.kernels[0].hit_kernel[0,0]+=0.01
            try:apply_flow(compiled,model.flow,input_train,physics)
            except ValueError as exc:rejections.append(dict(fit=fit,fault='kernel_tamper',rejected=True,reason=str(exc)))
            else:raise ValueError('failed kernel tamper rejection')
            # Fault affects disposable cache only; original checkpoint and parameter bytes are unchanged.
            restored={name:torch.equal(value,model.state_dict()[name]) for name,value in selected['model'].items()}
            if not all(restored.values()) or sha(checkpoint)!=before:
                raise ValueError('original weights changed')
            save_json(folder/'UNCHANGED.json',{'checkpoint_sha256':before,'all_tensor_bytes_equal':all(restored.values())})
            print(json.dumps({'completed_fit':fit,'comparisons':len(results),'cpu':time.process_time()-started_cpu}),flush=True)
    passed=all(r.get('passed',True) and all(r[k]['passed'] for k in ('full','cold','gradient') if k in r)
               and r.get('same_argmax',True) for r in results)
    save_json(out/'RESULTS.json',dict(status='COMPLETE',semantic_tolerance_passed=passed,
        bitwise_qualification_claimed=False,original_test_quality_claimed=False,production_eligible=False,
        protocol_sha256=sha(ROOT/'PROTOCOL_FROZEN.json'),results=results,rejections=rejections,
        compile_costs=compile_costs,counters=counters,
        body_cpu_seconds=time.process_time()-started_cpu,body_wall_seconds=time.perf_counter()-started_wall,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024))
    if not passed:raise SystemExit(2)


if __name__=='__main__':
    main()
