"""Original CPU calculation + distinct replay; synthetic Q24 stimulus only."""
import copy
import hashlib
import struct
import unittest

from stem_cell_fleet_v3 import FleetError, Q24, WIDTH, PARAMS, scalar_stream, pool_q24, calculate
from stem_cell_fleet_v3_review import ReviewError, verify


def stimulus(rows=3):
    raw=b''.join(struct.pack('>q', ((i%11)-5)*Q24//8) for i in range(rows*WIDTH))
    return raw, hashlib.sha256(raw).hexdigest()


class FleetV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw,cls.sha=stimulus()
        cls.result=calculate(cls.raw,3,feature_sha256=cls.sha,review_sha256='a'*64,
                             sizes=(64,),warmups=1,repeats=2)

    def test_real_physical_independent_weights_and_review(self):
        r=self.result
        x=r['results'][0]
        self.assertEqual(len(scalar_stream(64)),64*PARAMS)
        self.assertEqual(x['physically_allocated_head_bytes'],64*6914*2)
        self.assertEqual(len(x['selected_cell_indices']),32)
        report=verify(r,self.raw,3,feature_sha256=self.sha,
                      review_sha256='a'*64,expected_sizes=(64,))
        self.assertTrue(report['all_routing_gates_recomputed'])
        self.assertFalse(report['production_authorized'])

    def test_wrong_feature_rejected(self):
        with self.assertRaises(FleetError):
            calculate(self.raw,3,feature_sha256='b'*64,review_sha256='a'*64,sizes=(64,))
        with self.assertRaises(ReviewError):
            verify(self.result, self.raw+b'x',3,feature_sha256=self.sha,
                   review_sha256='a'*64,expected_sizes=(64,))

    def test_head_score_and_gate_drift_rejected(self):
        for key in ('selected_head_scores','complete_gate_score_sha256',
                    'physical_head_parameter_sha256','selected_cell_indices'):
            r=copy.deepcopy(self.result)
            if key=='selected_head_scores':r['results'][0][key][0] += .01
            elif key=='selected_cell_indices':r['results'][0][key][0]=9999
            else:r['results'][0][key]='0'*64
            with self.subTest(key=key),self.assertRaises(ReviewError):
                verify(r,self.raw,3,feature_sha256=self.sha,
                       review_sha256='a'*64,expected_sizes=(64,))

    def test_no_forged_forward_quality_or_cost(self):
        for key,value in (('production_authorized',True),('parameters_trained',True),
                          ('real_task_success_measured',True),('physical_pretrained_encoder_forward_in_this_stage',True)):
            r=copy.deepcopy(self.result);r[key]=value
            with self.subTest(key=key),self.assertRaises(ReviewError):
                verify(r,self.raw,3,feature_sha256=self.sha,
                       review_sha256='a'*64,expected_sizes=(64,))
        r=copy.deepcopy(self.result);r['results'][0]['actual_complete_gate_evaluations']=0
        with self.assertRaises(ReviewError):
            verify(r,self.raw,3,feature_sha256=self.sha,
                   review_sha256='a'*64,expected_sizes=(64,))

    def test_unknown_authority_and_extra_work_are_rejected(self):
        for target in ('parent', 'result'):
            r=copy.deepcopy(self.result)
            if target=='parent':
                r['final_use_authorized']=True
            else:
                r['results'][0]['unmetered_forward_count']=999
            with self.subTest(target=target), self.assertRaises(ReviewError):
                verify(r,self.raw,3,feature_sha256=self.sha,
                       review_sha256='a'*64,expected_sizes=(64,))

    def test_shape_limits_and_tampered_q24(self):
        with self.assertRaises(FleetError):pool_q24(b'bad',3)
        raw=bytearray(self.raw);raw[0:8]=struct.pack('>q',9*Q24)
        with self.assertRaises(FleetError):pool_q24(bytes(raw),3)
        with self.assertRaises(FleetError):scalar_stream(4097)

if __name__=='__main__':
    unittest.main()
