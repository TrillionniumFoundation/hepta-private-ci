"""Independent stdlib-only negative admission gate for the 14 original E2 cases.

This consumes aggregate source-only published research facts, not model
weights or publisher labels. It NEVER grants promotion or FinalUse.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ARMS=('bm25','untyped_equal_budget','typed_equal_budget')
PROFILE='hepta.amcn.original-two-family-14-typed-untyped-physical-reader.shadow.v1.postseal-publisher-weak-diagnostic.v1'


def assess(r):
    if r.get('schema') != PROFILE or type(r.get('original_question_count')) is not int or r['original_question_count'] != 14:
        raise ValueError('unregistered original E2 research receipt')
    if (r.get('original_reader_calls') != 42 or
        r.get('original_reader_failed_attempts_preserved') != 0 or
        r.get('source_replacement_questions') != 10 or
        r.get('evidence_order_only_questions') != 4 or
        r.get('independent_original_source_family_roots') != 2 or
        r.get('type_different_raw_text_question_count') != 11):
        raise ValueError('original complete answer/difference census drift')
    totals = r.get('arm_totals')
    if not isinstance(totals,dict) or set(totals)!=set(ARMS):
        raise ValueError('missing original equal-Head controls')
    for arm in ARMS:
        a = totals[arm]
        if not isinstance(a,dict) or any(type(a.get(k)) is not int for k in
              ('questions','weak_any_at3','weak_all_at3','strict_literal_answer_match',
               'input_tokens','output_tokens','ordinary_questions','adversarial_questions')):
            raise ValueError('invalid numeric original result')
        if (a['questions']!=14 or a['ordinary_questions']!=12 or
            a['adversarial_questions']!=2 or
            not 0<=a['weak_all_at3']<=a['weak_any_at3']<=14 or
            not 0<=a['strict_literal_answer_match']<=14 or
            not 14<=a['output_tokens']<=448):
            raise ValueError('changed original complete-result denominator')
    expected={
        'bm25':(5,5,0,3464,340),
        'untyped_equal_budget':(7,7,0,3424,281),
        'typed_equal_budget':(7,7,0,3341,321),
    }
    for arm, (hit, all_hit, exact, input_tokens, output_tokens) in expected.items():
        a=totals[arm]
        if (a['weak_any_at3'],a['weak_all_at3'],a['strict_literal_answer_match'],
            a['input_tokens'],a['output_tokens'])!=(hit,all_hit,exact,input_tokens,output_tokens):
            raise ValueError('original experimentally observed counts changed')
    fields_false=('production_accepted','type_specialization_whole_task_qualified',
                  'learned_graph_vs_fixed_graph_whole_task_qualified',
                  'independent_semantic_entailment_verified','official_hf_parity_verified',
                  'equal_total_cost_including_encoder_and_training',
                  'selection_cohort_representative_of_400_questions',
                  'identical_observed_input_tokens')
    fields_true=('matched_final_evidence_slots',
                 'same_reader_weights_tokenizer_prompt_template',
                 'same_max_generation_tokens')
    if any(r.get(k) is not False for k in fields_false) or any(r.get(k) is not True for k in fields_true):
        raise ValueError('illicit or unverified source/model/task authority')
    if r.get('independent_future_calendar_windows')!=0:
        raise ValueError('invented original future windows')
    fam=r.get('per_family'); kind=r.get('per_divergence_kind')
    if not isinstance(fam,dict) or set(fam)!={'conv-49','conv-50'} or not isinstance(kind,dict) or set(kind)!={'source_replacement','order_only'}:
        raise ValueError('historical family/type strata missing')
    for grouping, sizes in ((fam,{'conv-49':6,'conv-50':8}),
                            (kind,{'source_replacement':10,'order_only':4})):
        for group, arms in grouping.items():
            if set(arms)!=set(ARMS):
                raise ValueError('missing original group arm')
            for arm in ARMS:
                if arms[arm].get('questions')!=sizes[group]:
                    raise ValueError('missing original group questions')
        for arm in ARMS:
            for measure in ('questions','weak_any_at3','weak_all_at3',
                            'strict_literal_answer_match','input_tokens','output_tokens'):
                if sum(v[arm].get(measure,-10**12) for v in grouping.values())!=totals[arm][measure]:
                    raise ValueError('original group sum differs from complete total')
    changes=r.get('paired_weak_support_flips_vs_bm25')
    if not isinstance(changes,dict) or set(changes)!=set(ARMS):
        raise ValueError('missing original paired weakness/strongness counts')
    for arm in ARMS:
        flips=changes[arm]
        require_new=0 if arm=='bm25' else 2
        if flips.get('new_weak_hit_vs_bm25')!=require_new or flips.get('lost_weak_hit_vs_bm25')!=0:
            raise ValueError('original weak-support paired flips changed')
    return {'profile':'hepta.amcn.original-e2-type14-independent-no-go.v1',
            'actual_reader_model_calls':42,'source_changing_original_cases':10,
            'typed_untyped_output_text_changed_cases':11,
            'bm25_hit3':5,'untyped_hit3':7,'typed_hit3':7,
            'independent_source_roots':2,'natural_equal_input_tokens':False,
            'typed_specific_task_superiority_verified':False,
            'full_task_semantic_utility_verified':False,
            'production_accepted':False,'automatic_cell_fission_or_promotion_eligible':False}


def main():
    a=argparse.ArgumentParser();a.add_argument('aggregate',type=Path);a.add_argument('--output',type=Path)
    cli=a.parse_args()
    data=json.loads(cli.aggregate.read_text())
    verdict=assess(data)
    if cli.output:
        if cli.output.exists() or cli.output.is_symlink():raise ValueError('create-only negative research receipt')
        cli.output.write_text(json.dumps(verdict,sort_keys=True,indent=2)+'\n')
    print(json.dumps(verdict,sort_keys=True))

if __name__=='__main__':main()
