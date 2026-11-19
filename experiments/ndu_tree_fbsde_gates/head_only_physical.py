"""Physically executed NumPy Cell Head-only CPU microbenchmark (no pretrained Stem).

Per-Cell distinct 384/64/rank-8/8-class gated residual weights. A single
synthetic shared input drives all Cells; no actual Encoder forward occurs.
Reports measured batch times, CPU and memory samples, not true end-to-end TCO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from dataclasses import dataclass

import numpy as np

FEATURE_DIM=384
STATE_DIM=64
RANK=8
CLASSES=8


def head_parameters(d=FEATURE_DIM,s=STATE_DIM,r=RANK,c=CLASSES):
    if any(type(x) is not int or x <= 0 for x in (d,s,r,c)):
        raise ValueError("strict positive shapes")
    return d*r + (s+1)*r + d*r + (d+1)*c


@dataclass(frozen=True)
class HeadBank:
    feature: np.ndarray
    local: np.ndarray
    down: np.ndarray
    gate: np.ndarray
    gate_bias: np.ndarray
    up: np.ndarray
    output: np.ndarray
    output_bias: np.ndarray

    @property
    def cells(self):
        return len(self.local)

    @property
    def physical_parameters(self):
        return sum(a.size for a in (self.down,self.gate,self.gate_bias,
                                    self.up,self.output,self.output_bias))

    @property
    def weight_bytes(self):
        return sum(a.nbytes for a in (self.down,self.gate,self.gate_bias,
                                      self.up,self.output,self.output_bias))


def build_bank(cells,seed=7347):
    if type(cells) is not int or not 1 <= cells <= 4096:
        raise ValueError("bounded physical Cell count 1..4096")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("bounded reproducibility seed")
    rng=np.random.default_rng(seed)
    def arr(shape):
        return (rng.standard_normal(shape,dtype=np.float32)*np.float32(.015)).astype(np.float32)
    return HeadBank(arr((FEATURE_DIM,)),arr((cells,STATE_DIM)),
                    arr((cells,RANK,FEATURE_DIM)),arr((cells,RANK,STATE_DIM)),
                    arr((cells,RANK)),arr((cells,FEATURE_DIM,RANK)),
                    arr((cells,CLASSES,FEATURE_DIM)),arr((cells,CLASSES)))


def forward(bank):
    """One physical matmul for each of N distinct Head weight sets, no mixing."""
    if type(bank) is not HeadBank or bank.down.shape!=(bank.cells,RANK,FEATURE_DIM) or \
            bank.local.shape!=(bank.cells,STATE_DIM) or \
            bank.gate.shape!=(bank.cells,RANK,STATE_DIM) or \
            bank.up.shape!=(bank.cells,FEATURE_DIM,RANK) or \
            bank.output.shape!=(bank.cells,CLASSES,FEATURE_DIM) or \
            bank.gate_bias.shape!=(bank.cells,RANK) or \
            bank.output_bias.shape!=(bank.cells,CLASSES) or bank.feature.shape!=(FEATURE_DIM,):
        raise ValueError("full distinct Head shape required")
    d=np.einsum('nrd,d->nr',bank.down,bank.feature)
    g=np.einsum('nrs,ns->nr',bank.gate,bank.local)+bank.gate_bias
    # silu(d) * sigmoid(g), matching the research post-Encoder Head's mechanism.
    z=(d/(1+np.exp(-d)))*(1/(1+np.exp(-g)))
    delta=np.einsum('ndr,nr->nd',bank.up,z)
    shared=bank.feature[np.newaxis,:]+delta
    result=np.einsum('ncd,nd->nc',bank.output,shared)+bank.output_bias
    if result.shape!=(bank.cells,CLASSES) or not np.isfinite(result).all():
        raise ValueError("non-finite or missing physical Cell output")
    return result.astype('<f4',copy=False)


def _resident():
    # Current process RSS from Linux procfs, rather than cumulative peak RSS.
    try:
        with open('/proc/self/status',encoding='ascii') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1])*1024
    except OSError:
        return None
    return None


def _digest_arrays(arrays):
    h=hashlib.sha256()
    for a in arrays:
        h.update(str(a.shape).encode('ascii'))
        h.update(b'\0')
        h.update(a.tobytes(order='C'))
    return h.hexdigest()


def _percentile(samples,q):
    """Recorded empirical nearest-rank upper order statistic, not a CI."""
    ordered=sorted(samples)
    from math import ceil
    return ordered[max(0,ceil(q*len(ordered))-1)]


def run(cells,*,trials=5,seed=7347):
    if type(trials) is not int or not 3 <= trials <= 200:
        raise ValueError("bounded physical trial count 3..200")
    if head_parameters()!=9744:
        raise AssertionError("declared Head geometry drift")
    prior=_resident()
    build_wall_start=time.perf_counter_ns()
    build_cpu_start=time.process_time_ns()
    bank=build_bank(cells,seed)
    build_wall=time.perf_counter_ns()-build_wall_start
    build_cpu=time.process_time_ns()-build_cpu_start
    loaded=_resident()
    if bank.physical_parameters!=cells*9744 or bank.weight_bytes!=cells*9744*4:
        raise ValueError("incorrect physical parameter inventory")
    weights_sha=_digest_arrays((bank.down,bank.gate,bank.gate_bias,bank.up,bank.output,bank.output_bias))
    shared_sha=hashlib.sha256(bank.feature.tobytes()).hexdigest()
    with open(__file__,'rb') as source_file:
        execution_source_sha256=hashlib.sha256(source_file.read()).hexdigest()
    results=[]
    cpu=[]
    output_hashes=[]
    rss_samples=[]
    # Warmup (charged separately) is not silently included in trial denominator.
    warmup_start=time.perf_counter_ns()
    warmup_output=forward(bank)
    warmup_ns=time.perf_counter_ns()-warmup_start
    if warmup_output.shape!=(cells,CLASSES):
        raise ValueError("incomplete Cell fanout")
    for _ in range(trials):
        a=time.perf_counter_ns(); b=time.process_time_ns()
        out=forward(bank)
        results.append(time.perf_counter_ns()-a)
        cpu.append(time.process_time_ns()-b)
        output_hashes.append(hashlib.sha256(out.tobytes()).hexdigest())
        rss_samples.append(_resident())
    if weights_sha!=_digest_arrays((bank.down,bank.gate,bank.gate_bias,bank.up,bank.output,bank.output_bias)):
        raise ValueError("Head weight bytes drifted during benchmark")
    if shared_sha!=hashlib.sha256(bank.feature.tobytes()).hexdigest():
        raise ValueError("shared input mutated during benchmark")
    if len(set(output_hashes))!=1:
        raise ValueError("frozen Head bytes produced inconsistent outputs")
    return {
        'schema':'hepta.ndu-stem.head-only-physical.v1',
        'host':{'platform':platform.platform(), 'python':platform.python_version(),
                'numpy':np.__version__,'pid':os.getpid()},
        'seed':seed,
        'execution_source_sha256':execution_source_sha256,
        'declared_blas_threads':os.environ.get('OPENBLAS_NUM_THREADS'),
        'cells_actually_executed':cells,
        'distinct_head_parameter_sets':cells,
        'total_head_parameters':bank.physical_parameters,
        'physical_fp32_head_weight_bytes':bank.weight_bytes,
        'per_cell_head_parameters':head_parameters(),
        'synthetic_shared_feature_sha256':shared_sha,
        'synthetic_feature_producer_model':None,
        'physical_encoder_forward_count':0,
        'weights_material_sha256':weights_sha,
        'output_sha256':output_hashes[0],
        'build_wall_ns':build_wall,'build_cpu_ns':build_cpu,
        'warmup_wall_ns':warmup_ns,
        'physical_batch_trials':trials,
        'batch_wall_p50_ns':_percentile(results,.5) if trials>=3 else None,
        'batch_wall_p95_ns':_percentile(results,.95) if trials>=20 else None,
        'batch_wall_p99_ns':_percentile(results,.99) if trials>=100 else None,
        'batch_wall_raw_ns':results,
        'batch_cpu_raw_ns':cpu,
        'rss_prebuild_bytes':prior,
        'rss_after_weight_load_bytes':loaded,
        'rss_during_trials_sampled_bytes':rss_samples,
        'true_process_peak_rss_bytes':None,
        'request_queue_p99_ns':None,
        'gpu_bytes':None,'energy_joules':None,
        'model_training_performed':False,
        'physical_target_host_qualified':False,
        'source_owner_signature_verified':False,
        'request_level_latency_measurement':False,
        'pretrained_stem_executed':False,
        'real_multimodal_competence_established':False,
        'independent_task_utility_established':False,
        'production_accepted':False,
        'authority':'DENY_ALL',
    }


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--cells',type=int,choices=(64,256,1024,4096),required=True)
    a.add_argument('--trials',type=int,default=5)
    a.add_argument('--seed',type=int,default=7347)
    a.add_argument('--output',type=str)
    x=a.parse_args()
    result=run(x.cells,trials=x.trials,seed=x.seed)
    rendered=json.dumps(result,sort_keys=True,indent=2)+'\n'
    if x.output:
        with open(x.output,'x',encoding='utf-8') as f:
            f.write(rendered)
    print(rendered,end='')

if __name__=='__main__':
    main()
