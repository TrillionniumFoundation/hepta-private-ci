"""P4 CPU NumPy baseline and *actual separate-process* interrupted replay.

This is NOT Rust, GPU, power measurement or a production Cell. We report
physical local CPU timings for fixed 64/256/1024/4096 vector states and verify
that a checkpoint after abrupt os._exit can be loaded/replayed bit-exactly.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import multiprocessing as mp
import numpy as np
import psutil

SIZES=(64,256,1024,4096)
MAGIC=b'HCSN_DEMO_V1'


def step(h,tick):
    """A deterministic tiny analytic-gate-like vector recurrence, NOT HCSN."""
    i=np.arange(len(h),dtype=np.float64)
    dt=0.035+(tick%17)*0.0004
    signal=np.sin(tick*0.07+i*0.003)
    logz=np.log1p(np.abs(h))
    gamma=.65
    continuation=np.expm1(logz)+np.expm1(-gamma*logz)/gamma
    risk=np.exp(-gamma*logz)
    margin=np.logaddexp(0.,3*(h-.1))/3.
    keep=np.exp(-dt)
    updated=keep*h+(1-keep)*np.tanh(signal+.4*continuation-.2*risk+.3*margin)
    if not np.all(np.isfinite(updated)):
        raise FloatingPointError('nonfinite cell state')
    return updated


def initial(n):
    if n not in SIZES:raise ValueError('unregistered cell count')
    return np.zeros(n,dtype='<f8')


def replay(n,upto,checkpoint=None):
    if checkpoint is None: h=initial(n); seq=0
    else: h,seq=read_checkpoint(checkpoint,n)
    for t in range(seq,upto):h=step(h,t)
    return h


def _content(h,seq):
    meta=MAGIC+int(len(h)).to_bytes(4,'little')+int(seq).to_bytes(8,'little')
    body=np.asarray(h,dtype='<f8').tobytes()
    return meta+body


def write_checkpoint(path,h,seq):
    path=Path(path)
    if not 0<=seq<=1_000_000 or len(h) not in SIZES or not np.isfinite(h).all():
        raise ValueError('invalid checkpoint')
    payload=_content(h,seq)
    sealed=payload+hashlib.sha256(payload).digest()
    tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as out:
        out.write(sealed);out.flush();os.fsync(out.fileno())
    os.replace(tmp,path)
    # fsync directory ensures atomic rename is actually persisted on POSIX FS.
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def read_checkpoint(path,n):
    data=Path(path).read_bytes()
    expected_len=len(MAGIC)+4+8+n*8+32
    if len(data)!=expected_len or not data.startswith(MAGIC):
        raise ValueError('corrupt version or checkpoint length')
    payload,claimed=data[:-32],data[-32:]
    if hashlib.sha256(payload).digest()!=claimed:
        raise ValueError('checkpoint checksum invalid')
    offset=len(MAGIC)
    size=int.from_bytes(payload[offset:offset+4],'little')
    seq=int.from_bytes(payload[offset+4:offset+12],'little')
    if size!=n or seq>1_000_000:
        raise ValueError('checkpoint size/sequence invalid')
    h=np.frombuffer(payload[offset+12:],dtype='<f8').copy()
    if not np.isfinite(h).all():
        raise ValueError('nonfinite persisted state')
    return h,seq


def _crash_child(path,n,upto):
    h=replay(n,upto)
    write_checkpoint(path,h,upto)
    os._exit(127)  # abrupt process exit, no Python cleanup or return


def crash_recovery(n=64,total=60,kill_after=27):
    if not 0<kill_after<total:raise ValueError('bad recovery sequence')
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'snapshot.bin'
        p=mp.Process(target=_crash_child,args=(path,n,kill_after))
        p.start();p.join(timeout=10)
        if p.is_alive():p.kill();p.join();raise TimeoutError('child not terminated')
        if p.exitcode!=127:
            raise AssertionError(f'child did not exit at checkpoint: {p.exitcode}')
        recovered=replay(n,total,path)
        expected=replay(n,total)
        bit_exact=bool(np.array_equal(recovered,expected))
        # Provable on-disk checkpoint corruption rejection test:
        b=bytearray(path.read_bytes());b[len(MAGIC)+24]^=1;path.write_bytes(b)
        corrupt_rejected=False
        try:read_checkpoint(path,n)
        except ValueError: corrupt_rejected=True
        if not (bit_exact and corrupt_rejected):
            raise AssertionError('replay or corruption rejection failed')
        return {'cells':n,'abrupt_exit_code':p.exitcode,
                'checkpoint_seq':kill_after,'final_seq':total,
                'bit_exact_replayed':bit_exact,
                'corrupt_checkpoint_rejected':corrupt_rejected,
                'original_final_sha256':hashlib.sha256(expected.tobytes()).hexdigest(),
                'replayed_final_sha256':hashlib.sha256(recovered.tobytes()).hexdigest(),
                'scope':'single-process CPU toy with disk snapshot, not production crash recovery'}


def benchmark(scales=SIZES,events=96):
    reports=[]
    proc=psutil.Process()
    for n in scales:
        h=initial(n)
        p_start=proc.cpu_times()
        rss_begin=proc.memory_info().rss
        lat=[]
        for t in range(events):
            before=time.perf_counter_ns()
            h=step(h,t)
            after=time.perf_counter_ns()
            lat.append((after-before)/1e6)
        cpu_end=proc.cpu_times()
        elapsed=sum(lat)/1000.
        # 1 event advances n Cells, not events per distinct source neuron.
        reports.append({'cells':n,'source':'local_python_numpy_cpu_reference',
                        'not_rust':True,'not_gpu':True,
                        'physical_wall_timing':True,'simulated_events':events,
                        'cell_updates':events*n,
                        'throughput_cell_updates_per_s':events*n/elapsed,
                        'mean_latency_ms':float(np.mean(lat)),
                        'p95_ms':float(np.quantile(lat,.95)),
                        'p99_ms':float(np.quantile(lat,.99)),
                        'rss_initial_bytes':rss_begin,
                        'peak_rss_observed_bytes':max(rss_begin,proc.memory_info().rss),
                        'cpu_seconds_user_system':(cpu_end.user+cpu_end.system)-(p_start.user+p_start.system),
                        'gpu_utilization':None,'energy_joules':None,
                        'final_state_sha256':hashlib.sha256(h.tobytes()).hexdigest()})
    return reports


if __name__=='__main__':
    out={'scope':'physical CPU NumPy reference timing, NOT Rust/GPU or production',
         'hardware_benchmark':benchmark(),
         'abrupt_process_recovery':crash_recovery(n=256),
         'production_evidence_accepted':False}
    path=Path('reports/p4_cpu_oracle.json')
    path.write_text(json.dumps(out,indent=2))
    print('saved',path)
    for b in out['hardware_benchmark']:
        print(b['cells'],'Cell p95:',round(b['p95_ms'],4),'p99:',round(b['p99_ms'],4),
              'throughput',round(b['throughput_cell_updates_per_s']))
    print('crash',out['abrupt_process_recovery'])
