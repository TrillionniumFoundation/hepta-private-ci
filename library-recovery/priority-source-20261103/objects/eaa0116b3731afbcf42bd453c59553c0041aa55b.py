"""P4 Rust/GPU capacity evidence validator: rejects omitted physical costs.

This checks completeness only: real measurements, instrumentation accuracy,
source SHA, host manifests and power-meter provenance need independent review.
"""
import math
import re

SHA40=re.compile('^[0-9a-f]{40}$')
SIZES=(64,256,1024,4096)
REQUIRED=('cells','real_kernel','device','source_sha','throughput_events_s',
          'p95_ms','p99_ms','cpu_util_percent','peak_rss_bytes',
          'gpu_peak_bytes','gpu_util_percent','joules_per_1000_events',
          'completed_events','successful_recovery','failure_injection_log_sha256')


def check_hardware(records):
    problems=[]
    seen=set()
    for rec in records:
        missing=[x for x in REQUIRED if x not in rec]
        if missing:
            problems.append(f'missing fields {missing}')
            continue
        n=rec['cells']
        if n in seen:
            problems.append(f'duplicate cell scale {n}')
        seen.add(n)
        if n not in SIZES:
            problems.append(f'unregistered cell scale {n}')
        if rec['real_kernel'] not in ('rust_cpu','rust_gpu'):
            problems.append(f'{n}: stub or unknown compute kernel')
        if not SHA40.fullmatch(str(rec['source_sha'])):
            problems.append(f'{n}: invalid exact source SHA')
        for field in ('throughput_events_s','p95_ms','p99_ms',
                      'peak_rss_bytes','joules_per_1000_events','completed_events'):
            v=rec[field]
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
                problems.append(f'{n}: invalid or absent measurement {field}')
        if rec['p99_ms']<rec['p95_ms']:
            problems.append(f'{n}: p99 lower than p95')
        for field in ('cpu_util_percent','gpu_util_percent'):
            v=rec[field]
            if not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100:
                problems.append(f'{n}: bad utilization {field}')
        if not isinstance(rec['gpu_peak_bytes'],int) or rec['gpu_peak_bytes']<0:
            problems.append(f'{n}: bad gpu bytes')
        if rec['successful_recovery'] is not True:
            problems.append(f'{n}: crash recovery not proven')
        if not re.fullmatch('[0-9a-f]{64}',str(rec['failure_injection_log_sha256'])):
            problems.append(f'{n}: missing failure injection log digest')
    for n in SIZES:
        if n not in seen:
            problems.append(f'missing physical scale {n}')
    # A parsable metric is not evidence of a calibrated wattmeter.
    return {'metadata_complete':not problems,'issues':problems,
            'instrumentation_verified':False,'production_evidence_accepted':False}
