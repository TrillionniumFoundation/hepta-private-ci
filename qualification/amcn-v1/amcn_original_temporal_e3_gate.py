"""Independent stdlib-only E3 archival retrospective NO-GO qualification gate.

Consumes only a sanitized, previously sealed aggregate, never original model
weights, publisher question labels, independent user authority, or Reader gold.
Every refusal preserves the original scientific negative evidence.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path

SCHEMA='hepta.amcn.original-chronological-graph-e3-negative-v1'
ARMS=('bm25','temporal_fixed','temporal_learned','temporal_edge_lesion')
EXPECTED={'bm25':(174,149),'temporal_fixed':(177,152),
          'temporal_learned':(171,145),'temporal_edge_lesion':(171,145)}
ORIGINAL_CORPUS='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'


def require(cond,msg):
    if not cond:raise ValueError(msg)


def negative_original_verdict(source):
    require(isinstance(source,dict) and source.get('schema')==SCHEMA and
            source.get('source_corpus_sha256')==ORIGINAL_CORPUS,
            'unregistered original E3 source or result schema')
    require(source.get('400_retrospective_original_questions')==400 and
            source.get('two_correlated_historical_roots')==['conv-49','conv-50'],
            'heldout original root/question census drift')
    required_false=['automatic_cell_fission_and_model_promotion_authorized',
        'full_reader_task_semantic_success_independently_verified',
        'graph_learning_task_superiority_proven','original_200_independent_source_groups',
        'original_hf_tokenizer_and_operator_parity_confirmed',
        'source_relationships_causal_truth_confirmed',
        'strong_hybrid_rag_equal_total_compute_compared',
        'real_source_revocation_and_retention_benefit_proven',
        'production_accepted']
    require(all(source.get(k) is False for k in required_false) and
            source.get('real_future_calendar_windows')==0,
            'false model, network, future or issuer qualification')
    work=source.get('train_relation_scientific_details')
    require(isinstance(work,dict) and work.get('training_examples')==3505 and
            work.get('train_positive')==701 and work.get('train_negative')==2804 and
            work.get('steps')==96 and work.get('parameters')==6 and
            work.get('training_families')==['conv-26','conv-30','conv-41','conv-42','conv-43','conv-44'] and
            work.get('calibrated_against_independent_scalar_sgd') is True and
            work.get('relation_truth_independently_authenticated') is False and
            source.get('repeated_physical_coefficients_bitwise_equal') is True,
            'no original CPU physical TRAIN-only relation coefficients')
    params=work.get('weights')
    require(isinstance(params,dict) and set(params)=={'supports','temporal',
            'causal_candidate','procedural','associative','contradicts'} and
            all(type(x) is float and isfinite(x) for x in params.values()) and
            abs(params['temporal']+0.7992032766342163)<2e-5 and
            abs(params['associative']+0.9171789884567261)<2e-5 and
            all(params[k]==0 for k in ('supports','causal_candidate','procedural','contradicts')),
            'changed physical trained graph original numbers')
    weak=source.get('within_experiment_retrieval_weak_support')
    require(isinstance(weak,dict) and set(weak)==set(ARMS),
            'incomplete four original E3 retrieval arms')
    for arm in ARMS:
        d=weak[arm]
        require(isinstance(d,dict) and d.get('questions')==400 and
                (d.get('hit3'),d.get('all3'))==EXPECTED[arm],
                'altered weak retrieval E3 arm/census')
    reader=source.get('reader_diagnostic_weak_and_literal')
    require(isinstance(reader,dict) and set(reader)==set(ARMS) and
            source.get('original_reader_attempts_sealed')==24 and
            source.get('original_reader_failures')==0 and
            source.get('paired_equal_natural_four_arm_reader_input_cases')==5 and
            source.get('cases_chosen_after_observing_graph_route_difference_not_publisher_labels') is True,
            'missing or biased original full Reader diagnoses')
    original_tokens={'bm25':(1139,94),'temporal_fixed':(1139,94),
                     'temporal_learned':(1122,96),'temporal_edge_lesion':(1139,94)}
    for arm in ARMS:
        d=reader[arm]
        require(d.get('attempts')==d.get('success')==6 and
                d.get('weak_any3')==4 and d.get('weak_all3')==3 and
                d.get('strict_literal')==0 and
                (d.get('input_tokens'),d.get('generated_tokens'))==original_tokens[arm],
                'original Reader failure, output, prompt or token budget concealed')
    diffs=source.get('reader_raw_answer_differences')
    require(isinstance(diffs,dict) and
            diffs.get('learned_vs_fixed_different_raw_answer')==3 and
            diffs.get('lesion_vs_learned_different_raw_answer')==5,
            'source graph intervention did not reproduce original text differences')
    return {
        'profile':'hepta.amcn.original-E3-research-qualification-denial.v1',
        'original_retrospective_questions':400,
        'original_reader_attempts':24,
        'original_historical_correlated_roots':2,
        'fixed_graph_minus_bm25_weak_hit3_proxy':3,
        'learned_graph_minus_fixed_weak_hit3_proxy':-6,
        'lesioned_graph_minus_learned_weak_hit3_proxy':0,
        'reader_independent_semantic_success':None,
        'relation_edges_proven_causal':False,
        'valid_equal_total_compute_comparison':False,
        'future_windows':0,
        'graph_learning_task_superiority_proven':False,
        'automatic_cell_fission_fusion_eligible':False,
        'production_accepted':False}


def main():
    cli=argparse.ArgumentParser();cli.add_argument('sanitized_original')
    cli.add_argument('output')
    args=cli.parse_args()
    dst=Path(args.output)
    require(not dst.exists() and not dst.is_symlink(),'immutable negative receipt create-only')
    verdict=negative_original_verdict(json.loads(Path(args.sanitized_original).read_bytes()))
    dst.parent.mkdir(parents=True,exist_ok=True)
    with dst.open('x') as f:json.dump(verdict,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(verdict,sort_keys=True))

if __name__=='__main__':main()
