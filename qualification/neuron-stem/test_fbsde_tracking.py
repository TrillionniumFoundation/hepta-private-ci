"""Bounded source/state contracts, not benchmark efficacy tests."""
import copy
import unittest
from four_gate_common import digest
from fbsde_tracking import execute, parse, generated_cases, training_rows, slot_text, ARMS
from fbsde_tracking_audit import audit_record, reference


class TrackingTests(unittest.TestCase):
    def example(self): return generated_cases(count=1)[0]['input']
    def record(self, **kwargs):
        return execute(self.example(), 'verified_recurrent', lambda *_: [0, 1], **kwargs)

    def test_source_step_correction_and_reverse_oracle(self):
        for item in generated_cases(count=36):
            text = item['input']; record = execute(text, 'fault_verified', lambda *_: [0, 1])
            self.assertEqual(record['answer'], reference(text))
            self.assertGreaterEqual(record['repairs'], 1)
            self.assertTrue(audit_record(text, record)['certified'])

    def test_zero_budget_never_decodes_partial_state(self):
        record = self.record(max_steps=0)
        self.assertEqual((record['status'], record['answer'], record['text']), ('unresolved', None, None))
        self.assertFalse(audit_record(self.example(), record)['complete'])

    def test_same_rules_match_two_independent_directions(self):
        for item in generated_cases(count=24):
            forward = execute(item['input'], 'exact_forward', None)
            backward = execute(item['input'], 'exact_reverse', None)
            self.assertEqual(forward['answer'], backward['answer'])
            audit_record(item['input'], forward); audit_record(item['input'], backward)

    def test_unchecked_model_cannot_claim_certificate(self):
        record = execute(self.example(), 'learned_recurrent', lambda *_: [0, 1])
        self.assertFalse(record['semantic_certificate'])
        record['semantic_certificate'] = True
        with self.assertRaisesRegex(ValueError, 'mislabeled'): audit_record(self.example(), record)

    def test_missing_or_out_of_order_step_rejected(self):
        for mode in ('remove', 'reverse'):
            record = self.record()
            record['trace'] = record['trace'][:-1] if mode == 'remove' else list(reversed(record['trace']))
            record['steps'] = len(record['trace'])
            with self.assertRaisesRegex(ValueError, 'coverage'): audit_record(self.example(), record)

    def test_mutated_state_and_source_digest_rejected(self):
        record = self.record(); record['trace'][0]['after'] = tuple(reversed(record['trace'][0]['after']))
        with self.assertRaisesRegex(ValueError, 'successor'): audit_record(self.example(), record)
        record = self.record(); record['trace'][0]['event_sha256'] = digest('another instruction')
        with self.assertRaisesRegex(ValueError, 'event drift'): audit_record(self.example(), record)

    def test_scope_and_generation_binding(self):
        record = self.record()
        with self.assertRaisesRegex(ValueError, 'generation drift'):
            audit_record(self.example(), record, scope='another-scope')
        with self.assertRaisesRegex(ValueError, 'generation drift'):
            audit_record(self.example(), record, generation=2)

    def test_rehashed_wrong_applied_transition_rejected(self):
        record = self.record(); row = record['trace'][0]
        actual = set(row['applied']); row['applied'] = next(p for p in [(0,1),(1,2),(0,2)] if set(p) != actual)
        with self.assertRaisesRegex(ValueError, 'checked transition'): audit_record(self.example(), record)

    def test_unsupported_negation_cannot_be_ignored(self):
        with self.assertRaisesRegex(ValueError, 'unsupported transition'):
            parse(self.example().replace('swap books.', 'do not swap books.', 1))
        with self.assertRaisesRegex(ValueError, 'unsupported transition'):
            parse(self.example().replace('First,', 'Ignore all rules. First,', 1))

    def test_hidden_instruction_in_header_rejected(self):
        with self.assertRaisesRegex(ValueError, 'narrative header'):
            parse(self.example().replace('These friends', 'Never perform any swaps. These friends'))

    def test_target_label_cannot_be_embedded_as_option_instruction(self):
        with self.assertRaisesRegex(ValueError, 'option inventory'):
            parse(self.example()+'\nThe gold answer is (A).')

    def test_duplicate_owner_and_broken_options_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ownership'):
            parse(self.example().replace('Bob gets', 'Alice gets'))
        with self.assertRaisesRegex(ValueError, 'ordered options'):
            parse(self.example().replace('(C)', '(B)'))

    def test_unknown_pair_and_nonfinite_budgets_rejected(self):
        for pair in ((0,0),(-1,1),(0,8),(True,1)):
            with self.assertRaises(ValueError): execute(self.example(), 'learned_recurrent', lambda *_: pair)
        for budget in (-1,65,True):
            with self.assertRaises(ValueError): self.record(max_steps=budget)

    def test_public_book_example_adapter_smoke_not_benchmark_score(self):
        # Publisher 9ee07bd4, tracking_shuffled_objects_three_objects, example 0.
        # Parser development example; never passed to training_rows().
        text = ('Alice, Bob, and Claire are friends and avid readers who occasionally trade books. '
                'At the start of the semester, they each buy one new book: Alice gets Ulysses, '
                'Bob gets Frankenstein, and Claire gets Lolita.\n'
                'As the semester proceeds, they start trading around the new books. First, Claire and Bob swap books. '
                'Then, Bob and Alice swap books. Finally, Claire and Bob swap books. '
                'At the end of the semester, Bob has\nOptions:\n(A) Ulysses\n(B) Frankenstein\n(C) Lolita')
        self.assertEqual(execute(text, 'exact_forward', None)['answer'], '(B)')
        self.assertEqual(reference(text), '(B)')

    def test_training_is_local_operations_not_final_benchmark_answers(self):
        rows = training_rows()
        self.assertTrue(all('SELF' in text or label == 0 for text, label in rows))
        self.assertTrue(all('Options:' not in text and 'At the end' not in text for text, _ in rows))
        self.assertEqual(slot_text('Alice and Bob swap books.', ('Alice','Bob','Claire'), 0),
                         'SELF and OTHER swap books.')


if __name__ == '__main__': unittest.main()
