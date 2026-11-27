"""Synthetic qualification census with bounded attempts and cooperative stops.

Not a production sandbox: RSS is this Linux process's historical peak, wall
checks occur only between calls, and evidence bytes mean serialized payload,
not filesystem occupancy. No subprocess, automatic retry, artifact loading or
real-data admission is provided. A killed process can lose this in-memory census.
"""
import copy
import hashlib
from pathlib import Path
import json
import math
import sys
import time
import numpy as np
from cell_field_fixed_actions import fixed_library
from cell_field_fixed_adapter import fixed_impulse_predictions

MODES=("loss2","q4","full")


def encoded(ledger):
    return json.dumps(ledger,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def bounded_json_text(value, budget):
    text=''.join(c if c.isprintable() else ' ' for c in value[:budget])
    while len(encoded(text))>budget+2:text=text[:-1]
    return text


def process_observation():
    if sys.platform!='linux':raise RuntimeError('Linux RSS unit contract required')
    import resource
    return {'monotonic_seconds':time.monotonic(),
            'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}


def run_synthetic_census(references, *, identities, attempt_limit, wall_seconds, rss_bytes,
                         evidence_bytes, observer=process_observation,
                         predictor=fixed_impulse_predictions):
    """Register every outcome before execution; never adapt the fixed plan.

    Predictor/observer injection is for deterministic failure tests, not proof
    of resource enforcement. Reference provenance is explicitly unverified here.
    Ordinary action errors continue; limits and failed observations stop all
    later attempts. Limit-crossing results are marked over_budget, not success.
    """
    if (not isinstance(references,dict) or not 1<=len(references)<=18
            or any(not isinstance(k,str) or not 1<=len(k)<=128 for k in references)
            or type(attempt_limit)!=int or not 0<=attempt_limit<=2646
            or type(wall_seconds) not in (int,float) or not math.isfinite(wall_seconds)
            or not 0<wall_seconds<=600 or type(rss_bytes)!=int or not 1<=rss_bytes<=2*1024**3
            or type(evidence_bytes)!=int or not 1<=evidence_bytes<=1024**3):
        raise ValueError('bounded synthetic census protocol required')
    required={"source_sha256","protocol_sha256","features_sha256","checkpoint_sha256"}
    if (not isinstance(identities,dict) or set(identities)!=set(references)
            or any(not isinstance(v,dict) or set(v)!=required or
                   any(not isinstance(d,str) or len(d)!=64 or any(c not in '0123456789abcdef' for c in d)
                       for d in v.values()) for v in identities.values())):
        raise ValueError('complete declared source/protocol/features/checkpoint identities required')
    bound={}
    for anchor,ref in references.items():
        digest=hashlib.sha256()
        for value in (ref.A,ref.C,ref.states,ref.scales):
            a=np.ascontiguousarray(value,dtype='<f8')
            digest.update(encoded({'shape':list(a.shape)}));digest.update(a.tobytes())
        pool=fixed_library(ref.state.parameter_count)
        bound[anchor]={**identities[anchor], 'parameters':ref.state.parameter_count,
                       'horizon':ref.horizon,'dt':ref.dt, 'reference_maps_sha256':digest.hexdigest(),
                       'action_set_sha256':hashlib.sha256(encoded(pool)).hexdigest()}
    root=Path(__file__).resolve().parent
    execution_sources={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                       for name in ('cell_field_fixed_census.py','cell_field_fixed_fixture.py','cell_field_fixed_sources.json','cell_field_fixed_adapter.py','cell_field_fixed_actions.py','cell_field_fixed_summary.py',
                           'cell_field_control.py','cell_field_state.py',
                           'cell_learning_models.py','cell_learning_metrics.py')}
    plan=[]
    for anchor,ref in sorted(references.items()):
        for action,_ in fixed_library(ref.state.parameter_count):
            for mode in MODES:
                plan.append({'anchor':anchor,'action':action,'mode':mode,
                             'status':'not_run','reason':'not_started'})
    ledger={'scope':'synthetic prediction census only','resource_enforcement':'cooperative',
            'provenance_verified':False,'crash_durable':False,
            'fixture_hooks':predictor is not fixed_impulse_predictions or observer is not process_observation,
            'counts_are':'predictor calls, not physical nonlinear branches',
            'bindings':bound,'execution_sources':execution_sources,
            'request_sha256':hashlib.sha256(encoded({'bindings':bound,'sources':execution_sources,
                'modes':MODES,'fixture_hooks':predictor is not fixed_impulse_predictions or observer is not process_observation,
                'attempt_limit':attempt_limit,'wall_seconds':wall_seconds,
                'rss_bytes':rss_bytes,'evidence_bytes':evidence_bytes})).hexdigest(),
            'attempted':0,'stop_reason':None,'all_succeeded':False,'records':plan,
            'observations':[]}
    # Reserve a fixed observation slot pair per call, avoiding unbounded telemetry.
    # Reserve enough room to retain every status even if output itself hits budget.
    skeleton=copy.deepcopy(ledger)
    for r in skeleton['records']:
        r.update(status='not_run_budget',reason='x'*80,error_message='x'*256,
                 error_message_sha256='0'*64,execution_status='success',error_type='x'*80,
                 output_status='omitted_budget')
    reserve=len(encoded(skeleton))+512
    if reserve>evidence_bytes:raise ValueError('budget cannot hold complete census metadata')

    def observe():
        value=observer()
        if (set(value)!={'monotonic_seconds','process_peak_rss_bytes'}
                or type(value['monotonic_seconds']) not in (int,float)
                or not math.isfinite(value['monotonic_seconds'])
                or not 0<=value['monotonic_seconds']<=1e15
                or type(value['process_peak_rss_bytes'])!=int
                or not 0<=value['process_peak_rss_bytes']<2**63):
            raise ValueError('invalid resource observation')
        return value

    def reserved_payload_size():
        projected=copy.deepcopy(ledger)
        for item in projected['records']:
            if item['status']=='not_run':
                item.update(status='not_run_budget',reason='observation_error')
        return len(encoded(projected))+512

    try:first=observe()
    except Exception:
        ledger['stop_reason']='observation_error';first=None
    last=first
    # Retain initial and latest readings, not per-call unbounded samples.
    if first is not None:ledger['observations']=[first,first]
    for record in plan:
        if ledger['stop_reason'] is not None:break
        if ledger['attempted']>=attempt_limit:
            ledger['stop_reason']='attempt_limit';break
        try:
            current=observe()
            if current['monotonic_seconds']<last['monotonic_seconds']:
                raise ValueError('clock regression')
            last=current;ledger['observations'][-1]=current
        except Exception:
            ledger['stop_reason']='observation_error';break
        reason=('wall_seconds' if current['monotonic_seconds']-first['monotonic_seconds']>=wall_seconds else
                'rss_bytes' if current['process_peak_rss_bytes']>rss_bytes else None)
        if reason:ledger['stop_reason']=reason;break
        ledger['attempted']+=1
        try:
            result=predictor(references[record['anchor']],record['action'],mode=record['mode'])
            fields=np.asarray(result['fields'],dtype=np.float64)
            h=references[record['anchor']].horizon
            if fields.shape!=(h+1,2) or not np.isfinite(fields).all():raise ValueError('invalid loss path')
            record.update(status='success',reason=None,fields=fields.tolist())
        except Exception as error:
            # Length-bounded diagnostic text is not redacted; this runner is synthetic-only.
            try:message=str(error)
            except Exception:message='<exception message unavailable>'
            record.update(status='error',reason=bounded_json_text(type(error).__name__,80),
                          error_type=bounded_json_text(type(error).__name__,80),
                          error_message=bounded_json_text(message,256),
                          error_message_sha256=hashlib.sha256(message.encode('utf-8',errors='replace')).hexdigest())
        record['execution_status']=record['status']
        try:
            current=observe()
            if current['monotonic_seconds']<last['monotonic_seconds']:raise ValueError('clock regression')
            last=current;ledger['observations'][-1]=current
            reason=('wall_seconds' if current['monotonic_seconds']-first['monotonic_seconds']>=wall_seconds else
                    'rss_bytes' if current['process_peak_rss_bytes']>rss_bytes else None)
        except Exception:reason='observation_error'
        if reason:
            record.update(status='over_budget' if reason!='observation_error' else 'unverified_resource',reason=reason)
            ledger['stop_reason']=reason
        # Keep a full metadata reserve for remaining not-run outcomes.
        if reserved_payload_size()>evidence_bytes:
            if 'fields' in record:
                record.pop('fields')
                record['output_status']='omitted_budget'
            ledger['stop_reason']='evidence_bytes'
            # Earlier output retention must not prevent preserving the full census.
            for prior in plan:
                if reserved_payload_size()<=evidence_bytes:break
                if 'fields' in prior:
                    prior.pop('fields')
                    prior['output_status']='omitted_budget'
    if ledger['stop_reason']:
        for record in plan:
            if record['status']=='not_run':record.update(status='not_run_budget',reason=ledger['stop_reason'])
    ledger['all_succeeded']=all(r['status']=='success' and r.get('output_status')!='omitted_budget' for r in plan)
    if len(encoded(ledger))>evidence_bytes:raise RuntimeError('census serialization exceeded reserved budget')
    return ledger
