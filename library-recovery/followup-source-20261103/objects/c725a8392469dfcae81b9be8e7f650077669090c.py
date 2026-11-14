#!/usr/bin/env python3
"""Independent ORIGINAL AG News E1/E2 two-arm retrospective audit (DENY_ALL).

Only the EXACT historical original GitHub Actions artifact for run 38893928466
is eligible. The missing third original mmBERT arm remains explicitly failed.
Does not replay Encoder weights or grant model selection, FinalUse or NDU.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import zipfile

SCHEMA = 'hepta.e1e2.original-public-two-model-partial-review.v1'
SOURCE_HEAD = 'ec889943bbc990dce34c8546ad013fefe7fc7a78'
ORIGINAL_RUN = 38893928466
ORIGINAL_ARTIFACT = 12046289415
ZIP_SHA256 = '62fc3d986c66bc35b78f449ba6972efecd58e8752ff53103f0f18d9f6e509e8b'
PANEL_SHA256 = '2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'
SOURCE_FILES = {
    'train':'cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5',
    'calibration_test':'3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672',
}
TRAIN_IDS_SHA256 = 'd48193efe44561ad895b00f9b0514260ee96866cb82a54eff479037da9a3d2cb'
MODEL_INFO = {
    'granite_97m_r2': ('835ad14087e140460703cf0fae09f97d469d65c2', 384, 770),
    'embeddinggemma_2_text': ('914f7f89142e33e77833254d9c9b90c3cef7303b', 256, 514),
}
ORIGINAL_MEMBERS_SHA256 = {
    'e1-pinned-runtime.txt':'2ad4df154bae66ad90c08c716aed631082ec6f4c8ebd262d576e26b92a8f058c',
    'e1-public/embeddinggemma_2_text.e2.json':'6e8aeae969f4df703755d0ce8452161f1a5d37a3795e5cf9e2f6da6312015e79',
    'e1-public/embeddinggemma_2_text.json':'87cfd1a98f02a6ae543be984445c239fb16a6a275d5595dc99efe404c26a07fb',
    'e1-public/gemma-source-receipt.json':'84946c32fb37ab877a05240bb2768ef3fff70aa4e5e9a15dfb96130002c98b64',
    'e1-public/granite_97m_r2.e2.json':'dc287de5dea111d48c150686b1974f9b5615fea6218bf8fb182f794de5a1984c',
    'e1-public/granite_97m_r2.json':'397a1a6502cdec78c54186e9c571aeb5106ca5d27f8f8fa3250c609ad10f60e5',
    'e1-public/mmbert_small.failed.txt':'c47c96a99cf8ca855b51418012eb2226d720fbc3cfb77b4d57c687aaaa1690f5',
    'e1-public/original-source-lock.json':'9b4b49039c813be2725c36d20afc795436c3014136d3b234156e9f0170ce4ecb',
    'e1-public/panel.json':PANEL_SHA256,
    'e1-public/public-source-receipt.json':'f0d24978ba1623160da4676aff13cfd3f9c37cff1b94b0e34b7644bf3bd9da2e',
}
SPLITS={'train':128,'calibration':32,'test':64}
E2_ARMS=('cosine_prototype','from_zero','frozen_head','residual_2k','residual_8k','residual_16k')
HEX64=re.compile(r'[a-f0-9]{64}\Z')

class Invalid(ValueError):
    pass


def canonical(data):
    return json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs_unique(pairs):
    obj={}
    for name,value in pairs:
        if name in obj:
            raise Invalid('duplicate original evidence JSON key')
        obj[name]=value
    return obj


def strict_json(data):
    if len(data)>512*1024 or len(data)<2:
        raise Invalid('unbounded or empty evidence source')
    return json.loads(data,object_pairs_hook=pairs_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite source JSON')))


def strict_original_artifact(path):
    """Open exact original runner bytes only; ZIP may never extract paths."""
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise Invalid('missing or symlinked original action artifact')
    if not 512<p.stat().st_size<1024*1024:
        raise Invalid('unbounded original run artifact')
    if sha(p.read_bytes())!=ZIP_SHA256:
        raise Invalid('historical GitHub Actions artifact bytes differ from frozen source')
    raw={}
    with zipfile.ZipFile(p) as z:
        members=z.infolist()
        names=[x.filename for x in members]
        if len(names)!=len(ORIGINAL_MEMBERS_SHA256) or set(names)!=set(ORIGINAL_MEMBERS_SHA256) or len(set(names))!=len(names):
            raise Invalid('incomplete/extra/duplicate original historical members')
        for member in members:
            if (member.flag_bits & 1 or member.is_dir() or member.file_size>512*1024 or member.file_size<1 or
                    member.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)):
                raise Invalid('unsafe historical artifact member')
            content=z.read(member)
            if sha(content)!=ORIGINAL_MEMBERS_SHA256[member.filename]:
                raise Invalid('historical model evidence source SHA mismatch')
            raw[member.filename]=content
    return raw


def validate_panel(panel):
    if (type(panel) is not dict or panel.get('schema')!='hepta.stem.agnews-binary-capability-panel.v1' or
            panel.get('dataset')!='szhuggingface/ag_news' or panel.get('dataset_commit_prefix')!='98c5322' or
            panel.get('dataset_file_sha256')!=SOURCE_FILES or panel.get('label_mapping')!={'world':0,'sports':1} or
            panel.get('production_promotion')!='DENY_ALL' or panel.get('cross_sectional_not_future') is not True or
            panel.get('case_count')!=224 or type(panel.get('cases')) is not list or len(panel['cases'])!=224 or
            sha(canonical(panel))!=PANEL_SHA256):
        raise Invalid('original public AG News source panel identity changed')
    seen={};counts={k:0 for k in SPLITS}
    for c in panel['cases']:
        if (type(c) is not dict or set(c)!={'case_id','group_id','joint_input','joint_input_digest','label','label_name','source_digest','split'} or
                c['split'] not in SPLITS or type(c['label']) is not int or c['label'] not in (0,1) or
                c['label_name'] not in ('world','sports') or panel['label_mapping'][c['label_name']]!=c['label']):
            raise Invalid('invalid original AG News source case/label')
        x=c['joint_input']
        if (type(x) is not dict or set(x)!={'state','question','options'} or type(x['state']) is not str or
                not x['state'] or x['question']!='Which category does the news report describe?' or
                x['options']!=['world','sports']):
            raise Invalid('altered original physical model-facing text')
        digest=sha(x['state'].encode('utf8'))
        if (c['case_id']!=digest[:24] or c['group_id']!=digest or
                c['source_digest']!=digest or c['joint_input_digest']!=sha(canonical(x)) or
                c['case_id'] in seen):
            raise Invalid('duplicate/source-drifting original AG News case')
        counts[c['split']]+=1;seen[c['case_id']]=c
    if counts!=SPLITS:
        raise Invalid('original frozen train/calibration/test split population changed')
    train_ids=[c['case_id'] for c in panel['cases'] if c['split']=='train']
    if sha(canonical(train_ids))!=TRAIN_IDS_SHA256:
        raise Invalid('original training identity/order changed')
    return seen


def validate_predictions(rows, panel_cases, expected, *, context):
    """Recount only CAL/TEST identity, compute source-level descriptive metrics."""
    if type(rows) is not list or len(rows)!=len(expected):
        raise Invalid('missing original '+context+' predictions')
    appeared=set();test=[];cal=[]
    for row in rows:
        if type(row) is not dict or set(row)!={'case_id','joint_input_digest','split','positive_probability'}:
            raise Invalid('unregistered original prediction envelope')
        case_id=row['case_id']
        if type(case_id) is not str or case_id not in expected or case_id in appeared:
            raise Invalid('duplicate or extra historical prediction case')
        sample=panel_cases[case_id]
        if (row['joint_input_digest']!=sample['joint_input_digest'] or row['split']!=sample['split'] or
                type(row['positive_probability']) not in (int,float) or
                not math.isfinite(row['positive_probability']) or not 0.0<=row['positive_probability']<=1.0):
            raise Invalid('prediction/source/score drift')
        appeared.add(case_id)
        (test if row['split']=='test' else cal).append(row)
    if appeared!=set(expected) or len(test)!=SPLITS['test'] or len(cal)!=SPLITS['calibration']:
        raise Invalid('incomplete or changed original public TEST/CAL population')
    # Public AG News TEST labels were accessible in the research producer's
    # original panel. This retrospective descriptive score is NOT held-out.
    y=[panel_cases[r['case_id']]['label'] for r in test]
    p=[r['positive_probability'] for r in test]
    correct=sum(int((v>=0.5)==bool(label)) for v,label in zip(p,y))
    return {'original_public_calibration_cases':len(cal),
            'original_public_test_cases':len(test),
            'correct':correct, 'accuracy':correct/len(test),
            'brier':sum((v-label)**2 for v,label in zip(p,y))/len(test),
            'independent_hidden_test_labels':False,
            'chronological_future_utility':False}


def assess_model(model, panel_cases, e1, e2, e1_raw):
    revision,width,base_params=MODEL_INFO[model]
    if (type(e1) is not dict or type(e2) is not dict or
            e1.get('model')!=model or e2.get('model')!=model or
            e1.get('model_revision')!=revision or e2.get('source_model_revision')!=revision or
            e1.get('feature_width')!=width or e2.get('width')!=width or
            e1.get('schema')!='hepta.e1-english-public-pretrained-head.v1' or
            e2.get('schema')!='hepta.e2-feature-gated-head-public.v1' or
            e1.get('public_panel_sha256')!=PANEL_SHA256 or e2.get('public_panel_sha256')!=PANEL_SHA256 or
            e2.get('source_e1_report_sha256')!=sha(e1_raw) or
            e1.get('authority')!='DENY_ALL' or e2.get('authority')!='DENY_ALL' or
            e1.get('production_promotion_permitted') is not False or
            e2.get('production_promotion_permitted') is not False or
            e1.get('model_origin_independently_authenticated') is not False or
            e1.get('actual_pretrained_local_weight_execution_claimed') is not True or
            e1.get('public_dataset_is_chronological_future') is not False or
            e1.get('future_ndu_verified') is not False or
            e2.get('chronological_future_ndu_verified') is not False or
            e2.get('independent_no_change_production_arm_present') is not False or
            e2.get('additional_encoder_model_loads')!=0 or e2.get('additional_encoder_feature_forwards')!=0 or
            e2.get('existing_frozen_encoder_features_reused') is not True or
            e2.get('frozen_base_weight_storage_shared_among_residual_arms') is not True or
            e2.get('frozen_base_parameters_counted_as_shared_storage')!=base_params or
            e2.get('reader_sufficiency_evaluated') is not False or
            e2.get('cosine_uses_train_labels_not_no_fit') is not True or
            e2.get('head_kind')!='post_encoder_feature_gated_residual_not_cell_state_film' or
            e1.get('frozen_feature_bank_identity')!=e2.get('frozen_feature_bank_identity') or
            e1.get('fitting',{}).get('train_case_ids_sha256')!=TRAIN_IDS_SHA256 or
            e2.get('train_case_ids_sha256')!=TRAIN_IDS_SHA256 or
            e1.get('fitting',{}).get('head_parameter_count')!=base_params or
            e1.get('fitting',{}).get('seed')!=20261014 or
            e1.get('fitting',{}).get('steps')!=40 or
            e1.get('fitting',{}).get('training_test_labels_accessed') is not False or
            e1.get('fitting',{}).get('retrospective_public_labels_available_in_process') is not True or
            e2.get('steps')!=40 or e2.get('seed')!=20261014):
        raise Invalid('untrusted E1/E2 model/source/approval/budget lineage')
    bank=e1['frozen_feature_bank_identity']
    if (type(bank) is not dict or bank.get('case_count')!=224 or bank.get('feature_width')!=width or
            bank.get('authority')!='DENY_ALL' or bank.get('model_origin_independently_verified') is not False or
            type(bank.get('case_q24_sha256')) is not dict or
            set(bank['case_q24_sha256'])!=set(panel_cases) or
            type(e1.get('features_q24_identity')) is not dict or
            set(e1['features_q24_identity'])!=set(panel_cases) or
            type(e1.get('tokens_per_case')) is not dict or set(e1['tokens_per_case'])!=set(panel_cases) or
            type(e1.get('physical_observations')) is not dict or
            e1['physical_observations'].get('local_model_api_requests')!=224 or
            e1['physical_observations'].get('physical_transformer_forward_count_attested') is not False or
            type(e1.get('process_lifetime_peak_rss_bytes')) not in (int,float) or
            e1['process_lifetime_peak_rss_bytes']<=0 or
            type(e1.get('wall_ms')) not in (int,float) or e1['wall_ms']<=0):
        raise Invalid('unverified frozen bank, incomplete original feature census or missing resource report')
    for case_id, tokens in e1['tokens_per_case'].items():
        if type(tokens) is not int or not 1<=tokens<=512:
            raise Invalid('invalid original token cap')
    controls=e1['fitting'].get('controls')
    arms=e2.get('arms')
    if (type(controls) is not dict or set(controls)!={'frozen_head','learned_head'} or
            type(arms) is not dict or set(arms)!=set(E2_ARMS)):
        raise Invalid('incomplete original frozen/learned/residual control population')
    expected={x for x,c in panel_cases.items() if c['split'] in ('test','calibration')}
    validated={}
    for name,receipt in arms.items():
        if type(receipt) is not dict or receipt.get('trainable_parameters') is None:
            raise Invalid('missing residual control parameter evidence')
        params=receipt['trainable_parameters']
        if type(params) is not int or params<0 or (name=='from_zero' and params!=base_params) or (name in ('cosine_prototype','frozen_head') and params!=0):
            raise Invalid('unmatched original model Head parameter budget')
        if name.startswith('residual_') and params>{'residual_2k':2048,'residual_8k':8192,'residual_16k':16384}[name]:
            raise Invalid('original residual Head exceeded declared per-arm budget')
        validated[name]={'trainable_head_parameters':params,
                         **validate_predictions(receipt.get('predictions'),panel_cases,expected,context=name)}
    for orig,sidecar in (('frozen_head','frozen_head'),('learned_head','from_zero')):
        left=controls[orig]['predictions'];right=arms[sidecar]['predictions']
        validate_predictions(left,panel_cases,expected,context='E1 '+orig)
        if len(left)!=len(right):
            raise Invalid('E1/E2 original baseline length changed')
        left_map={p['case_id']:p for p in left}
        right_map={p['case_id']:p for p in right}
        if (set(left_map)!=set(right_map) or
                any(abs(left_map[k]['positive_probability']-right_map[k]['positive_probability'])>1e-6
                    for k in left_map)):
            raise Invalid('E2 frozen or trained baselines do not reproduce original E1 probabilities')
    return {'model':model, 'source_revision':revision, 'width':width,
            'e1_report_sha256':sha(e1_raw),
            'e2_report_sha256':ORIGINAL_MEMBERS_SHA256['e1-public/'+model+'.e2.json'],
            'actual_pretrained_cpu_encoding_claimed_by_runner':e1['actual_pretrained_local_weight_execution_claimed'],
            'original_model_publisher_independently_authenticated':False,
            'original_encoder_recomputed_by_this_audit':False,
            'head_probability_recomputed_from_weights_by_this_audit':False,
            'original_public_test_cases':64, 'training_labels_accessible_to_producer':True,
            'residual_arcs':validated,
            'frozen_vs_trained_accuracy_delta':validated['from_zero']['accuracy']-validated['frozen_head']['accuracy'],
            'residual_2k_vs_trained_accuracy_delta':validated['residual_2k']['accuracy']-validated['from_zero']['accuracy'],
            'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def audit_original_zip(path):
    raw=strict_original_artifact(path)
    if b'mmbert_small failed source-based real CPU trial' not in raw['e1-public/mmbert_small.failed.txt']:
        raise Invalid('original mmBERT missing/failed arm was silently promoted')
    panel=strict_json(raw['e1-public/panel.json'])
    cases=validate_panel(panel)
    origin=strict_json(raw['e1-public/original-source-lock.json'])
    receipt=strict_json(raw['e1-public/public-source-receipt.json'])
    if (origin.get('authority')!='DENY_ALL' or origin.get('public_panel_sha256')!=PANEL_SHA256 or
            origin.get('source_selection_matches_original_real_run') is not True or
            origin.get('future_chronology_or_independent_labels_verified') is not False or
            origin.get('production_promotion_permitted') is not False or
            receipt.get('panel_digest')!=PANEL_SHA256 or receipt.get('source_sha256')!=SOURCE_FILES or
            receipt.get('external_source_signer_authenticated') is not False or
            receipt.get('production_promotion')!='DENY_ALL'):
        raise Invalid('historical AG News original panel/source authority drift')
    models={}
    for name in MODEL_INFO:
        b=raw['e1-public/'+name+'.json']
        models[name]=assess_model(name,cases,strict_json(b),
                                  strict_json(raw['e1-public/'+name+'.e2.json']),b)
    return {'schema':SCHEMA,'original_git_commit':SOURCE_HEAD,
            'original_github_run_id':ORIGINAL_RUN,'original_github_artifact_id':ORIGINAL_ARTIFACT,
            'original_runner_zip_sha256':ZIP_SHA256,
            'original_public_panel_sha256':PANEL_SHA256,
            'public_train_cases':128,'public_calibration_cases':32,'public_test_cases':64,
            'reviewed_models':models,
            'unavailable_model':{'model':'mmbert_small','status':'original_physical_model_failed','scored':False},
            'original_complete_three_encoder_panel_qualified':False,
            'independent_future_outcome_or_negative_transfer_verified':False,
            'original_model_head_weights_independently_replayed':False,
            'held_test_labels_separated_from_model_producer':False,
            'independent_pretrained_source_signatures_verified':False,
            'production_model_winner_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-run-zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    opt=parser.parse_args()
    if opt.output.exists() or opt.output.is_symlink():
        raise FileExistsError('original public partial review output is create-only')
    result=audit_original_zip(opt.original_run_zip)
    with opt.output.open('xb') as f:
        f.write(canonical(result)+b'\n')
        f.flush()
        import os
        os.fsync(f.fileno())
    print(json.dumps({'schema':SCHEMA,'models_reviewed':len(result['reviewed_models']),
                      'original_all_three_models_qualified':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':
    main()
