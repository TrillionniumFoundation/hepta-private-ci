"""Fail-closed no-evidence Reader guard, stdlib and deliberately NO model mocks."""
import copy
from hashlib import sha256
import unittest

from amcn_research_empty_evidence_guard import admit_for_research


def fixture():
    text='A true original source passage.'
    item={'source_id':'D1:1','source_root':'conv-1','scope':'research',
          'generation':'g1','revision':2,'text':text,
          'content_sha256':sha256(text.encode()).hexdigest(),'revoked':False}
    return item, {item['source_id']:copy.deepcopy(item)}


class EvidenceEmptyGuardTest(unittest.TestCase):
    def test_zero_evidence_zero_reader_calls(self):
        r=admit_for_research('Which event?',[],{},scope='research',generation='g1')
        self.assertEqual(r['literal_answer'],'unknown')
        self.assertEqual(r['reader_calls'],0)
        self.assertEqual(r['reader_input_tokens'],0)
        self.assertEqual(r['reader_output_tokens'],0)
        self.assertFalse(r['production_accepted'])

    def test_nonempty_cannot_automatically_claim_reader_call(self):
        s,latest=fixture()
        r=admit_for_research('Which event?',[s],latest,scope='research',generation='g1')
        self.assertEqual(r['source_ids'],['D1:1'])
        self.assertEqual(r['reader_calls'],0)
        self.assertFalse(r['source_owner_independently_authenticated'])
        self.assertTrue(r['model_not_yet_invoked'])

    def test_content_drift_refused(self):
        s,latest=fixture(); s['text']+=' altered'
        with self.assertRaisesRegex(ValueError,'revoked/foreign/modified'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_withdrawal_refused(self):
        s,latest=fixture();latest['D1:1']['revoked']=True
        with self.assertRaisesRegex(ValueError,'owner frontier'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_revision_superseded_refused(self):
        s,latest=fixture();latest['D1:1']['revision']=3
        with self.assertRaisesRegex(ValueError,'owner frontier'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_generation_changed_refused(self):
        s,latest=fixture();s['generation']='g0'
        with self.assertRaises(ValueError):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_deduplicated_sources_required(self):
        s,latest=fixture()
        with self.assertRaisesRegex(ValueError,'repeated source'):
            admit_for_research('Which event?',[s,s],latest,scope='research',generation='g1')

    def test_forged_authorization_field_refused(self):
        s,latest=fixture();s['owner_signature_verified']=True
        with self.assertRaisesRegex(ValueError,'exact immutable evidence'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_oversize_window_refused(self):
        s,latest=fixture()
        with self.assertRaisesRegex(ValueError,'window cap'):
            admit_for_research('Which event?',[s]*17,latest,scope='research',generation='g1')

    def test_foreign_source_id_refused(self):
        s,latest=fixture();s['source_id']='X-new'
        with self.assertRaisesRegex(ValueError,'owner frontier'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_whitespace_question_refused(self):
        with self.assertRaisesRegex(ValueError,'question'):
            admit_for_research(' \t\n',[],{},scope='research',generation='g1')

    def test_empty_source_bypass_refused(self):
        s,latest=fixture()
        s['text']=''
        s['content_sha256']=sha256(b'').hexdigest()
        latest[s['source_id']]=copy.deepcopy(s)
        with self.assertRaisesRegex(ValueError,'revoked/foreign/modified'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_whitespace_source_bypass_refused(self):
        s,latest=fixture()
        s['text']='\n \t'
        s['content_sha256']=sha256(s['text'].encode()).hexdigest()
        latest[s['source_id']]=copy.deepcopy(s)
        with self.assertRaisesRegex(ValueError,'revoked/foreign/modified'):
            admit_for_research('Which event?',[s],latest,scope='research',generation='g1')

    def test_question_empty_refused(self):
        with self.assertRaisesRegex(ValueError,'question'):
            admit_for_research('',[],{},scope='research',generation='g1')

    def test_no_evidence_never_requires_model_weight(self):
        # Deliberately no Tensor, OpenAI model or mock inference in this test.
        r=admit_for_research('Date?',[],{},scope='research',generation='g1')
        self.assertNotIn('model_invoked',r)
        self.assertIsNone(r['independent_semantic_correctness'])

if __name__=='__main__':unittest.main()
