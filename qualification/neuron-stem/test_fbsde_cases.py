import unittest
from fbsde_encoder_cases import (cases, partition_utterances, INTENTS, formula_vector,
                                decode_probability, score_decoded, TRAIN_FORMULAS, TEST_FORMULAS, checked_probability)
from four_gate_common import digest


class CaseTests(unittest.TestCase):
    def fixture(self):
        return {s:[[s+' '+label+' '+str(i),label] for label in INTENTS for i in range(40)]
                for s in ('train','val','test')}

    def test_disjoint_publisher_splits_and_no_labels_in_model_cases(self):
        parts=partition_utterances(self.fixture())
        self.assertEqual([len(parts[k]) for k in ('train','validation','calibration','test')],[128,40,40,120])
        seen=set()
        for split,rows in parts.items():
            ids={r['source_sha256'] for r in rows}
            self.assertFalse(seen&ids);seen.update(ids)
            public,truth=cases(rows,split,24,31)
            self.assertEqual(len(public),len(truth))
            for r in public:
                self.assertEqual(set(r),{'case_id','utterance_ids','target_intents','formula'})
                self.assertEqual(len(formula_vector(r['formula'])),105)

    def test_cross_split_repeated_text_is_rejected(self):
        d=self.fixture();d['val'][0][0]=d['train'][0][0]
        with self.assertRaisesRegex(ValueError,'overlap'):partition_utterances(d)

    def test_test_formulas_are_not_training_formulas(self):
        parts=partition_utterances(self.fixture())
        train,_=cases(parts['train'],'train',64,9);test,_=cases(parts['test'],'test',64,10)
        self.assertFalse({digest(r['formula']) for r in train}&{digest(r['formula']) for r in test})

    def test_decoder_checked_after_generation(self):
        records=[{'case_id':'a','probability':.9,'text':decode_probability(.9)}]
        self.assertEqual(score_decoded(records,{'a':True})['decoded_exact_accuracy'],1.)
        records[0]['text']=decode_probability(.1)
        with self.assertRaisesRegex(ValueError,'decoder changed latent'):score_decoded(records,{'a':True})

    def test_solver_nonfinite_not_silently_clamped(self):
        for value in (float('nan'), float('inf'), -float('inf'), -.01, 1.01, True):
            with self.assertRaises(ValueError): checked_probability(value)
        self.assertEqual(checked_probability(-1e-15), 0.)
        self.assertEqual(checked_probability(1+1e-15), 1.)
        self.assertEqual(checked_probability(.25), .25)

    def test_bad_decoder_probability(self):
        for p in (float('nan'),float('inf'),-.1,1.1):
            with self.assertRaises(ValueError):decode_probability(p)


if __name__=='__main__':unittest.main()
