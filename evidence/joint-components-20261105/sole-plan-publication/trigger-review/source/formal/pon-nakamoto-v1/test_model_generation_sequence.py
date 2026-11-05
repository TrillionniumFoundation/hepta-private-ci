"""Synthetic signed sequence regressions; not real model or operator evidence."""
import copy
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import model_window_history as window
from contract_wire import H, canonical
from model_generation_sequence import verify_generation_sequence
import test_model_window_history as fixtures
from test_llm_adapter_contract import identity


class GenerationSequenceTests(unittest.TestCase):
    def case(self, gains=(True, True, True), decisions=('adopted', 'adopted', 'adopted')):
        fixture = fixtures.ProspectiveGenerationLineageTests()
        fixture.setUp()
        history, data = fixture.three(gains)
        generations, receipts = fixture.benefit(history, data, decisions)
        for generation, receipt in zip(generations, receipts):
            receipt['decision_reason'] = ('adopted_gain' if generation['decision'] == 'adopted'
                                          else 'no_gain')
            receipt['owner_decision'] = identity('decision:' + str(receipt['ordinal']))
        case = dict(history=history, generations=generations, receipts=receipts,
                    run_plans=[item['plan'] for item in data],
                    expected_initial_model=generations[0]['predecessor_model'])
        self.sign(case)
        return case

    def sign(self, case):
        attestations = []
        for index, receipt in enumerate(case['receipts'], 1):
            consumer = Ed25519PrivateKey.from_private_bytes(bytes([10 + index]) * 32)
            controller = Ed25519PrivateKey.from_private_bytes(bytes([20 + index]) * 32)
            consumer_public = consumer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            controller_public = controller.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            receipt['consumer'] = H(window.CONSUMER_KEY_DOMAIN, consumer_public).hex()
            receipt['controller'] = H(window.CONTROLLER_KEY_DOMAIN, controller_public).hex()
            case['generations'][index - 1]['consumer_receipt'] = H(
                'model-consumer-decision-receipt-v2', canonical(receipt)).hex()
            message = H('model-consumer-decision-attestation-v2', canonical(receipt))
            attestations.append(dict(ordinal=index, consumer_public_key=consumer_public.hex(),
                controller_public_key=controller_public.hex(),
                consumer_signature=consumer.sign(message).hex(),
                controller_signature=controller.sign(message).hex()))
        case['attestations'] = attestations

    def verify(self, case, *, legacy=False):
        raw, pin = window.freeze_exposure_history(case['history'])
        args = (raw, pin, case['generations'], case['receipts'], case['attestations'])
        if legacy:
            return window.verify_signed_prospective_consumer_decisions_v2(*args)
        return verify_generation_sequence(*args, case['run_plans'], case['expected_initial_model'])

    def test_signed_sequence_preserves_inputs_and_unaccepted_physical_claims(self):
        case = self.case()
        before = copy.deepcopy(case)
        result = self.verify(case)
        self.assertEqual(case, before)
        self.assertEqual(result, self.verify(case))
        self.assertTrue(result['supplied_run_plans_verified'])
        self.assertTrue(result['reported_cross_generation_chronology_verified'])
        self.assertEqual(result['verified_decisions'], self.verify(case, legacy=True)['id'])
        self.assertEqual(result['terminal_model'], case['generations'][-1]['adopted_model'])
        self.assertIsNone(result['boundaries'][-1]['next_registered_at'])
        for name in ('actual_model_installation_verified', 'independent_controller_verified',
                     'new_consumer_benefit_verified', 'prospective_accepted',
                     'independent_accepted', 'public_reward_eligible', 'production_activation',
                     'ordinary_hepta_generation_verified'):
            self.assertIs(result[name], False)

    def test_resigned_late_and_equal_use_do_not_qualify_next_generation(self):
        original = self.case()
        for index in (0, 1):
            boundary = original['history']['entries'][index + 1]['registered_at']
            for used_at in (boundary, boundary + 1, window.MAX_TIME):
                case = copy.deepcopy(original)
                case['receipts'][index]['used_at'] = used_at
                self.sign(case)
                # Original V2 promises post-window use, not cross-window causality.
                self.assertTrue(self.verify(case, legacy=True)['external_receipt_signatures_verified'])
                with self.subTest(index=index, used_at=used_at), self.assertRaisesRegex(
                        ValueError, 'GENERATION_SEQUENCE_PREDECESSOR_USE'):
                    self.verify(case)
            case = copy.deepcopy(original)
            case['receipts'][index]['used_at'] = boundary - 1
            self.sign(case)
            self.assertTrue(self.verify(case)['reported_cross_generation_chronology_verified'])

    def test_initial_owner_pin_cannot_be_taken_from_a_submitted_lineage(self):
        case = self.case()
        case['expected_initial_model'] = identity('different-actually-admitted-parent')
        self.assertTrue(self.verify(case, legacy=True)['external_receipt_signatures_verified'])
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_INITIAL_MODEL'):
            self.verify(case)

    def test_consistently_resigned_candidate_alias_cannot_replace_actual_plan(self):
        case = self.case()
        alias = identity('candidate-not-in-the-retained-plan')
        for record in (case['generations'][0], case['receipts'][0]):
            record.update(candidate_model=alias, adopted_model=alias)
        for record in (case['generations'][1], case['receipts'][1]):
            record['predecessor_model'] = alias
        self.sign(case)
        self.assertTrue(self.verify(case, legacy=True)['external_receipt_signatures_verified'])
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_CANDIDATE_BINDING'):
            self.verify(case)

    def test_rehashed_plan_substitution_and_missing_plan_refuse(self):
        case = self.case()
        plan = case['run_plans'][1]
        plan['source_registration']['owner_record'] = identity('substituted-plan')
        # Remain inside the admitted plan grammar so this reaches identity binding.
        _, changed_plan = fixtures.freeze(
            plan, fixtures.validate_run_plan, 'target-decoder-evaluation-run-plan-v1')
        self.assertNotEqual(changed_plan, case['generations'][1]['run_plan'])
        self.assertTrue(self.verify(case, legacy=True)['external_receipt_signatures_verified'])
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_PLAN_BINDING'):
            self.verify(case)
        case['run_plans'].pop()
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_PLAN_COUNT'):
            self.verify(case)
        malformed = self.case()
        malformed['run_plans'][1]['owner_record'] = identity('unknown-top-level-field')
        with self.assertRaisesRegex(ValueError, 'LLM_RUN_PLAN_FIELDS'):
            self.verify(malformed)

    def test_no_gain_and_positive_gain_owner_hold_remain_valid_no_update(self):
        decisions = ('adopted', 'no_update', 'adopted')
        case = self.case((True, False, True), decisions)
        self.assertTrue(self.verify(case)['reported_cross_generation_chronology_verified'])
        case = self.case(decisions=decisions)
        case['receipts'][1].update(candidate_score=90, decision_reason='safety_hold')
        self.sign(case)
        result = self.verify(case)
        self.assertEqual(case['generations'][1]['predecessor_model'],
                         case['generations'][2]['predecessor_model'])
        self.assertIs(result['ordinary_hepta_generation_verified'], False)

    def test_signature_failure_cannot_be_hidden_by_correct_chronology(self):
        case = self.case()
        case['attestations'][0]['controller_signature'] = '00' * 64
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_CONTROLLER_SIGNATURE'):
            self.verify(case)


if __name__ == '__main__':
    unittest.main()
