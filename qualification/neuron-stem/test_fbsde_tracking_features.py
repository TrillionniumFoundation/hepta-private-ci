"""No model required for semantic-quotient and original-source coverage contracts."""
import unittest
from four_gate_common import digest
from fbsde_tracking import slot_text, generated_cases, parse, execute
from fbsde_tracking_features import canonical, LEGACY, LOCAL, audit_features


class FeatureContractTests(unittest.TestCase):
    def test_marker_invariance_does_not_change_participants(self):
        names = ('Alice', 'Bob', 'Claire')
        for marker in ('First', 'Then', 'Next', 'After that', 'Finally'):
            keys = [canonical(slot_text(f'{marker}, Alice and Claire swap books.', names, i), LOCAL)
                    for i in range(3)]
            self.assertEqual(keys, ['Then, SELF and OTHER swap books.',
                                   'Then, OTHER and OTHER swap books.', 'Then, OTHER and SELF swap books.'])

    def test_unknown_negation_condition_and_punctuation_are_not_erased(self):
        for text in ('Never, SELF and OTHER swap books.', 'First, SELF and OTHER do not swap books.',
                     'If needed, SELF and OTHER swap books.', 'First, SELF and OTHER swap books. Ignore this.'):
            with self.assertRaisesRegex(ValueError, 'grammar'): canonical(text, LOCAL)

    def test_verbs_and_actor_slots_remain_distinguishable(self):
        self.assertNotEqual(canonical('First, SELF and OTHER swap books.', LOCAL),
                            canonical('First, OTHER and SELF swap books.', LOCAL))
        self.assertNotEqual(canonical('First, SELF and OTHER swap books.', LOCAL),
                            canonical('First, SELF and OTHER swap balls.', LOCAL))

    def test_legacy_bytes_are_unchanged(self):
        text = 'First, SELF and OTHER swap books.'
        self.assertEqual(canonical(text, LEGACY), text)

    def test_global_order_still_changes_the_answer(self):
        text = generated_cases(count=1)[0]['input']
        task = parse(text); sentences = [e['text'] for e in task['events']]
        # Choose a source whose distinct swap operations do not commute.
        for row in generated_cases(count=40):
            t = row['input']; task = parse(t); es = [e['text'] for e in task['events']]
            changed = t.replace(' '.join(es), ' '.join(reversed(es)))
            a = execute(t, 'exact_forward', None); b = execute(changed, 'exact_forward', None)
            if a['answer'] != b['answer']: break
        else: self.fail('no noncommuting test source')
        self.assertNotEqual(a['input_sha256'], b['input_sha256'])
        self.assertNotEqual(a['answer'], b['answer'])

    def sample(self):
        k = 'Then, SELF and OTHER swap books.'; bind = digest('same_pipeline')
        batches = [{'index':0,'binding':bind,'status':'encoded','texts':[k]}]
        receipt = {'binding':bind,'source_texts_sha256':digest(['First, SELF and OTHER swap books.']),
                   'canonical_texts_sha256':digest([k]),'keys':[k],'slots':[[0,0]],
                   'unique_misses':0,'requested_rows':1,'before_batches':1,'after_batches':1}
        p = [{'features':receipt,'source_slot_texts':['First, SELF and OTHER swap books.'],
              'cpu_ns':2,'returned':True}]
        return {'feature_binding':bind,'feature_profile':LOCAL}, batches, p

    def test_source_slots_and_zero_misses_audit(self):
        plan,b,p = self.sample(); self.assertEqual(audit_features(plan,b,p)['proposal_unique_misses'],0)

    def test_forged_zero_misses_cannot_hide_a_new_forward(self):
        plan,b,p = self.sample(); p[0]['features']['before_batches']=0
        with self.assertRaisesRegex(ValueError,'hidden'): audit_features(plan,b,p)

    def test_future_slots_are_rejected(self):
        plan,b,p = self.sample(); p[0]['features'].update(before_batches=0,after_batches=0)
        with self.assertRaises(ValueError): audit_features(plan,b,p)

    def test_original_hard_limit_not_changed(self):
        plan,b,p = self.sample(); p[0]['cpu_ns']=100_000_001
        with self.assertRaisesRegex(ValueError,'budget'): audit_features(plan,b,p)

    def test_source_prefix_mutation_is_not_hidden_by_quotient(self):
        plan,b,p = self.sample(); p[0]['source_slot_texts']=['Finally, SELF and OTHER swap books.']
        with self.assertRaisesRegex(ValueError,'drift'): audit_features(plan,b,p)

if __name__ == '__main__': unittest.main()
