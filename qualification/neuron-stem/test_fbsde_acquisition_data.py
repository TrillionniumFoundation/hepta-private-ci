"""Input isolation and policy semantics, not a pretrained benchmark."""
import unittest
from fbsde_acquisition_data import text_view, INTENTS, partition
from fbsde_acquisition import JointKernel, Objective
from fbsde_acquisition_study import choose, execute, scored
from four_gate_common import digest


class AcquisitionDataTests(unittest.TestCase):
    def test_views_do_not_add_truth(self):
        self.assertEqual([text_view('please transfer money to my savings account', v) for v in range(3)],
                         ['please transfer money', 'my savings account', 'please transfer money to my savings account'])
        self.assertEqual(text_view('two words', 0), text_view('two words', 1))

    def test_empty_and_unsupported_view_rejected(self):
        for t, v in (('', 0), ('  ', 1), ('text', True), ('text', 3)):
            with self.assertRaises(ValueError): text_view(t, v)

    def test_original_partitions_complete_and_disjoint(self):
        data = {split: [[f'{split} text {intent} {i}', intent] for intent in INTENTS for i in range(count)]
                for split, count in (('train', 100), ('val', 20), ('test', 30))}
        parts = partition(data)
        self.assertEqual({k: len(v) for k, v in parts.items()},
                         {'fit':480, 'kernel':320, 'selection':80, 'validation':80, 'test':240})
        data['test'][0][0] = data['train'][0][0]
        with self.assertRaisesRegex(ValueError, 'overlap'): partition(data)

    def test_stale_compiled_kernel_rejected(self):
        k = JointKernel.fit([(0, 0, 0, 0), (1, 1, 1, 1)], 2, {})
        with self.assertRaisesRegex(ValueError, 'stale'):
            choose('compiled_same_model', k, ((0,0),), Objective(), (), .8, ('wrong', {}))

    def test_initial_only_cannot_read_the_future(self):
        kernel = JointKernel.fit([(0, 0, 0, 0)]*10+[(1,1,1,1)]*10, 2, {})
        calls = []
        def provider(view):
            calls.append(view)
            if view != 0: raise AssertionError('future was touched')
            return 0, {'fixture':True}
        row = {'id':'one', 'text_sha256':digest('fixture')}
        rec = execute(row, 'initial_only', kernel, Objective(), provider, (), .8, None, 'fixture-head')
        self.assertEqual(calls, [0]); self.assertEqual(rec['modeled_cost'], 0)
        self.assertEqual(rec['action'], 'answer:0')

    def test_decoded_answer_and_duplicate_acquisition_rejected(self):
        base = {'id':'one','action':'answer:0','text':f'The request is classified as {INTENTS[0]}.',
                'events':[{'view':0}], 'modeled_cost':0.}
        self.assertEqual(scored([base], {'one':0}, Objective())['correct'], 1)
        with self.assertRaisesRegex(ValueError,'drift'):
            scored([{**base,'text':'An invented explanation.'}], {'one':0}, Objective())
        with self.assertRaisesRegex(ValueError,'invalid acquisition'):
            scored([{**base,'events':[{'view':0},{'view':0}]}], {'one':0}, Objective())


if __name__ == '__main__': unittest.main()
