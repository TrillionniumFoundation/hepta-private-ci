#!/usr/bin/env python3
"""Independent, model-free E2 Head parameter and numeric review of archived E1+E2.

This script does not load a model or select a winning Stem. Reports remain
retrospective English-only, with no production no-change, future or NDU proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

BUDGETS={'residual_2k':2048,'residual_8k':8192,'residual_16k':16384}
ARMS=('frozen_head','from_zero','cosine_prototype',*BUDGETS)
class Invalid(ValueError):pass


def _pairs(items):
    d={}
    for k,v in items:
        if k in d:raise Invalid('duplicate JSON field')
        d[k]=v
    return d

def read(path):
    raw=Path(path).read_bytes()
    if not 10<len(raw)<6*1024*1024:raise Invalid('missing/oversized E2 evidence')
    data=json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
    return data,hashlib.sha256(raw).hexdigest()

def _digest(v):
    if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
        raise Invalid('missing/invalid digest')
    return v

def _finite(v):
    if type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=1:
        raise Invalid('invalid probability')
    return float(v)

def review(panel,e1,e1_file_sha,e2):
    if (type(panel) is not dict or panel.get('case_count')!=224 or panel.get('cross_sectional_not_future') is not True or
        panel.get('production_promotion')!='DENY_ALL'):
        raise Invalid('nonapproved E1 public panel')
    cases=panel['cases'];index={c['case_id']:c for c in cases}
    if len(index)!=224 or len(cases)!=224:raise Invalid('duplicate source case')
    panel_sha=hashlib.sha256(json.dumps(panel,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()
    if (type(e1) is not dict or e1.get('schema')!='hepta.e1-english-public-pretrained-head.v1' or
        e1.get('public_panel_sha256')!=panel_sha or e1.get('production_promotion_permitted') is not False or
        e1.get('actual_pretrained_local_weight_execution_claimed') is not True):
        raise Invalid('incomplete E1 physical source claim')
    if (type(e2) is not dict or e2.get('schema')!='hepta.e2-feature-gated-head-public.v1' or
        e2.get('authority')!='DENY_ALL' or e2.get('production_promotion_permitted') is not False or
        e2.get('source_e1_report_sha256')!=_digest(e1_file_sha) or e2.get('public_panel_sha256')!=panel_sha or
        e2.get('model')!=e1.get('model') or e2.get('source_model_revision')!=e1.get('model_revision') or
        e2.get('width')!=e1.get('feature_width') or e2.get('case_count')!=224 or
        e2.get('existing_frozen_encoder_features_reused') is not True or
        e2.get('additional_encoder_model_loads')!=0 or e2.get('additional_encoder_feature_forwards')!=0 or
        e2.get('independent_no_change_production_arm_present') is not False or
        e2.get('chronological_future_ndu_verified') is not False):
        raise Invalid('unbound or overstated E2 source/authority')
    def check_bank(bank):
        if (type(bank) is not dict or bank.get('schema')!='hepta.e1e2-q24-feature-bank.v1'
                or bank.get('authority')!='DENY_ALL'
                or bank.get('model_origin_independently_verified') is not False
                or bank.get('case_count')!=224
                or bank.get('feature_width')!=e1['feature_width']):
            raise Invalid('E1/E2 feature inventory identity not declared')
        entries=bank.get('case_q24_sha256')
        if type(entries) is not dict or set(entries)!=set(index):
            raise Invalid('E1/E2 feature inventory missing source cases')
        for value in entries.values():
            _digest(value)
        ordered=[[key,entries[key]] for key in sorted(entries)]
        canonical=json.dumps(ordered,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
        recomputed=hashlib.sha256(b'hepta.e1e2.bank-q24.v1'+bytes([0])+canonical).hexdigest()
        if recomputed!=_digest(bank.get('bank_q24_sha256')):
            raise Invalid('inconsistent feature bank full digest')
        return entries,recomputed
    old_bank,old_sha=check_bank(e1.get('frozen_feature_bank_identity'))
    learned_bank,learned_sha=check_bank(e2.get('frozen_feature_bank_identity'))
    if old_sha!=learned_sha or old_bank!=learned_bank:
        raise Invalid('E2 Head trained on feature bytes inconsistent with E1 original')
    fit=e1['fitting']
    if (e2.get('optimizer')!='SGD_full_train_batch' or e2.get('steps')!=fit['steps'] or
        e2.get('seed')!=fit['seed'] or e2.get('learning_rate')!=fit['learning_rate'] or
        e2.get('train_case_ids_sha256')!=fit['train_case_ids_sha256'] or
        e2.get('frozen_base_parameters_counted_as_shared_storage')!=fit['head_parameter_count'] or
        e2.get('head_kind')!='post_encoder_feature_gated_residual_not_cell_state_film' or
        e2.get('frozen_base_weight_storage_shared_among_residual_arms') is not True or
        e2.get('cosine_uses_train_labels_not_no_fit') is not True or
        e2.get('head_parameter_ceiling_by_arm')!=BUDGETS):
        raise Invalid('Head budget/schedule or frozen base accounting drift')
    controls=e2.get('arms');train=e2.get('training')
    if type(controls) is not dict or set(controls)!=set(ARMS) or type(train) is not dict or set(train)!=set(ARMS)-{'cosine_prototype','frozen_head'}:
        raise Invalid('missing full E2 controls')
    expected={c['case_id'] for c in cases if c['split'] in ('calibration','test')}
    labels={c['case_id']:c['label'] for c in cases if c['split'] in ('calibration','test')}
    outputs={};descriptive={}
    for name,item in controls.items():
        if type(item) is not dict or type(item.get('head_sha256')) is not str or len(item['head_sha256'])!=64:
            raise Invalid('missing E2 learned artifact bytes')
        n=item.get('trainable_parameters')
        if type(n) is not int or n<0 or (name in BUDGETS and not 0<n<=BUDGETS[name]):
            raise Invalid('unbounded residual Head')
        if name in BUDGETS and item.get('initial_baseline_logits_identical') is not True:
            raise Invalid('baseline-residual initialization not preserved')
        if name=='cosine_prototype' and n!=0:
            raise Invalid('cosine prototype incorrectly counted as neural update')
        if name=='from_zero' and n!=fit['head_parameter_count']:
            raise Invalid('from-zero Head parameter count differs from E1')
        rows=item.get('predictions')
        if type(rows) is not list or len(rows)!=96:
            raise Invalid('missing complete E2 prediction set')
        predictions={}
        for r in rows:
            case=r.get('case_id')
            if case not in expected or case in predictions or r.get('joint_input_digest')!=index[case]['joint_input_digest'] or r.get('split')!=index[case]['split']:
                raise Invalid('E2 case/source/partition mismatch')
            predictions[case]=_finite(r.get('positive_probability'))
        if set(predictions)!=expected:raise Invalid('incomplete E2 split coverage')
        outputs[name]=predictions
        descriptive[name]={}
        for split in ('calibration','test'):
            ids=[c['case_id'] for c in cases if c['split']==split]
            correct=sum(int((predictions[c]>=.5)==bool(labels[c])) for c in ids)
            brier=sum((predictions[c]-labels[c])**2 for c in ids)/len(ids)
            descriptive[name][split]={'n':len(ids),'correct':correct,'accuracy':correct/len(ids),'brier':brier}
    for original,ref in (('frozen_head','frozen_head'),('learned_head','from_zero')):
        old={r['case_id']:r['positive_probability'] for r in fit['controls'][original]['predictions']}
        if set(old)!=expected or any(abs(old[k]-outputs[ref][k])>1e-6 for k in expected):
            raise Invalid('E2 control not reproducible from original E1 Head')
    for name,item in train.items():
        if (type(item) is not dict or item.get('optimizer_steps')!=40 or
            item.get('trainable_parameters')!=controls[name]['trainable_parameters'] or
            item.get('trainable_weights_changed') is not True or
            _digest(item.get('initial_head_sha256'))==_digest(item.get('final_head_sha256')) or
            type(item.get('train_ms')) not in (float,int) or not math.isfinite(item['train_ms']) or item['train_ms']<=0):
            raise Invalid('invalid optimizer operation or parameter lineage')
        if _digest(item['final_head_sha256']) != controls[name]['head_sha256']:
            raise Invalid('trained residual Head differs from final digest')
    deltas={}
    for name in BUDGETS:
        a=descriptive[name]['test']; b=descriptive['frozen_head']['test'];c=descriptive['from_zero']['test']
        deltas[name]={'vs_frozen_accuracy_delta':a['accuracy']-b['accuracy'],
                      'vs_from_zero_accuracy_delta':a['accuracy']-c['accuracy'],
                      'vs_frozen_brier_delta':a['brier']-b['brier']}
    return {'schema':'hepta.e2-residual-independent-numeric.v1','model':e1['model'],
            'same_input_features_reused_claimed':True,
            'per_case_q24_inventory_identical_with_e1_source_report':True,
            'observed_feature_bank_q24_sha256':old_sha,
            'independent_model_encoder_execution_attested':False,'n_test_cases':64,
            'scores':descriptive,'descriptive_residual_deltas':deltas,
            'no_change_model_or_future_ndu_verified':False,'actual_weights_and_forwards_signed':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('panel','e1','e2','output'):
        p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args()
    panel,_=read(args.panel);e1,e1sha=read(args.e1);e2,_=read(args.e2)
    result=review(panel,e1,e1sha,e2)
    with args.output.open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')

if __name__=='__main__':main()
