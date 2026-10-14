"""Canonical feature-bank identity tests. No pretrained model or efficacy claims."""
import copy
import hashlib
import json
import math
import struct
import unittest
import e1e2_q24_identity as q

def fixture(width=384):
    ids=["case-A","case-B","case-C"]
    features={"case-A":[.25]*width, "case-B":[-.125]*width, "case-C":[0.]*width}
    return ids,features

class Q24BankTests(unittest.TestCase):
    def test_actual_integer_pack_matches_independent_scalar_digest(self):
        ids,bank=fixture(256)
        result=q.feature_inventory(ids,bank)
        raw=(b'hepta.e1e2.case-q24.v1\0'+ids[0].encode()+b'\0'+
             struct.pack('<H',256)+struct.pack('<q',round(.25*q.Q24))*256)
        self.assertEqual(result['case_q24_sha256']['case-A'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['feature_width'],256)
        self.assertFalse(result['model_origin_independently_verified'])
    def test_384_width(self):
        ids,features=fixture()
        self.assertEqual(q.feature_inventory(ids,features)['feature_width'],384)
    def test_reordered_requests_same_hash(self):
        ids,features=fixture()
        self.assertEqual(q.feature_inventory(ids,features)['bank_q24_sha256'],
                         q.feature_inventory(ids[::-1],features)['bank_q24_sha256'])
    def test_content_tamper_changes_binding(self):
        ids,features=fixture();old=q.feature_inventory(ids,features)
        features['case-B'][4]=.5
        new=q.feature_inventory(ids,features)
        self.assertNotEqual(old['bank_q24_sha256'],new['bank_q24_sha256'])
    def test_negative_zero_canonical(self):
        a=q.feature_digest('case-X',[0.]*256)
        b=q.feature_digest('case-X',[-0.]*256)
        self.assertEqual(a,b)
    def test_halfway_q24_ties_to_even(self):
        a=[0.]*256;b=copy.deepcopy(a)
        b[0]=.5/q.Q24
        self.assertEqual(q.feature_digest('case-X',a),q.feature_digest('case-X',b))
        b[0]=1.5/q.Q24
        self.assertNotEqual(q.feature_digest('case-X',a),q.feature_digest('case-X',b))
    def test_missing_case_rejected(self):
        ids,features=fixture();features.pop('case-C')
        with self.assertRaises(q.Invalid):q.feature_inventory(ids,features)
    def test_duplicate_case_rejected(self):
        ids,features=fixture()
        with self.assertRaises(q.Invalid):q.feature_inventory(ids+[ids[0]],features)
    def test_wrong_width_rejected(self):
        ids,features=fixture();features['case-B']=[0.]*257
        with self.assertRaises(q.Invalid):q.feature_inventory(ids,features)
    def test_nan_rejected(self):
        ids,features=fixture();features['case-B'][0]=float('nan')
        with self.assertRaises(q.Invalid):q.feature_inventory(ids,features)
    def test_out_of_domain_rejected(self):
        ids,features=fixture();features['case-B'][0]=9.
        with self.assertRaises(q.Invalid):q.feature_inventory(ids,features)
    def test_bool_disallowed(self):
        ids,features=fixture();features['case-B'][0]=True
        with self.assertRaises(q.Invalid):q.feature_inventory(ids,features)
    def test_case_identity_changed(self):
        ids,features=fixture()
        self.assertNotEqual(q.feature_digest('case-X',[0.]*384),q.feature_digest('case-Y',[0.]*384))
    def test_not_an_owner_receipt(self):
        ids,features=fixture()
        x=q.feature_inventory(ids,features)
        self.assertEqual(x['authority'],'DENY_ALL')
        self.assertNotIn('production_promotion_permitted',x)
if __name__=='__main__':unittest.main()
