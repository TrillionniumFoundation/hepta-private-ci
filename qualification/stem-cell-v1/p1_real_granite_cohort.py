"""Research-only pinned Granite97 + packed Cell physical cohort with genuine AG News labels.

No model weights or data are downloaded by this module. Hosted CI supplies the
existing audited, exact-revision FrozenCompactStem implementation and separately
pinned original AG News panel. This is NOT a production model/effect authorizer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import OrderedDict
from pathlib import Path
import resource
import sys
import time

import torch
from torch.nn import functional as F

from shared_stem_cell_population import (
    WIDTH, STATE, HEAD_PARAMS, SIZES, PackedGatedHeads,
    unpacked_single_head, tensor_sha,
)

PANEL_SHA = '2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'
GRANITE_REVISION = '835ad14087e140460703cf0fae09f97d469d65c2'
GRANITE_MODEL = 'granite-97m-multilingual-r2'
MODEL_ID = 'ibm-granite/granite-embedding-97m-multilingual-r2'
SCHEMA = 'hepta.stem.p1-real-granite-physical-cohort.v1'
MATERIAL = 'hepta.stem.p1-real-granite-material.v1'
PREDICT = 'hepta.stem.p1-real-granite-predictions.v1'
MODES = ('repeated4', 'test_panel', 'two_scopes')
COST_PHASES = ('encoding_material_ms','head_quality_training_ms','baseline_requests_ms',
               'shared_requests_ms','physical_cell_training_ms','scoring_forward_ms')
MAX_BYTES = 16 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(s):
    return hashlib.sha256(s).hexdigest()


def q24_vector(value):
    check(isinstance(value, torch.Tensor) and value.shape == (WIDTH,)
          and value.dtype == torch.float32 and value.device.type == 'cpu'
          and not value.requires_grad and bool(torch.isfinite(value).all()),
          'physical Encoder must return finite detached 384D FP32 vector')
    check(bool(torch.all(value.abs() <= 8)), 'Q24 physical values out of range')
    q = torch.round(value * (1 << 24)) / (1 << 24)
    check(torch.equal(q, value), 'actual Stem output is not exact Q24')
    return value.detach().clone()


def validate_case(c, *, labeled):
    fields = {'case_id','group_id','split','joint_input','joint_input_digest'} | ({'label'} if labeled else set())
    check(type(c) is dict and set(c) == fields, 'full case field and label isolation required')
    check(c['split'] in ('train','calibration','test') and isinstance(c['joint_input'], dict)
          and set(c['joint_input']) == {'state','question','options'}
          and c['joint_input']['options'] == ['world','sports']
          and c['joint_input']['question'] == 'Which category does the news report describe?'
          and isinstance(c['joint_input']['state'], str)
          and 1 <= len(c['joint_input']['state']) <= 10000,
          'original paired public news question schema required')
    expected = sha256(c['joint_input']['state'].encode('utf8'))
    check(c['case_id'] == expected[:24] and c['group_id'] == expected
          and c['joint_input_digest'] == sha256(canonical(c['joint_input'])),
          'original public source group / case / Q24 input drift')
    if labeled:
        check(type(c['label']) is int and c['label'] in (0, 1) and c['split']=='train',
              'only train cases may carry labels into training')


def prepare_material(original_panel):
    """Execute ONLY in source-owner preparation, before any model is loaded."""
    check(type(original_panel) is dict and digest(original_panel) == PANEL_SHA,
          'original public panel bytes are not the source-locked 224-case candidate')
    rows = original_panel.get('cases')
    check(type(rows) is list and len(rows)==224,'exact historical original panel required')
    train=[];blind=[];labels=[];seen=set();counts={'train':0,'calibration':0,'test':0}
    for item in rows:
        check(type(item) is dict and all(k in item for k in
              ('case_id','group_id','split','joint_input','joint_input_digest','label')),
              'source-owner panel lacks original category')
        part = item['split']; counts[part] += 1
        payload={k:item[k] for k in ('case_id','group_id','split','joint_input','joint_input_digest')}
        if part=='train':
            payload['label']=item['label']; validate_case(payload,labeled=True);train.append(payload)
        else:
            validate_case(payload,labeled=False);blind.append(payload)
            check(type(item['label']) is int and item['label'] in (0,1),
                  'original labels must be binary')
            labels.append({'case_id':item['case_id'],'label':item['label'],'split':part})
        check(item['group_id'] not in seen,'source identity must not overlap partitions')
        seen.add(item['group_id'])
    check(counts=={'train':128,'calibration':32,'test':64},'exact 128/32/64 source census')
    root={'schema':MATERIAL,'panel_sha256':PANEL_SHA,
          'source_is_cross_sectional_not_future':True,'source_origin_independently_signed':False,
          'model_revision':GRANITE_REVISION}
    training=dict(root,rows=train,role='train_labels_only')
    evaluation=dict(root,rows=blind,role='blind_calibration_and_test')
    owner=dict(schema=MATERIAL+'.labels',panel_sha256=PANEL_SHA,rows=labels,
               independent_observer_authenticated=False)
    for obj in (training,evaluation,owner):obj['seal_id']=digest(obj)
    return training,evaluation,owner


def verify_material(training,blind):
    check(type(training) is dict and type(blind) is dict,'separate train/eval material required')
    for doc,role,n in ((training,'train_labels_only',128),(blind,'blind_calibration_and_test',96)):
        check(doc.get('schema')==MATERIAL and doc.get('panel_sha256')==PANEL_SHA
              and doc.get('role')==role and doc.get('model_revision')==GRANITE_REVISION
              and doc.get('source_is_cross_sectional_not_future') is True
              and doc.get('source_origin_independently_signed') is False
              and doc.get('seal_id')==digest({k:v for k,v in doc.items() if k!='seal_id'})
              and type(doc.get('rows')) is list and len(doc['rows'])==n,
              'untrusted split/source/model/material seal')
    ids=set();split_counts={'train':0,'calibration':0,'test':0}
    for doc in (training,blind):
        for c in doc['rows']:
            validate_case(c,labeled=doc is training)
            check(c['group_id'] not in ids,'actual source group leaked across rows or splits')
            ids.add(c['group_id']);split_counts[c['split']]+=1
    check(split_counts=={'train':128,'calibration':32,'test':64},
          'exact independent source-group census required')
    return True


def backend_digest(backend):
    model=getattr(backend,'model',None)
    check(isinstance(model,torch.nn.Module) and not model.training,
          'frozen local PyTorch model object required')
    check(all(not p.requires_grad for p in model.parameters()),'pretrained Stem weights are not frozen')
    h=hashlib.sha256();count=0
    for name,param in sorted(model.named_parameters()):
        check(param.device.type=='cpu' and bool(torch.isfinite(param).all()),
              'invalid on-device Stem weight')
        # BF16 has no NumPy scalar conversion. Reinterpret the original
        # contiguous CPU tensor as uint8: preserve every stored bit rather
        # than rounding/casting a pretrained checkpoint to FP32 for hashing.
        raw=param.detach().contiguous()
        payload=raw.view(torch.uint8).numpy().tobytes()
        check(len(payload)==raw.numel()*raw.element_size(),
              'physical Stem parameter byte length drift')
        h.update(name.encode()+b'\0');h.update(payload)
        count+=param.numel()
    check(count>0,'real physical model tensor count required')
    return h.hexdigest(),count


def encode(backend,case,*, call_stats):
    begin=time.perf_counter_ns()
    with torch.inference_mode():
        feature,proof,meta=backend.encode(case['joint_input'],allow_truncation=False)
    call_stats['calls']+=1
    if not isinstance(proof,dict) or not isinstance(meta,dict):
        raise ValueError('registered physical Stem must emit source feature receipt')
    check(meta.get('truncated') is False and type(meta.get('original_tokens')) is int
          and 1<=meta['original_tokens']<=512,'tokenizer may not silently truncate')
    q24_vector(feature)
    check(isinstance(proof.get('research_only_feature_sha256'),str)
          and len(proof['research_only_feature_sha256'])==64,
          'pretrained Q24 feature provenance field required')
    call_stats['model_encode_wall_ns']+=time.perf_counter_ns()-begin
    return feature.detach().clone()


def _source_selection(blind,indices,mode):
    test=[r for r in blind['rows'] if r['split']=='test']
    check(len(test)==64,'original test panel must be complete')
    cases=[]
    for slot,cell_index in enumerate(indices.tolist()):
        if mode=='repeated4':source=test[slot%4];principal='tenant-a'
        elif mode=='test_panel':source=test[slot%64];principal='tenant-a'
        elif mode=='two_scopes':source=test[slot%4];principal=('tenant-b' if (slot//4)%2 else 'tenant-a')
        else:raise ValueError('unknown no-change/Cache source-distribution control')
        cases.append(dict(cell_index=cell_index,source=source,principal=principal))
    return cases


def _fanout(backend,cases,*,cache_bytes,claim,material_features):
    check(type(cache_bytes) is int and 0<=cache_bytes<=128*1024*1024,
          'bounded reproducible fanout cache memory cap required')
    cache=OrderedDict();resident=0;peak=0;hits=0;evictions=0;use=0
    stats=dict(calls=0,model_encode_wall_ns=0)
    features=[];keys=set();before=time.perf_counter_ns()
    for request in cases:
        c=request['source'];principal=request['principal']
        context=(principal,'public.agnews','research-v1',1,1,GRANITE_REVISION,
                 'granite-official-cls-l2','source-use-v1',c['group_id'],c['joint_input_digest'])
        key=sha256(canonical(context));keys.add(key)
        check(claim(request['cell_index'],key,context) is True,
              'every Cell use requires a current explicit research access check')
        use+=1
        if key in cache:
            v,n,prior=cache.pop(key)
            check(tensor_sha(v)==prior,'stored pretrained feature mutated by consumer')
            cache[key]=(v,n,prior);hits+=1
        else:
            v=encode(backend,c,call_stats=stats)
            n=v.untyped_storage().nbytes();prior=tensor_sha(v)
            if n<=cache_bytes:
                while cache and resident+n>cache_bytes:
                    _,(_,rm,_) = cache.popitem(last=False);resident-=rm;evictions+=1
                cache[key]=(v,n,prior);resident+=n;peak=max(peak,resident)
        check(torch.equal(v,material_features[c['case_id']]),
              'real pretrained source feature differs from original source-bound material')
        features.append(v)
    check(stats['calls']+hits==len(cases),'physical pretrained API call accounting mismatch')
    return torch.stack(features),dict(physical_model_api_calls=stats['calls'],logical_head_uses=use,
        real_encoder_wall_ns=stats['model_encode_wall_ns'],cache_hits=hits,
        cache_evictions=evictions,unique_scoped_input_keys=len(keys),
        physical_cache_payload_peak_bytes=peak,request_batch_wall_ns=time.perf_counter_ns()-before,
        cache_budget_bytes=cache_bytes)


def _quality_probe(training,blind,material_features,*,seed,steps=40):
    # Frozen/no-change and learned linear baselines are *separate* from 9,744p Cell bank.
    check(type(steps) is int and steps==40,'fixed original E1 Head update budget')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed);module=torch.nn.Linear(WIDTH,2)
    original={k:v.detach().clone() for k,v in module.state_dict().items()}
    train_x=torch.stack([material_features[c['case_id']] for c in training['rows']])
    train_y=torch.tensor([c['label'] for c in training['rows']],dtype=torch.long)
    start=time.perf_counter_ns()
    opt=torch.optim.SGD(module.parameters(),lr=.15)
    for _ in range(steps):
        opt.zero_grad(set_to_none=True)
        loss=F.cross_entropy(module(train_x),train_y)
        check(bool(torch.isfinite(loss)),'invalid real-label training loss')
        loss.backward();opt.step()
    time_ms=(time.perf_counter_ns()-start)/1e6
    check(not all(torch.equal(original[k],v) for k,v in module.state_dict().items()),
          'genuine training must update at least one parameter')
    def state_hash(d):
        h=hashlib.sha256()
        for k,v in sorted(d.items()):h.update(k.encode()+b'\0'+v.detach().numpy().tobytes())
        return h.hexdigest()
    with torch.inference_mode():
        output={}
        for name,weights in (('no_change',original),('trained',module.state_dict())):
            linear=torch.nn.Linear(WIDTH,2);linear.load_state_dict(weights);linear.eval()
            rows=[]
            for c in blind['rows']:
                logits=linear(material_features[c['case_id']].unsqueeze(0))[0]
                prob=float(torch.softmax(logits,dim=0)[1].item())
                rows.append(dict(case_id=c['case_id'],group_id=c['group_id'],split=c['split'],
                                 joint_input_digest=c['joint_input_digest'],positive_probability=prob))
            output[name]=dict(parameter_count=sum(p.numel() for p in linear.parameters()),
                              weights_sha256=state_hash(weights),rows=rows)
    return output,time_ms


def run_cohort(training,blind,backend,*,cells,mode,cache_bytes,seed=7347,
               weight_origin='fixture',steps=2):
    verify_material(training,blind)
    check(type(cells) is int and cells in SIZES and mode in MODES
          and type(cache_bytes) is int and 0<=cache_bytes<=128*1024*1024
          and weight_origin in ('fixture','pinned_public_research')
          and type(seed) is int and 0<seed<2**31 and type(steps) is int and 2<=steps<=8,
          'registered real candidate / compute control required')
    torch.set_num_threads(1)
    start=time.perf_counter_ns();cpu=time.process_time_ns()
    sha_before,params=backend_digest(backend)
    if weight_origin=='pinned_public_research':
        check(getattr(backend,'model_id',None)==GRANITE_MODEL
              and getattr(backend,'revision',None)==GRANITE_REVISION
              and getattr(backend,'device',None)=='cpu'
              and params>=90_000_000,
              'actual pinned full Granite97 model required, no fixture fallback')
    population=PackedGatedHeads(cells,seed)
    generator=torch.Generator(device='cpu').manual_seed(seed+17)
    selected=torch.randperm(cells,generator=generator)[:max(8,cells//10)]
    index_hash=tensor_sha(selected.to(torch.float32))
    quality_stats=dict(calls=0,model_encode_wall_ns=0)
    started=time.perf_counter_ns();material_features={}
    for c in training['rows']+blind['rows']:
        material_features[c['case_id']]=encode(backend,c,call_stats=quality_stats)
    materials_ms=(time.perf_counter_ns()-started)/1e6
    check(len(material_features)==224 and quality_stats['calls']==224,
          'actual physical 224-case pretrained Encoder bank incomplete')
    probes,quality_train_ms=_quality_probe(training,blind,material_features,seed=seed)
    cases=_source_selection(blind,selected,mode)
    claimed=[]
    def permit(i,key,context):
        claimed.append((i,key,context));return True  # research caller; not signed FinalUse
    baseline_x,baseline=_fanout(backend,cases,cache_bytes=0,claim=permit,
                               material_features=material_features)
    shared_x,shared=_fanout(backend,cases,cache_bytes=cache_bytes,claim=permit,
                           material_features=material_features)
    check(torch.equal(baseline_x,shared_x),'cache changed actual public pretrained input features')
    check(len(claimed)==2*len(cases) and baseline['logical_head_uses']==len(cases)
          and shared['logical_head_uses']==len(cases),
          'every use (including cache hit) must check research scope')
    state=torch.randn(len(cases),STATE,generator=torch.Generator(device='cpu').manual_seed(seed+123))
    started=time.perf_counter_ns()
    with torch.no_grad():
        frozen=population.predict(population.rows(selected),baseline_x,state)
        reused=population.predict(population.rows(selected),shared_x,state)
    pred_ms=(time.perf_counter_ns()-started)/1e6
    check(torch.equal(frozen,reused),'cached and no-cache Cell logits must be identical')
    spot=set((0,len(cases)//2,len(cases)-1))
    before_error=0.0
    for pos in spot:
        f=unpacked_single_head(population.weights,shared_x[pos],state[pos],int(selected[pos]))
        before_error=max(before_error,float(torch.max(torch.abs(f-frozen[pos])).item()))
    check(before_error<=1e-5,'unpacked frozen Cell Head numerics differ from packed')
    # Physically update only active private Heads with *real original train* labels.
    train_assign=[training['rows'][i%len(training['rows'])] for i in range(len(cases))]
    train_vectors=torch.stack([material_features[c['case_id']] for c in train_assign])
    train_labels=torch.tensor([c['label'] for c in train_assign],dtype=torch.long)
    before_logits=tensor_sha(frozen);started=time.perf_counter_ns()
    train_result=population.fit_sparse(selected,train_vectors,state,train_labels,steps=steps)
    trained_ms=(time.perf_counter_ns()-started)/1e6
    with torch.no_grad():learned=population.predict(population.rows(selected),shared_x,state)
    check(before_logits!=tensor_sha(learned),'genuine label-trained per-Cell Head logits unchanged')
    post_error=0.0
    for pos in spot:
        f=unpacked_single_head(population.weights,shared_x[pos],state[pos],int(selected[pos]))
        post_error=max(post_error,float(torch.max(torch.abs(f-learned[pos])).item()))
    check(post_error<=1e-5,'independent post-update Head replay failed')
    sha_after,params_after=backend_digest(backend)
    check(sha_before==sha_after and params==params_after,
          'frozen full pretrained model weight bytes changed during local SGD')
    stats={
      'encoding_material_ms':materials_ms,
      'head_quality_training_ms':quality_train_ms,
      'baseline_requests_ms':baseline['request_batch_wall_ns']/1e6,
      'shared_requests_ms':shared['request_batch_wall_ns']/1e6,
      'physical_cell_training_ms':trained_ms,
      'scoring_forward_ms':pred_ms,
    }
    result=dict(schema=SCHEMA, model=MODEL_ID,model_revision=GRANITE_REVISION,
       pretrained_weight_execution_claimed=(weight_origin=='pinned_public_research'),
       model_origin_independently_authenticated=False,source_origin_independently_authenticated=False,
       pretrained_forward_count_independently_attested=False,
       true_prospective_future_evaluation=False,independent_reader_evidence_sufficiency=False,
       complete_worker_signed_final_use=False,model_parameter_count=params,
       frozen_model_tensor_sha256=sha_before,model_unchanged_after_cell_fit=True,
       panel_sha256=PANEL_SHA,cohort_logical_cells=cells,active_cells=len(cases),
       active_roster_sha256=index_hash,mode=mode,cache_budget_bytes=cache_bytes,
       complete_real_source_material_calls=quality_stats['calls'],
       complete_real_source_encoding_wall_ns=quality_stats['model_encode_wall_ns'],
       complete_actual_pretrained_api_calls=(quality_stats['calls']+baseline['physical_model_api_calls']+shared['physical_model_api_calls']),
       matched_baseline_total_api_calls=(quality_stats['calls']+baseline['physical_model_api_calls']),
       matched_shared_total_api_calls=(quality_stats['calls']+shared['physical_model_api_calls']),
       source_group_count=len({c['source']['group_id'] for c in cases}),
       unique_scoped_source_count=(len({(c['principal'],c['source']['case_id']) for c in cases})),
       per_use_research_access_hook_count=len(claimed),
       baseline=baseline,shared=shared,quality_probes=probes,
       head_per_cell_parameters=HEAD_PARAMS,head_parameter_count=population.param_count,
       resident_head_tensor_bytes=population.param_count*4,
       frozen_head_max_unpacked_abs_error=before_error,
       learned_head_max_unpacked_abs_error=post_error,
       frozen_packed_logits_sha256=before_logits,learned_packed_logits_sha256=tensor_sha(learned),
       local_cell_train=train_result,cost_phases_ms=stats,
       model_load_ms=float(getattr(backend,'model_load_ms',0.0)),
       entire_process_wall_ms=(time.perf_counter_ns()-start)/1e6,
       process_wall_excludes_model_load=True,
       entire_process_cpu_ms=(time.process_time_ns()-cpu)/1e6,
       lifetime_peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
       no_claim_of_general_reasoning=True,quality_superiority_established=False,
       decoder_generation_executed=False,real_421m_copy_control_executed=False,
       model_cpu_runtime_order_control_matched=False,
       production_promotion_permitted=False,authority='DENY_ALL')
    check(baseline['physical_model_api_calls']==len(cases)
          and shared['physical_model_api_calls']+shared['cache_hits']==len(cases)
          and result['per_use_research_access_hook_count']==2*len(cases),
          'actual physical Stem and Cell census inconsistent')
    result['report_sha256']=digest(result)
    return result


def read_json(path):
    p=Path(path)
    check(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=MAX_BYTES,
          'bounded regular original research artifact required')
    def pairs(items):
        out={}
        for k,v in items:
            check(k not in out,'duplicate source JSON key')
            out[k]=v
        return out
    return json.loads(p.read_bytes(),object_pairs_hook=pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('invalid nonfinite number')))


def write_exclusive(path,doc):
    with Path(path).open('x',encoding='utf8') as f:
        json.dump(doc,f,allow_nan=False,sort_keys=True,indent=2)
        f.write('\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--original-panel',required=True)
    prepare.add_argument('--e1-source',required=True)
    prepare.add_argument('--output-dir',required=True)
    run=sub.add_parser('run')
    batch=sub.add_parser('run-batch')
    for a in ('train-material','blind-material','compact-source','output'):
        run.add_argument('--'+a,required=True)
    run.add_argument('--cells',type=int,choices=SIZES,required=True)
    run.add_argument('--mode',choices=MODES,required=True)
    run.add_argument('--cache-bytes',type=int,default=32*1024*1024)
    for a in ('train-material','blind-material','compact-source','output-dir'):
        batch.add_argument('--'+a,required=True)
    batch.add_argument('--cache-bytes',type=int,default=32*1024*1024)
    args=parser.parse_args()
    if args.cmd=='prepare':
        # Existing owner handles all original source assertions; this trial adds an exact digest seal.
        sys.path.insert(0,str(Path(args.e1_source)/'experiments/shared_stem_cell'))
        from e1_public_triplet_real_cpu import load_panel
        panel,sha=load_panel(args.original_panel)
        check(sha==PANEL_SHA,'original panel does not equal pinned E1 observed source')
        train,blind,labels=prepare_material(panel)
        root=Path(args.output_dir);root.mkdir(exist_ok=False)
        write_exclusive(root/'train.json',train)
        write_exclusive(root/'blind.json',blind)
        write_exclusive(root/'owner-labels.json',labels)
        write_exclusive(root/'COMMITTED.json',{'schema':MATERIAL+'.material-owner',
            'panel_sha256':PANEL_SHA,'train_sha256':sha256(canonical(train)),
            'blind_sha256':sha256(canonical(blind)),'owner_labels_sha256':sha256(canonical(labels)),
            'e1_source_revision':'09bb40d8bf3a058a34607179d4e0fbdf11a41277',
            'authority':'DENY_ALL'})
    else:
        training=read_json(args.train_material);blind=read_json(args.blind_material)
        verify_material(training,blind)
        sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
        from compact_stem_trial import FrozenCompactStem
        backend=FrozenCompactStem(GRANITE_MODEL,GRANITE_REVISION,device='cpu',max_tokens=512)
        if args.cmd=='run':
            output=run_cohort(training,blind,backend,cells=args.cells,mode=args.mode,
                              cache_bytes=args.cache_bytes,weight_origin='pinned_public_research')
            write_exclusive(args.output,output)
        else:
            outroot=Path(args.output_dir);outroot.mkdir(exist_ok=False)
            # A single physically loaded public checkpoint serves all matched cohorts.
            # No report is marked complete until its own exclusive file exists.
            import gc
            for n in SIZES:
                for mode in MODES:
                    result=run_cohort(training,blind,backend,cells=n,mode=mode,
                        cache_bytes=args.cache_bytes,weight_origin='pinned_public_research')
                    write_exclusive(outroot/f'{n}-{mode}.json',result)
                    del result;gc.collect()
            for mode in ('repeated4','test_panel'):
                result=run_cohort(training,blind,backend,cells=256,mode=mode,
                      cache_bytes=0,weight_origin='pinned_public_research')
                write_exclusive(outroot/f'256-{mode}-zero-cache.json',result)


if __name__=='__main__':main()
