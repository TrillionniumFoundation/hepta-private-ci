"""Predeclared scalar/grouped SwiGLU study: synthetic features, real CPU fitting.

No pretrained weights, future observation, production selection or native code.
Each arm has identical initial parameters/data/SGD streams and runs independently.
Whole fitting-call timing includes setup inside the fitter and all candidate copies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from development_ablation import PhaseClock, fit_candidate
from development_head_training import SwiGLUCellHead, fit_gated_cells
from development_tensors import parameter_digest

SEEDS = (1414, 2525, 3636)
# heads / width / gated hidden width / output classes / updates per Head
PROFILES = ((1,16,8,2,20), (64,384,8,4,12), (256,384,8,4,6), (4096,64,4,2,3))
SOURCES = ('development_gated_training_study.py','development_head_training.py',
           'development_ablation.py','development_composition.py','development_tensors.py')


def targets(x, family, classes):
    score = (x[:,0], x[:,0]*x[:,1], x[:,0].square()+x[:,1].square()-1.3,
             x[:,0]+x[:,1]*x[:,2])[family]
    if classes == 2: return (score > 0).long()
    return torch.bucketize(score, torch.tensor([-.7,0.,.7]))


def run_study(output, seed):
    output = Path(output)
    if seed not in SEEDS: raise ValueError('unregistered study seed')
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).parent
    source_hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCES}
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    total = PhaseClock()
    results=[]
    try:
        with torch.random.fork_rng(devices=[]):
            warm = PhaseClock()
            torch.manual_seed(seed)
            head=SwiGLUCellHead(4,2,2)
            x=torch.randn(8,4); y=(x[:,0]>0).long()
            fit_candidate(head,x,y,steps=2,seed=seed)
            fit_gated_cells((head,),x,(torch.arange(8),),(y,),seeds=(seed,),steps=2)
            warmup=warm.finish()
            for count,width,hidden,classes,steps in PROFILES:
                setup=PhaseClock()
                torch.manual_seed(seed+count)
                train=torch.randn(64,width)
                heldout=torch.randn(64,width)
                heads=tuple(SwiGLUCellHead(width,hidden,classes) for _ in range(count))
                rows=(torch.arange(64),)*count
                labels=tuple(targets(train,i%4,classes) for i in range(count))
                seeds=tuple(seed+i for i in range(count))
                original=tuple(parameter_digest(h) for h in heads)
                setup_cost=setup.finish()
                models={}; timings={}; counters={}
                order=('scalar','grouped') if seed != 2525 else ('grouped','scalar')
                for arm in order:
                    clock=PhaseClock()
                    if arm=='scalar':
                        fitted=[]; useful=0
                        for h,r,y,local_seed in zip(heads,rows,labels,seeds):
                            m,report=fit_candidate(h,train[r],y,steps=steps,seed=local_seed)
                            fitted.append(m); useful+=report['examples_processed']
                        models[arm]=tuple(fitted)
                        counters[arm]={'optimizer_steps':count*steps,'useful_example_updates':useful,
                                       'physical_example_lanes':useful}
                    else:
                        models[arm],report=fit_gated_cells(heads,train,rows,labels,seeds=seeds,steps=steps)
                        counters[arm]={key:sum(g[key] for g in report['groups'])
                                       for key in ('optimizer_steps','useful_example_updates','physical_example_lanes')}
                    timings[arm]=clock.finish()
                verification=PhaseClock()
                if original != tuple(parameter_digest(h) for h in heads):
                    raise RuntimeError('initial Heads were modified')
                max_parameter_error=0.0
                parameter_equal=True
                for a,b in zip(models['scalar'],models['grouped']):
                    for p,q in zip(a.parameters(),b.parameters()):
                        max_parameter_error=max(max_parameter_error,float((p-q).abs().max().detach()))
                        parameter_equal = parameter_equal and torch.equal(p,q)
                        torch.testing.assert_close(p,q,rtol=2e-5,atol=2e-6)
                with torch.no_grad():
                    frozen=torch.stack([h(heldout) for h in heads])
                    scalar=torch.stack([h(heldout) for h in models['scalar']])
                    grouped=torch.stack([h(heldout) for h in models['grouped']])
                torch.testing.assert_close(scalar,grouped,rtol=2e-5,atol=2e-6)
                if counters['scalar']['useful_example_updates'] != counters['grouped']['useful_example_updates']:
                    raise RuntimeError('different useful training work')
                # Persist actual predictions before consulting heldout targets.
                path=output/f'predictions-{count}.npz'
                with path.open('xb') as stream:
                    np.savez_compressed(stream,features=heldout.numpy(),frozen=frozen.numpy(),
                                        scalar=scalar.numpy(),grouped=grouped.numpy())
                payload_sha=hashlib.sha256(path.read_bytes()).hexdigest()
                truth=torch.stack([targets(heldout,i%4,classes) for i in range(count)])
                scores={name:int((value.argmax(-1)==truth).sum())
                        for name,value in (('frozen',frozen),('scalar',scalar),('grouped',grouped))}
                results.append({'heads':count,'width':width,'hidden':hidden,'classes':classes,'steps':steps,
                                'setup':setup_cost,'fit':timings,'execution_order':order,'work':counters,
                                'wall_ratio_scalar_over_grouped':timings['scalar']['wall_ns']/timings['grouped']['wall_ns'],
                                'maximum_parameter_error':max_parameter_error,'parameter_bitwise_equal':parameter_equal,
                                'maximum_logit_error':float((scalar-grouped).abs().max()),
                                'classification_disagreements':int((scalar.argmax(-1)!=grouped.argmax(-1)).sum()),
                                'correct':scores,'prediction_count':count*len(heldout),'independent_heldout_inputs':len(heldout),
                                'parameter_count':sum(p.numel() for h in heads for p in h.parameters()),
                                'raw_candidate_parameter_bytes':sum(p.numel()*p.element_size() for h in heads for p in h.parameters()),
                                'predictions':path.name,'prediction_sha256':payload_sha,
                                'source_head_digests':original,'verification':verification.finish()})
                with (output/f'profile-{count}.json').open('x') as stream:
                    json.dump(results[-1],stream,sort_keys=True,indent=2,allow_nan=False)
                print(json.dumps({k:results[-1][k] for k in ('heads','wall_ratio_scalar_over_grouped','classification_disagreements','maximum_parameter_error')}),flush=True)
                del models,heads,scalar,grouped,frozen
            if source_hashes != {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCES}:
                raise RuntimeError('source changed during experiment')
            summary={'schema':'hepta.gated-head-training.study.v1','seed':seed,'source_sha256':source_hashes,
                     'python':sys.version,'torch':torch.__version__,'platform':platform.platform(),'threads':1,
                     'warmup':warmup,'profiles':results,'total':total.finish(),
                     'synthetic_features':True,'pretrained_encoder_executed':False,'same_real_task_quality_established':False,
                     'full_lifecycle_cost_measured':False,'production_authorized':False}
            with (output/'summary.json').open('x') as stream:
                json.dump(summary,stream,sort_keys=True,indent=2,allow_nan=False)
            return summary
    except Exception as error:
        with (output/'FAILED.json').open('x') as stream:
            json.dump({'error':type(error).__name__,'message':str(error),'source_sha256':source_hashes},stream)
        raise
    finally: torch.set_num_threads(previous_threads)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true',required=True)
    parser.add_argument('--seed',type=int,choices=SEEDS,default=SEEDS[0])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run_study(args.output,args.seed)
