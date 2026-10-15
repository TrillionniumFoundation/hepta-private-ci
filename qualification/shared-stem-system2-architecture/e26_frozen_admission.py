"""E26: pre-outcome passage-cluster, exact two-sided E25 research gate.

Only one fixed comparison: E24 tau .01 vs E16 candidate Brier, on six new
passages (twelve complete questions). Never grant model use or production.
Historical E24 evidence is reused as a NEGATIVE statistical control, not a
new test panel. No hidden model inference or independent source signer.
"""
from __future__ import annotations

from fractions import Fraction as F
from hashlib import sha256
from itertools import product
from json import loads
from math import isfinite
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
SPEC=ROOT/'E26_FROZEN_HYPOTHESIS_20261015.json'
OLD=ROOT/'E26_ORIGINAL_E24_HUMAN_CONTROL_20261015.json'
SPEC_SCHEMA='hepta.e26.frozen-six-original-passages-evaluation-v1'
OUTPUT_SCHEMA='hepta.e26.exact-six-passage-original-human-research-gate-v1'
SOURCE_SHA='5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
E25_SCHEMA='hepta.e25.new-six-original-source-complete-question-score.v1'
METHODS=('conditioned','mean_pool_query_fused','no_evidence','no_query',
         'e16_scaled_brier_5','question_softworst_tau_001')


def strict_json(data: bytes):
    if type(data) is not bytes or not 0<len(data)<=300000:
        raise ValueError('bounded original receipt required')
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    return loads(data,object_pairs_hook=pairs,
        parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def load_spec(path=SPEC):
    data=Path(path).read_bytes();d=strict_json(data)
    if (type(d) is not dict or set(d)!={
        'schema','authority','frozen_while_e25_true_six_passage_outcome_unobserved',
        'e25_source_head','e25_original_validation_parquet_sha256',
        'e25_original_frozen_policy_sha256','old_original_e24_human_control_sha256',
        'primary_method','primary_control','descriptive_controls','unit_of_pairing',
        'number_of_new_passages','number_of_new_questions',
        'hypothesis_count_for_confirmatory_e25_comparison',
        'two_sided_exact_passage_sign_flip_alpha',
        'maximum_allowed_new_human_two_class_brier_degradation',
        'no_passage_negative_transfer_for_research_promise',
        'secondary_candidate_accuracy_and_frozen_reader_scores_descriptive_only',
        'tau_was_chosen_posthoc_on_old_passages',
        'new_panel_same_public_data_family',
        'separate_original_owner_and_future_time_qualification_missing',
        'whole_service_cost_qualification_missing',
        'independent_model_and_outcome_signer_missing',
        'production_accepted','model_selected'}
        or d['schema']!=SPEC_SCHEMA or d['authority']!='DENY_ALL'
        or d['e25_source_head']!='5aa65b120df705d2c96adde9a093b4627958a64f'
        or d['e25_original_validation_parquet_sha256']!=SOURCE_SHA
        or d['e25_original_frozen_policy_sha256']!='dec01b016354733183d6feac374e6a333a22b08af8ef2d48196480064ff36a88'
        or d['old_original_e24_human_control_sha256']!='b88af557b4fd2aa50a26f523aee452fb7a08bbe659b3f0fc4c0aaf325f8c9b59'
        or d['primary_method']!=METHODS[-1] or d['primary_control']!=METHODS[-2]
        or d['descriptive_controls']!=list(METHODS[:4])
        or d['number_of_new_passages']!=6 or d['number_of_new_questions']!=12
        or d['hypothesis_count_for_confirmatory_e25_comparison']!=1
        or d['unit_of_pairing']!='original_validation_passage_with_two_complete_questions'
        or d['two_sided_exact_passage_sign_flip_alpha']!='1/20'
        or d['maximum_allowed_new_human_two_class_brier_degradation']!='1/50'
        or any(d[k] is not True for k in (
            'frozen_while_e25_true_six_passage_outcome_unobserved',
            'no_passage_negative_transfer_for_research_promise',
            'secondary_candidate_accuracy_and_frozen_reader_scores_descriptive_only',
            'tau_was_chosen_posthoc_on_old_passages',
            'new_panel_same_public_data_family',
            'separate_original_owner_and_future_time_qualification_missing',
            'whole_service_cost_qualification_missing',
            'independent_model_and_outcome_signer_missing'))
        or d['production_accepted'] is not False or d['model_selected'] is not False):
        raise ValueError('E26 preregistered single hypothesis changed')
    return d,sha256(data).hexdigest()


def exact_signflip(deltas):
    """Two-sided exact random sign flips on SOURCE passages, not candidates."""
    if (type(deltas) not in (list,tuple) or not 1<=len(deltas)<=12
        or any(type(d) is not int or not -16<=d<=16 for d in deltas)):
        raise ValueError('integer complete-question difference per passage required')
    observed=abs(sum(deltas))
    count=sum(abs(sum(sign*d for sign,d in zip(signs,deltas,strict=True)))>=observed
              for signs in product((-1,1),repeat=len(deltas)))
    return F(count,2**len(deltas))


def original_e24_negative_control(path=OLD, spec=SPEC):
    s,sh=load_spec(spec)
    raw=Path(path).read_bytes();h=sha256(raw).hexdigest()
    if h!=s['old_original_e24_human_control_sha256']:
        raise ValueError('original independent true-human E24 receipt differs in bytes')
    d=strict_json(raw)
    if (d.get('schema')!='hepta.e24.independent-original-human-question-risk-review.v1'
        or d.get('authority')!='DENY_ALL'
        or d.get('source_sha256')!='1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
        or d.get('exact_original_8_mixed_questions')!=8
        or d.get('exact_original_4_passages')!=4
        or d.get('model_selected') is not False
        or d.get('production_accepted') is not False):
        raise ValueError('original E24 human summary not authenticated by provenance checks')
    a=d['results']['e16_scaled_brier_5'];b=d['results']['question_softworst_tau_001']
    if (a['correct'],a['complete_questions'],b['correct'],b['complete_questions'])!=(20,0,21,2):
        raise ValueError('historical E24 whole-question effect changed')
    keys=sorted(a['by_passage'])
    if len(keys)!=4 or keys!=sorted(b['by_passage']):
        raise ValueError('old four passage groups lost')
    diffs=[]
    for key in keys:
        def question_count(obs):
            return sum(obs['by_question'][f'{key}:{j}'] for j in (0,1))
        diffs.append(question_count(b)-question_count(a))
    if sum(diffs)!=2 or sorted(diffs)!=[0,0,1,1]:
        raise ValueError('E24 old source-group gains changed')
    p=exact_signflip(diffs)
    if p!=F(1,2):raise ValueError('source-cluster E24 p-value must be 1/2')
    return {'schema':'hepta.e26.old-e24-check-v1','authority':'DENY_ALL',
        'historical_E24_human_sha256':h, 'old_source_count':4,
        'old_complete_question_delta':2,'old_two_sided_source_sign_flip_p':str(p),
        'old_result_is_exploratory':True,'old_result_proves_future_gain':False}


def _typed(v,lower,upper):
    return type(v) is int and lower<=v<=upper


def validate_e25_score(receipt):
    """Validate original six-passage score *structure*, not its signer/oracle.

    A self-consistent JSON object cannot establish that a different model
    host actually loaded the pinned weights or that the source signed it.
    The original E25 source/Parquet and seal checks remain mandatory.
    """
    if (type(receipt) is not dict or set(receipt)!={
        'schema','authority','production_accepted','original_validation_source_sha256',
        'human_truth_read_only_after_seal','actual_new_reader_train_anchor_slate_evidence_forwards',
        'original_checkpoint_probe_forwards_additional_not_in_count',
        'original_pretrained_four_readers_newly_fitted','original_passages_in_new_holdout',
        'new_holdout_passages','novel_source_family','prospective_time_window',
        'statistical_superiority_established','tau_chosen_posthoc_on_original_historical_groups',
        'fourfold_ensemble_not_five_scalar_single_head',
        'whole_service_training_inference_energy_and_verifier_cost_established',
        'model_selected','all_source_original_human_labels_are_public_annotations',
        'methods','paired','blind_sha256','independent_reference_recomputed'}):
        raise ValueError('exact new-six scorer schema required')
    if (receipt['schema']!=E25_SCHEMA or receipt['authority']!='DENY_ALL'
        or receipt['production_accepted'] is not False
        or receipt['original_validation_source_sha256']!=SOURCE_SHA
        or receipt['human_truth_read_only_after_seal'] is not True
        or receipt['actual_new_reader_train_anchor_slate_evidence_forwards']!=20
        or receipt['original_checkpoint_probe_forwards_additional_not_in_count'] is not True
        or receipt['original_pretrained_four_readers_newly_fitted'] is not True
        or receipt['original_passages_in_new_holdout']!=0
        or receipt['new_holdout_passages']!=6
        or receipt['novel_source_family'] is not False
        or receipt['prospective_time_window'] is not False
        or receipt['statistical_superiority_established'] is not False
        or receipt['tau_chosen_posthoc_on_original_historical_groups'] is not True
        or receipt['fourfold_ensemble_not_five_scalar_single_head'] is not True
        or receipt['whole_service_training_inference_energy_and_verifier_cost_established'] is not False
        or receipt['model_selected'] is not False
        or receipt['all_source_original_human_labels_are_public_annotations'] is not True
        or receipt['independent_reference_recomputed'] is not True
        or type(receipt['blind_sha256']) is not str or len(receipt['blind_sha256'])!=64
        or any(c not in '0123456789abcdef' for c in receipt['blind_sha256'])
        or type(receipt['methods']) is not dict or set(receipt['methods'])!=set(METHODS)
        or type(receipt['paired']) is not dict or set(receipt['paired'])!=set(METHODS[-2:])):
        raise ValueError('original new-six source or authority inconsistent')
    ms=receipt['methods']; baseline=ms[METHODS[1]]
    groups=None;total=None
    for key,metrics in ms.items():
        if (type(metrics) is not dict or set(metrics)!={
            'correct_candidates','total_candidates','complete_questions','total_questions',
            'complete_passages','total_passages','brier','per_passage_candidate_correct',
            'per_passage_complete_question'}):
            raise ValueError('full original method metric geometry required')
        if (not _typed(metrics['correct_candidates'],0,96)
            or not _typed(metrics['total_candidates'],24,96)
            or metrics['correct_candidates']>metrics['total_candidates']
            or not _typed(metrics['complete_questions'],0,12)
            or metrics['total_questions']!=12 or metrics['total_passages']!=6
            or not _typed(metrics['complete_passages'],0,6)
            or type(metrics['brier']) not in (float,int) or not isfinite(metrics['brier'])
            or not 0<=metrics['brier']<=2
            or type(metrics['per_passage_candidate_correct']) is not dict
            or type(metrics['per_passage_complete_question']) is not dict):
            raise ValueError('incorrect candidate/complete-task denominators')
        a=metrics['per_passage_candidate_correct'];b=metrics['per_passage_complete_question']
        if set(a)!=set(b) or len(a)!=6 or any(type(g) is not str or len(g)!=32 for g in a):
            raise ValueError('changed exact six passage grouping')
        if (any(not _typed(v,0,16) for v in a.values())
            or any(not _typed(v,0,2) for v in b.values())
            or sum(a.values())!=metrics['correct_candidates']
            or sum(b.values())!=metrics['complete_questions']
            or sum(v==2 for v in b.values())!=metrics['complete_passages']):
            raise ValueError('aggregate results differ from exact source groups')
        if groups is None:groups=set(a);total=metrics['total_candidates']
        elif set(a)!=groups or metrics['total_candidates']!=total:
            raise ValueError('source/denominator inconsistent between policy arms')
    for name,matched in receipt['paired'].items():
        ref=ms[name];ctrl=baseline
        if (type(matched) is not dict or set(matched)!={
            'paired_candidate_gain','paired_whole_question_gain','six_cluster_sign_flip_descriptive'}
            or matched['paired_candidate_gain']!=ref['correct_candidates']-ctrl['correct_candidates']
            or matched['paired_whole_question_gain']!=ref['complete_questions']-ctrl['complete_questions']):
            raise ValueError('original matched baseline paired work changed')
        diffs=[ref['per_passage_candidate_correct'][g]-ctrl['per_passage_candidate_correct'][g] for g in sorted(groups)]
        # Original E25 uses an exact permutation on 6 groups; recompute it.
        p=exact_signflip(diffs)
        if matched['six_cluster_sign_flip_descriptive']!=f'{p.numerator}/{p.denominator}' and (
            # Original scorer emits unsimplified raw tail/64.
            matched['six_cluster_sign_flip_descriptive']!=f'{int(p*64)}/64'):
            raise ValueError('incorrect historical descriptive paired sign flip')
    return sorted(groups)


def assess_e25_score(receipt,spec=SPEC):
    d,sha=load_spec(spec);groups=validate_e25_score(receipt)
    a=receipt['methods'][d['primary_control']];b=receipt['methods'][d['primary_method']]
    diffs=[b['per_passage_complete_question'][g]-a['per_passage_complete_question'][g] for g in groups]
    p=exact_signflip(diffs)
    brier_delta=b['brier']-a['brier']
    # Historical E25 Brier reports are FP64; only a fixed 1e-12 source
    # rounding allowance is permitted at the precommitted 0.02 boundary.
    less_brier=(brier_delta<=float(F(d['maximum_allowed_new_human_two_class_brier_degradation']))+1e-12)
    no_harm=all(x>=0 for x in diffs)
    improve=b['complete_questions']>a['complete_questions']
    promising=(p<=F(d['two_sided_exact_passage_sign_flip_alpha'])
               and no_harm and improve and less_brier)
    return {'schema':OUTPUT_SCHEMA,'authority':'DENY_ALL','frozen_hypothesis_sha256':sha,
        'original_e25_human_output_sha256_authenticated_by_independent_issuer':False,
        'unit':'six_original_passage_clusters_two_complete_questions_each',
        'primary_contrast':d['primary_method']+' vs '+d['primary_control'],
        'primary_comparison_count':1,
        'delta_complete_questions_by_passage':diffs,
        'complete_questions_candidate':b['complete_questions'],
        'complete_questions_control':a['complete_questions'],
        'exact_two_sided_six_passage_sign_flip_p':str(p),
        'alpha':d['two_sided_exact_passage_sign_flip_alpha'],
        'brier_delta':brier_delta,'brier_noninferiority_descriptive':less_brier,
        'source_level_no_negative_transfer':no_harm,
        'research_only_followup_signal':promising,
        'future_source_family_generalization_established':False,
        'production_admitted':False,'model_selected':False,
        'whole_service_cost_qualified':False,
        'independent_model_owner_and_label_signer_verified':False,
        'outcome_not_observed_in_this_model_free_precheck':False}


def model_free_precheck():
    hist=original_e24_negative_control()
    six=[1]*6
    if exact_signflip(six)!=F(1,32):raise ValueError('exact six-source floor changed')
    holm_two_floor=min(F(1),2*exact_signflip(six))
    if holm_two_floor!=F(1,16):raise ValueError('two-hypothesis six-source infeasibility changed')
    s,h=load_spec()
    return {'schema':'hepta.e26.outcome-blind-statistical-power-precheck.v1',
        'authority':'DENY_ALL','e25_source_head':s['e25_source_head'],
        'frozen_hypothesis_sha256':h,'old_e24_negative_control':hist,
        'six_passage_two_sided_p_floor':str(exact_signflip(six)),
        'two_primary_hypotheses_Holm_min_adjusted_p':str(holm_two_floor),
        'two_primary_hypotheses_at_alpha_005_infeasible':holm_two_floor>F(1,20),
        'one_primary_comparison_preregistered':True,
        'new_six_passage_model_outcome_observed':False,
        'production_admitted':False}


def write_once(path,value):
    b=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as f:f.write(b)
    return sha256(b).hexdigest()


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('precheck');p.add_argument('--output',required=True)
    p=sub.add_parser('score');p.add_argument('--e25-original-human-score',required=True)
    p.add_argument('--e25-score-sha256',required=True);p.add_argument('--output',required=True)
    args=ap.parse_args()
    if args.mode=='precheck':result=model_free_precheck()
    else:
        raw=Path(args.e25_original_human_score).read_bytes()
        if sha256(raw).hexdigest()!=args.e25_score_sha256:
            raise ValueError('new human-score bytes do not match externally supplied evidence SHA')
        result=assess_e25_score(strict_json(raw))
    print(json.dumps({'sha256':write_once(args.output,result),'authority':'DENY_ALL'}))

if __name__=='__main__':main()
