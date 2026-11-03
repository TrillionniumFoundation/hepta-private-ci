"""P4: independent recomputation of raw latency, throughput, energy fields.

This is a structural gate, NOT source/probe attestation and NOT hardware data.
Never produces production PASS from user-supplied metrics alone.
"""
from __future__ import annotations
import math
import re
from statistics import quantiles

SCALES=(64,256,1024,4096)
KERNELS=('rust_cpu','rust_gpu')
HEX64=re.compile('^[0-9a-f]{64}$')
HEX40=re.compile('^[0-9a-f]{40}$')
FAULT_CASES=('mid_batch_crash','corrupt_checkpoint','old_generation_replay')


def _quantile(values,p):
    v=sorted(values)
    pos=(len(v)-1)*p
    i=int(pos)
    if i+1>=len(v):return v[-1]
    return v[i]*(1-(pos-i))+v[i+1]*(pos-i)


def check_raw_traces(records,min_samples=1000):
    issues=[]
    seen=set()
    summaries=[]
    for idx,r in enumerate(records):
        if not isinstance(r,dict):
            issues.append(f'row {idx}: not a dict');continue
        key=(r.get('cells'),r.get('kernel'))
        if key in seen:issues.append(f'duplicate scale/kernel {key}')
        seen.add(key)
        if key[0] not in SCALES or key[1] not in KERNELS:
            issues.append(f'row {idx}: invalid scale/kernel');continue
        for keyname,pattern in [('source_sha',HEX40),('model_sha256',HEX64),
                                ('input_sha256',HEX64),('hardware_manifest_sha256',HEX64)]:
            if not pattern.fullmatch(str(r.get(keyname,''))):
                issues.append(f'row {idx}: invalid {keyname}')
        l=r.get('latency_ms_samples')
        if (not isinstance(l,list) or len(l)<min_samples or
            any(not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in l)):
            issues.append(f'row {idx}: absent/invalid raw latency samples');continue
        elapsed=r.get('elapsed_seconds',0.)
        events=r.get('completed_events',0)
        if (not isinstance(elapsed,(float,int)) or not math.isfinite(elapsed)
                or elapsed<=0 or isinstance(events,bool)
                or not isinstance(events,int) or events<len(l)):
            issues.append(f'row {idx}: invalid elapsed/events');continue
        through=events/elapsed
        p95=_quantile(l,.95);p99=_quantile(l,.99)
        for field,actual in [('p95_ms',p95),('p99_ms',p99),('throughput_events_s',through)]:
            stated=r.get(field)
            if (not isinstance(stated,(int,float)) or not math.isfinite(stated)
                    or abs(stated-actual)>max(.0001, .005*actual)):
                issues.append(f'row {idx}: {field} disagrees with raw events')
        energy=r.get('energy')
        if not isinstance(energy,dict):
            issues.append(f'row {idx}: missing power-meter evidence')
        else:
            for name in ('meter_type','meter_scope','calibration_sha256','gross_joules',
                         'idle_joules','net_joules'):
                if name not in energy:issues.append(f'row {idx}: missing energy {name}')
            if (energy.get('meter_type') not in ('external','rapl','nvml') or
                energy.get('meter_scope')!='whole_node' or
                not HEX64.fullmatch(str(energy.get('calibration_sha256','')))):
                issues.append(f'row {idx}: invalid power meter attribution')
            try:
                gross,idle,net=(float(energy.get(k,float('nan'))) for k in
                                ('gross_joules','idle_joules','net_joules'))
                if (not all(math.isfinite(x) for x in (gross,idle,net)) or idle<0
                        or gross<=idle or net<=0 or abs(gross-idle-net)>max(1e-6,.001*net)):
                    issues.append(f'row {idx}: inconsistent measured energy')
            except (TypeError,ValueError):
                issues.append(f'row {idx}: nonnumeric energy')
        faults=r.get('fault_receipts',{})
        if not isinstance(faults,dict):
            issues.append(f'row {idx}: missing fault receipts');faults={}
        for fault in FAULT_CASES:
            if not HEX64.fullmatch(str(faults.get(fault,''))):
                issues.append(f'row {idx}: missing {fault} recovery evidence')
        for name in ('peak_rss_bytes','cpu_util_percent','gpu_util_percent','gpu_peak_bytes'):
            value=r.get(name)
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                issues.append(f'row {idx}: absent finite {name}')
            elif name.endswith('percent') and not 0<=value<=100:
                issues.append(f'row {idx}: invalid percentage {name}')
            elif name.endswith('bytes') and value<0:
                issues.append(f'row {idx}: invalid byte count {name}')
        summaries.append({'cells':r['cells'],'kernel':r['kernel'],
                          'recomputed_p95_ms':p95,'recomputed_p99_ms':p99,
                          'recomputed_throughput_events_s':through,
                          'trace_samples':len(l)})
    for c in SCALES:
        for k in KERNELS:
            if (c,k) not in seen:issues.append(f'missing true native trace {c}/{k}')
    return {'structurally_comparable':not issues,'issues':issues,
            'recomputed':summaries,'authenticated_machine_measurements':False,
            'kernel_source_executed_in_this_environment':False,
            'production_evidence_accepted':False}
