#!/usr/bin/env python3
"""Generate deterministic synthetic near-match training and disjoint Q24 probe inputs.

This emits no real data, model, A0, future-label claim or production authority.
Training timestamps precede the frozen training cutoff; native probe is separate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys

Q=1<<24

def generate(directory: Path) -> dict:
    directory.mkdir(parents=True,exist_ok=False)
    rng=random.Random(20261015)
    clock=datetime(2026,10,14,12,tzinfo=timezone.utc)
    train=[]
    for group in range(4):
        prior=0
        for step in range(1,9):
            features=[rng.randrange(-2*Q,2*Q) for _ in range(32)]
            decision=features[0]+features[1]//2+prior//4
            prior=features[0]
            train.append({
                'case_id':f'synthetic-{group}-{step}',
                'source_group':f'synthetic-source-group-{group}',
                'sequence':step,
                'event_time_utc':(clock+timedelta(seconds=step,minutes=group)).isoformat().replace('+00:00','Z'),
                'feature_q24':features,
                'label':int(decision>0),
            })
    training={
        'schema':'hepta.neuron.frozen-q24-train-input.v1',
        'encoder_digest':hashlib.sha256(b'synthetic features, NO actual encoder').hexdigest(),
        'cell_id':'synthetic-near-match-cell-only',
        'train_cutoff_utc':'2026-10-15T00:00:00Z',
        'samples':train,
    }
    native=[]
    for step in range(1,9):
        values=[rng.randrange(-2*Q,2*Q) for _ in range(32)]
        native.append({
            'sequence':step,'monotonic_micros':step*1_000_000,
            'temporal_drive_q24':values,
            'prediction_q24':[0]*32,
        })
    trace={
        'schema':'hepta.neuron.physical-q24-shadow-trace.v1',
        'scope_digest':hashlib.sha256(b'fixture-scope-only').hexdigest(),
        'objective_digest':hashlib.sha256(b'fixture-objective-only').hexdigest(),
        'ndu_digest':hashlib.sha256(b'fixture-no-real-ndu').hexdigest(),
        'body_digest':hashlib.sha256(b'fixture-body-only').hexdigest(),
        'events':native,
    }
    receipt={}
    for name,value in [('train',training),('trace',trace)]:
        encoded=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        filepath=directory/(name+'.json')
        with filepath.open('xb') as out:out.write(encoded)
        receipt[name+'_sha256']=hashlib.sha256(encoded).hexdigest()
    receipt['schema']='hepta.neuron.near-matched-synthetic-fixture.v1'
    receipt['authority']='DENY_ALL'
    receipt['real_encoder_executed']=False
    receipt['source_kind']='SYNTHETIC_ONLY'
    return receipt

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=generate(args.output_dir)
        with args.receipt.open('x') as handle:
            json.dump(report,handle,indent=2,sort_keys=True)
            handle.write('\n')
        return 0
    except (ValueError,OSError) as error:
        print('BLOCKED_NEAR_MATCHED_FIXTURE: '+str(error),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
