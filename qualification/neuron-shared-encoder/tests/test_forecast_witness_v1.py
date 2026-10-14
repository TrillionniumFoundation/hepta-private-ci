"""Offline genuine Ed25519 tests: no trusted time or producer identity claim."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from neuron_shared_encoder.forecast_witness_v1 import (
    SCHEMA, canonical_witness_message, verify_forecast_witnesses,
)
from neuron_shared_encoder.prequential_receipts import input_digest
from test_prequential_receipts import fixtures

D = lambda c: c * 64


def specimen():
    rows, base, cand, log = fixtures(n=8)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))  # disposable TEST key
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    forecasts = {}
    for e in log['events']:
        if e['kind'] == 'forecast':
            forecasts.setdefault(e['row_id'], []).append(e)
    receipts = []
    for row in (r for r in rows if r['split'] == 'future'):
        first, second = forecasts[row['row_id']]
        prior_time = datetime.fromisoformat(row['event_time']) - timedelta(minutes=30)
        receipt = {
            'schema': SCHEMA,
            'dataset_sha256': D('a'), 'cell_scope': ['p1', 'o1', 'c1'],
            'row_id': row['row_id'], 'source_group': row['source_group'],
            'input_digest': input_digest(row),
            'generation': 7, 'authority_epoch': 9,
            'first_forecast_seq': first['seq'],
            'first_forecast_digest': first['event_digest'],
            'second_forecast_seq': second['seq'],
            'second_forecast_digest': second['event_digest'],
            'witness_claimed_at': prior_time.isoformat(),
            'public_key_sha256': hashlib.sha256(pub).hexdigest(),
        }
        receipt['signature_ed25519_hex'] = key.sign(canonical_witness_message(receipt)).hex()
        receipts.append(receipt)
    bundle = {'schema': SCHEMA, 'receipts': receipts}
    return rows, base, cand, log, bundle, pub, key


def run(case):
    return verify_forecast_witnesses(case[0], D('a'), *case[1:6])


def test_genuine_signed_forecasts_are_cryptographically_valid_but_not_trusted():
    case = specimen()
    result = run(case)
    assert result['verified_forecast_pairs'] == 8
    assert result['cryptographic_signature_valid_for_supplied_key'] is True
    assert result['independent_key_authority_verified'] is False
    assert result['independent_timestamp_witness_verified'] is False
    assert result['ndu_verified'] is False
    assert result['production_admission'] == 'BLOCKED'


def test_replay_with_wrong_pinned_public_key_rejected():
    case = list(specimen())
    alternate = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    case[5] = alternate
    with pytest.raises(ValueError, match='not bound'):
        run(case)


def test_stale_signature_and_rewritten_signature_fail():
    case = list(specimen())
    case[4]['receipts'][0]['witness_claimed_at'] = (
        datetime.fromisoformat(case[4]['receipts'][0]['witness_claimed_at'])
        + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='signature failed'):
        run(case)
    case = list(specimen())
    case[4]['receipts'][0]['signature_ed25519_hex'] = 'ff' * 64
    with pytest.raises(ValueError, match='signature failed'):
        run(case)


@pytest.mark.parametrize('field,value,error', [
    ('first_forecast_seq', 1000, 'not bound'),
    ('second_forecast_digest', D('f'), 'not bound'),
    ('input_digest', D('f'), 'not bound'),
    ('authority_epoch', 10, 'not bound'),
    ('generation', 8, 'not bound'),
    ('dataset_sha256', D('e'), 'not bound'),
    ('cell_scope', ['somebody-else', 'o1', 'c1'], 'not bound'),
    ('public_key_sha256', D('d'), 'not bound'),
    ('witness_claimed_at', 'not-a-time', 'signed witness time'),
    ('signature_ed25519_hex', '0', 'invalid bounded'),
])
def test_reject_forged_rewritten_or_malformed_receipts(field, value, error):
    case = list(specimen())
    case[4]['receipts'][0][field] = value
    with pytest.raises(ValueError, match=error):
        run(case)


def test_fake_inband_authority_flag_rejected_even_with_valid_signature():
    case = list(specimen())
    first = case[4]['receipts'][0]
    first['independent_timestamp_witness_verified'] = True
    first['signature_ed25519_hex'] = case[6].sign(canonical_witness_message({
        k: v for k, v in first.items() if k != 'signature_ed25519_hex'
    })).hex()
    with pytest.raises(ValueError, match='only exact supported fields'):
        run(case)


def test_duplicate_missing_and_cross_row_witnesses_rejected():
    case = list(specimen())
    case[4]['receipts'][1] = deepcopy(case[4]['receipts'][0])
    with pytest.raises(ValueError, match='duplicate witness'):
        run(case)
    case = list(specimen())
    case[4]['receipts'].pop()
    with pytest.raises(ValueError, match='exactly one'):
        run(case)
    case = list(specimen())
    case[4]['receipts'][0]['row_id'] = 'foreign-future'
    with pytest.raises(ValueError, match='unexpected or duplicate'):
        run(case)


def test_perfectly_signed_backdated_claim_does_not_grant_trust():
    # A holder of a testing signing key can backdate every claim, re-sign it,
    # and obtain a cryptographically VALID signature. Clock remains untrusted.
    case = list(specimen())
    for receipt in case[4]['receipts']:
        receipt['signature_ed25519_hex'] = case[6].sign(canonical_witness_message({
            k: v for k, v in receipt.items() if k != 'signature_ed25519_hex'
        })).hex()
    result = run(case)
    assert result['cryptographic_signature_valid_for_supplied_key']
    assert not result['prediction_before_label_independently_verified']
    assert result['status'] == 'SIGNATURES_VALID_CLOCK_AND_ISSUER_UNVERIFIED'


def test_different_chain_fork_cannot_reuse_forecast_witness():
    case = list(specimen())
    # The attacker can rewrite chain and snapshots while retaining the old
    # detached witness. Signature binds the old two event digests, so fails.
    case[3]['events'][0]['self_proclaimed_verified'] = True
    from test_prequential_receipts import resign
    resign(case[3])
    with pytest.raises(ValueError, match='not bound'):
        run(case)


def test_unsigned_witness_payload_refuses_embedded_signature_and_bad_json():
    with pytest.raises(ValueError, match='exclude signature'):
        canonical_witness_message({'signature_ed25519_hex': 'abc'})
    with pytest.raises(ValueError, match='canonical JSON'):
        canonical_witness_message({'bad': float('nan')})


def test_witness_does_not_bypass_full_prequential_chain_validation():
    case = list(specimen())
    case[3]['events'][0]['input_digest'] = D('f')
    with pytest.raises(ValueError, match='event digest/chain'):
        run(case)


def test_e4_integration_has_real_crypto_probe_but_no_release_authority():
    from neuron_shared_encoder.validation_v3 import evaluate_shadow
    rows, baseline, candidate, event_log, bundle, pub, _key = specimen()
    report = evaluate_shadow(rows, D('a'), baseline, candidate,
                             bootstrap_repeats=100,
                             prequential_event_log=event_log,
                             detached_forecast_witnesses=bundle,
                             detached_witness_public_key=pub)
    signed = report['detached_forecast_witness_probe']
    assert signed['status'] == 'SIGNATURES_VALID_CLOCK_AND_ISSUER_UNVERIFIED'
    assert signed['verified_forecast_pairs'] == 8
    assert signed['independent_key_authority_verified'] is False
    assert report['selection'] == 'NOT_AUTHORIZED'
    assert report['ndu_receipt_verified'] is False
    assert report['causal_learning_verified'] is False
    assert report['production_admission'] == 'BLOCKED'


def test_e4_refuses_detached_signature_without_pinned_chain_or_public_key():
    from neuron_shared_encoder.validation_v3 import evaluate_shadow
    rows, baseline, candidate, log, witnesses, pub, _key = specimen()
    with pytest.raises(ValueError, match='supplied together'):
        evaluate_shadow(rows, D('a'), baseline, candidate, bootstrap_repeats=100,
                        prequential_event_log=log, detached_forecast_witnesses=witnesses)
    with pytest.raises(ValueError, match='require a pinned prequential event log'):
        evaluate_shadow(rows, D('a'), baseline, candidate, bootstrap_repeats=100,
                        detached_forecast_witnesses=witnesses,
                        detached_witness_public_key=pub)


def test_e4_cli_exposes_separate_witness_artifact_and_pinned_public_key_args():
    from neuron_shared_encoder.validation_v3 import _parser
    options = _parser().parse_args([
        'e4-future', '--output', 'shadow.json',
        '--prequential-event-log', 'events.json', '--prequential-event-log-sha256', D('e'),
        '--detached-witnesses', 'witnesses.json', '--detached-witnesses-sha256', D('f'),
        '--detached-witness-public-key', 'witness.pub',
        '--detached-witness-public-key-sha256', D('c'),
    ])
    assert options.detached_witnesses == 'witnesses.json'
    assert options.detached_witness_public_key == 'witness.pub'
    assert options.detached_witness_public_key_sha256 == D('c')
