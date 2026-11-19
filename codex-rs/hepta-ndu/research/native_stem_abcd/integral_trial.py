"""R3 isolated from-scratch trial; original full-law fit and all historical files retained."""
import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np
import scipy
import torch

from integral import IntegralStem, ScalarIntegralStem, fresh_terminals
from models import StateStem, TransformerStem, assign, vector
from problem import decimal_oracle, make_world, terminals
from run import digest, fit, predictions, residual, scores, write_json
from structured import StructuredStem, invariant_probe, panel_specs, panel_world, priced_decisions


def sources():
    return {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}


def model_for(family, seed, intervals=64):
    if family == 'integral': return IntegralStem(seed, intervals)
    if family == 'scalar': return ScalarIntegralStem(seed, intervals)
    if family == 'raw': return StateStem(seed)
    if family == 'mixture': return StructuredStem(seed)
    if family == 'transformer': return TransformerStem(seed)
    if family == 'direct': return None
    raise ValueError('unknown model family')


def panels():
    return panel_specs() + [('tail_spread', 'uniform', 2, 3, 'base')]


def terminal_for(world, family, name):
    values = fresh_terminals(world, family)
    return 4 * values if name == 'tail_spread' else values


def save_arrays(path, arrays):
    with open(path, 'xb') as f: np.savez_compressed(f, **arrays)


def execute(args):
    start = time.perf_counter(), time.process_time()
    args.out.mkdir(parents=True, exist_ok=False)
    plan = dict(schema='hepta.native-stem.integral.r3', family=args.family, optimizer=args.optimizer,
                seed=args.seed, cpu_cap=args.cpu_seconds, intervals=args.intervals,
                source_sha256=sources(), panels=panels(), training='unchanged 12x12x3 full law',
                terminal_seeds=[2026101431,2026101432,2026101433], holdout_selection=False,
                no_pretrained_encoder=True, production_authorized=False)
    plan_hash = write_json(args.out/'PLAN.json', plan)
    write_json(args.out/'STARTED.json', dict(plan_sha256=plan_hash))
    world=make_world(); w=world.tensor()
    g=torch.tensor(terminals(world,'train'),dtype=torch.float64)
    model=model_for(args.family,args.seed,args.intervals)
    initial=None if model is None else vector(model)
    if initial is not None:
        with open(args.out/'INITIAL.npy','xb') as f: np.save(f,initial,allow_pickle=False)
    initialized=time.process_time()
    if args.optimizer=='none':
        fitting=dict(status='direct' if model is None else 'untrained',training_cpu_seconds=0.,counts={})
    else:
        arm={'adam':'A' if args.family=='transformer' else 'B','trf':'C','lbfgs':'B_LBFGS'}[args.optimizer]
        fitting=fit(model,arm,w,g,3,args.cpu_seconds)
    fit_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    selected=None if model is None else vector(model)
    if selected is not None:
        with open(args.out/'WEIGHTS.npy','xb') as f:np.save(f,selected,allow_pickle=False)
    whash=None if selected is None else digest(selected.tobytes())
    write_json(args.out/'WEIGHT_SEAL.json',dict(sha256=whash,intervals=args.intervals))
    raw, timing={}, {}; t=time.process_time()
    for name,family,bits,horizon,intervention in panels():
        ww=panel_world(bits,intervention); terminal=terminal_for(ww,family,name); now=time.process_time()
        raw[name]=predictions(model,'D' if model is None else 'B',ww.tensor(),terminal,horizon)
        if not np.isfinite(raw[name]).all():raise FloatingPointError(name)
        raw[name+'_terminal']=terminal
        timing[name]=dict(cpu_seconds=time.process_time()-now,sha256=digest(raw[name].tobytes()))
    save_arrays(args.out/'PREDICTIONS.npz',raw)
    phash=digest((args.out/'PREDICTIONS.npz').read_bytes())
    write_json(args.out/'PREDICTIONS_SEAL.json',dict(sha256=phash,weights=whash))
    prediction_cpu=time.process_time()-t
    # Oracle evaluation begins only after the complete prediction seal.
    t=time.process_time(); metrics,oracles={},{}
    for name,family,bits,horizon,intervention in panels():
        ww=panel_world(bits,intervention)
        truth=decimal_oracle(ww,raw[name+'_terminal'],horizon);oracles[name]=truth
        out=scores(raw[name],truth,ww,name=='probability_joint')
        out.update(priced_decisions(raw[name],truth))
        prior=raw[name][:-1]
        u=ww.risk*(prior[...,ww.left]-prior[...,ww.right])
        out['derivative_grid_tail_fraction']=float(np.mean(np.abs(u)>4))
        metrics[name]=out
    save_arrays(args.out/'ORACLES.npz',oracles)
    oracle_cpu=time.process_time()-t
    t=time.process_time(); probe={};train_mse=None;replay_max=0.
    if model is not None:
        probe=invariant_probe(model,world)
        with torch.no_grad():train_mse=float(residual(model,w,g,3).square().sum())
        restored=model_for(args.family,args.seed,args.intervals)
        assign(restored,np.load(args.out/'WEIGHTS.npy',allow_pickle=False))
        for name,family,bits,horizon,intervention in panels():
            ww=panel_world(bits,intervention)
            again=predictions(restored,'B',ww.tensor(),raw[name+'_terminal'],horizon)
            replay_max=max(replay_max,float(np.max(np.abs(again-raw[name]))))
        if replay_max>1e-13 or whash!=digest(vector(model).tobytes()):raise AssertionError('replay/weights')
    if plan['source_sha256']!=sources():raise AssertionError('source drift')
    report=dict(plan_sha256=plan_hash,family=args.family,optimizer=args.optimizer,seed=args.seed,
                intervals=args.intervals,cpu_cap=args.cpu_seconds,fit=fitting,metrics=metrics,timings=timing,
                parameter_count=0 if selected is None else selected.size,
                initial_sha256=None if initial is None else digest(initial.tobytes()),selected_sha256=whash,
                weight_change_norm=0. if selected is None else float(np.linalg.norm(selected-initial)),
                prediction_sha256=phash,training_mse=train_mse,invariant_probes=probe,replay_max_error=replay_max,
                phases_cpu_seconds=dict(initialization=initialized-start[1],prediction_seal=prediction_cpu,
                                        oracle_score_save=oracle_cpu,diagnostics_replay=time.process_time()-t),
                training_peak_rss_bytes=fit_peak,process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                whole_main_cpu=time.process_time()-start[1],whole_main_wall=time.perf_counter()-start[0],
                environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,
                                 torch=torch.__version__,platform=platform.platform(),threads=torch.get_num_threads()),
                flops=None,energy_joules=None,production_authorized=False,project_cloud=False,
                general_pmp_solver=False,exact_compute_matched=False)
    write_json(args.out/'REPORT.json',report)
    print(json.dumps(dict(family=args.family,optimizer=args.optimizer,seed=args.seed,
                         composed=metrics['new_composed']['rmse'],probability=metrics['probability_joint']['rmse'])),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--family',choices=['raw','mixture','integral','transformer','direct','scalar'],required=True)
    p.add_argument('--optimizer',choices=['adam','trf','lbfgs','none'],required=True)
    p.add_argument('--seed',type=int,default=11);p.add_argument('--cpu-seconds',type=float,default=8)
    p.add_argument('--intervals',type=int,default=64);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if not np.isfinite(args.cpu_seconds) or args.cpu_seconds<=0 or args.seed<0:p.error('invalid budget/seed')
    if args.family=='direct' and args.optimizer!='none':p.error('direct is not trained')
    if args.family=='transformer' and args.optimizer!='adam':p.error('unsupported Transformer optimizer')
    execute(args)


if __name__=='__main__':main()
