"""Opt-in create-only successor CLI for the existing P2 25-process-CPU run.

This wrapper calls the UNCHANGED v2 training function in process memory,
then atomically publishes a canonical self-verifying receipt. It never writes
mutable JSON outputs. Historical v2 files are NOT retroactively considered
immutable and no additional model efficacy is asserted here.
"""
import argparse
import json
from pathlib import Path

from .immutable_trial_receipts import (ARMS,SEEDS,TASKS,UnresolvedReceipt,
                                      publish,read,seal,verify_seal,recover_stages)


def run_and_publish(task: str, seed: int, arm: str, root: Path):
    if task not in TASKS or type(seed) is not int or seed not in SEEDS or arm not in ARMS:
        raise UnresolvedReceipt('unregistered live P2 training')
    key=f'{task}.{seed}.{arm}'
    root=Path(root)
    # Avoid spending 25 CPU seconds on an already committed key.
    if (root/'seal.json').exists() or (root/'records'/(key+'.json')).exists():
        raise UnresolvedReceipt('sealed or existing trial; no replace/retrain')
    # Delayed import keeps receipt inspection independent of Torch/training.
    from .timed_cpu_matched_v2 import run
    result=run(task,seed,arm)
    receipt=publish(root,result)
    checked,_=read(root,key)
    if checked.file_sha256!=receipt.file_sha256:
        raise UnresolvedReceipt('post-publication readback mismatch')
    return receipt


def main(argv=None):
    ap=argparse.ArgumentParser(description='P2 immutable trial receipts; NO_GO')
    sub=ap.add_subparsers(dest='operation',required=True)
    run=sub.add_parser('run');run.add_argument('--task',required=True,choices=TASKS)
    run.add_argument('--seed',type=int,required=True,choices=SEEDS)
    run.add_argument('--arm',required=True,choices=ARMS)
    for name in ('run','seal','verify','recover'):
        parser=run if name=='run' else sub.add_parser(name)
        parser.add_argument('--archive',required=True,type=Path)
        if name=='recover':parser.add_argument('--quiescent',action='store_true')
    args=ap.parse_args(argv)
    if args.operation=='run':
        r=run_and_publish(args.task,args.seed,args.arm,args.archive)
        out={'key':r.key,'receipt_sha256':r.file_sha256,
             'payload_sha256':r.payload_sha256,'production_activation':False,
             'all_scientific_blockers_closed':False}
    elif args.operation=='seal':
        out={'sealed_sha256':seal(args.archive),'record_count':12,
             'production_activation':False,'all_scientific_blockers_closed':False}
    elif args.operation=='verify':out=verify_seal(args.archive)
    else:
        out={'recovery':recover_stages(args.archive,quiescent=args.quiescent),
             'production_activation':False,'all_scientific_blockers_closed':False}
    print(json.dumps(out,sort_keys=True))
    return out


if __name__=='__main__':main()
