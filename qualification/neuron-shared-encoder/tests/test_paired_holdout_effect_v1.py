"""Source-group and repeated-seed guarded descriptive quality evidence."""
from __future__ import annotations

from copy import deepcopy

import pytest

from neuron_shared_encoder.paired_holdout_effect_v1 import paired_original_case_effect_v1


def panel(seeds=(11, 23, 47)):
    records = []
    for seed in seeds:
        for cell in (0, 1):
            for case in range(16):
                gold = case % 4
                # Pooled wrongly selects the next class on 8 of 16 cases;
                # Query corrects four of those, loses two earlier successes.
                pooled_answer = (gold + 1) % 4 if case % 2 == 0 else gold
                query_answer = (gold if case % 4 == 0 else (gold + 1) % 4
                                if case % 8 == 1 else pooled_answer)
                pooled = [-1.0] * 4
                pooled[pooled_answer] = 2.0 + (seed % 3) * 0.01
                queried = [-1.0] * 4
                queried[query_answer] = 2.0 + (seed % 3) * 0.01
                records.append({'seed': seed, 'cell': cell,
                                'case_id': f'original-case-{cell}-{case}',
                                'source_group': f'original-group-{cell}-{case}',
                                'label': gold, 'pooled_logits': pooled,
                                'token_logits': queried})
    return records


def test_actual_original_case_panel_not_case_seed_panel():
    r = paired_original_case_effect_v1(panel(), repeats=1000, bootstrap_seed=19)
    assert r['schema'] == 'hepta.neuron.paired-original-case-retrospective.v1'
    assert r['original_holdout_cases'] == 32
    assert r['number_of_actual_case_seed_comparisons'] == 96
    assert r['repeated_train_seeds'] == [11, 23, 47]
    assert r['three_training_seeds_are_not_independent_cases']
    assert not r['case_source_independence_verified']
    assert not r['prospective_future_outcome_verified']
    assert not r['independent_signed_NDU_verified']
    assert not r['model_winner_selected'] and not r['selection_authorized']
    assert r['production_admission'] == 'BLOCKED'
    assert set(r['paired_token_minus_pooled']) == {'accuracy', 'brier', 'nll'}
    for item in r['paired_token_minus_pooled'].values():
        assert len(item['original_case_stratified_bootstrap_95_descriptive']) == 2
    assert len(r['per_cell']) == 2 and all(x['original_cases'] == 16 for x in r['per_cell'])
    # The report contains no case IDs, raw logits, original text or token IDs.
    assert 'original-case-0-0' not in str(r)


def test_order_independence_and_deterministic_case_resampling():
    rows = panel()
    a = paired_original_case_effect_v1(rows, repeats=1000, bootstrap_seed=42)
    b = paired_original_case_effect_v1(list(reversed(rows)), repeats=1000,
                                       bootstrap_seed=42)
    assert a == b
    assert a == paired_original_case_effect_v1(rows, repeats=1000,
                                                bootstrap_seed=42)


def test_seed_repetitions_do_not_expand_bootstrap_sampling_unit():
    a = paired_original_case_effect_v1(panel(seeds=(11,)), repeats=1000)
    b = paired_original_case_effect_v1(panel(seeds=(11, 23, 47)), repeats=1000)
    assert a['original_holdout_cases'] == b['original_holdout_cases'] == 32
    assert a['number_of_actual_case_seed_comparisons'] == 32
    assert b['number_of_actual_case_seed_comparisons'] == 96
    assert a['model_winner_selected'] is False
    assert b['model_winner_selected'] is False


@pytest.mark.parametrize('error, match', [
    ('duplicate', 'bounded matched|duplicate case x training seed'),
    ('missing_case', 'bounded matched original-case observation panel|incomplete 32-case'),
    ('missing_seed', 'incomplete 32-case matched'),
    ('swapped_cell', 'reused source group|incomplete 32-case'),
    ('changed_group', 'case group or label changed'),
    ('changed_label', 'case group or label changed'),
    ('reused_group', 'reused source group'),
    ('invented_future_time', 'complete fixed-schema'),
    ('nonfinite', 'four finite'),
    ('wrong_classes', 'four finite'),
    ('boolean_label', 'invalid independent case'),
    ('boolean_seed', 'invalid independent case'),
    ('bad_seed', 'invalid independent case'),
    ('case_text_included', 'complete fixed-schema'),
    ('duplicate_seed_only', 'duplicate case x training seed'),
])
def test_forged_or_incomplete_panel_denied(error, match):
    rows = deepcopy(panel())
    if error == 'duplicate': rows.append(deepcopy(rows[0]))
    if error == 'missing_case': rows = [r for r in rows if r['case_id'] != 'original-case-0-0']
    if error == 'missing_seed': rows.pop()
    if error == 'swapped_cell': rows[0]['cell'] = 1
    if error == 'changed_group': rows[0]['source_group'] = 'other-group'
    if error == 'changed_label': rows[0]['label'] = (rows[0]['label'] + 1) % 4
    if error == 'reused_group': rows[0]['source_group'] = rows[1]['source_group']
    if error == 'invented_future_time': rows[0]['observed_at'] = '2026-10-14T00:00:00Z'
    if error == 'nonfinite': rows[0]['pooled_logits'][0] = float('nan')
    if error == 'wrong_classes': rows[0]['token_logits'].append(0.1)
    if error == 'boolean_label': rows[0]['label'] = False
    if error == 'boolean_seed': rows[0]['seed'] = True
    if error == 'bad_seed': rows[0]['seed'] = -1
    if error == 'case_text_included': rows[0]['text'] = 'secret original text'
    if error == 'duplicate_seed_only': rows[0] = deepcopy(rows[1])
    with pytest.raises(ValueError, match=match):
        paired_original_case_effect_v1(rows, repeats=1000)


def test_bounded_resampling_controls():
    rows = panel()
    for value in (0, 999, 5001, True, 1000.5):
        with pytest.raises(ValueError, match='bounded matched'):
            paired_original_case_effect_v1(rows, repeats=value)
    for value in (True, -1, 2**32, 0.5):
        with pytest.raises(ValueError, match='bounded matched'):
            paired_original_case_effect_v1(rows, repeats=1000,
                                           bootstrap_seed=value)


def test_signs_hold_for_completely_correct_query():
    records = panel()
    for row in records:
        answer = row['label']
        row['pooled_logits'] = [4.0 if i == (answer + 1) % 4 else -4.0
                                for i in range(4)]
        row['token_logits'] = [4.0 if i == answer else -4.0
                               for i in range(4)]
    report = paired_original_case_effect_v1(records, repeats=1000)
    delta = report['paired_token_minus_pooled']
    assert delta['accuracy']['point_estimate'] == 1
    assert delta['brier']['point_estimate'] < 0
    assert delta['nll']['point_estimate'] < 0
    assert not report['model_winner_selected']  # Even a strong retrospective pattern cannot promote.


def test_actual_independent_numpy_reviewer_attaches_same_case_panel(tmp_path):
    from neuron_shared_encoder.physical_token_reviewer_v1 import audit_sealed_token_pair
    from test_physical_token_reviewer_v1 import prepared

    replay = audit_sealed_token_pair(**prepared(tmp_path))
    assert replay['independent_numeric_replay_all_metrics_passed'] is True
    paired = replay['paired_original_case_descriptive_effect']
    assert paired['original_holdout_cases'] == 32
    assert paired['repeated_train_seeds'] == [11, 23]
    assert paired['number_of_actual_case_seed_comparisons'] == 64
    assert not paired['model_winner_selected']
    assert not paired['independent_signed_NDU_verified']
    assert paired['production_admission'] == 'BLOCKED'
