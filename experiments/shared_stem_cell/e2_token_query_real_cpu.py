#!/usr/bin/env python3
"""Physical Token Matrix and pooled vectors from the SAME pinned forward.

The only real path consumes previously validated E1 model-source directories;
no network, silent conversion, synthetic fallback or promotion is permitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
from torch.nn import functional as F

from e2_token_query_ablation import study, frozen_bank, Q24, Invalid

MAX_BATCH = 8
MAX_TOKENS = 512


def _digest_file(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024**2),b''):
            h.update(chunk)
    return h.hexdigest()


def validate_stage(stage: Path, parent_report: dict, *, model: str):
    """Bind E2 model bytes to actual E1 parent publisher inventory."""
    from e1_core_real_cpu import MODELS, canonical, sha
    if model not in MODELS:
        raise Invalid('unregistered core candidate')
    repository, revision, width, kind, pooling = MODELS[model]
    if (parent_report.get('model')!=model or parent_report.get('model_name')!=repository
            or parent_report.get('model_revision')!=revision
            or parent_report.get('feature_width')!=width
            or parent_report.get('authority')!='DENY_ALL'
            or parent_report.get('production_promotion_permitted') is not False):
        raise Invalid('E1 model parent missing exact source binding')
    obs=parent_report.get('physical_observations')
    expected=obs.get('publisher_file_inventory_sha256') if isinstance(obs,dict) else None
    if type(expected) is not str or len(expected)!=64:
        raise Invalid('missing original publisher inventory')
    root=stage/'model'
    if stage.is_symlink() or root.is_symlink() or not root.is_dir():
        raise Invalid('missing or symlinked original staged model')
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise Invalid('no symlinked model material')
        if path.is_file():
            relative=path.relative_to(root).as_posix()
            if len(relative)>256 or len(files)>=128:
                raise Invalid('unbounded original publisher inventory')
            files[relative]=_digest_file(path)
    if ('model.safetensors' not in files or 'tokenizer.json' not in files
            or 'config.json' not in files or sha(canonical(sorted(files.items())))!=expected):
        raise Invalid('E1-to-E2 publisher weight/tokenizer content changed')
    return {'path':'model','kind':kind,'revision':revision,'model_id':repository,
            'conversion':None,'files':files},pooling,width


def extract(cases: list[dict], backend, *, pooling: str, width: int,
            batch_size: int = MAX_BATCH):
    """One real nn.Module forward for each physical microbatch, never per Cell.

    Model-hook counts are local process observations, not signed Worker witness.
    Token Matrix is unit-L2 token normalized, Q24 and unpadded; the separate
    native pool is computed from the same original hidden state before norm.
    """
    if width not in (384,768) or type(batch_size) is not int or not 1<=batch_size<=8:
        raise Invalid('invalid E2 physical batch or feature width')
    from e1_core_real_cpu import _render_joint
    from multimodal_native_pool_v7 import pool_hidden_state
    if len(cases)!=224 or getattr(backend,'forward_calls',None)!=0:
        raise Invalid('exact original case count and pristine backend needed')
    model=backend.model
    if not isinstance(model,torch.nn.Module) or not isinstance(backend.tokenizer,object):
        raise Invalid('real registered nn.Module and tokenizer required')
    observed=[0]
    def witness(_module,_args,_output):
        observed[0]+=1
    hook=model.register_forward_hook(witness)
    features={};counts={};duration={};started=time.perf_counter_ns()
    try:
        for start in range(0,len(cases),batch_size):
            group=cases[start:start+batch_size]
            strings=[_render_joint(c['joint_input']) for c in group]
            special=getattr(getattr(backend,'loaded',None),'config',None)
            native_modern=getattr(special,'model_type',None)=='modernbert'
            options={'padding':True,'truncation':False,'return_tensors':'pt'}
            if native_modern:options['return_token_type_ids']=False
            tokenized=backend.tokenizer(strings,**options)
            if type(tokenized) not in (dict,) and not hasattr(tokenized,'items'):
                raise Invalid('tokenizer returned invalid native tensors')
            if native_modern and set(tokenized)!={'input_ids','attention_mask'}:
                raise Invalid('unexpected ModernBERT tokenizer key')
            ids=tokenized['input_ids'];mask=tokenized['attention_mask']
            if (ids.ndim!=2 or tuple(mask.shape)!=tuple(ids.shape)
                    or ids.shape[0]!=len(group) or ids.shape[1]>MAX_TOKENS
                    or not bool(((mask==0)|(mask==1)).all())
                    or not bool((mask[:,0]==1).all())
                    or not bool((mask[:,1:]<=mask[:,:-1]).all())):
                raise Invalid('invalid or truncated exact token matrix')
            t0=time.perf_counter_ns()
            with torch.inference_mode():
                native=model(**tokenized).last_hidden_state.float()
                if (native.ndim!=3 or native.shape[:2]!=mask.shape
                        or native.shape[2]!=width or not bool(torch.isfinite(native).all())):
                    raise Invalid('real Encoder returned wrong token matrix')
                pooled=pool_hidden_state(native,mask,pooling)
                pooled=F.normalize(pooled,dim=-1)
                tokens=F.normalize(native,dim=-1)
                q_tokens=torch.round(tokens*Q24)/Q24
                q_pooled=torch.round(pooled*Q24)/Q24
            elapsed=(time.perf_counter_ns()-t0)/1e6
            if observed[0]!=(start//batch_size+1):
                raise Invalid('backend real model hook/physical batch drift')
            for n,row in enumerate(group):
                count=int(mask[n].sum())
                if not 1<=count<=MAX_TOKENS or row['case_id'] in features:
                    raise Invalid('missing or duplicated full token input')
                features[row['case_id']]={
                    'tokens':q_tokens[n,:count].detach().cpu().contiguous(),
                    'native_pooled':q_pooled[n].detach().cpu().contiguous()}
                counts[row['case_id']]=count
                duration[row['case_id']]=elapsed/len(group)
            backend.forward_calls+=1
    finally:
        hook.remove()
    if observed[0]!=math.ceil(len(cases)/batch_size) or backend.forward_calls!=observed[0]:
        raise Invalid('incomplete real physical batch fanout')
    receipt={'observed_model_module_forward_hooks':observed[0],
             'observed_backend_forward_calls':backend.forward_calls,
             'actual_unique_input_count':len(features),
             'microbatch_size_bound':batch_size,
             'max_tokens_per_input':max(counts.values()),
             'min_tokens_per_input':min(counts.values()),
             'producer_observed_encode_wall_ms':(time.perf_counter_ns()-started)/1e6,
             'encoder_forward_elapsed_ms_by_case_amortized':duration,
             'native_pool_and_token_query_derived_from_same_hidden_tensor':True,
             'independent_model_module_execution_attested':False}
    return features,receipt


def execute(panel: dict, panel_sha: str, model: str, stage: Path,
            parent: dict, parent_sha: str, replay_capture: dict | None = None):
    from e1_core_real_cpu import PANEL_SHA256,MODELS
    from experiments.shared_stem_cell.execution import LocalEncoder
    if (panel_sha!=PANEL_SHA256 or parent.get('public_panel_sha256')!=panel_sha
            or model not in MODELS):
        raise Invalid('different exact E1 original public cohort')
    manifest,pooling,width=validate_stage(stage,parent,model=model)
    start=time.perf_counter_ns();cpu=time.process_time_ns()
    torch.set_num_threads(2)
    load=time.perf_counter_ns()
    backend=LocalEncoder(stage/'model',manifest,maximum_tokens=MAX_TOKENS)
    load_ms=(time.perf_counter_ns()-load)/1e6
    if backend.loaded.config.hidden_size!=width:
        raise Invalid('wrong full pretrained Encoder architecture')
    cases=panel['cases']
    bank,physical=extract(cases,backend,pooling=pooling,width=width)
    backend.close()
    pre=frozen_bank(cases,bank,width=width)
    heads = {} if replay_capture is not None else None
    training=study(cases,bank,width=width,replay_head_states=heads)
    if training['feature_bank']!=pre or frozen_bank(cases,bank,width=width)!=pre:
        raise Invalid('physical frozen feature bank modified by learning')
    if replay_capture is not None:
        if type(replay_capture) is not dict or replay_capture:
            raise Invalid('replay capture must start empty')
        replay_capture.update(cases=cases,snapshots=bank,head_states=heads)
    return {'schema':'hepta.stem.e2-paired-actual-encoder-heads.v1',
        'model':model,'model_revision':manifest['revision'],
        'parent_e1_report_sha256':parent_sha,'panel_sha256':panel_sha,
        'pooling_profile':pooling,'token_normalization':'token_unit_l2_then_q24',
        'native_pooled_normalization':'native_pool_then_unit_l2_then_q24',
        'physical':physical,'feature_bank':pre,'head_study':training,
        'total_wall_ms':(time.perf_counter_ns()-start)/1e6,
        'cpu_process_ms':(time.process_time_ns()-cpu)/1e6,
        'model_load_ms':load_ms,
        'process_lifetime_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'energy_joules':None,'p95_ms':None,'p99_ms':None,
        'physically_shared_across_production_cells_verified':False,
        'independent_model_source_attestation':False,
        'real_future_ndu_verified':False,'production_no_change_verified':False,
        'stem_winner_selected':False,'production_promotion_permitted':False,
        'authority':'DENY_ALL'}


def main():
    from e1_core_real_cpu import load_panel,sha
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',type=Path,required=True)
    parser.add_argument('--model',choices=('granite_97m_r2','mmbert_small','modernbert_base'),required=True)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--e1',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replay-bundle',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.replay_bundle.exists():
        raise FileExistsError('cannot overwrite E2 research or replay receipt')
    panel,panel_sha=load_panel(args.panel)
    raw=args.e1.read_bytes()
    parent=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(Invalid('nonfinite E1')))
    capture={}
    result=execute(panel,panel_sha,args.model,args.stage,parent,sha(raw),replay_capture=capture)
    with args.output.open('x',encoding='utf8') as target:
        json.dump(result,target,sort_keys=True,allow_nan=False)
        target.write('\n')
    from e2_head_replay import write_bundle
    write_bundle(args.replay_bundle,capture['cases'],capture['snapshots'],
                 capture['head_states'],result,sha(args.output.read_bytes()))

if __name__=='__main__':main()
