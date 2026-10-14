#!/usr/bin/env python3
"""Opt-in synthetic train -> 20 physical safetensors -> real Rust Q24 mechanism.

No selected production artifact, true Encoder, independently observed labels,
crash recovery or target-host qualification is present. Always NO_PROMOTION.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys

from matched_train import Q, train
from run_native_physical_matrix import evaluate, sha


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(binary: Path, report: Path) -> dict:
    import torch
    from safetensors.torch import save_file
    torch.set_num_threads(1)
    with TemporaryDirectory(prefix='hepta-native-physical-canary-') as temp:
        home = Path(temp)
        baseline = home/'synthetic-unselected-v1.safetensors'
        save_file({'head.weight':torch.zeros((1,32)),
                   'head.bias':torch.zeros((1,))},str(baseline))
        dataset = {
            'schema':'hepta.neuron.frozen-q24-train-input.v1',
            'encoder_digest':sha(b'synthetic-encoder-NOT-pretrained'),
            'cell_id':'synthetic-canary-not-owner',
            'train_cutoff_utc':'2026-10-01T00:00:00Z',
            'samples':[],
        }
        trace_rows=[]
        for i in range(4):
            features=[(Q//8) * ((i+j)%7 - 3) for j in range(32)]
            dataset['samples'].append({
                'case_id':f'train-{i}',
                'source_group':f'isolated-group-{i//2}',
                'sequence':i%2+1,
                'event_time_utc':f'2026-09-2{i+1}T00:00:00Z',
                'feature_q24':features,'label':i%2,
            })
            trace_rows.append({
                'sequence':i+1, 'monotonic_micros':(i+1)*1_000_000,
                'temporal_drive_q24':features,
                'prediction_q24':[0]*32,
            })
        data = home/'synthetic-training.json'
        data.write_text(json.dumps(dataset,sort_keys=True),encoding='utf-8')
        weights = home/'20-physical-synthetic-trained'
        settings=SimpleNamespace(train_data=str(data),train_sha256=file_hash(data),
            selected_v1=str(baseline),selected_v1_sha256=file_hash(baseline),
            synthetic_canary=True,steps=2,window=2,seed=7347,lr=.01,
            max_train_cpu_seconds=90.0, output=str(weights))
        produced=train(settings)
        if len(produced['models'])!=20:
            raise ValueError('training did not physically save 20 distinct arm/tier files')
        trace={
            'schema':'hepta.neuron.physical-q24-shadow-trace.v1',
            'scope_digest':sha(b'synthetic-only-scope'),
            'objective_digest':sha(b'synthetic-only-objective'),
            'ndu_digest':sha(b'synthetic-untrusted-ndu'),
            'body_digest':sha(b'synthetic-only-body'),
            'events':trace_rows,
        }
        trace_file=home/'unlabelled-synthetic-q24-trace.json'
        trace_file.write_text(json.dumps(trace,sort_keys=True),encoding='utf-8')
        result=evaluate(binary, file_hash(binary), weights,
                        file_hash(weights/'training-receipt.json'),
                        trace_file,file_hash(trace_file),synthetic_canary=True)
        # Native Rust must reject physical material violations even when an
        # attacker supplies a freshly matching file SHA. These are isolated
        # synthetic negatives: they do not exercise a real model owner.
        import subprocess
        from safetensors.torch import load_file
        source_file=weights/'2048'/'v3.safetensors'
        original=load_file(str(source_file),device='cpu')
        def run_negative(name, changed, *, bad_trace=None, stale_sha=False):
            local=home/(name+'.safetensors')
            save_file(changed,str(local))
            current_trace=trace_file if bad_trace is None else bad_trace
            command=[str(binary),'--arm','v3','--model',str(local),
                     '--model-sha256',(file_hash(source_file) if stale_sha else file_hash(local)),
                     '--trace',str(current_trace),'--trace-sha256',file_hash(current_trace),
                     '--cap','2048']
            proc=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL,timeout=30,check=False)
            if proc.returncode == 0 or b'BLOCKED_PHYSICAL_NATIVE_Q24_SHADOW' not in proc.stderr:
                raise ValueError(f'{name}: native invalid weights/trace unexpectedly accepted')
            return {'test':name,'rejected_by_native_rust':True}
        negatives=[]
        changed={k:v.clone() for k,v in original.items()}
        changed['temporal.gate_bias'][0]=-1
        negatives.append(run_negative('negative-native-q24-gate-bias',changed))
        changed={k:v.clone() for k,v in original.items()}
        changed['head.weight'][0,0]=float('nan')
        negatives.append(run_negative('nonfinite-native-head',changed))
        changed={k:v.clone() for k,v in original.items()}
        changed['head.weight']=torch.zeros((2,16),dtype=torch.float32)
        negatives.append(run_negative('same-count-wrong-native-head-shape',changed))
        changed={k:v.clone() for k,v in original.items()}
        changed['temporal.gate_bias'][0]=(changed['temporal.gate_bias'][0]+1).clamp(0,Q)
        negatives.append(run_negative('changed-sha-native-model',changed,stale_sha=True))
        invalid_trace=dict(trace)
        invalid_trace['events']=[dict(row) for row in trace['events']]
        invalid_trace['events'][1]['sequence']=1  # duplicate logical sequence
        bad_trace=home/'invalid-duplicate-sequence-trace.json'
        bad_trace.write_text(json.dumps(invalid_trace,sort_keys=True),encoding='utf-8')
        negatives.append(run_negative('duplicate-native-trace-sequence',
                                      {k:v.clone() for k,v in original.items()},bad_trace=bad_trace))
        result['native_negative_cases_rejected']=len(negatives)
        result['native_negative_cases']=negatives
        with report.open('x',encoding='utf-8') as out:
            json.dump(result,out,sort_keys=True,indent=2)
            out.write('\n')
        return result


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    try:
        report=run(args.binary,args.report)
        if (report['twenty_native_physical_model_executions'] != 20
                or report['production_qualification'] is not False):
            raise ValueError('native physical matrix failed or claimed authority')
        print(json.dumps({'status':'RESEARCH_ONLY_20_NATIVE_Q24_PHYSICAL_REPLAYS',
                          'models':20,'trained_head_q24_parity':False,
                          'independent_a0_a4':False,'production_qualification':False}))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'status':'BLOCKED_NATIVE_PHYSICAL_CANARY',
                          'reason':str(error),'production_qualification':False}),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
