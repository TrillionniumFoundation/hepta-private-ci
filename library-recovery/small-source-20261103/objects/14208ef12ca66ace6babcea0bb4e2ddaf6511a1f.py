#!/usr/bin/env python3
"""Research-only 4,145-param additive/gated Heads on ORIGINAL P0 frozen features.

This is a partial, source-byte-checked CPU shadow study (2/4 source models).
No original held test labels are opened, and no model admission, NDU choice,
chronological future benefit or production FinalUse is certified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import zipfile

import numpy as np
import torch
from safetensors.numpy import load as load_safetensors

SOURCE_GITHUB_RUN = 38868208650
SOURCE_HEAD = '09e5d4806c166586ba18b2ac87f75034fecd6687'
E1_SOURCE_GIT_BLOB = '3d3f0a76741733bb3354ce6951a55009726409c0'
ORIGINAL_SHA256 = {
 'p0_granite97_38868208650.zip': '3b66e9d83fa93f4b6b113a367fe10e8572b31199e2ead9c8b1819a0aaeb7c26f',
 'p0_embeddinggemma_attempt_38868208650.zip': 'e9de525b6c02e98bdd799b6e6671f6d6439db5ce895063adcee3fc38dd67d466',
 'p0_multirc_fit_38868208650.zip': '03b17dd2787700095f4f429ea5e1be36ee466f6b8fcdb371e70216d40a92032a',
 'p0_multirc_blind_38868208650.zip': '788b7a2b45f186293ea8f69511556447d053a6e5eba98befdc6ab23cd30eaee3',
 'hepta_e1_matched_gated_head_20261015.zip': '85bc0c30818a08644b1af107bbbf07fcf8f6eb5009d124b116e0e365eb37b80c',
}
MODELS = {
 'granite_97m_r2': ('p0_granite97_38868208650.zip',384),
 'embeddinggemma_2_text': ('p0_embeddinggemma_attempt_38868208650.zip',256),
}
SCHEMA = 'hepta.p0.actual-frozen-feature-matched-4145-head-partial-shadow.v1'

class Invalid(ValueError):
    pass


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical(o: object) -> bytes:
    return json.dumps(o,sort_keys=True, separators=(',', ':'),allow_nan=False).encode()


def verify_archive(root: Path, name: str) -> Path:
    if name not in ORIGINAL_SHA256:
        raise Invalid('unregistered original immutable source file')
    p=root/name
    if p.is_symlink() or not p.is_file() or p.stat().st_size>3_000_000:
        raise Invalid('missing/symlinked/unbounded original evidence archive')
    if sha(p.read_bytes())!=ORIGINAL_SHA256[name]:
        raise Invalid('original GitHub artifact outer SHA differs from pinned study')
    with zipfile.ZipFile(p) as z:
        if len(z.infolist())>32 or len(set(z.namelist()))!=len(z.namelist()):
            raise Invalid('unsafe archive inventory')
        if any(info.file_size>2_000_000 or '..' in Path(info.filename).parts or info.filename.startswith('/')
               for info in z.infolist()):
            raise Invalid('unbounded/path-traversal source artifact')
    return p


def zip_read(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as z:
        if name not in z.namelist() or z.getinfo(name).file_size>2_000_000:
            raise Invalid('missing/unbounded source ZIP entry')
        return z.read(name)


def parse_source(raw: bytes) -> dict:
    def no_dup(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise Invalid('duplicate source JSON identity')
            obj[key]=value
        return obj
    x=json.loads(raw,object_pairs_hook=no_dup,
                 parse_constant=lambda x: (_ for _ in ()).throw(Invalid('nonfinite source number')))
    if type(x) is not dict:raise Invalid('malformed original research source')
    return x


def load_existing_probe(root: Path):
    archive=verify_archive(root,'hepta_e1_matched_gated_head_20261015.zip')
    raw=zip_read(archive,'experiments/shared_stem_cell/e1_matched_gated_head.py')
    exact_blob=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
    if exact_blob!=E1_SOURCE_GIT_BLOB:raise Invalid('unverified registered E1 Head source')
    # Isolate the exact source inside a temporary namespace; it has no rights
    # beyond tensor operations, and its independently reviewed CLI is NOT used
    # to bypass the still-failed four-model admission gate.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'existing_e1_head.py';p.write_bytes(raw)
        spec=importlib.util.spec_from_file_location('exact_e1_4145_source',p)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    if (module.PARAMETERS!=4145 or module.PROJECTED_WIDTH!=128 or
            module.HIDDEN!=16 or module.SEEDS!=(41,47,53) or module.STEPS!=40 or
            module.ARMS!=('frozen_additive','trained_additive','frozen_gated','trained_gated')):
        raise Invalid('original equal-budget Head protocol changed')
    return module


def source_indices(fit: dict, blind: dict):
    if (type(fit.get('cases')) is not list or type(blind.get('cases')) is not list or
            any('label' in case for case in blind['cases']) or
            fit.get('metadata')!=blind.get('metadata')):
        raise Invalid('source split/human-label custody violated')
    items=fit['cases'];other=blind['cases']
    train=[i for i,c in enumerate(items) if c['split']=='train' and c['condition']=='original']
    cal=[i for i,c in enumerate(items) if c['split']=='calibration' and c['condition']=='original']
    held=list(range(len(items),len(items)+len(other)))
    if (len(items)!=246 or len(other)!=116 or len(train)!=91 or len(cal)!=32 or
            any('label' not in items[i] for i in train+cal) or
            any(type(items[i]['label']) is not int or items[i]['label'] not in (0,1) for i in train+cal)):
        raise Invalid('unregistered TRAIN/CAL only population')
    keys={part:{c['source_group'] for c in items if c['split']==part}
          for part in ['train','calibration']}
    keys['test']={c['source_group'] for c in other}
    if (keys['train'] & keys['calibration'] or keys['train'] & keys['test'] or
            keys['calibration'] & keys['test']):
        raise Invalid('original source passages leaked across partitions')
    pairs={}
    for i,row in enumerate(other):
        key=(row['source_group'],row['question_id'],row['answer_id'])
        existing=pairs.setdefault(key,{})
        if row['condition'] in existing:raise Invalid('duplicate held source/control pair')
        existing[row['condition']]=i
    if len(pairs)!=58 or any(set(item)!={'original','no_evidence'} for item in pairs.values()):
        raise Invalid('held original/no-evidence inputs unpaired')
    return train,cal,held,list(pairs.values())


def evaluation_summary(e1,features,indices,labels,blind,paired,head_tensors,record):
    seed,arm=record['seed'],record['arm']
    prefix=f'seed{seed}.{arm}'
    head=e1.MatchedHead('gated' if arm.endswith('gated') else 'additive').eval()
    state={key:torch.tensor(head_tensors[f'{prefix}.{key}']) for key in ('a.weight','a.bias','b.weight','b.bias','out.weight','out.bias')}
    head.load_state_dict(state,strict=True)
    projection=torch.tensor(head_tensors['shared_projection'],dtype=torch.float32)
    projected=torch.from_numpy(features) @ projection
    with torch.inference_mode():
        logits=head(projected[indices])
        probs=torch.sigmoid(logits/record['temperature'])
        expected=torch.tensor(labels,dtype=torch.float32)
        brier=float(torch.mean((probs-expected)**2))
        nll=float(torch.nn.functional.binary_cross_entropy(probs,expected))
        accuracy=float(torch.mean(((probs>=0.5)==(expected==1)).float()))
    if not all(math.isfinite(x) for x in (brier,nll,accuracy)):
        raise Invalid('nonfinite calibration-only observation')
    # Blind predictions are already emitted by exact, original E1 numerical
    # probe. Only their source-paired, label-free displacement is summarized.
    p=record['blind_probabilities']
    if len(p)!=len(blind) or any(not math.isfinite(x) or not 0<=x<=1 for x in p):
        raise Invalid('missing or nonfinite original blind forecasts')
    paired_diffs=[abs(p[x['original']]-p[x['no_evidence']]) for x in paired]
    return {'calibration_accuracy_optimistically_tuned':accuracy,
            'calibration_brier_optimistically_tuned':brier,
            'calibration_log_loss_optimistically_tuned':nll,
            'calibration_predicted_positive_count_at_0_5':int((probs>=0.5).sum()),
            'calibration_observed_positive_count':int(expected.sum()),
            'calibration_predicted_positive_probability_mean':float(probs.mean()),
            'blind_original_vs_no_evidence_mean_abs_probability_change_without_labels':float(np.mean(paired_diffs)),
            'blind_original_vs_no_evidence_max_abs_probability_change_without_labels':max(paired_diffs),
            'blind_forecast_sha256':sha(canonical([float(x) for x in p]))}


def execute(root: Path) -> dict:
    e1=load_existing_probe(root)
    fit=parse_source(zip_read(verify_archive(root,'p0_multirc_fit_38868208650.zip'),'fit.json'))
    blind=parse_source(zip_read(verify_archive(root,'p0_multirc_blind_38868208650.zip'),'blind.json'))
    train,cal,held,pairs=source_indices(fit,blind)
    train_y=[fit['cases'][i]['label'] for i in train]
    cal_y=[fit['cases'][i]['label'] for i in cal]
    if set(train_y)!={0,1} or set(cal_y)!={0,1}:raise Invalid('missing original human-backed training/callabel')
    output={}
    for name,(artifact,width) in MODELS.items():
        p=verify_archive(root,artifact)
        record=parse_source(zip_read(p,f'{name}.json'))
        manifest=parse_source(zip_read(p,f'{name}.replay/COMMITTED.json'))
        features_raw=zip_read(p,f'{name}.replay/features.safetensors')
        heads_raw=zip_read(p,f'{name}.replay/heads.safetensors')
        # Independent ORIGINAL source-bound numerical replay validates all
        # recorded features, Head tensors and 348 forecasts BEFORE new training.
        sys.path.insert(0,str(root))
        if name=='granite_97m_r2':
            from hepta_p0_granite97_partial_replay import evaluate
        else:
            from hepta_p0_gemma_partial_replay import evaluate
        numeric=evaluate(fit,blind,record,manifest,features_raw,heads_raw)
        if (numeric['total_predictions_replayed']!=348 or numeric['authority']!='DENY_ALL'
                or numeric['original_human_held_labels_opened'] is not False):
            raise Invalid('original true feature/Head source did not pass numeric replay')
        features=load_safetensors(features_raw)['features_q24_fp32']
        if features.shape!=(362,width) or features.dtype!=np.float32:
            raise Invalid('genuine original frozen feature matrix geometry differs')
        source_bank_sha=sha(features_raw)
        results,weights=e1.run_probe(features,train,train_y,cal,cal_y,held)
        if results['authority']!='DENY_ALL' or results['quality_scored'] is not False:
            raise Invalid('original Head unexpectedly acquired production authority')
        arms=[]
        for r in results['arms']:
            o={'seed':r['seed'],'arm':r['arm'],'parameter_count':r['parameter_count'],
               'trained':r['arm'].startswith('trained_'),
               'weights_changed_from_same_seed_initialization':r['initial_sha256']!=r['final_sha256'],
               'optimizer_steps':r['optimizer_steps'],
               'fit_cpu_ms_self_reported':r['fit_cpu_ms'],
               'calibration_temperature':r['temperature'],
               'head_final_weights_sha256':r['final_sha256'],
               **evaluation_summary(e1,features,cal,cal_y,blind['cases'],pairs,weights,r)}
            if o['trained'] != o['weights_changed_from_same_seed_initialization']:
                raise Invalid('claimed training does not match original actual Head change')
            arms.append(o)
        for seed in e1.SEEDS:
            z=[r for r in arms if r['seed']==seed]
            if len(z)!=4 or len({r['parameter_count'] for r in z})!=1 or z[0]['parameter_count']!=4145:
                raise Invalid('unmatched Head seeds / parameter budgets')
        output[name]={
            'original_model_revision':manifest['revision'],
            'original_p0_artifact_zip_sha256':ORIGINAL_SHA256[artifact],
            'original_frozen_feature_archive_sha256':source_bank_sha,
            'original_feature_width':width,
            'original_source_tensor_bank_shape':[362,width],
            'original_P0_head_predictions_independently_replayed':numeric['total_predictions_replayed'],
            'new_pretrained_encoder_model_loads':0,
            'new_pretrained_encoder_forward_passes':0,
            'shared_projection_coefficient_count':width*128,
            'shared_projection_fp32_bytes':width*128*4,
            'amortized_feature_bank_fp32_bytes':362*128*4,
            'head_per_cell_trainable_parameters':4145,
            'head_per_cell_fp32_parameter_bytes':4145*4,
            'trained_head_arms_count':6,
            'arms':arms,
        }
    return {
       'schema':SCHEMA,'original_actions_run_id':SOURCE_GITHUB_RUN,
       'original_source_commit_sha':SOURCE_HEAD,
       'exact_original_e1_source_blob':E1_SOURCE_GIT_BLOB,
       'source_fit_outer_zip_sha256':ORIGINAL_SHA256['p0_multirc_fit_38868208650.zip'],
       'source_blind_outer_zip_sha256':ORIGINAL_SHA256['p0_multirc_blind_38868208650.zip'],
       'source_train_original_cases':len(train),'source_calibration_original_cases':len(cal),
       'source_blind_unlabeled_views':len(held),'original_blind_no_evidence_pairs':len(pairs),
       'calibration_labels_used_for_temperature_selection':True,
       'calibration_accuracies_not_independent_test_scores':True,
       'complete_original_four_stem_gate_satisfied':False,
       'original_human_held_labels_accessed':False,
       'original_encoder_freshly_loaded_or_reforwarded_in_this_shadow':False,
       'independent_hf_model_publisher_signature_authenticated':False,
       'longitudinal_utility_negative_transfer_verified':False,
       'production_finaluse_granted':False,'stem_selected':False,
       'production_promotion_permitted':False,'authority':'DENY_ALL',
       'models':output,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.is_symlink() or args.output.exists():
        raise FileExistsError('research evidence must be create-only')
    result=execute(args.root)
    data=canonical(result)+b'\n'
    if len(data)>100_000:raise Invalid('unbounded research evidence receipt')
    with args.output.open('xb') as stream:stream.write(data)
    print(json.dumps({'schema':SCHEMA,'models':sorted(result['models']),
                      'head_parameter_count':4145,'original_held_labels_opened':False,
                      'production_promotion_permitted':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
