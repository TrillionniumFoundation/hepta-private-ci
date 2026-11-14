"""Create-only CLI for future P2 equal-process-CPU training evidence.

Unlike historical v2 --output.write_text, this new entrypoint rejects reuse
of the same run-ID path and stores source fingerprints in the saved record.
The old experiment's observations and source are deliberately untouched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import scipy
import torch

from . import event_content, timed_fire_content, timed_training_budget_pilot, timed_cpu_matched_v2
from .sealed_run_records_v1 import publish_create_only, EvidenceUnresolved

ENTRY_SCHEMA = 'hcsn-p2-cpu-matched-sealed-cli-v1'


def _source_seals() -> dict[str,str]:
    out={}
    for module in (event_content,timed_fire_content,timed_training_budget_pilot,timed_cpu_matched_v2):
        path=Path(module.__file__)
        out[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def run_and_record(task: str, seed: int, arm: str, directory: Path, run_id: str) -> dict:
    if (task not in timed_cpu_matched_v2.TASKS or
            type(seed) is not int or seed not in timed_cpu_matched_v2.SEEDS or
            arm not in timed_cpu_matched_v2.ARMS or
            type(run_id) is not str or
            not run_id.startswith(f'{task}-s{seed}-{arm}-') or
            len(run_id)<len(f'{task}-s{seed}-{arm}-')+8):
        raise EvidenceUnresolved('invalid sealed P2 experiment identity')
    directory=Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise EvidenceUnresolved('sealed output directory unavailable or symlinked')
    # Refuse even before training if the run-id was already published. The
    # atomic link in publish_create_only is the authoritative race guard.
    if (directory/(run_id+'.json')).exists() or (directory/(run_id+'.json')).is_symlink():
        raise EvidenceUnresolved('prior run ID exists: no silent overwrite')
    source_sha=_source_seals()
    result=timed_cpu_matched_v2.run(task,seed,arm)  # actually consumes 25 process-CPU seconds
    if (result.get('schema')!=timed_cpu_matched_v2.SCHEMA or
            result.get('task')!=task or result.get('seed')!=seed or result.get('arm')!=arm or
            result.get('production_activation') is not False or
            result.get('all_scientific_blockers_closed') is not False or
            result.get('reached_cpu_budget') is not True or
            result.get('reached_step_cap') is not False):
        raise EvidenceUnresolved('training did not produce an admitted *record*')
    result=dict(result)
    result['run_id']=run_id
    result['sealed_entry_schema']=ENTRY_SCHEMA
    result['source_sha256']=source_sha
    result['runtime_versions']={'python':sys.version,'torch':torch.__version__,
          'numpy':np.__version__,'scipy':scipy.__version__}
    receipt=publish_create_only(directory,run_id,result)
    receipt['scientific_superiority_certified']=False
    return receipt


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--task',required=True,choices=timed_cpu_matched_v2.TASKS)
    p.add_argument('--seed',required=True,type=int,choices=timed_cpu_matched_v2.SEEDS)
    p.add_argument('--arm',required=True,choices=timed_cpu_matched_v2.ARMS)
    p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--run-id',required=True)
    args=p.parse_args()
    receipt=run_and_record(args.task,args.seed,args.arm,args.output_dir,args.run_id)
    print(json.dumps(receipt,sort_keys=True))  # retain this digest in independent CI logs

if __name__=='__main__':main()
