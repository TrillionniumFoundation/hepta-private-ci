"""Synthetic context/chronology controls; not training or independent operations."""
import copy
import hashlib
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import model_consumer_context as context


def identity(label):
    return hashlib.sha256(label.encode()).hexdigest()


def verify_test_signature(public, signature, message):
    # Unit-test primitive only. The public production entry uses the existing
    # strict_signature verifier through model_window_history, never this helper.
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
    except InvalidSignature as failure:
        raise ValueError('invalid test signature') from failure


def sign_contexts(rows, generations, attestations):
    values = []
    for i, (row, generation) in enumerate(zip(rows, generations), 1):
        statement = dict(schema=context.SCHEMA, ordinal=i, window=generation['window'],
                         run_plan=row['window']['run_plan'], assessment=row['receipt'],
                         receipt=generation['consumer_receipt'])
        message = context.context_signing_message(statement)
        values.append(dict(statement=statement,
            consumer_signature=Ed25519PrivateKey.from_private_bytes(bytes([10 + i]) * 32).sign(message).hex(),
            controller_signature=Ed25519PrivateKey.from_private_bytes(bytes([20 + i]) * 32).sign(message).hex()))
    return values


class ConsumerContextTests(unittest.TestCase):
    """Exercise additional relation and actual Ed25519 without claiming full V2 execution."""
    def setUp(self):
        self.rows = []
        self.generations = []
        self.receipts = []
        self.attestations = []
        for i in range(1, 4):
            self.rows.append(dict(window=dict(run_plan=identity('plan' + str(i))),
                                  receipt=identity('assessment' + str(i)), registered_at=100*i))
            self.generations.append(dict(window=identity('window' + str(i)),
                                          consumer_receipt=identity('receipt' + str(i))))
            self.receipts.append(dict(used_at=100*i+20))
            attestation = {}
            for role, offset in [('consumer', 10), ('controller', 20)]:
                key = Ed25519PrivateKey.from_private_bytes(bytes([offset+i])*32)
                attestation[role+'_public_key'] = key.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex()
            self.attestations.append(attestation)
        self.contexts = sign_contexts(self.rows, self.generations, self.attestations)

    def verify(self):
        return context._verify_context_rows(self.rows, self.generations, self.receipts,
            self.attestations, self.contexts, verify_test_signature)

    def test_actual_six_signatures_and_three_contexts(self):
        self.assertEqual(len(self.verify()), 3)

    def test_message_is_canonical_and_domain_separated(self):
        statement = self.contexts[0]['statement']
        reverse = dict(reversed(list(statement.items())))
        self.assertEqual(context.context_signing_message(statement), context.context_signing_message(reverse))
        import json
        raw = json.dumps(statement, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
        self.assertEqual(context.context_signing_message(statement),
                         hashlib.sha256(context.DOMAIN + len(raw).to_bytes(4, 'little') + raw).digest())
        self.assertNotEqual(context.context_signing_message(statement), hashlib.sha256(raw).digest())

    def test_changed_expected_window_and_rehashed_statement_need_new_signatures(self):
        self.generations[0]['window'] = identity('replacement-window')
        self.contexts[0]['statement']['window'] = self.generations[0]['window']
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CONSUMER_SIGNATURE'):
            self.verify()

    def test_changed_plan_assessment_and_receipt_each_need_new_signatures(self):
        for field in ('run_plan', 'assessment', 'receipt'):
            with self.subTest(field=field):
                self.setUp()
                changed = identity('replacement-' + field)
                self.contexts[0]['statement'][field] = changed
                if field == 'run_plan':
                    self.rows[0]['window']['run_plan'] = changed
                elif field == 'assessment':
                    self.rows[0]['receipt'] = changed
                else:
                    self.generations[0]['consumer_receipt'] = changed
                with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CONSUMER_SIGNATURE'):
                    self.verify()

    def test_unmodified_signature_cannot_bind_a_changed_expected_context(self):
        self.generations[0]['window'] = identity('other-window')
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_BINDING'):
            self.verify()

    def test_both_keys_are_required_and_last_failure_emits_no_partial_result(self):
        saved = copy.deepcopy((self.rows, self.generations, self.receipts, self.attestations))
        self.contexts[2]['controller_signature'] = '00'*64
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CONTROLLER_SIGNATURE'):
            self.verify()
        self.assertEqual(saved, (self.rows, self.generations, self.receipts, self.attestations))

    def test_later_use_cannot_explain_an_already_registered_successor(self):
        for offset in (0, 1, 1000):
            self.receipts[0]['used_at'] = self.rows[1]['registered_at'] + offset
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CAUSAL_ORDER'):
                self.verify()
        self.receipts[0]['used_at'] = self.rows[1]['registered_at'] - 1
        self.assertEqual(len(self.verify()), 3)

    def test_every_array_has_exact_bounded_cardinality(self):
        for field in ('rows', 'generations', 'receipts', 'attestations', 'contexts'):
            for value in (None, (), [], [None]*4):
                with self.subTest(field=field, value=value):
                    self.setUp()
                    setattr(self, field, value)
                    with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_COUNT'):
                        self.verify()

    def test_unknown_envelope_field_does_not_grant_authority(self):
        self.contexts[0]['production_activation'] = True
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_ENVELOPE'):
            self.verify()

    def test_strict_statement_and_signature_encodings(self):
        original = self.contexts[0]['statement']
        for field, value in [('ordinal', True), ('ordinal', 0), ('ordinal', 4),
                             ('schema', 'old-domain'), ('window', 'A'*64), ('window', '0'*63)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                context.context_signing_message(dict(original, **{field: value}))
        with self.assertRaises(ValueError):
            context.context_signing_message(dict(original, extra=1))
        for signature in ('00'*63, 'AA'*64, '00 '*64, None):
            self.contexts[0]['consumer_signature'] = signature
            with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_SIGNATURE_ENCODING'):
                self.verify()


class ConsumerContextIntegrationTests(unittest.TestCase):
    """Use the actual full V2 window owner and its retained synthetic fixtures."""
    def setUp(self):
        import model_window_history as owner
        import test_model_window_history as fixtures
        self.owner = owner
        fixture = fixtures.ProspectiveGenerationLineageTests()
        fixture.setUp()
        self.history, data = fixture.three()
        self.generations, self.receipts, self.attestations = fixture.signed_benefit(self.history, data)
        for i, (receipt, attestation) in enumerate(zip(self.receipts, self.attestations), 1):
            receipt.update(decision_reason='adopted_gain', owner_decision=identity('decision' + str(i)))
            self.resign_receipt(i - 1)
        self.contexts = sign_contexts(self.history['entries'][-3:], self.generations, self.attestations)

    def resign_receipt(self, index):
        receipt = self.receipts[index]
        self.generations[index]['consumer_receipt'] = self.owner.H(
            'model-consumer-decision-receipt-v2', self.owner.canonical(receipt)).hex()
        message = self.owner.H('model-consumer-decision-attestation-v2', self.owner.canonical(receipt))
        for role, offset in [('consumer', 10), ('controller', 20)]:
            key = Ed25519PrivateKey.from_private_bytes(bytes([offset+index+1])*32)
            self.attestations[index][role+'_signature'] = key.sign(message).hex()

    def verify(self):
        raw, pin = self.owner.freeze_exposure_history(self.history)
        return context.verify_context_bound_prospective_decisions(raw, pin,
            self.generations, self.receipts, self.attestations, self.contexts)

    def test_full_owner_accepts_bound_context_without_promoting_independence(self):
        result = self.verify()
        self.assertTrue(result['context_signatures_verified'])
        self.assertTrue(result['declared_causal_use_order_verified'])
        for field in ('actual_model_installation_verified', 'independent_controller_verified',
                      'new_consumer_benefit_verified', 'hidden_windows_excluded',
                      'prospective_accepted', 'independent_accepted', 'public_reward_eligible',
                      'production_activation'):
            self.assertIs(result[field], False)

    def test_old_v2_signatures_cannot_be_used_as_context_signatures(self):
        for attestation, value in zip(self.attestations, self.contexts):
            value['consumer_signature'] = attestation['consumer_signature']
            value['controller_signature'] = attestation['controller_signature']
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CONSUMER_SIGNATURE'):
            self.verify()

    def test_context_layer_cannot_bypass_existing_v2_owner(self):
        self.receipts[0]['candidate_score'] = self.receipts[0]['baseline_score']
        self.resign_receipt(0)
        self.contexts = sign_contexts(self.history['entries'][-3:], self.generations, self.attestations)
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_ADOPTED_GAIN'):
            self.verify()

    def test_resealed_other_series_keeps_v2_scope_but_requires_new_context_signatures(self):
        prior = self.history['prior_history']
        prior['context']['series'] = identity('another-series')
        prior['head'] = self.owner._context(prior['context'])
        previous = self.owner._identity(self.owner.EXPOSURE_ANCHOR_DOMAIN, prior)
        for row, generation in zip(self.history['entries'], self.generations):
            row['window']['context'] = self.owner._context(prior['context'])
            row['window']['previous'] = previous
            generation['window'] = self.owner._identity(self.owner.EXPOSURE_WINDOW_DOMAIN, row['window'])
            previous = self.owner._identity(self.owner.EXPOSURE_ENTRY_DOMAIN, row)
        self.history['head'] = previous
        raw, pin = self.owner.freeze_exposure_history(self.history)
        # V2 intentionally verifies receipt-key possession only. Do not rewrite
        # that historical contract into a context or independence assertion.
        self.owner.verify_signed_prospective_consumer_decisions_v2(
            raw, pin, self.generations, self.receipts, self.attestations)
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_BINDING'):
            self.verify()
        for value, generation in zip(self.contexts, self.generations):
            value['statement']['window'] = generation['window']
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CONSUMER_SIGNATURE'):
            self.verify()

    def test_improved_candidate_can_remain_on_safety_hold_without_breaking_lineage(self):
        predecessor = self.generations[1]['predecessor_model']
        self.generations[1].update(decision='no_update', adopted_model=predecessor)
        self.generations[2]['predecessor_model'] = predecessor
        self.receipts[1].update(decision_reason='safety_hold', adopted_model=predecessor)
        self.receipts[2]['predecessor_model'] = predecessor
        self.resign_receipt(1)
        self.resign_receipt(2)
        self.contexts = sign_contexts(self.history['entries'][-3:], self.generations, self.attestations)
        self.assertTrue(self.verify()['context_signatures_verified'])
        self.assertEqual(self.generations[1]['adopted_model'], predecessor)

    def test_valid_late_v2_receipt_does_not_establish_causal_generation_use(self):
        self.receipts[0]['used_at'] = self.history['entries'][1]['registered_at']
        self.resign_receipt(0)
        self.contexts = sign_contexts(self.history['entries'][-3:], self.generations, self.attestations)
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_CAUSAL_ORDER'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
