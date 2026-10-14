"""Model-free question-preservation contracts, not actual tokenizer benchmarks."""
import copy
import unittest
from four_gate_inputs import QuestionPreservingInputs,joint_text

class TokenizerFixture:
    def encode(self,text,add_special_tokens=False):return list(text.encode('utf-8'))
    def num_special_tokens_to_add(self,pair=False):return 3 if pair else 2
    def build_inputs_with_special_tokens(self,first,second=None):
        return [300]+first+[301] if second is None else [300]+first+[301]+second+[301]
    def pad(self,items,padding=True,return_tensors='pt'):return {'input_ids':[r['input_ids'] for r in items]}

class InputTests(unittest.TestCase):
    def setUp(self):
        self.payloads={}
        for i,q in enumerate(('what?', 'much longer question?')):
            self.payloads[str(i)]={'state':'source '*100,'question':q,'options':['yes','no'],
                                   'joint':joint_text('source '*100,q,['yes','no'])}
    def test_same_retained_state_budget_in_both_arms(self):
        a=QuestionPreservingInputs(TokenizerFixture(),self.payloads,128)
        rows=[{'request_id':k} for k in self.payloads]
        joint=a(rows,'joint_batch')['input_ids'];shared=a(rows,'feature_reuse')['input_ids']
        self.assertEqual(shared[0],shared[1]);self.assertNotEqual(joint[0],joint[1])
        for rid,r in a.audit.items():
            self.assertFalse(r['condition_truncated']);self.assertTrue(r['state_truncated'])
            self.assertEqual(r['retained_state_tokens'],a.state_budget)
    def test_entire_question_and_options_are_in_joint_tokens(self):
        a=QuestionPreservingInputs(TokenizerFixture(),self.payloads,128)
        joint=a([{'request_id':'1'}],'joint_batch')['input_ids'][0]
        self.assertIn(b'Question: much longer question?\nOptions: yes | no',bytes(x for x in joint if x<256))
    def test_impossible_condition_budget_fails_instead_of_truncating(self):
        with self.assertRaisesRegex(ValueError,'no evidence budget'):
            QuestionPreservingInputs(TokenizerFixture(),self.payloads,16)
    def test_unregistered_input_and_nochange_are_rejected(self):
        a=QuestionPreservingInputs(TokenizerFixture(),self.payloads,128)
        with self.assertRaises(ValueError):a([{'request_id':'x'}],'joint_batch')
        with self.assertRaises(ValueError):a([{'request_id':'1'}],'no_change')
    def test_joint_content_drift_is_rejected(self):
        self.payloads['1']['options'].reverse()
        with self.assertRaisesRegex(ValueError,'admitted components'):
            QuestionPreservingInputs(TokenizerFixture(),self.payloads,128)
    def test_legacy_input_is_not_silently_reinterpreted(self):
        self.payloads['1'].pop('question')
        with self.assertRaisesRegex(ValueError,'explicit'):
            QuestionPreservingInputs(TokenizerFixture(),self.payloads,128)

if __name__=='__main__':unittest.main()
