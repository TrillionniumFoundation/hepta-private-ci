"""E6 physical NumPy fan-out of real Cell-head math over a SYNTHETIC Stem.

No actual pretrained weights/encoder are loaded. This is an offline contract and
resource profile, not Neuron Worker/final-use authority or model-quality proof.
The synthetic bottleneck below is not a 97M/421M forward; do NOT compare times.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import time
from typing import Callable, Sequence

import numpy as np

from budget import CellUse, FeatureIdentity, Profile, estimate

D, S, R, C = 384, 64, 8, 8
_SOURCE_BYTES = D * 4
_MAX_ACTIVE = 4096


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Source:
    identity: FeatureIdentity
    raw_float32: bytes

    def checked(self) -> np.ndarray:
        self.identity.validate()
        if type(self.raw_float32) is not bytes or len(self.raw_float32) != _SOURCE_BYTES:
            raise ValueError("fixed complete synthetic source vector required")
        if sha(self.raw_float32) != self.identity.source_sha256:
            raise ValueError("source bytes are not bound to the scoped identity")
        inp = np.frombuffer(self.raw_float32, dtype='<f4')
        if inp.shape != (D,) or not np.isfinite(inp).all() or np.abs(inp).max() > 8:
            raise ValueError("invalid source numerics")
        return inp


@dataclass(frozen=True)
class Bank:
    down: np.ndarray
    gate: np.ndarray
    gb: np.ndarray
    up: np.ndarray
    out: np.ndarray
    ob: np.ndarray
    state: np.ndarray

    @property
    def size(self) -> int:
        return self.state.shape[0]

    def checked(self, n: int) -> None:
        sizes = ((n,R,D), (n,R,S), (n,R), (n,D,R), (n,C,D), (n,C), (n,S))
        for array, shape in zip((self.down,self.gate,self.gb,self.up,self.out,self.ob,self.state), sizes):
            if not isinstance(array,np.ndarray) or array.shape!=shape or array.dtype!=np.dtype('float32') or not np.isfinite(array).all():
                raise ValueError("physical Head geometry/numerics invalid")
        count=sum(x.size for x in (self.down,self.gate,self.gb,self.up,self.out,self.ob))
        if count != n*9744:
            raise ValueError("actual trainable Head tensor count mismatch")


def make_bank(n: int, seed: int = 1506) -> Bank:
    if type(n) is not int or not 1 <= n <= _MAX_ACTIVE:
        raise ValueError("1..4096 Cell bank required")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid reproducibility seed")
    rng=np.random.default_rng(seed)
    def draw(shape):
        return (rng.standard_normal(shape,dtype=np.float32)*np.float32(.015)).astype(np.float32)
    return Bank(draw((n,R,D)),draw((n,R,S)),draw((n,R)),draw((n,D,R)),
                draw((n,C,D)),draw((n,C)),draw((n,S)))


class SyntheticStem:
    """Fixed *toy* 384→48→384 projection; never call this an Encoder model."""
    def __init__(self, seed: int=1775):
        rng=np.random.default_rng(seed)
        self.p = (rng.standard_normal((D,48),dtype=np.float32)*np.float32(.025)).astype(np.float32)
        self.q = (rng.standard_normal((48,D),dtype=np.float32)*np.float32(.025)).astype(np.float32)
        self.calls=0

    def encode(self, inp: np.ndarray) -> np.ndarray:
        if not isinstance(inp,np.ndarray) or inp.shape!=(D,) or inp.dtype!=np.float32 or not np.isfinite(inp).all():
            raise ValueError("only validated synthetic 384D float32 inputs admitted")
        self.calls+=1
        with np.errstate(over='raise',invalid='raise'):
            feat=np.tanh(np.tanh(inp@self.p)@self.q).astype(np.float32)
        feat.setflags(write=False)
        return feat


def head_forward(bank: Bank, idx: np.ndarray, shared_feature: np.ndarray) -> np.ndarray:
    """Actually compute all six distinct 9744-param tensors of selected Cells."""
    if type(idx) is not np.ndarray or idx.ndim!=1 or len(idx)==0 or idx.dtype.kind not in ('i','u'):
        raise ValueError("nonempty integer Cell indices required")
    if not isinstance(shared_feature,np.ndarray) or shared_feature.shape!=(D,) or shared_feature.dtype!=np.dtype('float32') or not np.isfinite(shared_feature).all():
        raise ValueError("validated shared feature required")
    down=np.einsum('nrd,d->nr',bank.down[idx],shared_feature, optimize=False)
    gates=np.einsum('nrs,ns->nr',bank.gate[idx],bank.state[idx],optimize=False)+bank.gb[idx]
    latent=(down/(1+np.exp(-down)))*(1/(1+np.exp(-gates)))
    delta=np.einsum('ndr,nr->nd',bank.up[idx],latent,optimize=False)
    hidden=shared_feature[None,:]+delta
    result=np.einsum('ncd,nd->nc',bank.out[idx],hidden,optimize=False)+bank.ob[idx]
    if not np.isfinite(result).all():
        raise ValueError("nonfinite Cell logits")
    return np.asarray(result, dtype='<f4')


def execute(uses: Sequence[CellUse], sources: dict[FeatureIdentity,Source], bank: Bank,
            *, reuse: bool, authorize: Callable[[FeatureIdentity],bool]) -> dict:
    """Same complete per-Cell inference both arms; reuse affects only toy Stem.

    A host callback is invoked on *every Cell use*, even cache hits, before
    reading the source/cache. This callback is only a research fixture: no
    authority comes from this Python layer. Revocation never falls back.
    """
    if type(reuse) is not bool or not callable(authorize):
        raise ValueError("explicit cache policy and authorization callback needed")
    if type(uses) not in (tuple,list) or not 1<=len(uses)<=_MAX_ACTIVE:
        raise ValueError("bounded Cell cohort required")
    # Delegate complete identity, duplicate and profile accounting to E0.
    profile=estimate(uses, Profile())
    bank.checked(len(uses))
    if type(sources) is not dict:
        raise ValueError("source map required")
    if any(type(k) is not FeatureIdentity or type(v) is not Source or v.identity!=k
           for k,v in sources.items()):
        raise ValueError("source map identity conflict")
    stem=SyntheticStem()
    rows=np.zeros((len(uses),C),dtype=np.float32)
    groups:dict[FeatureIdentity,list[int]]={}
    normalized={}
    t0=time.perf_counter_ns(); c0=time.process_time_ns()
    approved=0
    for i,use in enumerate(uses):
        if not use.active:
            continue
        # The expensive/permission-sensitive callback runs before cache lookup.
        if authorize(use.identity) is not True:
            raise PermissionError("current-scope final-use denied: no result")
        approved+=1
        source=sources.get(use.identity)
        if source is None:
            raise ValueError("unbound source identity")
        validated=source.checked()
        if use.identity in normalized:
            # Even an apparently shared identity is never a substitute for a
            # check of the full supplied source bytes.
            if not np.array_equal(normalized[use.identity],validated):
                raise ValueError("same-identity source collision")
        else:
            normalized[use.identity]=validated
        groups.setdefault(use.identity,[]).append(i)
    cache={}
    for key,ix in groups.items():
        inp=normalized[key]
        if reuse:
            if key not in cache:
                cache[key]=stem.encode(inp)
            feat=cache[key]
        else:
            # Physically recompute the toy encoder for every logical Cell.
            # Head grouping is unchanged, so both arms pay the SAME Head work.
            repeated=[stem.encode(inp) for _ in ix]
            if any(x.tobytes()!=repeated[0].tobytes() for x in repeated[1:]):
                raise ValueError("synthetic encoder is not deterministic")
            feat=repeated[0]
        rows[np.asarray(ix,dtype=np.int64)]=head_forward(bank,np.asarray(ix,dtype=np.int64),feat)
    wall=time.perf_counter_ns()-t0; cpu=time.process_time_ns()-c0
    if stem.calls!=(len(groups) if reuse else profile['active_cell_uses']):
        raise ValueError("physical synthetic invocation inventory changed")
    return {'schema':'hepta.e6.head-toy-encoder-physical.v1','authority':'DENY_ALL',
            'actual_pretrained_encoder_invocations':0,'synthetic_encoder_invocations':stem.calls,
            'real_cell_head_forwards':profile['active_cell_uses'],
            'separately_authorized_cell_uses':approved,'unique_scoped_sources':len(groups),
            'cached':reuse, 'measured_batch_wall_ns':wall,'measured_process_cpu_ns':cpu,
            'logits_sha256':sha(rows.astype('<f4',copy=False).tobytes()),
            'head_trainable_parameters':len(uses)*9744,
            'weight_geometry_not_rss_bytes':len(uses)*9744*4,
            'process_maxrss_kib':_maxrss_kib(),
            'qualified_final_use':False,'production_accepted':False,'real_task_utility':None}


def _maxrss_kib() -> int | None:
    if os.name!='posix':
        return None
    try:
        import resource
        import sys
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss if sys.platform.startswith('linux') else None
    except ImportError:
        return None


def build_sources(n: int, source_groups: int, *, split_scope: bool=False):
    if type(n) is not int or not 1<=n<=_MAX_ACTIVE or type(source_groups) is not int or not 1<=source_groups<=n:
        raise ValueError("invalid physical sample cohort/group counts")
    rng=np.random.default_rng(1201)
    records={};use=[]
    def hx(i):
        return f'{i:064x}'
    for i in range(n):
        j=i%source_groups
        scope='demo_scope_B' if split_scope and (i%2) else 'demo_scope_A'
        inp=(np.sin(np.arange(D,dtype=np.float32)*np.float32(.01)+np.float32(j))*.1).astype('<f4')
        raw=inp.tobytes()
        key=FeatureIdentity(scope,23,hx(1),hx(2),hx(3),sha(raw),hx(4))
        records.setdefault(key,Source(key,raw))
        use.append(CellUse(f'cell_{i}',key))
    return use,records


def bench(n:int,source_groups:int,trials:int,split_scope:bool):
    if type(trials) is not int or not 1<=trials<=100:
        raise ValueError("bounded 1..100 observed repetitions")
    uses,sources=build_sources(n,source_groups,split_scope=split_scope)
    bank=make_bank(n)
    hashes=set();results={}
    for caching in (False,True):
        key='cached' if caching else 'no_feature_reuse'
        results[key]=[]
        for _ in range(trials):
            val=execute(uses,sources,bank,reuse=caching,authorize=lambda _key:True)
            hashes.add(val['logits_sha256']);results[key].append(val)
    if len(hashes)!=1:
        raise ValueError("cached and uncached output logits differ")
    return {'schema':'hepta.e6.paired-synthetic-physical-cost.v1','authority':'DENY_ALL',
            'physical_cell_head_tensors_used':True,'real_pretrained_forward_count':0,
            'head_bank_trainable_weight_bytes':bank.down.nbytes+bank.gate.nbytes+bank.gb.nbytes+bank.up.nbytes+bank.out.nbytes+bank.ob.nbytes,
            'cells':n,'source_groups_requested':source_groups,'scope_split':split_scope,
            'trials':trials,'all_observed_outputs_identical':True,'logits_sha256':next(iter(hashes)),
            'arms':{name:{'median_batch_wall_ns':int(np.median([x['measured_batch_wall_ns'] for x in observations])),
                          'min_batch_wall_ns':min(x['measured_batch_wall_ns'] for x in observations),
                          'max_batch_wall_ns':max(x['measured_batch_wall_ns'] for x in observations),
                          'median_process_cpu_ns':int(np.median([x['measured_process_cpu_ns'] for x in observations])),
                          'synthetic_encoder_invocations_per_trial':observations[0]['synthetic_encoder_invocations'],
                          'head_forwards_per_trial':observations[0]['real_cell_head_forwards'],
                          'authorized_uses_per_trial':observations[0]['separately_authorized_cell_uses'],
                          'process_maxrss_kib_last_trial':observations[-1]['process_maxrss_kib'],
                          'observed_batch_wall_ns':[x['measured_batch_wall_ns'] for x in observations],
                          'observed_process_cpu_ns':[x['measured_process_cpu_ns'] for x in observations],
                          'observed_maxrss_kib':[x['process_maxrss_kib'] for x in observations]}
                    for name,observations in results.items()},
            'p95_p99_latency_qualified':False,'full_end_to_end_cost_qualified':False,
            'qualified_final_use':False,'production_accepted':False}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--cells',type=int,default=64)
    a.add_argument('--source-groups',type=int,default=8)
    a.add_argument('--trials',type=int,default=3)
    a.add_argument('--split-scope',action='store_true')
    a.add_argument('--output',required=True)
    opts=a.parse_args()
    result=bench(opts.cells,opts.source_groups,opts.trials,opts.split_scope)
    # prevent accidental overwriting of measurement files or source drift
    with open(opts.output,'x',encoding='utf-8') as out:
        json.dump(result,out,sort_keys=True,separators=(',',':'),allow_nan=False)
        out.write('\n')
    print(json.dumps({'cells':opts.cells,'sources':result['arms']['cached']['synthetic_encoder_invocations_per_trial'],
                      'full_pretrained_calls':0,'production_accepted':False},sort_keys=True))


if __name__=='__main__':
    main()
