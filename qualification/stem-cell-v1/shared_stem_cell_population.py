"""Actual CPU sparse-Cell cohort behind one frozen, physically shared toy Stem.

Research-only. The 384x384 encoder is randomly seeded, NOT pretrained. Every
state-gated 384/64/rank-8/8 Head is an actual FP32 tensor, not a claimed Cell.
Memory, caching, local SGD, and inference are physically executed, but neither
pretrained task efficacy, end-to-end 421M costs, native Rust FinalUse nor NDU
improvement is inferred. This is a falsifiable P1 mechanics counterfactual.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from reader_support_fanout import context_claim, validate_context

SCHEMA = 'hepta.reader.physical-stem-packed-cell-cohort.v1'
WIDTH, STATE, RANK, CLASSES = 384, 64, 8, 8
HEAD_PARAMS = 9744
SIZES = (64, 256, 1024, 4096)
MODES = ('repeated', 'distinct', 'two_scopes')
MAX_CACHE_BYTES = 256 * 1024 * 1024


def digest_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def tensor_sha(tensor):
    if (not isinstance(tensor, torch.Tensor) or tensor.dtype != torch.float32
            or tensor.device.type != 'cpu' or not torch.isfinite(tensor).all().item()):
        raise ValueError('exact finite CPU FP32 tensor required')
    return hashlib.sha256(tensor.detach().contiguous().numpy().tobytes()).hexdigest()


def stem_weight_sha(stem):
    h=hashlib.sha256()
    for p in stem.parameters():
        h.update(p.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


class SmallFrozenStem(torch.nn.Module):
    """Physically executed tiny linear stem; deliberately not pretrained."""

    def __init__(self, seed=7347):
        super().__init__()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.linear = torch.nn.Linear(WIDTH, WIDTH).eval()
        self.eval()
        for p in self.parameters():
            p.requires_grad_(False)
        self.calls = 0
        self.actual_parameter_count = sum(p.numel() for p in self.parameters())

    @torch.no_grad()
    def forward(self, x):
        if (not isinstance(x,torch.Tensor) or x.shape != (WIDTH,)
                or x.dtype != torch.float32 or not torch.isfinite(x).all().item()):
            raise ValueError('unsupported synthetic Stem input')
        self.calls += 1
        return self.linear(x).detach().clone()


class PackedGatedHeads:
    """Exactly the six matrices of the 9,744-parameter output-only Head."""

    def __init__(self, cells, seed):
        if type(cells) is not int or cells not in SIZES:
            raise ValueError('physical registered Cell cohort required')
        gen = torch.Generator(device='cpu').manual_seed(seed)
        self.n = cells
        self.weights = {
            'down': torch.randn(cells,RANK,WIDTH,generator=gen,dtype=torch.float32)/(WIDTH**.5),
            'gate': torch.randn(cells,RANK,STATE,generator=gen,dtype=torch.float32)/(STATE**.5),
            'gate_bias': torch.zeros(cells,RANK,dtype=torch.float32),
            'up': torch.zeros(cells,WIDTH,RANK,dtype=torch.float32),
            'output': torch.randn(cells,CLASSES,WIDTH,generator=gen,dtype=torch.float32)/(WIDTH**.5),
            'output_bias': torch.zeros(cells,CLASSES,dtype=torch.float32),
        }
        self.param_count = sum(w.numel() for w in self.weights.values())
        assert self.param_count == HEAD_PARAMS * cells

    def rows(self, selected):
        return {name: weight.index_select(0,selected) for name,weight in self.weights.items()}

    @staticmethod
    def predict(w, feature, state):
        if (feature.ndim != 2 or feature.shape[1]!=WIDTH
                or state.shape != (len(feature),STATE)
                or any(x.shape[0] != len(feature) for x in w.values())
                or not torch.isfinite(feature).all().item()
                or not torch.isfinite(state).all().item()):
            raise ValueError('bounded attached state/feature geometry required')
        a=torch.bmm(w['down'],feature.detach().unsqueeze(-1)).squeeze(-1)
        b=torch.bmm(w['gate'],state.detach().unsqueeze(-1)).squeeze(-1)+w['gate_bias']
        delta=torch.bmm(w['up'],(F.silu(a)*torch.sigmoid(b)).unsqueeze(-1)).squeeze(-1)
        return torch.bmm(w['output'],(feature.detach()+delta).unsqueeze(-1)).squeeze(-1)+w['output_bias']

    def dormant_digest(self, selected):
        """Hash every dormant physical weight by bounded streaming, no giant audit copy."""
        active=set(selected.tolist());h=hashlib.sha256()
        for name,weight in self.weights.items():
            h.update(name.encode()+b'\0')
            for i in range(self.n):
                if i not in active:
                    h.update(weight[i].detach().contiguous().numpy().tobytes())
        return h.hexdigest()

    def fit_sparse(self, selected, train_features, train_state, labels, steps=2):
        if type(steps) is not int or not 2<=steps<=8:
            raise ValueError('real bounded sparse SGD steps required')
        before=self.dormant_digest(selected)
        subset={name:torch.nn.Parameter(v.detach().clone()) for name,v in self.rows(selected).items()}
        optimizer=torch.optim.SGD(subset.values(),lr=.04)
        def forward():
            return self.predict(subset,train_features.detach(),train_state.detach())
        with torch.no_grad():
            initial=float(F.cross_entropy(forward(),labels,reduction='mean').item())
        changed=[]
        original={name:p.detach().clone() for name,p in subset.items()}
        for _ in range(steps):
            optimizer.zero_grad(set_to_none=True)
            loss=F.cross_entropy(forward(),labels,reduction='sum')/len(labels)
            if not bool(torch.isfinite(loss).item()):
                raise ValueError('finite actual Head update required')
            loss.backward()
            optimizer.step()
        final=float(F.cross_entropy(forward(),labels,reduction='mean').item())
        for name,param in subset.items():
            changed.append(int(torch.count_nonzero(param.detach()!=original[name]).item()))
        with torch.no_grad():
            for name,param in subset.items():
                self.weights[name].index_copy_(0,selected,param.detach())
        if before!=self.dormant_digest(selected) or sum(changed)==0:
            raise ValueError('dormant mutation or no actual trainable Head learning')
        return {'training_steps':steps,'training_examples':len(labels)*steps,
                'train_loss_initial':initial,'train_loss_final':final,
                'trainable_active_parameters':HEAD_PARAMS*len(labels),
                'physically_changed_active_scalars':sum(changed),
                'dormant_weights_byte_identical':True}


def unpacked_single_head(weights, feature, state, idx):
    """Separate native F.linear reconstruction; checks packed bmm math."""
    w={k:v[idx] for k,v in weights.items()}
    a=F.silu(F.linear(feature,w['down']))
    b=torch.sigmoid(F.linear(state,w['gate'],w['gate_bias']))
    delta=F.linear(a*b,w['up'])
    return F.linear(feature+delta,w['output'],w['output_bias'])


def study_context(principal):
    return context_claim(principal=principal,scope='research-no-production',
          generation=1,authority_epoch=1,stem_sha256='a'*64,
          tokenizer_sha256='b'*64,source_use_revision='sealed-synthetic-v1')


def study_cases(selected, *, seed, mode):
    if mode not in MODES:
        raise ValueError('registered duplicated/distinct source distribution required')
    cases=[]
    for ordinal,cell in enumerate(selected.tolist()):
        group=ordinal if mode=='distinct' else ordinal%4
        principal='tenant-b' if mode=='two_scopes' and (ordinal//4)%2 else 'tenant-a'
        gen=torch.Generator(device='cpu').manual_seed(seed+group+9000)
        raw=torch.randn(WIDTH,generator=gen,dtype=torch.float32)
        cases.append(dict(cell=cell,group=f'source-{group}',principal=principal,raw=raw))
    return cases


def physical_encode(cases,stem,*,cache_bytes,allow):
    if (not isinstance(stem,SmallFrozenStem) or type(cache_bytes) is not int
            or not 0<=cache_bytes<=MAX_CACHE_BYTES or not callable(allow)):
        raise ValueError('bounded owned physical research provider and access hook required')
    cache=OrderedDict();cache_used=0;hit=0;evictions=0;access=0;max_resident=0
    features=[];invariant_context={};distinct=set()
    start=stem.calls
    t0=time.perf_counter_ns()
    for c in cases:
        ctx=study_context(c['principal'])
        validate_context(ctx)
        rawsha=tensor_sha(c['raw'])
        key=digest_json({'scope_claim':ctx,'source_group':c['group'], 'raw_sha256':rawsha})
        distinct.add(key)
        context_sha=digest_json(ctx)
        if allow(c['cell'],c['group'],key,ctx) is not True or digest_json(ctx)!=context_sha:
            raise ValueError('per-cell access rejected or context modified by caller')
        access+=1
        if key in cache:
            feat,sz,sha=cache.pop(key)
            cache[key]=(feat,sz,sha)
            if tensor_sha(feat)!=sha:
                raise ValueError('cached feature mutated across logical Cells')
            hit+=1
        else:
            feat=stem(c['raw'])
            if feat.shape!=(WIDTH,):
                raise ValueError('physical Stem width drift')
            sz=feat.untyped_storage().nbytes(); sha=tensor_sha(feat)
            if sz<=cache_bytes:
                while cache and cache_used+sz>cache_bytes:
                    _,(_,removed,_) = cache.popitem(last=False)
                    cache_used-=removed;evictions+=1
                cache[key]=(feat,sz,sha)
                cache_used+=sz
                max_resident=max(max_resident,cache_used)
        features.append(feat)
    return (torch.stack(features,dim=0),{
        'encoder_calls':stem.calls-start,'logical_borrows':len(cases),
        'access_hook_calls':access,'cache_hits':hit,'cache_evictions':evictions,
        'unique_scoped_input_keys':len(distinct),'peak_cache_tensor_bytes':max_resident,
        'encoder_and_lookup_wall_ns':time.perf_counter_ns()-t0,
        'cache_budget_bytes':cache_bytes})


def run_study(cells,*,mode='repeated',seed=7347,cache_bytes=32*1024*1024,steps=2):
    if (type(cells) is not int or cells not in SIZES or mode not in MODES
            or type(seed) is not int or not 1<=seed<=2**31-1
            or type(cache_bytes) is not int or not 0<=cache_bytes<=MAX_CACHE_BYTES):
        raise ValueError('declared physical Cell experiment configuration required')
    torch.set_num_threads(1)
    start=time.perf_counter_ns()
    population=PackedGatedHeads(cells,seed)
    selection=torch.randperm(cells,generator=torch.Generator(device='cpu').manual_seed(seed+17))[:max(8,cells//10)]
    cases=study_cases(selection,seed=seed,mode=mode)
    stem=SmallFrozenStem(seed)
    initial_stem_sha=stem_weight_sha(stem)
    active_indices_sha=hashlib.sha256(selection.contiguous().numpy().tobytes()).hexdigest()
    actual_inputs_sha=hashlib.sha256(b''.join(c['raw'].contiguous().numpy().tobytes() for c in cases)).hexdigest()
    def permit(*_):return True  # Research hook only; not a signed FinalUse verifier.
    no_cache,control=physical_encode(cases,stem,cache_bytes=0,allow=permit)
    shared,cache=physical_encode(cases,stem,cache_bytes=cache_bytes,allow=permit)
    if not torch.equal(no_cache,shared):
        raise ValueError('cached Stem features diverge from physically recomputed original')
    state=torch.randn(len(cases),STATE,generator=torch.Generator(device='cpu').manual_seed(seed+123))
    snap=population.rows(selection)
    t0=time.perf_counter_ns()
    with torch.no_grad():
        before=population.predict(snap,no_cache,state)
        cached=population.predict(snap,shared,state)
    head_wall=time.perf_counter_ns()-t0
    max_diff=float(torch.max(torch.abs(before-cached)).item())
    if max_diff>0:
        raise ValueError('cache altered frozen specialized Cell predictions')
    max_module_diff=0.0
    for slot in sorted({0,len(cases)//2,len(cases)-1}):
        expected=unpacked_single_head(population.weights,shared[slot],state[slot],int(selection[slot]))
        max_module_diff=max(max_module_diff,float(torch.max(torch.abs(before[slot]-expected)).item()))
    if max_module_diff>1e-5:
        raise ValueError('independent unpacked real Head disagrees with packed bmm')
    old_digest=tensor_sha(before)
    labels=(torch.arange(len(cases),dtype=torch.int64)*7+seed)%CLASSES
    t0=time.perf_counter_ns()
    trained=population.fit_sparse(selection,shared,state,labels,steps)
    train_wall=time.perf_counter_ns()-t0
    with torch.no_grad():
        post=population.predict(population.rows(selection),shared,state)
    if tensor_sha(post)==old_digest:
        raise ValueError('frozen/learned Cell predictions did not change')
    learned_unpacked_error=0.0
    for slot in sorted({0,len(cases)//2,len(cases)-1}):
        expected=unpacked_single_head(population.weights,shared[slot],state[slot],int(selection[slot]))
        learned_unpacked_error=max(learned_unpacked_error,float(torch.max(torch.abs(post[slot]-expected)).item()))
    if learned_unpacked_error>1e-5 or stem_weight_sha(stem)!=initial_stem_sha:
        raise ValueError('trained Head numerics or selected frozen Stem weights drifted')
    out=dict(schema=SCHEMA,cohort_logical_cells=cells,active_cells=len(cases),
       active_fraction=len(cases)/cells,distribution=mode,seed=seed,
       stem_frozen_parameters=stem.actual_parameter_count,
       stem_original_weight_sha256=initial_stem_sha,
       stem_unchanged_after_learning=True,
       active_indices_sha256=active_indices_sha,
       original_source_input_sha256=actual_inputs_sha,
       stem_real_pretrained=False,stem_actual_physical_calls=stem.calls,
       head_parameters_total=population.param_count,
       head_resident_fp32_tensor_bytes=sum(x.numel()*x.element_size() for x in population.weights.values()),
       head_per_cell_parameters=HEAD_PARAMS,
       baseline=control,shared=cache,
       frozen_logits_sha256=old_digest,learned_logits_sha256=tensor_sha(post),
       shared_vs_uncached_logits_max_abs=max_diff,
       unpacked_vs_packed_logits_max_abs=max_module_diff,
       trained_unpacked_vs_packed_logits_max_abs=learned_unpacked_error,
       physical_head_forward_rows=(5+steps)*len(cases)+3,
       head_frozen_paired_forward_rows=2*len(cases),
       head_sparse_training_forward_rows=(2+steps)*len(cases),
       head_trained_validation_forward_rows=len(cases),
       head_unpacked_spot_rows=3,
       head_frozen_paired_forward_wall_ns=head_wall,
       head_local_training_wall_ns=train_wall,
       **trained,
       complete_study_wall_ns=time.perf_counter_ns()-start,
       is_cpu_synthetic=True, real_421m_model_loaded=False,
       model_quality_gain_established=False,independent_future_task_utility=False,
       actual_4096_real_worker_executed=False,
       signed_final_use_verified=False,full_lifecycle_cost_qualified=False,
       production_authorized=False,authority='DENY_ALL')
    if (out['baseline']['encoder_calls'] != out['active_cells']
         or out['shared']['encoder_calls']+out['shared']['cache_hits']!=out['active_cells']
         or out['baseline']['access_hook_calls']!=out['active_cells']
         or out['shared']['access_hook_calls']!=out['active_cells']):
        raise ValueError('inconsistent physical Encoder/cached Cell accounting')
    out['report_sha256']=digest_json(out)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cells',required=True,type=int,choices=SIZES)
    p.add_argument('--distribution',choices=MODES,default='repeated')
    p.add_argument('--seed',type=int,default=7347)
    p.add_argument('--cache-bytes',type=int,default=32*1024*1024)
    p.add_argument('--steps',type=int,default=2)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    result=run_study(args.cells,mode=args.distribution,seed=args.seed,
                     cache_bytes=args.cache_bytes,steps=args.steps)
    with args.output.open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,allow_nan=False,indent=2)
        f.write('\n')
    print(json.dumps({k:result[k] for k in ('schema','cohort_logical_cells','active_cells',
                                            'distribution','stem_actual_physical_calls','authority')},sort_keys=True))


if __name__=='__main__':main()
