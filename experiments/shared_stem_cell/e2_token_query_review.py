#!/usr/bin/env python3
"""Read-only E2 pooled-vs-Token-Query paired retrospective reviewer.

All physical/source evidence is producer-claimed, never signed deployment proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

from e2_pairwise_evidence import paired, Invalid as PairedInvalid

MODELS={
 'granite_97m_r2':('835ad14087e140460703cf0fae09f97d469d65c2',384),
 'mmbert_small':('0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',384),
 'modernbert_base':('fa3113d09d6dacfe5528708803dd92a62240237a',768)}
ARMS=('pooled_linear','pooled_gated','token_query')
PANEL_SHA='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'


class Invalid(ValueError):pass


def read(path):
    b=Path(path).read_bytes()
    if not 10<len(b)<4*1024*1024:raise Invalid('missing/oversized report')
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise Invalid('duplicate JSON member')
            d[k]=v
        return d
    return json.loads(b,object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON'))),hashlib.sha256(b).hexdigest()


def _positive(v):
    if type(v) not in (float,int) or not math.isfinite(v) or v<=0:raise Invalid('invalid time/resource value')
    return float(v)


def _hash(s):
    if type(s) is not str or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):
        raise Invalid('invalid original SHA256 identifier')
    return s


def review(panel, parents, studies, parent_sha):
    if (panel.get('schema')!='hepta.stem.agnews-binary-capability-panel.v1'
        or panel.get('cross_sectional_not_future') is not True
        or panel.get('case_count')!=224 or len(panel.get('cases',[]))!=224):
        raise Invalid('not the original frozen retrospective panel')
    if set(parents)!=set(MODELS) or set(studies)!=set(MODELS) or set(parent_sha)!=set(MODELS):
        raise Invalid('all three actual pretrained models required')
    bycase={r['case_id']:r for r in panel['cases']}
    if len(bycase)!=224:raise Invalid('duplicate public case')
    observed={k for k,r in bycase.items() if r['split'] in ('calibration','test')}
    if len(observed)!=96:raise Invalid('missing exact public scoring population')
    metrics={};comparisons={};budgets={};fingerprints=set()
    for model,(revision,width) in MODELS.items():
        parent=parents[model];d=studies[model]
        if (parent.get('model')!=model or parent.get('model_revision')!=revision or
            parent.get('public_panel_sha256')!=PANEL_SHA or
            parent.get('authority')!='DENY_ALL' or
            parent.get('production_promotion_permitted') is not False):
            raise Invalid('E1 parent model or source does not match original registered control')
        if (d.get('schema')!='hepta.stem.e2-paired-actual-encoder-heads.v1' or
            d.get('model')!=model or d.get('model_revision')!=revision or
            d.get('panel_sha256')!=PANEL_SHA or
            d.get('parent_e1_report_sha256')!=_hash(parent_sha[model]) or
            d.get('authority')!='DENY_ALL' or
            d.get('production_promotion_permitted') is not False or
            d.get('stem_winner_selected') is not False or
            d.get('physically_shared_across_production_cells_verified') is not False or
            d.get('independent_model_source_attestation') is not False or
            d.get('real_future_ndu_verified') is not False or
            d.get('production_no_change_verified') is not False):
            raise Invalid('unregistered or over-authorized E2 model report')
        state=d.get('head_study');feature=d.get('feature_bank')
        if (not isinstance(state,dict) or state.get('schema')!='hepta.stem.e2-token-query-physical-shadow.v1'
            or state.get('width')!=width or state.get('head_parameter_ceiling')!=2048 or
            state.get('optimizer')!='full_batch_sgd' or state.get('seed')!=20261015 or
            state.get('steps')!=40 or state.get('learning_rate')!=.15 or
            state.get('pretrained_model_origin_independently_authenticated') is not False or
            state.get('authentic_future_ndu_available') is not False or
            state.get('production_no_change_authenticated') is not False or
            state.get('stem_winner_selected') is not False or
            state.get('production_promotion_permitted') is not False or
            state.get('authority')!='DENY_ALL' or
            state.get('feature_bank')!=feature or
            not isinstance(feature,dict) or feature.get('case_count')!=224 or
            feature.get('dimension')!=width or
            feature.get('authenticated_model_forward') is not False or
            feature.get('authority')!='DENY_ALL'):
            raise Invalid('unmatched complete frozen token matrix, Head or research limits')
        digest=_hash(feature.get('frozen_token_and_native_pooled_sha256'))
        if digest in fingerprints:raise Invalid('different model registrations share the same frozen bank')
        fingerprints.add(digest)
        phys=d.get('physical')
        if (not isinstance(phys,dict) or
            phys.get('observed_model_module_forward_hooks')!=28 or
            phys.get('observed_backend_forward_calls')!=28 or
            phys.get('actual_unique_input_count')!=224 or
            phys.get('microbatch_size_bound')!=8 or
            phys.get('native_pool_and_token_query_derived_from_same_hidden_tensor') is not True or
            phys.get('independent_model_module_execution_attested') is not False or
            type(phys.get('min_tokens_per_input')) is not int or
            type(phys.get('max_tokens_per_input')) is not int or
            not 1<=phys['min_tokens_per_input']<=phys['max_tokens_per_input']<=512):
            raise Invalid('missing original physical microbatch/Token Matrix call ledger')
        _positive(phys.get('producer_observed_encode_wall_ms'))
        observations=phys.get('encoder_forward_elapsed_ms_by_case_amortized')
        if (type(observations) is not dict or set(observations)!=set(bycase) or
                any(_positive(v)<=0 for v in observations.values())):
            raise Invalid('missing actual per-original-case producer encode cost')
        if type(state.get('arms')) is not dict or set(state['arms'])!=set(ARMS):
            raise Invalid('missing pooled matched-capacity or Token Query arm')
        costs={}
        current={}
        for arm in ARMS:
            info=state['arms'][arm]
            train=info.get('train_receipt')
            params=(width+1 if arm=='pooled_linear' else 2*width+1)
            if (type(train) is not dict or train.get('train_steps')!=40 or
                    train.get('trainable_parameters')!=params or
                    _hash(train.get('initial_head_sha256'))==_hash(train.get('final_head_sha256')) or
                    info.get('frozen_initial_head_sha256')!=train['initial_head_sha256'] or
                    info.get('calibration_temperature') not in (.5,.75,1.,1.5,2.,3.,4.)):
                raise Invalid('Head training/complete private parameter mismatch')
            if train.get('learnable_query_actually_changed') is not (arm=='token_query' if arm=='token_query' else None):
                raise Invalid('learnable token Query movement must be physically recorded')
            costs[arm]=_positive(train.get('train_ms'))
            if info.get('frozen_calibration_temperature') not in (.5,.75,1.,1.5,2.,3.,4.):
                raise Invalid('frozen original Head calibration missing')
            current[arm]={}
            for mode in ('frozen_predictions','predictions'):
                predictions={}
                for p in info.get(mode,[]):
                    case=p.get('case_id')
                    if (case not in observed or case in predictions or
                        p.get('split')!=bycase[case]['split'] or
                        p.get('joint_input_digest')!=bycase[case]['joint_input_digest']):
                        raise Invalid('E2 frozen/learned case swap or duplication')
                    value=p.get('positive_probability')
                    if type(value) not in (float,int) or not math.isfinite(value) or not 0<=value<=1:
                        raise Invalid('invalid frozen/learned probability')
                    predictions[case]=float(value)
                if set(predictions)!=observed:raise Invalid('incomplete source-matched control')
                current[arm]['frozen' if mode=='frozen_predictions' else 'learned']=predictions
        required=_positive(d.get('model_load_ms'))+_positive(phys['producer_observed_encode_wall_ms'])+sum(costs.values())
        if _positive(d.get('total_wall_ms')) +.001<required:
            raise Invalid('model+feature+Head lifecycle underreported')
        _positive(d.get('cpu_process_ms'))
        _positive(d.get('process_lifetime_peak_rss_bytes'))
        metrics[model]={}
        test=[row for row in panel['cases'] if row['split']=='test']
        for arm,control in current.items():
            record={}
            for mode,pred in control.items():
                correct=sum(int((pred[row['case_id']]>=.5)==bool(row['label'])) for row in test)
                brier=sum((pred[row['case_id']]-row['label'])**2 for row in test)/len(test)
                record[mode]={'n':len(test),'correct':correct,'accuracy':correct/len(test),
                              'brier':brier}
            record['trained_minus_frozen_accuracy']=record['learned']['accuracy']-record['frozen']['accuracy']
            record['train_ms_reported']=costs[arm]
            metrics[model][arm]=record
        # The published outcome panel has 96 calibration+test predictions,
        # but these predeclared paired statistics use only the 64 TEST cases.
        try:
            test_ids={row['case_id'] for row in test}
            def only_test(predictions):
                return {k:v for k,v in predictions.items() if k in test_ids}
            pairwise={
                'query_vs_equal_parameter_pooled_gated':paired(
                    test,only_test(current['token_query']['learned']),
                    only_test(current['pooled_gated']['learned'])),
                'query_vs_pooled_linear':paired(
                    test,only_test(current['token_query']['learned']),
                    only_test(current['pooled_linear']['learned'])),
                'query_learned_vs_own_frozen':paired(
                    test,only_test(current['token_query']['learned']),
                    only_test(current['token_query']['frozen'])),
            }
        except PairedInvalid as exc:
            raise Invalid('failed independent paired source/statistical preflight') from exc
        comparisons[model]={
            'query_minus_equal_parameter_pooled_gated_accuracy':pairwise['query_vs_equal_parameter_pooled_gated']['left_minus_right_accuracy'],
            'query_minus_linear_pooled_accuracy':pairwise['query_vs_pooled_linear']['left_minus_right_accuracy'],
            'query_trained_minus_own_frozen_accuracy':pairwise['query_learned_vs_own_frozen']['left_minus_right_accuracy'],
            'retrospective_exact_unadjusted_discordance':pairwise,
            'multiple_comparison_adjustment_applied':False,
            'hypothesis_pre_registered_with_independent_labels':False,
        }
        budgets[model]={'original_model_loaded_once_for_E2_claimed':True,
                        'model_load_ms_reported':d['model_load_ms'],
                        'whole_E2_process_wall_ms_reported':d['total_wall_ms'],
                        'observed_physical_forward_hook_count_claimed':phys['observed_model_module_forward_hooks'],
                        'energy_joules':None,'native_target_host_p99_attested':False}
    return {'schema':'hepta.stem.e2-physical-token-query-descriptive-review.v1',
            'original_public_panel_sha256':PANEL_SHA,'models':metrics,
            'paired_differences':comparisons,'resource_descriptions':budgets,
            'strictly_retrospective_English_source':True,
            'same_original_model_execution_independently_authenticated':False,
            'production_no_change_authenticated':False,
            'future_ndu_utility_verified':False,'stem_winner_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',type=Path,required=True)
    for model in MODELS:
        parser.add_argument('--'+model.replace('_','-')+'-e1',type=Path,required=True)
        parser.add_argument('--'+model.replace('_','-')+'-e2',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from e1_core_real_cpu import load_panel
    panel,sha=load_panel(args.panel)
    if sha!=PANEL_SHA:raise Invalid('different archived AG News original')
    parents={};studies={};parent_sha={}
    for model in MODELS:
        parents[model],parent_sha[model]=read(getattr(args,model+'_e1'))
        studies[model],_=read(getattr(args,model+'_e2'))
    result=review(panel,parents,studies,parent_sha)
    with args.output.open('x',encoding='utf8') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write('\n')

if __name__=='__main__':main()
