"""Source-independent heldout eligibility tests; no model or labels."""
import copy
import hashlib
import json
import unittest
from source_gate import SourceGateError, verify

def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def plan():
    return {'schema':'hepta.independent-video-source-gate.v1',
        'prior_source_ids':[digest('old'+str(i)) for i in range(10)],
        'candidate_repository':'publisher/heldout-videos','candidate_revision':'a'*40,
        'candidate_sources':[{'source_id':digest('new'+str(i)), 'media_sha256':digest('bytes'+str(i)),
            'split':['train','train','calibration','calibration','holdout','holdout'][i],
            'group_id':'source'+str(i)} for i in range(6)]}
class Tests(unittest.TestCase):
    def test_valid(self):
        p=plan();pin=digest(json.dumps(sorted(p['prior_source_ids']),separators=(',',':')))
        result=verify(p,expected_prior_sha256=pin)
        self.assertEqual(result['candidate_count'],6)
        self.assertFalse(result['independent_quality_established'])
    def test_wrong_prior_pin(self):
        with self.assertRaises(SourceGateError): verify(plan(),expected_prior_sha256='0'*64)
    def test_prior_overlap(self):
        p=plan();p['candidate_sources'][0]['source_id']=p['prior_source_ids'][0]
        with self.assertRaises(SourceGateError):verify(p)
    def test_same_media_different_source(self):
        p=plan();p['candidate_sources'][1]['media_sha256']=p['candidate_sources'][0]['media_sha256']
        with self.assertRaises(SourceGateError):verify(p)
    def test_group_leak(self):
        p=plan();p['candidate_sources'][4]['group_id']=p['candidate_sources'][0]['group_id']
        with self.assertRaises(SourceGateError):verify(p)
    def test_no_second_heldout_source(self):
        p=plan();p['candidate_sources'][5]['group_id']=p['candidate_sources'][4]['group_id']
        with self.assertRaises(SourceGateError):verify(p)
    def test_label_field_refused(self):
        p=plan();p['candidate_sources'][0]['label']=1
        with self.assertRaises(SourceGateError):verify(p)
    def test_unpinned_revision(self):
        p=plan();p['candidate_revision']='main'
        with self.assertRaises(SourceGateError):verify(p)
    def test_duplicate_prior(self):
        p=plan();p['prior_source_ids'][1]=p['prior_source_ids'][0]
        with self.assertRaises(SourceGateError):verify(p)
    def test_duplicate_candidate(self):
        p=plan();p['candidate_sources'][1]['source_id']=p['candidate_sources'][0]['source_id']
        with self.assertRaises(SourceGateError):verify(p)
    def test_noncanonical_hash(self):
        p=plan();p['candidate_sources'][0]['media_sha256']='A'*64
        with self.assertRaises(SourceGateError):verify(p)
if __name__=='__main__':unittest.main()
