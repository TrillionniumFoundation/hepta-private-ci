"""Pinned original ModernBERT/BANKING77 -> separate HDCF CellBank bridge.

Stage, model production and blind scoring are separate commands/processes.
The old 2026 public model archive DID NOT contain raw Encoder features; this
producer must execute NEW original model forwards before any new efficacy claim.
No arbitrary model weights, remote model code, OS effects or production grants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any

from physical_bank import SCHEMA, Denied, digest, train, score, validate_bundle
from physical_cli import read_document, write_once
from independent_head_replay import audit_head_replay
from paired_utility_gate import audit_paired_utility

ORIGINAL_CODE_SHA = '758205d3de23ccbf76649b1446c271101dc917b0'
ORIGINAL_SOURCE = '57ec275d8078af65b7731c2a98be812d844a6d6b'
ORIGINAL_MODEL = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
ORIGINAL_MODEL_SNAPSHOT = '43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d'
ORIGINAL_SELECTED_INPUT_ID = '95dc97bd0700165b431d140e77c35500713bc95dd3f6c31b6dabb9e021d26fad'
ORIGINAL_CSV_SHA256 = {
    'train': 'b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b',
    'test': 'd12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d',
}
INTENTS = ('card_arrival','cash_withdrawal_not_recognised','exchange_rate','lost_or_stolen_phone')
PUBLIC_SCHEMA = 'hepta.hdcf.banking77-public-inputs.v1'
BLIND_SCHEMA = 'hepta.hdcf.banking77-blind-targets.v1'
RECEIPT_SCHEMA = 'hepta.hdcf.original-encoder-feature-producer.v1'


def _require(cond, reason):
    if not cond:
        raise Denied(reason)


def _name(text):
    _require(type(text) is str and 1 <= len(text) <= 128 and text.isascii() and
             not any(c.isspace() for c in text), 'invalid case identity')
    return text


def _cell_type(case_id):
    _name(case_id)
    # A pre-registered label-blind partition. Not an automatically learned
    # meaningful specialization; it must not see the target at fit or held time.
    hx = hashlib.sha256(('hepta.hdcf.original-type-partition.v1\0' + case_id).encode()).digest()
    return 'hash0' if hx[0] & 1 == 0 else 'hash1'


def _original_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _check_original_inputs(inputs, observer, selection):
    _require(type(inputs) is dict and set(inputs) == {'schema','intents','fit','heldout','input_id'} and
             inputs['schema'] == 'hepta.banking77-four-intent-inputs.v1' and
             inputs['intents'] == list(INTENTS) and
             inputs['input_id'] == _original_digest({k:v for k,v in inputs.items() if k!='input_id'}),
             'original public inputs changed')
    _require(type(observer) is dict and set(observer)=={'schema','input_id','rows'} and
             observer['schema']=='hepta.banking77-four-intent-labels.v1' and
             observer['input_id']==inputs['input_id'] and type(observer['rows']) is list,
             'original private target mismatch')
    _require(type(selection) is dict and selection.get('schema')=='hepta.banking77-subset-selection.v1' and
             selection.get('input_id')==inputs['input_id'] and
             selection.get('task_subset_not_full_benchmark') is True and
             type(selection.get('raw_sha256')) is dict and
             set(selection['raw_sha256'])=={'train','test'} and
             all(type(v) is str and len(v)==64 for v in selection['raw_sha256'].values()),
             'original selected source bytes not identified')
    _require(len(inputs['fit'])==64 and len(inputs['heldout'])==32 and
             len(observer['rows'])==32 and
             selection['selected_ids']['fit']==[r['id'] for r in inputs['fit']] and
             selection['selected_ids']['heldout']==[r['id'] for r in inputs['heldout']],
             'original fixed four-intent/96-case population changed')
    fit_counts=[0]*4
    for r in inputs['fit']:
        _require(type(r) is dict and set(r)=={'id','text','label'} and
                 type(r['label']) is int and 0<=r['label']<4 and
                 type(r['text']) is str and r['text'].strip() and len(r['text'].encode())<=4096,
                 'invalid fit row')
        _name(r['id']);fit_counts[r['label']]+=1
    _require(fit_counts==[16]*4, 'wrong training class inventory')
    for held, target in zip(inputs['heldout'],observer['rows'],strict=True):
        _require(type(held) is dict and set(held)=={'id','text'} and
                 type(held['text']) is str and held['text'].strip() and len(held['text'].encode())<=4096 and
                 type(target) is dict and set(target)=={'id','label'} and
                 held['id']==target['id'] and type(target['label']) is int and
                 0<=target['label']<4, 'held target leaked or unbound')
        _name(held['id'])
    _require(len({r['id'] for r in inputs['fit']+inputs['heldout']})==96,
             'duplicate case across source splits')


def stage_original(inputs, observer, selection):
    """Stage exact original public examples and independent blind target file."""
    _check_original_inputs(inputs, observer, selection)
    stage_digest = digest({'source':ORIGINAL_SOURCE,'inputs':inputs,'selection':selection})
    pub = {'schema':PUBLIC_SCHEMA,'input_id':inputs['input_id'],'source_revision':ORIGINAL_SOURCE,
           'original_code_sha':ORIGINAL_CODE_SHA,'source_material_sha256':selection['raw_sha256'],
           'stage_digest':stage_digest, 'intents':list(INTENTS),
           'fit':inputs['fit'],'heldout':inputs['heldout'],
           'cell_type_method':'sha256_original_case_id_parity_v1',
           'source_family_independence_verified':False, 'production_authorized':False}
    priv = {'schema':BLIND_SCHEMA,'input_id':inputs['input_id'],'source_revision':ORIGINAL_SOURCE,
            'public_content_digest':digest(pub),
            'stage_digest':stage_digest,'source_material_sha256':selection['raw_sha256'],
            'original_code_sha':ORIGINAL_CODE_SHA,
            'targets':[{'id':r['id'],'family':'BANKING77-test-original','type':_cell_type(r['id']),
                        'target':t['label'] % 2} for r,t in zip(inputs['heldout'],observer['rows'],strict=True)],
            'original_four_class_labels_not_exported':True,
            'binary_target_definition':'original_label_mod_2',
            'production_authorized':False}
    validate_public(pub)
    return pub, priv


def validate_public(pub, *, exact_original_source=False):
    _require(type(pub) is dict and set(pub)=={'schema','input_id','source_revision','original_code_sha',
             'source_material_sha256','stage_digest','intents','fit','heldout',
             'cell_type_method','source_family_independence_verified','production_authorized'} and
             pub['schema']==PUBLIC_SCHEMA and pub['source_revision']==ORIGINAL_SOURCE and
             pub['original_code_sha']==ORIGINAL_CODE_SHA and pub['intents']==list(INTENTS) and
             pub['cell_type_method']=='sha256_original_case_id_parity_v1' and
             pub['source_family_independence_verified'] is False and
             pub['production_authorized'] is False, 'unrecognized public input source profile')
    _require(len(pub['fit'])==64 and len(pub['heldout'])==32 and
             set(pub['source_material_sha256'])=={'train','test'} and
             len(pub['input_id'])==64 and len(pub['stage_digest'])==64, 'incomplete public source')
    seen=set()
    for split in ('fit','heldout'):
        for row in pub[split]:
            fields={'id','text','label'} if split=='fit' else {'id','text'}
            _require(type(row) is dict and set(row)==fields and
                     type(row['text']) is str and row['text'].strip() and len(row['text'].encode())<=4096,
                     'unsafe source row or held label leakage')
            _name(row['id']);_require(row['id'] not in seen,'duplicate input case')
            seen.add(row['id'])
            if split=='fit':
                _require(type(row['label']) is int and 0<=row['label']<4, 'unvalidated fit label')
    _require(len(seen)==96,'source-count mismatch')
    # Recompute public source identity from every original input byte and label.
    # This does not authorize a publisher or make an unsigned SHA a signature.
    original_input={'schema':'hepta.banking77-four-intent-inputs.v1',
                    'intents':pub['intents'], 'fit':pub['fit'], 'heldout':pub['heldout']}
    _require(_original_digest(original_input)==pub['input_id'],
             'original content-to-input identity mismatch')
    counts={t:{0:0,1:0} for t in ('hash0','hash1')}
    for row in pub['fit']:
        counts[_cell_type(row['id'])][row['label']%2]+=1
    _require(all(counts[t][y] for t in counts for y in (0,1)),
             'unsupported Cell-type and label train combinations')
    held_type={_cell_type(r['id']) for r in pub['heldout']}
    _require(held_type=={'hash0','hash1'},'missing held Cell-type population')
    if exact_original_source:
        _require(pub['input_id']==ORIGINAL_SELECTED_INPUT_ID and
                 pub['source_material_sha256']==ORIGINAL_CSV_SHA256,
                 'public data does not equal exact archived immutable source')


def _source_checkout(upstream_root: str):
    """Explicit closed-world source checkout: do not import mutable main."""
    root=Path(upstream_root).resolve()
    p=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=20)
    _require(p.returncode==0 and p.stdout.strip()==ORIGINAL_CODE_SHA,
             'source checkout is not the pinned original pretrained executor')
    module=root/'qualification'/'stem-cell-v1'
    _require(module.is_dir() and not module.is_symlink() and
             (module/'matrix_runtime.py').is_file() and
             (module/'public_encoder_probe.py').is_file(), 'original source modules unavailable')
    for name in ('public_encoder_probe.py','matrix_runtime.py','banking77_material.py',
                 'hf_complete_checkpoint.py','hf_encoder_kernel.py'):
        rel='qualification/stem-cell-v1/'+name
        _require(not (module/name).is_symlink(), 'linked original execution source denied')
        source=subprocess.run(['git','-C',str(root),'show',ORIGINAL_CODE_SHA+':'+rel],
                              capture_output=True,timeout=20)
        _require(source.returncode==0 and (module/name).read_bytes()==source.stdout,
                 'original execution source differs from pinned Git blob: '+name)
    if str(module) not in sys.path:
        sys.path.insert(0,str(module))
    return module


def _feature_vector(backend, row):
    import torch
    with torch.inference_mode():
        original,length=backend.encode(dict(state=row['text'],question='Select the customer service intent.',
                                            options=list(INTENTS)))
    _require(original.ndim==1 and original.dtype==torch.float32 and
             original.device.type=='cpu' and original.shape[0]==backend.dimension and
             torch.isfinite(original).all().item() and not original.requires_grad,
             'invalid original physical pretrained feature')
    _require(type(length) is int and 0<length<=256,'physical pretrained token length invalid')
    norm=torch.linalg.vector_norm(original)
    _require(torch.isfinite(norm).item() and norm.item()>1e-12, 'bad original zero feature')
    out=(original/norm).tolist()
    _require(len(out)==backend.dimension and all(type(x) is float and math.isfinite(x) and
             abs(x)<=1.01 for x in out),'noncanonical normalized feature')
    return out,length


def produce_original(pub, backend, *, clock=time, exact_original_source=False):
    """Execute physically loaded pinned Encoder under an independent producer.

    `backend` is a test seam; only CLI's pinned LocalHFEncoder supplies real
    runtime receipts. This function does not authenticate a caller-supplied
    backend and must never be used as an independent model witness.
    """
    validate_public(pub, exact_original_source=exact_original_source)
    _require(type(backend.dimension) is int and 1<=backend.dimension<=1024 and
             type(backend.calls) is int and backend.calls==0, 'bad physical producer state')
    _require(backend.receipt['snapshot_sha256']==ORIGINAL_MODEL_SNAPSHOT and
             backend.receipt['upstream_revision']==ORIGINAL_MODEL and
             backend.receipt['pretrained_provenance_independently_verified'] is False,
             'unexpected model weights/signer profile')
    start_wall=clock.perf_counter_ns();start_cpu=clock.process_time_ns()
    rows=[];lengths={'fit':[], 'heldout':[]}
    for split in ('fit','heldout'):
        for row in pub[split]:
            vector, n = _feature_vector(backend,row)
            lengths[split].append(n)
            obj={'id':row['id'],'family':'BANKING77-train-original' if split=='fit'
                  else 'BANKING77-test-original', 'type':_cell_type(row['id']), 'vector':vector}
            if split=='fit':obj['target']=row['label']%2
            rows.append((split,obj))
    backend.reverify()
    _require(backend.calls==96, 'unaccounted physical Encoder forwards')
    out={'schema':SCHEMA,'producer':{
            'encoder_sha256':ORIGINAL_MODEL_SNAPSHOT,
            'preprocess_sha256':digest({'normalization':'l2_fp32_per_case','prompt':'four-intents',
                                         'original_source_commit':ORIGINAL_CODE_SHA}),
            'source_sha256':pub['stage_digest'], 'generation':1,'principal':'research-BANKING77'},
         'dimension':backend.dimension, 'types':['hash0','hash1'],
         'fit':[item for split,item in rows if split=='fit'],
         'held':[item for split,item in rows if split=='heldout']}
    validate_bundle(out)
    receipt={'schema':RECEIPT_SCHEMA,'feature_bundle_digest':digest(out),
             'source_stage_digest':pub['stage_digest'], 'public_content_digest':digest(pub),
             'input_id':pub['input_id'],
             'model_snapshot_sha256':ORIGINAL_MODEL_SNAPSHOT,
             'original_code_sha':ORIGINAL_CODE_SHA,'original_source_revision':ORIGINAL_SOURCE,
             'source_file_sha256':pub['source_material_sha256'],
             'dimension':backend.dimension,'observed_encoder_forward_calls':backend.calls,
             'observed_encoder_forward_cpu_ns':clock.process_time_ns()-start_cpu,
             'observed_encoder_forward_wall_ns':clock.perf_counter_ns()-start_wall,
             'observed_process_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'token_counts':lengths,
             'encoder_receipt_claim_digest':digest(backend.receipt),
             'pretrained_publisher_signature_independently_verified':False,
             'source_family_independence_verified':False,
             'held_labels_loaded_in_encoder_producer':False,
             'full_encoder_plus_head_tco_verified':False,
             'production_authorized':False}
    return out,receipt


def review_original(pub, priv, bundle, receipt, trial, *, expected_steps=256, expected_seed=7347, expected_lr=0.05,
                    exact_original_source=False, publisher_train_csv=None, publisher_test_csv=None):
    validate_public(pub, exact_original_source=exact_original_source)
    _require(type(priv) is dict and set(priv)=={'schema','input_id','source_revision','stage_digest',
             'source_material_sha256','original_code_sha','public_content_digest','targets','original_four_class_labels_not_exported',
             'binary_target_definition','production_authorized'} and
             priv['schema']==BLIND_SCHEMA and priv['source_revision']==pub['source_revision'] and
             priv['original_code_sha']==ORIGINAL_CODE_SHA and priv['input_id']==pub['input_id'] and
             priv['stage_digest']==pub['stage_digest'] and
             priv['public_content_digest']==digest(pub) and
             priv['source_material_sha256']==pub['source_material_sha256'] and
             priv['production_authorized'] is False and
             priv['binary_target_definition']=='original_label_mod_2' and
             priv['original_four_class_labels_not_exported'] is True,
             'blind source-owner identity mismatch')
    # The private label artifact is not itself a publisher-authenticated target.
    # Only the independent final reviewer may read the original pinned source;
    # the Model Producer and CPU CellBank never receive these CSV bytes.
    target_source_receipt = None
    if exact_original_source:
        _require(type(publisher_train_csv) is bytes and type(publisher_test_csv) is bytes,
                 'independent reviewer requires original publisher CSV bytes')
        from held_target_source_revalidation import verify_publisher_held_targets
        target_source_receipt = verify_publisher_held_targets(
            pub, priv, publisher_train_csv, publisher_test_csv)
    else:
        _require(publisher_train_csv is None and publisher_test_csv is None,
                 'mock review may not launder publisher source provenance')
    validate_bundle(bundle)
    _require([r['id'] for r in bundle['fit']]==[r['id'] for r in pub['fit']] and
             [r['id'] for r in bundle['held']]==[r['id'] for r in pub['heldout']] and
             all(b['family']=='BANKING77-train-original' and
                 b['type']==_cell_type(b['id']) and b['target']==a['label'] % 2
                 for a,b in zip(pub['fit'],bundle['fit'],strict=True)) and
             all(b['family']=='BANKING77-test-original' and b['type']==_cell_type(b['id'])
                 for b in bundle['held']),
             'pretrained feature population or label-blind type drift')
    _require(type(receipt) is dict and receipt.get('schema')==RECEIPT_SCHEMA and
             receipt.get('feature_bundle_digest')==digest(bundle)==trial.get('bundle_digest') and
             receipt.get('source_stage_digest')==pub['stage_digest']==bundle['producer']['source_sha256'] and
             receipt.get('public_content_digest')==digest(pub) and
             receipt.get('input_id')==pub['input_id'] and
             receipt.get('model_snapshot_sha256')==bundle['producer']['encoder_sha256']==ORIGINAL_MODEL_SNAPSHOT and
             receipt.get('original_code_sha')==ORIGINAL_CODE_SHA and
             receipt.get('observed_encoder_forward_calls')==96 and
             receipt.get('dimension')==bundle['dimension'] and
             receipt.get('source_file_sha256')==pub['source_material_sha256'] and
             receipt.get('original_source_revision')==ORIGINAL_SOURCE and
             type(receipt.get('token_counts')) is dict and
             set(receipt['token_counts'])=={'fit','heldout'} and
             len(receipt['token_counts']['fit'])==64 and
             len(receipt['token_counts']['heldout'])==32 and
             receipt.get('observed_encoder_forward_wall_ns',-1)>0 and
             receipt.get('held_labels_loaded_in_encoder_producer') is False and
             receipt.get('pretrained_publisher_signature_independently_verified') is False and
             receipt.get('production_authorized') is False,
             'false or missing original pretrained feature receipt')
    _require(len(priv['targets'])==32 and
             [r['id'] for r in priv['targets']]==[r['id'] for r in bundle['held']]==
             [r['id'] for r in pub['heldout']] and
             all(r['family']=='BANKING77-test-original' and
                 r['type']==_cell_type(r['id']) and
                 type(r['target']) is int and r['target'] in (0,1)
                 for r in priv['targets']),
             'blind label target/type/identity mismatch')
    targets={'schema':'hepta.hdcf.blind-targets.v1','bundle_digest':digest(bundle),
             'targets':priv['targets']}
    paired=audit_paired_utility(bundle,trial,targets,steps=expected_steps,seed=expected_seed,lr=expected_lr)
    replay=paired['independent_replay']
    verified=paired['score']
    return {'schema':'hepta.hdcf.original-pretrained-head-review.v1',
            'source_stage_digest':pub['stage_digest'], 'real_feature_receipt_digest':digest(receipt),
            'model_snapshot_sha256':ORIGINAL_MODEL_SNAPSHOT,
            'source_code_sha':ORIGINAL_CODE_SHA,
            'observed_encoder_forward_calls':96,
            'head_training_measured_separately':True,
            'score':verified,
            'independent_head_sgd_replay':replay,
            'paired_science_gate':{k:v for k,v in paired.items() if k not in ('independent_replay','score')},
            'pretrained_publisher_signature_independently_verified':False,
            'original_labels_independent_of_public_source':False,
            'publisher_held_source_revalidation':target_source_receipt,
            'held_targets_recomputed_from_original_publisher_source':target_source_receipt is not None,
            'out_of_publisher_future_window_verified':False,
            'end_to_end_tco_verified':False,
            'production_authorized':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sp=ap.add_subparsers(dest='cmd',required=True)
    stage=sp.add_parser('stage');stage.add_argument('--upstream-checkout',required=True)
    stage.add_argument('--root',required=True);stage.add_argument('--out-public',required=True)
    stage.add_argument('--out-private',required=True)
    produce=sp.add_parser('produce');produce.add_argument('--upstream-checkout',required=True)
    produce.add_argument('--snapshot',required=True);produce.add_argument('--public',required=True)
    produce.add_argument('--out-features',required=True);produce.add_argument('--out-receipt',required=True)
    review=sp.add_parser('review');review.add_argument('--public',required=True)
    review.add_argument('--private',required=True);review.add_argument('--features',required=True)
    review.add_argument('--feature-receipt',required=True);review.add_argument('--trial',required=True)
    # These never enter the producer/train subcommands or their environments.
    review.add_argument('--publisher-train',required=True);review.add_argument('--publisher-test',required=True)
    review.add_argument('--out',required=True)
    args=ap.parse_args()
    try:
        if args.cmd=='stage':
            _source_checkout(args.upstream_checkout)
            from banking77_material import acquire,prepare,REVISION
            _require(REVISION==ORIGINAL_SOURCE,'unexpected original dataset revision')
            data=acquire(Path(args.root))
            inputs,observer,selection=prepare((data/'banking_data/train.csv').read_bytes(),
                                               (data/'banking_data/test.csv').read_bytes())
            pub,priv=stage_original(inputs,observer,selection)
            validate_public(pub, exact_original_source=True)
            write_once(args.out_public,pub);write_once(args.out_private,priv)
        elif args.cmd=='produce':
            _source_checkout(args.upstream_checkout)
            import torch
            from hf_encoder_kernel import snapshot_digest
            from hf_complete_checkpoint import ENCODER_PROFILE
            from matrix_runtime import LocalHFEncoder
            torch.set_num_threads(1)
            model_dir=Path(args.snapshot)
            _require(snapshot_digest(model_dir)==ORIGINAL_MODEL_SNAPSHOT,
                     'actual complete original pretrained snapshot differs')
            cfg={'snapshot_sha256':ORIGINAL_MODEL_SNAPSHOT,'context_tokens':256,
                 'encoder_profile':ENCODER_PROFILE, 'upstream_revision':ORIGINAL_MODEL,
                 'material_approval_sha256':None}
            backend=LocalHFEncoder(model_dir,cfg,{'stem':'smaller_control'})
            bundle,receipt=produce_original(read_document(args.public),backend,exact_original_source=True)
            write_once(args.out_features,bundle);write_once(args.out_receipt,receipt)
        else:
            from public_source_recount import _read_file
            publisher_train = _read_file(args.publisher_train, 2_000_000)
            publisher_test = _read_file(args.publisher_test, 2_000_000)
            out=review_original(read_document(args.public),read_document(args.private),
                 read_document(args.features),read_document(args.feature_receipt),read_document(args.trial),
                 exact_original_source=True, publisher_train_csv=publisher_train,
                 publisher_test_csv=publisher_test)
            write_once(args.out,out)
    except (Denied,OSError,ValueError) as exc:
        ap.exit(2,f'DENY_ALL: {type(exc).__name__}: {exc}\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
