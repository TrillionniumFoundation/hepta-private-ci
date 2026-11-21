"""Independent raw-receipt reader: no cache-producer or model imports.

Reconstructs keys directly from pinned receipts and array bytes, cold-reads
all ten complete history payloads, and recomputes counts/cost sums. It is an
integrity and accounting reader, not a second numerical CTMC oracle.
"""
from pathlib import Path
import hashlib
import json
import math
import resource
import struct
import time
import traceback
import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'attempt001'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def parse(raw):
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate field')
            result[key]=value
        return result
    def reject(x):raise ValueError('nonfinite JSON token')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=reject)


def read(path):
    return parse(Path(path).read_bytes())


def plain(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')


def tagged(value):
    if value is None:return ['null']
    if type(value) is bool:return ['bool',value]
    if type(value) is int:return ['int',str(value)]
    if type(value) is float:
        if not math.isfinite(value):raise ValueError('nonfinite typed identity')
        return ['f64le',struct.pack('<d',value).hex()]
    if type(value) is str:return ['str',value]
    if isinstance(value,(list,tuple)):return ['list',[tagged(v) for v in value]]
    if type(value) is dict and all(type(k) is str for k in value):
        return ['dict',[[k,tagged(value[k])] for k in sorted(value)]]
    raise ValueError('invalid identity value')


def typed_digest(value):
    return digest(json.dumps(tagged(value),ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii'))


def check_file(path,expected):
    raw=Path(path).read_bytes()
    if len(raw)!=expected['bytes'] or digest(raw)!=expected['sha256']:
        raise ValueError('source/artifact pin differs: '+str(path))


def array_digest(value,shape):
    a=np.asarray(value)
    assert a.dtype==np.dtype('float64') and a.shape==shape and np.isfinite(a).all()
    return digest(a.astype('<f8',copy=False).tobytes(order='C'))


def ck(kind,fields):
    return {'schema':'hepta.finite-cache-key.v1','kind':kind,'bindings':fields}


def state_basis():
    pairs=[]
    for h in range(7):
        for j in range(33):
            allowed=(h==0 and j<31) or (h==1 and j==31) or (h==2 and j==32) or (h==3 and j<32) or (h==4 and j!=31) or h in (5,6)
            if allowed:pairs.append([h,j])
    assert len(pairs)==163
    return pairs


def cold_read(expected,metadata):
    key=typed_digest(expected)
    if metadata['context_sha256']!=key or metadata['cache_key']!=key or typed_digest(metadata['context'])!=key:
        raise ValueError('cache context differs')
    path=OUT/'cache'/key
    if path.is_symlink() or not path.is_dir():raise ValueError('nonregular entry')
    for name,limit in [('entry.json',65536),('payload.bin',16*1024*1024)]:
        p=path/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:raise ValueError('entry bounds')
    header=read(path/'entry.json')
    if set(header)!={'schema','context','context_sha256','payload_sha256','payload_bytes'}:
        raise ValueError('unknown metadata fields')
    assert header['schema']=='hepta.finite-cache-entry.v1'
    assert typed_digest(header['context'])==key and header['context_sha256']==key
    payload=(path/'payload.bin').read_bytes()
    assert len(payload)==header['payload_bytes']==metadata['payload_bytes']
    assert digest(payload)==header['payload_sha256']==metadata['expected_payload_sha256']
    return payload


def check():
    p=read(ROOT/'PROTOCOL_FROZEN.json');queue=read(ROOT/'QUEUE_FROZEN.json')
    for path,pin in p['files'].items():check_file(path,pin)
    for path,pin in read(OUT/'RAW_RECEIPTS_SEAL.json').items():check_file(path,pin)
    u=read(queue['upstream_protocol']['path']);oracle=read(p['receipts']['oracle']);trace=read(p['receipts']['trace'])
    cost=read(p['receipts']['resource'])
    assert digest(Path(queue['upstream_protocol']['path']).read_bytes())==queue['upstream_protocol']['sha256']
    assert trace['protocol_sha256']==queue['upstream_protocol']['sha256']
    assert oracle['schema']=='hepta.event-history-oracle.v1' and trace['schema']=='hepta.event-operator-trace.v1'
    assert oracle['profile']==u['profile'] and len(oracle['models'])==5
    assert cost['source_script_sha256']==p['producer']['sha256']
    assert trace['baseline_already_reuses_operator'] is True and trace['full_history_result_cache_enabled'] is False
    assert trace['claimed_WSP_cache_saving'] is None and trace['request_count']==len(trace['requests'])==60
    assert digest(Path(p['receipts']['arrays']).read_bytes())==trace['arrays_sha256']
    metadata=read(OUT/'CACHE_ENTRIES.json');ivalues=read(OUT/'INTERVAL_IDENTITIES.json')
    assert len(metadata)==10 and len(ivalues)==60
    source=typed_digest(p['source_contract']);basish=typed_digest(state_basis())
    arithmetic=typed_digest(dict(upstream_numeric_contract=trace['numeric_contract'],audit_environment=p['environment'],producer_sha256=p['producer']['sha256']))
    decoder=typed_digest(dict(profile=u['profile'],producer_sha256=p['producer']['sha256'],output='entire joint history plus source-bound decoder; no financial payoff'))
    outcontract=typed_digest(dict(dtype='<f8',shape=[163,163],layout='C',orientation='row_probability'))
    request_keys=set();opkeys=set();historykeys=set();newopkeys=set();restore=[];ci=0;ri=0
    subtotals={k:0. for k in ['operator_build','lookup','application']}
    with np.load(p['receipts']['arrays'],allow_pickle=False) as arrays:
        for model,item in zip(oracle['models'],u['inputs']):
            assert model['fit']==item['fit'] and typed_digest(model['public'])==typed_digest(item['public'])
            fit=item['fit'];public=item['public'];generators={}
            for drive in (-1,0,1):
                generators[str(drive)]=array_digest(arrays[f'fit{fit}_joint_drive{drive}'],(163,163))
            initial=arrays[f'fit{fit}_initial_joint'];ih=array_digest(initial,(163,))
            assert len(model['cases'])==2
            for case,expected_label in zip(model['cases'],['WAIT_ONLY','TWO_LEGAL_READS']):
                assert case['label']==expected_label and len(case['steps'])==6 and case['initial_joint_sha256']==ih
                before=initial;actions=[]
                common=dict(checkpoint_gzip_sha256=item['checkpoint_gzip_sha256'],checkpoint_decoded_sha256=item['checkpoint_decoded_sha256'],source_contract_sha256=source,basis_sha256=basish,arithmetic_sha256=arithmetic)
                for tick,step in enumerate(case['steps']):
                    r=trace['requests'][ri];iv=ivalues[ri];ri+=1
                    rid=f'fit{fit}:{case["label"]}:tick{tick}'
                    assert r['request_id']==iv['request_id']==rid
                    kp={'checkpoint_sha256':item['checkpoint_gzip_sha256'],'generator_sha256':generators[str(public['drive'][tick])],
                        'duration_f64_le':struct.pack('<d',float(public['duration'][tick])).hex(),'numeric_contract':trace['numeric_contract']}
                    k=digest(plain(kp));assert r['operator_key']==iv['baseline_operator_key']==k and typed_digest(r['operator_key_payload'])==typed_digest(kp)
                    event='HIT' if k in opkeys else 'BUILD'
                    assert r['cache_event']==iv['baseline_event']==event
                    op=ck('linear_operator',common|dict(generator_sha256=kp['generator_sha256'],duration_f64_le=kp['duration_f64_le'],output_contract_sha256=outcontract))
                    oph=typed_digest(op);newopkeys.add(oph)
                    assert typed_digest(iv['context'])==oph==iv['context_sha256']
                    assert iv['operator_payload_sha256']==array_digest(arrays['operator_'+k],(163,163))
                    ident=dict(checkpoint=item['checkpoint_gzip_sha256'],public=public,owner_before=step['owner_before'],action=step['action'],completion=step['completion'],joint_state_sha256=array_digest(before,(163,)),profile=u['profile'])
                    assert digest(plain(ident))==r['complete_request_sha256']==iv['actual_complete_request_sha256']
                    assert ident['joint_state_sha256']==r['current_joint_sha256']==iv['current_joint_sha256']
                    request_keys.add(r['complete_request_sha256'])
                    assert r['initial_joint_sha256']==ih and r['restore_cpu_seconds'] is None and r['restore_cost_known'] is False
                    for field,total in [('lookup_cpu_seconds','lookup'),('application_cpu_seconds','application'),('operator_build_cpu_seconds','operator_build')]:
                        v=r[field]
                        if v is None:
                            assert field=='operator_build_cpu_seconds' and event=='HIT'
                        else:
                            assert type(v) in (float,int) and math.isfinite(v) and v>=0
                            if field=='operator_build_cpu_seconds':assert event=='BUILD'
                            subtotals[total]+=v
                    opkeys.add(k);before=np.asarray(step['joint'],dtype=np.float64)
                    actions.append(dict(owner_before=step['owner_before'],action=step['action'],completion=step['completion']))
                hcontext=ck('history_result',common|dict(generator_set_sha256=typed_digest(generators),initial_joint_sha256=ih,schedule_sha256=typed_digest(public),
                    action_observation_sha256=typed_digest(actions),decoder_sha256=decoder,horizon_intervals=6))
                hk=typed_digest(hcontext);assert hk not in historykeys;historykeys.add(hk)
                entry=metadata[ci];ci+=1;assert entry['history_id']==f'fit{fit}:{case["label"]}'
                start,wall=time.process_time(),time.perf_counter()
                payload=cold_read(hcontext,entry)
                expected=plain(dict(fit=fit,public=public,initial_joint=initial.tolist(),case=case))
                assert payload==expected and digest(expected)==entry['expected_payload_sha256']
                restore.append(dict(history_id=entry['history_id'],CPU_seconds=time.process_time()-start,wall_seconds=time.perf_counter()-wall,
                    bytes=len(payload),entire_history_bytes_equal=True,serving_cache_hit=False))
    reported=read(OUT/'COUNTS_AND_COST_SCOPE.json')
    expected_counts=dict(history_requests=10,unique_full_history_keys=10,full_history_hits=0,interval_requests=60,
        baseline_operator_builds=len(opkeys),baseline_operator_hits=60-len(opkeys),conservative_operator_keys=len(newopkeys),
        complete_interval_request_keys=len(request_keys),incremental_model_computations_avoided=0,feasibility_law_requests=0)
    for key,value in expected_counts.items():assert reported[key]==value
    assert trace['unique_operators']==len(opkeys)
    assert reported['baseline_operator_CPU_seconds']==subtotals
    assert reported['upstream_oracle_body_CPU_seconds']==cost['CPU_seconds']
    assert reported['upstream_unattributed_body_CPU_seconds']==cost['CPU_seconds']-sum(subtotals.values())
    assert reported['source_setup_CPU_seconds'] is None and reported['restore_CPU_seconds'] is None
    assert queue['total_history_requests']==10 and queue['total_interval_requests']==60
    assert queue['new_incremental_history_computation_avoided']==0 and queue['general_NDU']=='KEEP_ORIGINAL_AND_STOP'
    controls=read(OUT/'CONTROLS.json');assert controls['control_names']==p['safety_controls']
    assert [r['control'] for r in controls['records']]==p['safety_controls'] and controls['serving_requests']==0
    for row in controls['records']:
        assert row['status']=='PASS' and row['serving_request'] is False
        assert math.isfinite(row['CPU_seconds']) and row['CPU_seconds']>=0
    # Independently establish that the preserved damaged qualification payload
    # is indeed untrusted and the unmodified serving-audit payload remains exact.
    tamper=OUT/'controls/store'/metadata[0]['cache_key']/'payload.bin'
    assert digest(tamper.read_bytes())!=metadata[0]['expected_payload_sha256']
    assert typed_digest(-0.)!=typed_digest(0.) and typed_digest(1)!=typed_digest(1.)
    ledger=[parse(line) for line in (OUT/'TIMINGS.jsonl').read_text().splitlines()]
    for row in ledger:
        assert row['status']=='PASS'
        for k in ['CPU_seconds','wall_seconds']:assert math.isfinite(row[k]) and row[k]>=0
    result=read(OUT/'AUDIT_RESULT.json');assert result['status']=='PASS_FINITE_IDENTITY_AUDIT'
    assert sum(r['CPU_seconds'] for r in ledger)==result['timed_stage_CPU_seconds']
    assert result['timed_stage_CPU_seconds']<=result['CPU_seconds_until_receipt']
    return dict(counts=expected_counts,upstream_baseline_CPU_seconds=subtotals,
        cold_restore_records=restore,cold_restore_CPU_seconds=sum(r['CPU_seconds'] for r in restore),
        cache_producer_modules_imported=False,raw_numerical_CTMC_truth_recomputed=False,
        scientific_quality_claim=False,controls_checked=len(controls['records']),
        audit_timing_stages=len(ledger),zero_CPU_stages_retained=sum(r['CPU_seconds']==0 for r in ledger))


def main():
    start=time.process_time();wall=time.perf_counter();error=None;facts={}
    try:
        facts=check();status='PASS_INDEPENDENT_FINITE_RECEIPT_READER'
    except BaseException as exc:
        status='FAILED_READER_NO_RETRY';error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    result=dict(status=status,error=error,**facts,CPU_seconds_until_receipt=time.process_time(),body_CPU_seconds=time.process_time()-start,
        wall_seconds=time.perf_counter()-wall,peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        model_calls=0,CTMC_calls=0,expm_calls=0,automatic_retry=False)
    with (OUT/'INDEPENDENT_REVIEW.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(status)
    return 0 if error is None else 2


if __name__=='__main__':
    raise SystemExit(main())
