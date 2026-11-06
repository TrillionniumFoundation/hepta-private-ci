"""Synthetic signed cross-owner regressions, not actual Hepta evolution evidence.

These exercise the unchanged history/receipt/strict-signature owners and the
explicit context-bound successor. No validation doubles or native flags are used.
"""
import copy
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from contract_wire import H, NETWORK, PARAMETER_HASH, canonical
from llm_adapter_contract import CONTROL_IDS, SCOPE, freeze, validate_run_plan
import model_window_history as window
from model_consumer_context import (
    SCHEMA, context_signing_message, verify_context_bound_prospective_decisions,
)
from model_generation_sequence import (
    PLAN_DOMAIN, verify_generation_sequence, verify_context_bound_generation_sequence,
)


def identity(label):
    return H('generation-sequence-context-test-fixture', label.encode()).hex()


class ContextBoundGenerationSequenceTests(unittest.TestCase):
    def keys(self, index):
        return [Ed25519PrivateKey.from_private_bytes(bytes([offset + index]) * 32)
                for offset in (10, 20)]

    def case(self, decisions=('adopted', 'adopted', 'adopted')):
        # Reported windows are synthetic inputs. They do not assert that an
        # evaluator ran, that a task was untouched, or that a model was installed.
        prior = window.empty_history(identity('series'), identity('owner'), identity('governance'))
        history = dict(schema='pon-model-exposure-history-v2', scope=window.EXPOSURE_SCOPE,
                       prior_history=prior, entries=[], head='00' * 32)
        case = dict(history=history, plans=[], generations=[], receipts=[], attestations=[],
                    initial=identity('initial-owner-admitted-model'))
        predecessor = case['initial']
        for index, decision in enumerate(decisions, 1):
            candidate = identity('candidate:' + str(index))
            tasks = sorted([
                dict(id=identity(f'task:{index}:{partition}'), partition=partition,
                     source_group=identity(f'group:{index}:{partition}'),
                     prompt_sha256=identity(f'prompt:{index}:{partition}'),
                     target_output_sha256=identity(f'output:{index}:{partition}'),
                     input_tokens=4, output_tokens=2)
                for partition in ('calibration', 'evaluation')], key=lambda task: task['id'])
            plan = dict(schema='pon-target-decoder-evaluation-run-plan-v1',
                        network=NETWORK.hex(), parameters=PARAMETER_HASH.hex(),
                        contract=identity('contract'), backbone=identity('backbone'),
                        tokenizer=identity('tokenizer'), candidate=candidate,
                        controls=[dict(id=name, artifact=identity(f'control:{index}:{name}'))
                                  for name in CONTROL_IDS], tasks=tasks,
                        metric='equal-source-group-exact-output-bytes-accuracy-v1',
                        repeats=1, seeds=[index],
                        budgets={key: 10**6 for key in (
                            'cpu_ns', 'gpu_ns', 'wall_ns', 'memory_peak_bytes',
                            'bytes_read', 'bytes_written', 'training_steps', 'training_flops')},
                        stopping='all-frozen-repetitions-no-early-selection-v1',
                        source_registration=dict(
                            owner_record=identity('owner'), admission_root=identity('admission'),
                            task_release_record=identity(f'release:{index}'), custody_record=identity('custody'),
                            observation_status='external-owner-evidence-required',
                            prospective_accepted=False, independent_accepted=False,
                            public_reward_eligible=False), scope=SCOPE)
            _, plan_id = freeze(plan, validate_run_plan, PLAN_DOMAIN)
            row = dict(window=dict(schema='pon-model-exposure-window-v2', scope=window.EXPOSURE_SCOPE,
                       context=window._context(prior['context']), ordinal=index, previous='00' * 32,
                       preregistration=identity(f'prereg:{index}'), run_plan=plan_id), status='completed',
                       receipt=identity(f'assessment:{index}'), registered_at=index * 100,
                       observed_at=index * 100 + 10, closes_at=index * 100 + 40,
                       reported_gates_passed=True,
                       tasks=sorted([dict(id=t['id'], prompt=t['prompt_sha256'],
                                          group=t['source_group'], partition=t['partition'])
                                     for t in tasks], key=lambda task: task['id']),
                       probe_prompts=[], training_groups=[])
            adopted = candidate if decision == 'adopted' else predecessor
            generation = dict(window='00' * 32, run_plan=plan_id, predecessor_model=predecessor,
                              candidate_model=candidate, adopted_model=adopted, decision=decision,
                              consumer_receipt='00' * 32)
            receipt = dict(ordinal=index, consumer='00' * 32, controller='00' * 32,
                           task=identity(f'consumer-task:{index}'), input=identity(f'consumer-input:{index}'),
                           predecessor_model=predecessor, candidate_model=candidate, adopted_model=adopted,
                           baseline_output=identity(f'baseline-output:{index}'),
                           candidate_output=identity(f'candidate-output:{index}'),
                           metric='integer-loss-lower-is-better-v1', baseline_score=100,
                           candidate_score=90, used_at=index * 100 + 20,
                           decision_reason='adopted_gain' if decision == 'adopted' else 'safety_hold',
                           owner_decision=identity(f'owner-decision:{index}'))
            case['plans'].append(plan); history['entries'].append(row)
            case['generations'].append(generation); case['receipts'].append(receipt)
            predecessor = adopted
        self.relink(case)
        self.sign_receipts(case)
        self.sign_contexts(case)
        return case

    def relink(self, case):
        previous = window._identity(window.EXPOSURE_ANCHOR_DOMAIN, case['history']['prior_history'])
        for row, generation in zip(case['history']['entries'], case['generations']):
            row['window']['previous'] = previous
            previous = window._identity(window.EXPOSURE_ENTRY_DOMAIN, row)
            generation['window'] = window._identity(window.EXPOSURE_WINDOW_DOMAIN, row['window'])
        case['history']['head'] = previous

    def sign_receipts(self, case):
        attestations = []
        for index, (generation, receipt) in enumerate(zip(case['generations'], case['receipts']), 1):
            consumer, controller = self.keys(index)
            public = [key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                      for key in (consumer, controller)]
            receipt['consumer'] = H(window.CONSUMER_KEY_DOMAIN, public[0]).hex()
            receipt['controller'] = H(window.CONTROLLER_KEY_DOMAIN, public[1]).hex()
            generation['consumer_receipt'] = H('model-consumer-decision-receipt-v2', canonical(receipt)).hex()
            message = H('model-consumer-decision-attestation-v2', canonical(receipt))
            attestations.append(dict(ordinal=index, consumer_public_key=public[0].hex(),
                controller_public_key=public[1].hex(), consumer_signature=consumer.sign(message).hex(),
                controller_signature=controller.sign(message).hex()))
        case['attestations'] = attestations

    def sign_contexts(self, case):
        contexts = []
        for index, (row, generation) in enumerate(zip(case['history']['entries'], case['generations']), 1):
            statement = dict(schema=SCHEMA, ordinal=index, window=generation['window'],
                             run_plan=generation['run_plan'], assessment=row['receipt'],
                             receipt=generation['consumer_receipt'])
            message = context_signing_message(statement)
            consumer, controller = self.keys(index)
            contexts.append(dict(statement=statement, consumer_signature=consumer.sign(message).hex(),
                                 controller_signature=controller.sign(message).hex()))
        case['contexts'] = contexts

    def args(self, case):
        raw, pin = window.freeze_exposure_history(case['history'])
        return raw, pin, case['generations'], case['receipts'], case['attestations']

    def verify(self, case):
        return verify_context_bound_generation_sequence(
            *self.args(case), case['plans'], case['initial'], case['contexts'])

    def legacy(self, case):
        return verify_generation_sequence(*self.args(case), case['plans'], case['initial'])

    def context_only(self, case):
        return verify_context_bound_prospective_decisions(*self.args(case), case['contexts'])

    def test_complete_real_signatures_and_all_false_acceptance_flags(self):
        case = self.case(); before = copy.deepcopy(case)
        result = self.verify(case)
        self.assertEqual(case, before)
        self.assertEqual(result, self.verify(case))
        self.assertEqual(result['verified_sequence'], self.legacy(case)['id'])
        self.assertEqual(result['verified_context'], self.context_only(case)['id'])
        self.assertTrue(result['supplied_plan_exposure_verified'])
        self.assertTrue(result['context_signatures_verified'])
        for name in ('hidden_windows_excluded', 'actual_model_installation_verified',
                     'independent_controller_verified', 'new_consumer_benefit_verified',
                     'prospective_accepted', 'independent_accepted', 'public_reward_eligible',
                     'production_activation', 'ordinary_hepta_generation_verified', 'physical_custody_verified'):
            self.assertIs(result[name], False)

    def test_rehashed_assessment_cannot_transplant_old_context_signatures(self):
        case = self.case()
        case['history']['entries'][0]['receipt'] = identity('different-assessment')
        self.relink(case)
        self.assertTrue(self.legacy(case)['supplied_run_plans_verified'])
        with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_BINDING'):
            self.verify(case)
        # Same reported relation becomes eligible for this narrower check only
        # after BOTH existing role keys sign the exact new context.
        self.sign_contexts(case)
        self.assertTrue(self.verify(case)['context_signatures_verified'])

    def test_false_exposure_rejects_even_with_valid_new_context_signatures(self):
        original = self.case()
        for field in ('id', 'prompt', 'group', 'partition'):
            case = copy.deepcopy(original)
            row = case['history']['entries'][1]
            if field == 'partition':
                for task in row['tasks']:
                    task['partition'] = ('evaluation' if task['partition'] == 'calibration' else 'calibration')
            else:
                row['tasks'][0][field] = identity('different-exposure:' + field)
                row['tasks'].sort(key=lambda task: task['id'])
            self.relink(case); self.sign_contexts(case)
            self.assertTrue(self.legacy(case)['supplied_run_plans_verified'])
            self.assertTrue(self.context_only(case)['context_signatures_verified'])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_EXPOSURE_BINDING'):
                self.verify(case)

    def test_reused_actual_evaluation_prompt_cannot_hide_behind_fresh_history(self):
        case = self.case()
        first = next(t for t in case['plans'][0]['tasks'] if t['partition'] == 'evaluation')
        reused = next(t for t in case['plans'][1]['tasks'] if t['partition'] == 'evaluation')
        reused['prompt_sha256'] = first['prompt_sha256']
        _, pin = freeze(case['plans'][1], validate_run_plan, PLAN_DOMAIN)
        case['generations'][1]['run_plan'] = pin
        case['history']['entries'][1]['window']['run_plan'] = pin
        self.relink(case); self.sign_contexts(case)
        self.assertTrue(self.legacy(case)['supplied_run_plans_verified'])
        self.assertTrue(self.context_only(case)['context_signatures_verified'])
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_EXPOSURE_BINDING'):
            self.verify(case)
        # Disclosing the real reuse instead is rejected by the ORIGINAL owner.
        task = next(t for t in case['history']['entries'][1]['tasks'] if t['partition'] == 'evaluation')
        task['prompt'] = first['prompt_sha256']
        self.relink(case)
        with self.assertRaisesRegex(ValueError, 'WINDOW_REUSED_PROMPT'):
            self.verify(case)

    def test_each_context_role_signature_is_required(self):
        original = self.case()
        for index in range(3):
            for role in ('consumer', 'controller'):
                case = copy.deepcopy(original)
                case['contexts'][index][role + '_signature'] = '00' * 64
                with self.subTest(index=index, role=role), self.assertRaisesRegex(
                        ValueError, 'CONSUMER_CONTEXT_' + role.upper() + '_SIGNATURE'):
                    self.verify(case)

    def test_missing_or_extra_contexts_fail_before_acceptance(self):
        for contexts in (None, [], [{}] * 2, [{}] * 4):
            case = self.case(); case['contexts'] = contexts
            with self.assertRaisesRegex(ValueError, 'CONSUMER_CONTEXT_COUNT'):
                self.verify(case)

    def test_no_update_owner_hold_and_no_gain_are_preserved(self):
        case = self.case(('adopted', 'no_update', 'adopted'))
        self.assertTrue(self.verify(case)['supplied_plan_exposure_verified'])
        case['receipts'][1].update(candidate_score=100, decision_reason='no_gain')
        case['history']['entries'][1]['reported_gates_passed'] = False
        self.relink(case); self.sign_receipts(case); self.sign_contexts(case)
        self.assertTrue(self.verify(case)['supplied_plan_exposure_verified'])
        self.assertEqual(case['generations'][2]['predecessor_model'], case['generations'][0]['adopted_model'])

    def test_original_initial_model_signature_and_chronology_guards_still_run(self):
        original = self.case()
        case = copy.deepcopy(original); case['initial'] = identity('unrelated-initial')
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_INITIAL_MODEL'):
            self.verify(case)
        case = copy.deepcopy(original); case['attestations'][0]['consumer_signature'] = '00' * 64
        with self.assertRaisesRegex(ValueError, 'CONSUMER_BENEFIT_CONSUMER_SIGNATURE'):
            self.verify(case)
        case = copy.deepcopy(original); case['receipts'][0]['used_at'] = case['history']['entries'][1]['registered_at']
        self.sign_receipts(case); self.sign_contexts(case)
        with self.assertRaisesRegex(ValueError, 'GENERATION_SEQUENCE_PREDECESSOR_USE'):
            self.verify(case)


if __name__ == '__main__':
    unittest.main()
