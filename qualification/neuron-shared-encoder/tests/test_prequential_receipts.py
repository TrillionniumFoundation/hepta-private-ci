"""Adversarial E4 event-chain tests; a passing chain is never release evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from neuron_shared_encoder.prequential_receipts import (
    GENESIS, event_digest, input_digest, prequential_chain_audit,
)

D = lambda c: c * 64


def fixtures(n=8):
    rows = []
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for split, offset in [('train', 0), ('validation', 30), ('future', 60), ('ood', 90)]:
        for i in range(n):
            at = origin + timedelta(days=offset + i)
            rows.append({'row_id': f'{split}-{i}', 'source_group': f'{split}-{i}',
                         'event_time': at.isoformat(), 'split': split, 'principal': 'p1',
                         'organ_id': 'o1', 'cell_id': 'c1', 'question': 'Which?',
                         'state': {'source': f'episode-{split}-{i}'},
                         'options': ['no', 'yes'], 'label': i % 2})
    common = {'dataset_sha256': D('a'), 'cell_scope': ['p1', 'o1', 'c1'],
              'row_ids': [r['row_id'] for r in rows], 'source_commit': D('f')}
    def probs(strength):
        return [[strength, 1-strength] if r['label'] == 0 else [1-strength, strength]
                for r in rows]
    baseline = {**common, 'role': 'frozen_no_change', 'artifact_digest': D('b'),
                'probabilities': probs(.6)}
    candidate = {**common, 'role': 'candidate', 'artifact_digest': D('c'),
                 'probabilities': probs(.8)}
    events = []
    for index, row in enumerate(rows):
        if row['split'] != 'future':
            continue
        row_at = datetime.fromisoformat(row['event_time'])
        for role, model in [('frozen_no_change', baseline), ('candidate', candidate)]:
            events.append({'kind': 'forecast', 'row_id': row['row_id'], 'role': role,
                           'source_group': row['source_group'], 'input_digest': input_digest(row),
                           'artifact_digest': model['artifact_digest'],
                           'probabilities': model['probabilities'][index],
                           'recorded_at': (row_at - timedelta(hours=1)).isoformat()})
        events.append({'kind': 'outcome', 'row_id': row['row_id'],
                       'source_group': row['source_group'], 'input_digest': input_digest(row),
                       'label': row['label'],
                       'recorded_at': (row_at + timedelta(hours=1)).isoformat()})
    log = {'dataset_sha256': D('a'), 'cell_scope': common['cell_scope'], 'events': events}
    resign(log)
    return rows, baseline, candidate, log


def resign(log):
    prev = GENESIS
    for i, event in enumerate(log['events']):
        event.pop('event_digest', None)
        event.update({'seq': i, 'previous_digest': prev,
                      'dataset_sha256': log['dataset_sha256'],
                      'cell_scope': log['cell_scope'],
                      'generation': 7, 'authority_epoch': 9})
        event['event_digest'] = event_digest(event)
        prev = event['event_digest']


def run(rows, baseline, candidate, log):
    return prequential_chain_audit(rows, D('a'), baseline, candidate, log)


def test_complete_chain_is_only_unverified_consistency():
    receipt = run(*fixtures())
    assert receipt['status'] == 'HASH_CHAIN_CONSISTENT_UNVERIFIED'
    assert receipt['events_checked'] == 24
    assert receipt['future_rows_checked'] == 8
    assert receipt['independent_timestamp_witness_verified'] is False
    assert receipt['causal_learning_verified'] is False
    assert receipt['ndu_verified'] is False
    assert receipt['production_admission'] == 'BLOCKED'


def test_bit_tamper_detected():
    args = list(fixtures())
    args[3]['events'][0]['probabilities'] = [.99, .01]
    with pytest.raises(ValueError, match='digest/chain'):
        run(*args)


def test_recomputed_chain_cannot_change_model_predictions():
    args = list(fixtures())
    args[3]['events'][0]['probabilities'] = [.7, .3]
    resign(args[3])
    with pytest.raises(ValueError, match='forecast probabilities'):
        run(*args)


def test_recomputed_chain_rejects_after_event_predictions():
    args = list(fixtures())
    predicted = datetime.fromisoformat(args[0][16]['event_time'])
    args[3]['events'][0]['recorded_at'] = (predicted + timedelta(minutes=1)).isoformat()
    resign(args[3])
    with pytest.raises(ValueError, match='not earlier than future'):
        run(*args)


def test_recomputed_chain_rejects_outcome_before_predictions():
    args = list(fixtures())
    args[3]['events'][0], args[3]['events'][2] = args[3]['events'][2], args[3]['events'][0]
    resign(args[3])
    with pytest.raises(ValueError, match='outcome before'):
        run(*args)


def test_recomputed_chain_rejects_cross_generation_and_epoch():
    args = list(fixtures())
    resign(args[3])
    for i, e in enumerate(args[3]['events']):
        e.pop('event_digest', None)
        e['authority_epoch'] = 10 if i == 1 else 9
    prev = GENESIS
    for i, event in enumerate(args[3]['events']):
        event['previous_digest'] = prev
        event['event_digest'] = event_digest(event)
        prev = event['event_digest']
    with pytest.raises(ValueError, match='mixed generation'):
        run(*args)


def test_recomputed_chain_rejects_wrong_label():
    args = list(fixtures())
    args[3]['events'][2]['label'] ^= 1
    resign(args[3])
    with pytest.raises(ValueError, match='outcome label'):
        run(*args)


def test_missing_forecast_and_double_outcome_fail():
    args = list(fixtures())
    args[3]['events'].pop(1)
    resign(args[3])
    with pytest.raises(ValueError, match='exactly two forecasts'):
        run(*args)
    args = list(fixtures())
    args[3]['events'][1] = deepcopy(args[3]['events'][2])
    resign(args[3])
    with pytest.raises(ValueError, match='outcome before'):
        run(*args)


def test_scope_and_dataset_mismatch_rejected():
    args = list(fixtures())
    args[3]['cell_scope'][0] = 'p2'
    with pytest.raises(ValueError, match='Cell scope mismatch'):
        run(*args)
    args = list(fixtures())
    args[3]['dataset_sha256'] = D('d')
    with pytest.raises(ValueError, match='dataset identity mismatch'):
        run(*args)


def test_even_perfect_self_signed_log_does_not_verify_witness():
    args = list(fixtures())
    # An attacker can freely rewrite *all* times and recompute chain digests.
    # Even with consistency intact, the result is NOT proof of causal order.
    for event in args[3]['events']:
        event['self_proclaimed_verified'] = True
    resign(args[3])
    audit = run(*args)
    assert audit['producer_signature_verified'] is False
    assert audit['prediction_before_label_independently_verified'] is False
    assert audit['production_admission'] == 'BLOCKED'


def test_chain_is_included_but_never_authorizes_e4_shadow():
    from neuron_shared_encoder.validation_v3 import evaluate_shadow
    rows, baseline, candidate, log = fixtures()
    report = evaluate_shadow(rows, D('a'), baseline, candidate,
                             bootstrap_repeats=100, prequential_event_log=log)
    assert report['prequential_event_chain_audit']['events_checked'] == 24
    assert report['prequential_event_chain_audit']['production_admission'] == 'BLOCKED'
    assert report['selection'] == 'NOT_AUTHORIZED'
    assert report['ndu_receipt_verified'] is False
    assert report['causal_learning_verified'] is False
    no_event_log = evaluate_shadow(rows, D('a'), baseline, candidate, bootstrap_repeats=100)
    assert no_event_log['prequential_event_chain_audit']['status'] == 'NOT_PROVIDED'


def test_integrated_e4_rejects_mutated_validly_rehashed_forecast():
    from neuron_shared_encoder.validation_v3 import evaluate_shadow
    rows, baseline, candidate, log = fixtures()
    log['events'][0]['probabilities'] = [.9, .1]
    resign(log)
    with pytest.raises(ValueError, match='forecast probabilities'):
        evaluate_shadow(rows, D('a'), baseline, candidate,
                        bootstrap_repeats=100, prequential_event_log=log)

def test_input_identity_cannot_be_rebound_by_rehashing_chain():
    args = list(fixtures())
    args[3]['events'][0]['input_digest'] = D('e')
    resign(args[3])
    with pytest.raises(ValueError, match='source and admitted input'):
        run(*args)
    args = list(fixtures())
    args[3]['events'][0]['source_group'] = 'other-source'
    resign(args[3])
    with pytest.raises(ValueError, match='source and admitted input'):
        run(*args)


def test_monotonic_append_order_rejects_backdated_sealed_chain():
    args = list(fixtures())
    first = datetime.fromisoformat(args[3]['events'][0]['recorded_at'])
    args[3]['events'][1]['recorded_at'] = (first - timedelta(seconds=1)).isoformat()
    resign(args[3])
    with pytest.raises(ValueError, match='clock moved backwards'):
        run(*args)
