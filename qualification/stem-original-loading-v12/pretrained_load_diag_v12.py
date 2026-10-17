"""Physical original checkpoint loading/Head parity DIAGNOSTIC, not a fix.

V9 failed for two models; preserve original failure and investigate missing
pretrained token embeddings versus cross-process Head numerical drift. This
script emits only original-material, model-load and selected-score summaries.
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

ROOT=Path(__file__).resolve().parents[1]
for directory in ('stem-optimal-v1','stem-optimal-v5','stem-optimal-v8'):
    sys.path.insert(0,str(ROOT/directory))
import paired_review_v5 as custody
import selective_route_v8 as route
import stem_candidate_v1 as owner

SCHEMA='hepta.stem.pretrained-loading-head-parity-diagnostic.v12'
PROFILES={'granite47':('auto_model',),'granite97':('auto_model',),
          'mmbert140':('auto_model','full_mlm')}


def need(ok,why):
    if not ok: raise ValueError(why)


def loading_info(info):
    need(type(info) is dict,'pretrained loader gave no loading-info diagnostics')
    raw={}
    for name in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs'):
        v=info.get(name,[])
        need(type(v) is list and len(v)<10000 and
             all(type(x) is str or (name=='mismatched_keys' and isinstance(x,tuple))
                 for x in v),'invalid original model loading metadata')
        raw[name]=v
    # Unexpected pretrained MLM prediction-head parameters are not silently
    # treated as proof of complete base-Encoder restoration.
    missing=[str(x) for x in raw['missing_keys']]
    mismatched=[str(x)[:180] for x in raw['mismatched_keys']]
    errors=[str(x)[:180] for x in raw['error_msgs']]
    return {'missing_keys':missing[:30], 'missing_key_count':len(missing),
            'unexpected_key_count':len(raw['unexpected_keys']),
            'mismatched_keys':mismatched[:30], 'mismatched_key_count':len(mismatched),
            'error_messages':errors[:10], 'error_count':len(errors),
            'model_base_weights_complete':not(missing or mismatched or errors)}


def sha256_path(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_pinned(spec, profile):
    """No trust_remote_code, no .bin fallback and no mutable model revision."""
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel,AutoModelForMaskedLM,AutoTokenizer
    path=Path(snapshot_download(repo_id=spec['repo'],revision=spec['revision'],
          allow_patterns=['*.json','*.safetensors','*.txt','*.model'],
          ignore_patterns=['*.bin','*.pt','*.h5','*.onnx'],local_files_only=False))
    material=path/spec['weight_file']
    need(material.is_file() and 0 < material.stat().st_size < 1_000_000_000 and
         sha256_path(material)==spec['weight_sha256'],
         'real pinned safetensors material SHA was not verified')
    tokenizer=AutoTokenizer.from_pretrained(str(path),trust_remote_code=False,
                                             local_files_only=True)
    target=AutoModelForMaskedLM if profile=='full_mlm' else AutoModel
    loaded, info=target.from_pretrained(str(path),local_files_only=True,
        trust_remote_code=False,use_safetensors=True,torch_dtype=torch.float32,
        output_loading_info=True)
    loaded.eval().to('cpu')
    base=loaded.base_model if profile=='full_mlm' else loaded
    need(base is not None and callable(base),'invalid original base Encoder')
    result=loading_info(info)
    result['complete_model_resident_parameter_scalars']=sum(p.numel() for p in loaded.parameters())
    result['base_model_class']=type(base).__name__
    result['loader_class']=type(loaded).__name__
    # The loaded MLM owner must remain alive for resident full-model accounting.
    return tokenizer, base, loaded, result


def diagnose(source,cheap,model_runs,materials,*,candidate,profile):
    import torch
    need(candidate in PROFILES and profile in PROFILES[candidate],
         'unregistered model/loading profile')
    need(source['source_plan_sha256']==route.SOURCE_SHA and
         cheap['source_plan_sha256']==route.SOURCE_SHA,
         'not frozen original source cohort')
    original=model_runs[candidate]
    need(original['candidate']==candidate and
         original['source_plan_sha256']==route.SOURCE_SHA and
         original['actual_weight_sha256']==materials['candidates'][candidate]['weight_sha256'] and
         original['material_manifest_sha256']==owner.sha256(owner.canonical(materials)) and
         original['authority']=='DENY_ALL' and
         original['production_authorized'] is False,
         'not the true original model material')
    plan=route.produce(source,source,model_runs,cheap)
    test_by_id={r['case_id']:r for r in source['heldout']}
    selected=[test_by_id[k] for k in plan['selected_case_ids']]
    need(len(selected)==8,'not frozen V9 eight-input original route')
    torch.set_num_threads(2)
    start_wall=time.perf_counter();start_cpu=time.process_time()
    t=time.perf_counter()
    tokenizer,model,resident,loader=load_pinned(materials['candidates'][candidate],profile)
    load_wall=time.perf_counter()-t
    t=time.perf_counter()
    fit,fit_batches=owner._encode([r['text'] for r in source['train']],tokenizer,model)
    test,test_batches=owner._encode([r['text'] for r in selected],tokenizer,model)
    encode_wall=time.perf_counter()-t
    need(tuple(fit.shape)==(64,384) and tuple(test.shape)==(8,384) and
         fit_batches==4 and test_batches==1,'missing genuine original model forwards')
    result=owner._torch_head_training(fit,[r['label'] for r in source['train']],
                                       test,config=materials['training'])
    original_by_id={r['case_id']:r['scores'] for r in original['rows']}
    drift={}
    for arm in ('frozen_init','centroid','learned'):
        drift[arm]=max(abs(a-b) for i,r in enumerate(selected)
            for a,b in zip(result[arm][i],original_by_id[r['case_id']][arm]))
    initial_equal=result['initial_head_sha256']==original['initial_head_sha256']
    learned_equal=result['trained_head_sha256']==original['trained_head_sha256']
    # A model missing pretrained embeddings is never a valid scientific
    # comparison even if another downstream score happens to look good.
    valid=(loader['model_base_weights_complete'] and initial_equal and learned_equal and
           all(v<=5e-4 for v in drift.values()))
    return {'schema':SCHEMA,'candidate':candidate,'profile':profile,
        'source_plan_sha256':route.SOURCE_SHA,
        'original_model_revision':original['model_revision'],
        'original_weight_sha256':original['actual_weight_sha256'],
        'load_diagnostics':loader,
        'original_initial_head_sha256':original['initial_head_sha256'],
        'observed_initial_head_sha256':result['initial_head_sha256'],
        'initial_head_byte_equal':initial_equal,
        'original_trained_head_sha256':original['trained_head_sha256'],
        'observed_trained_head_sha256':result['trained_head_sha256'],
        'trained_head_byte_equal':learned_equal,
        'selected_case_count':len(selected),
        'original_encoder_sequences_paid':64+len(selected),
        'original_encoder_batches_paid':fit_batches+test_batches,
        'historical_original_probability_max_abs_drift':drift,
        'model_load_wall_seconds':load_wall,'actual_encode_wall_seconds':encode_wall,
        'actual_head_train_wall_seconds':result['training_wall_seconds'],
        'total_elapsed_wall_seconds':time.perf_counter()-start_wall,
        'total_elapsed_cpu_seconds':time.process_time()-start_cpu,
        'self_reported_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'scientifically_fully_reproducible_same_head_and_base':valid,
        'retrospective_test_labels_previously_exposed':True,
        'same_host_full_lifecycle_cost_verified':False,
        'stem_winner_verified':False,'ndu_benefit_verified':False,
        'production_authorized':False,'cell_split_authorized':False,
        'disposition':'HOLD_NO_GO','authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    for key in ('manifest','zip-dir','materials','candidate','profile','output'):
        p.add_argument('--'+key,required=True)
    args=p.parse_args()
    lock=json.loads(Path(args.manifest).read_text())
    need(lock['schema']=='hepta.stem.original-hard-charge.lock.v5' and
         lock['authority']=='DENY_ALL','not pinned artifact material')
    root=Path(args.zip_dir)
    docs={role:custody.locked_json(root/(role+'.zip'),lock['artifacts'],role)
          for role in ('source_v3','source_v4','cheap_v4')+tuple(PROFILES)}
    need(docs['source_v3']==docs['source_v4'],'original publisher source drift')
    material=owner.load_materials(Path(args.materials))
    result=diagnose(docs['source_v3'],docs['cheap_v4'],
                    {name:docs[name] for name in PROFILES},material,
                    candidate=args.candidate,profile=args.profile)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as f:f.write(owner.canonical(result)+b'\n')
    print(json.dumps({'digest':owner.sha256(output.read_bytes()),
       'candidate':args.candidate,'profile':args.profile,
       'qualified':result['scientifically_fully_reproducible_same_head_and_base'],
       'authority':'DENY_ALL','disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__=='__main__':main()
