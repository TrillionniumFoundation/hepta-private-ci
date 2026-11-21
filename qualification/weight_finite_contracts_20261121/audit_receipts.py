"""One fixed receipt/cache audit. It never calls a model, CTMC, or expm."""
import time
ENTRY_CPU = time.process_time()
from pathlib import Path
from collections import Counter
import gzip
import hashlib
import json
import math
import os
import resource
import struct
import traceback
import numpy as np
from cache_contract import (ContentStore, context, context_key, payload_bytes,
                            sha, strict_json, typed_bytes)
from offline_controls import CONTROL_NAMES, run_controls

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'attempt001'


def read(path):
    return strict_json(Path(path).read_bytes())


def put(path, value):
    with Path(path).open('xb') as handle:
        handle.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()+b'\n')


def pin(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=sha(raw))


def verify_pins(pins):
    for path, expected in pins.items():
        if pin(path) != expected:
            raise ValueError('frozen source changed: ' + path)


def a_sha(value, shape=None):
    value = np.asarray(value)
    if value.dtype != np.dtype('float64') or not np.isfinite(value).all():
        raise ValueError('array dtype or finite contract')
    if shape is not None and value.shape != shape:
        raise ValueError('array shape contract')
    return sha(np.asarray(value, dtype='<f8').tobytes(order='C'))


def ordinary_sha(value):
    return sha(payload_bytes(value))


def tagged_sha(value):
    return sha(typed_bytes(value))


def basis():
    out = []
    for history in range(7):
        latent = (list(range(31)) if history==0 else [31] if history==1 else [32]
                  if history==2 else list(range(32)) if history==3 else list(range(31))+[32]
                  if history==4 else list(range(33)))
        out.extend([[history,i] for i in latent])
    if len(out)!=163 or len({tuple(v) for v in out})!=163:
        raise ValueError('event basis')
    return out


def duration_bits(value):
    return struct.pack('<d', float(value)).hex()


def validate_timing(value, nullable=False):
    if value is None and nullable:
        return
    if type(value) not in (float,int) or not math.isfinite(value) or value<0:
        raise ValueError('invalid raw CPU timing')


def build_records(protocol, queue, oracle, trace, arrays):
    """Authenticate raw identities and emit exact per-object cache descriptors."""
    upstream = read(queue['upstream_protocol']['path'])
    if oracle['schema']!='hepta.event-history-oracle.v1' or trace['schema']!='hepta.event-operator-trace.v1':
        raise ValueError('unknown raw receipt schema')
    if trace['protocol_sha256']!=queue['upstream_protocol']['sha256'] or oracle['profile']!=upstream['profile']:
        raise ValueError('protocol/profile mismatch')
    if trace['baseline_already_reuses_operator'] is not True or trace['full_history_result_cache_enabled'] is not False:
        raise ValueError('baseline reuse scope changed')
    if trace['claimed_WSP_cache_saving'] is not None or trace['request_count']!=60 or len(trace['requests'])!=60:
        raise ValueError('unexpected serving/benefit claim')
    if trace['arrays_sha256']!=pin(protocol['receipts']['arrays'])['sha256']:
        raise ValueError('raw array pin mismatch')
    expected_fits=list(dict.fromkeys(row['fit'] for row in queue['histories']))
    if [m['fit'] for m in oracle['models']]!=expected_fits:
        raise ValueError('missing or extra model')
    source_sha = tagged_sha(protocol['source_contract'])
    arithmetic_sha = tagged_sha(dict(upstream_numeric_contract=trace['numeric_contract'],
                                    audit_environment=protocol['environment'],
                                    producer_sha256=protocol['producer']['sha256']))
    basis_sha = tagged_sha(basis())
    decoder_sha = tagged_sha(dict(profile=upstream['profile'],producer_sha256=protocol['producer']['sha256'],
                                  output='entire joint history plus source-bound decoder; no financial payoff'))
    output_sha = tagged_sha(dict(dtype='<f8',shape=[163,163],layout='C',orientation='row_probability'))
    histories=[]; intervals=[]; seen=set(); complete_requests=set(); index=0
    cpu = dict(operator_build=0.,lookup=0.,application=0.)
    for model,item in zip(oracle['models'],upstream['inputs']):
        fit=item['fit'];public=item['public']
        if typed_bytes(model['public'])!=typed_bytes(public) or model['checkpoint_sha256']!=item['checkpoint_gzip_sha256']:
            raise ValueError('source public or checkpoint mismatch')
        raw=Path(item['checkpoint_path']).read_bytes()
        if sha(raw)!=item['checkpoint_gzip_sha256'] or sha(gzip.decompress(raw))!=item['checkpoint_decoded_sha256']:
            raise ValueError('compressed/decoded checkpoint mismatch')
        if sha(Path(item['schedules_path']).read_bytes())!=item['schedules_sha256']:
            raise ValueError('schedule source changed')
        stored=json.loads(gzip.decompress(raw))
        generator_hashes={}
        for drive in (-1,0,1):
            origin=arrays[f'fit{fit}_original_drive{drive}']
            if a_sha(origin,(33,33))!=a_sha(np.asarray(stored['core']['generators'][str(drive)],dtype=np.float64),(33,33)):
                raise ValueError('stored generator bytes differ')
            generator_hashes[str(drive)]=a_sha(arrays[f'fit{fit}_joint_drive{drive}'],(163,163))
        initial=arrays[f'fit{fit}_initial_joint']; initial_sha=a_sha(initial,(163,))
        if [c['label'] for c in model['cases']]!=['WAIT_ONLY','TWO_LEGAL_READS']:
            raise ValueError('history order changed')
        for case in model['cases']:
            if len(case['steps'])!=6 or case['initial_joint_sha256']!=initial_sha:
                raise ValueError('history horizon or initial state')
            actions=[]; before=initial
            for tick,step in enumerate(case['steps']):
                row=trace['requests'][index];index+=1
                expected_id=f'fit{fit}:{case["label"]}:tick{tick}'
                if row['request_id']!=expected_id or row['fit']!=fit or row['history']!=case['label'] or row['tick']!=tick:
                    raise ValueError('actual interval queue differs')
                drive=public['drive'][tick]
                gkey=f'fit{fit}_joint_drive{drive}'; okey=f'fit{fit}_original_drive{drive}'
                kp=dict(checkpoint_sha256=item['checkpoint_gzip_sha256'],generator_sha256=generator_hashes[str(drive)],
                        duration_f64_le=duration_bits(public['duration'][tick]),numeric_contract=trace['numeric_contract'])
                key=ordinary_sha(kp)
                if row['operator_key_payload']!=kp or row['operator_key']!=key:
                    raise ValueError('operator is not content addressed')
                if row['joint_generator_array_key']!=gkey or row['original_generator_array_key']!=okey or row['operator_array_key']!='operator_'+key:
                    raise ValueError('array key binding')
                op_sha=a_sha(arrays['operator_'+key],(163,163))
                identity=dict(checkpoint=item['checkpoint_gzip_sha256'],public=public,owner_before=step['owner_before'],
                              action=step['action'],completion=step['completion'],joint_state_sha256=a_sha(before,(163,)),profile=upstream['profile'])
                if (row['complete_request_sha256']!=ordinary_sha(identity) or row['current_joint_sha256']!=identity['joint_state_sha256']
                        or row['initial_joint_sha256']!=initial_sha or row['public_sha256']!=ordinary_sha(public)
                        or row['checkpoint_sha256']!=item['checkpoint_gzip_sha256'] or row['checkpoint_decoded_sha256']!=item['checkpoint_decoded_sha256']):
                    raise ValueError('full request source/state identity')
                complete_requests.add(row['complete_request_sha256'])
                expected_event='HIT' if key in seen else 'BUILD'
                if row['cache_event']!=expected_event:
                    raise ValueError('baseline hit/build accounting mismatch')
                for k in ('lookup_cpu_seconds','application_cpu_seconds'):
                    validate_timing(row[k])
                validate_timing(row['operator_build_cpu_seconds'],nullable=expected_event=='HIT')
                if expected_event=='HIT' and row['operator_build_cpu_seconds'] is not None:
                    raise ValueError('hit carries a second build')
                if row['restore_cpu_seconds'] is not None or row['restore_cost_known'] is not False:
                    raise ValueError('restore is not a measured upstream component')
                cpu['operator_build']+=row['operator_build_cpu_seconds'] or 0.
                cpu['lookup']+=row['lookup_cpu_seconds'];cpu['application']+=row['application_cpu_seconds']
                oc=context('linear_operator',checkpoint_gzip_sha256=item['checkpoint_gzip_sha256'],
                           checkpoint_decoded_sha256=item['checkpoint_decoded_sha256'],source_contract_sha256=source_sha,
                           basis_sha256=basis_sha,arithmetic_sha256=arithmetic_sha,generator_sha256=generator_hashes[str(drive)],
                           duration_f64_le=kp['duration_f64_le'],output_contract_sha256=output_sha)
                intervals.append(dict(request_id=expected_id,baseline_event=expected_event,baseline_operator_key=key,
                    context=oc,context_sha256=context_key(oc),operator_payload_sha256=op_sha,
                    actual_complete_request_sha256=row['complete_request_sha256'],initial_joint_sha256=initial_sha,
                    current_joint_sha256=row['current_joint_sha256']))
                seen.add(key)
                actions.append(dict(owner_before=step['owner_before'],action=step['action'],completion=step['completion']))
                before=np.asarray(step['joint'],dtype=np.float64)
                a_sha(before,(163,))
            observed=[s['completion']['observation'] for s in case['steps'] if s['completion']['kind']=='observation']
            if case['label']=='WAIT_ONLY':
                if any(s['action']!=1 for s in case['steps']) or observed:
                    raise ValueError('WAIT queue contract')
            elif observed!=[0,1] or sum(s['action']==2 for s in case['steps'])!=2:
                raise ValueError('two READ/OBS history contract')
            hc=context('history_result',checkpoint_gzip_sha256=item['checkpoint_gzip_sha256'],
                       checkpoint_decoded_sha256=item['checkpoint_decoded_sha256'],source_contract_sha256=source_sha,
                       basis_sha256=basis_sha,arithmetic_sha256=arithmetic_sha,generator_set_sha256=tagged_sha(generator_hashes),
                       initial_joint_sha256=initial_sha,schedule_sha256=tagged_sha(public),
                       action_observation_sha256=tagged_sha(actions),decoder_sha256=decoder_sha,horizon_intervals=6)
            payload=dict(fit=fit,public=public,initial_joint=initial.tolist(),case=case)
            histories.append(dict(history_id=f'fit{fit}:{case["label"]}',context=hc,context_sha256=context_key(hc),
                                  expected_payload_sha256=sha(payload_bytes(payload)),payload=payload))
    if trace['unique_operators']!=len(seen) or len(histories)!=10 or len({h['context_sha256'] for h in histories})!=10:
        raise ValueError('finite queue identity count differs')
    return histories,intervals,dict(history_requests=10,unique_full_history_keys=10,full_history_hits=0,
        interval_requests=60,baseline_operator_builds=len(seen),baseline_operator_hits=60-len(seen),
        conservative_operator_keys=len({i['context_sha256'] for i in intervals}),
        complete_interval_request_keys=len(complete_requests),baseline_operator_CPU_seconds=cpu,
        incremental_model_computations_avoided=0,feasibility_law_requests=0,
        source_setup_CPU_seconds=None,restore_CPU_seconds=None,
        missing_cost_components=['upstream setup/source hashing/validation stage breakdown','upstream durable cold restore; not performed'],
        no_future_production_horizon_or_quality_claim=True)


def main():
    if not OUT.is_dir() or any(p.name not in {'audit.stdout.log','audit.stderr.log'} for p in OUT.iterdir()):
        raise ValueError('single supervisor-created audit directory with only empty process logs required')
    ledger=[];status='FAILED_NO_RETRY';error=None;body=time.process_time();wall=time.perf_counter()
    def timed(name, operation):
        a,b=time.process_time(),time.perf_counter()
        try:
            value=operation()
        except BaseException:
            row=dict(stage=name,status='FAILED',CPU_seconds=time.process_time()-a,wall_seconds=time.perf_counter()-b)
            ledger.append(row);raise
        else:
            row=dict(stage=name,status='PASS',CPU_seconds=time.process_time()-a,wall_seconds=time.perf_counter()-b)
            ledger.append(row);return value
        finally:
            if ledger:
                with (OUT/'TIMINGS.jsonl').open('a') as f:f.write(json.dumps(ledger[-1],sort_keys=True,allow_nan=False)+'\n')
    try:
        protocol=read(ROOT/'PROTOCOL_FROZEN.json');queue=read(ROOT/'QUEUE_FROZEN.json')
        timed('source_and_queue_identity',lambda:verify_pins(protocol['files']))
        original_pins={p:pin(p) for p in protocol['receipts'].values()}
        put(OUT/'RAW_RECEIPTS_SEAL.json',original_pins)
        oracle=timed('read_oracle_JSON',lambda:read(protocol['receipts']['oracle']))
        trace=timed('read_operator_trace_JSON',lambda:read(protocol['receipts']['trace']))
        upstream_cost=timed('read_oracle_resource_receipt',lambda:read(protocol['receipts']['resource']))
        if upstream_cost['source_script_sha256']!=protocol['producer']['sha256']:
            raise ValueError('producer source hash changed')
        validate_timing(upstream_cost['CPU_seconds'])
        with np.load(protocol['receipts']['arrays'],allow_pickle=False) as archive:
            histories,intervals,counts=timed('raw_arrays_and_complete_identity_validation',
                lambda:build_records(protocol,queue,oracle,trace,archive))
        store=timed('create_empty_isolated_store',lambda:ContentStore(OUT/'cache'))
        entries=[]
        for row in histories:
            payload=payload_bytes(row['payload']);ctx=row['context'];expected=row['expected_payload_sha256']
            miss=timed('history_lookup:'+row['history_id'],lambda:store.get(ctx,expected))
            if miss is not None:raise ValueError('uncommitted duplicate history hit')
            key=timed('history_payload_write:'+row['history_id'],lambda:store.put(ctx,payload,expected))
            entries.append({k:v for k,v in row.items() if k!='payload'}|dict(payload_bytes=len(payload),cache_key=key))
        controls=timed('isolated_safety_controls_not_serving_demand',lambda:run_controls(
            OUT/'controls',histories[0]['context'],payload_bytes(histories[0]['payload'])))
        put(OUT/'CONTROLS.json',dict(control_names=CONTROL_NAMES,records=controls,serving_requests=0))
        put(OUT/'CACHE_ENTRIES.json',entries);put(OUT/'INTERVAL_IDENTITIES.json',intervals)
        counts['upstream_oracle_body_CPU_seconds']=upstream_cost['CPU_seconds']
        counts['upstream_cost_scope']='body only; includes source/reconstruction/expm/application/validation/output; interpreter imports and later receipt emission are outside its field'
        counts['upstream_unattributed_body_CPU_seconds']=upstream_cost['CPU_seconds']-sum(counts['baseline_operator_CPU_seconds'].values())
        if counts['upstream_unattributed_body_CPU_seconds'] < -1e-8:
            raise ValueError('upstream substage costs exceed body total')
        put(OUT/'COUNTS_AND_COST_SCOPE.json',counts)
        timed('post_audit_source_and_raw_integrity',lambda:(verify_pins(protocol['files']),verify_pins(original_pins)))
        status='PASS_FINITE_IDENTITY_AUDIT'
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        put(OUT/'FAILURE.json',error)
    receipt=dict(status=status,error=error,CPU_seconds_until_receipt=time.process_time(),
        body_CPU_seconds=time.process_time()-body,import_and_entry_CPU_seconds=body,
        timed_stage_CPU_seconds=sum(r['CPU_seconds'] for r in ledger),wall_seconds=time.perf_counter()-wall,
        peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        affinity=sorted(os.sched_getaffinity(0)),model_calls=0,CTMC_calls=0,expm_calls=0,
        gradient_updates=0,production_mutations=0,automatic_retry=False,
        producer_emission_tail_in_supervisor_child_CPU=True)
    put(OUT/'AUDIT_RESULT.json',receipt)
    print(json.dumps(dict(status=status,CPU_seconds=receipt['CPU_seconds_until_receipt'])))
    return 0 if status.startswith('PASS') else 2


if __name__=='__main__':
    raise SystemExit(main())
