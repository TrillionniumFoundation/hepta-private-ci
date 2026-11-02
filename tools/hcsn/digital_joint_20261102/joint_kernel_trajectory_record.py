"""Expose complete event records by deterministic same-seed archived replay."""
import argparse
import copy
import csv
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback
import numpy as np
from ..digital_read_followup_20261101 import continuous_renewal as old

HERE=Path(__file__).resolve().parent


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def replay(protocol,rows):
    law=old.Law(**protocol['law']);rng=np.random.default_rng(protocol['seed'])
    saved=[];start,cpu=time.perf_counter(),time.process_time()
    for i,expected in enumerate(rows):
        before=copy.deepcopy(rng.bit_generator.state)
        try:state,events=old.advance(old.State(),protocol['duration'],law,rng)
        except Exception:
            saved.append(dict(index=i,matched_original_csv=False,rng_before=before,error=traceback.format_exc()))
            break
        first=events[0]['time'] if events else None
        values=[float(state.mode==-1),float(state.mode==1),float(state.mode==0),state.voltage,float(len(events)),float(len(events)>=2)]
        keys=('lower_refractory','upper_refractory','active','voltage','event_count','at_least_two_events')
        target=[float(expected[k]) for k in keys];target_first=float(expected['first_hit_time']) if expected['first_hit_time'] else None
        same=values==target and first==target_first and int(expected['sample'])==i
        saved.append(dict(index=i,matched_original_csv=same,state=asdict(state),events=events,first_hit_time=first,
          rng_before=before,rng_after=copy.deepcopy(rng.bit_generator.state),sample_vector=values,original_csv=expected))
    return dict(schema=protocol['schema'],passed=len(saved)==protocol['count'] and all(r['matched_original_csv'] for r in saved),
      count=len(saved),records=saved,wall_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,
      scope='same-seed recording replay; no new independent trajectories or fits')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='001');parser.add_argument('--published-source-commit',required=True)
    args=parser.parse_args();commit=args.published_source_commit
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('full published commit required')
    protocol_path=HERE/'joint_kernel_trajectory_record_protocol.json';protocol=json.loads(protocol_path.read_text())
    source=(HERE/protocol['source_relative']).resolve();csv_path=(HERE/protocol['csv_relative']).resolve()
    if digest(source)!=protocol['source_sha256'] or digest(csv_path)!=protocol['csv_sha256']:raise ValueError('archived input changed')
    with csv_path.open() as f:rows=[r for r in csv.DictReader(f) if r['condition']==protocol['condition']]
    if len(rows)!=protocol['count']:raise ValueError('recorded cohort count mismatch')
    before={str(p):digest(p) for p in (Path(__file__),protocol_path,source,csv_path)}
    prefix=HERE/('joint_kernel_trajectory_record_attempt_'+args.attempt)
    with prefix.with_name(prefix.name+'_sources.json.gz').open('xb') as f:
        f.write(gzip.compress(json.dumps({str(p):p.read_text() for p in (Path(__file__),protocol_path,source)},sort_keys=True).encode(),mtime=0))
    try:result=replay(protocol,rows)
    except Exception:result=dict(schema=protocol['schema'],passed=False,error=traceback.format_exc())
    unchanged=all(digest(p)==h for p,h in before.items())
    result.update(published_source_commit=commit,source_input_sha256=before,sources_unchanged_at_end=unchanged)
    result['passed']=result['passed'] and unchanged
    with prefix.with_name(prefix.name+'_RAW.json.gz').open('xb') as f:
        f.write(gzip.compress(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),mtime=0))
    summary={k:v for k,v in result.items() if k!='records'}
    summary['mismatched_samples']=[r['index'] for r in result.get('records',[]) if not r['matched_original_csv']]
    with prefix.with_suffix('.json').open('x') as f:json.dump(summary,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(summary,indent=2));raise SystemExit(0 if result['passed'] else 1)
