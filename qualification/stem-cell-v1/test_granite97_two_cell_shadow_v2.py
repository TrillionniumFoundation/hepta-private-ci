"""Source-only numeric Head controls; no pretrained forward in tests."""
import copy
import unittest
from granite97_feature_bridge_v2 import BridgeError
from granite97_two_cell_shadow_v2 import shadow_two_cells
from test_granite97_feature_bridge_v2 import fixtures,encode

class TwoCellTests(unittest.TestCase):
    def test_two_actual_source_bound_numerical_heads(self):
        s,e,r=fixtures()
        doc=shadow_two_cells(s,encode(e),encode(r),now_ms=1000000)
        self.assertEqual(doc['cell_head_forward_count'],2)
        self.assertEqual(doc['bridge_encoder_forward_count'],0)
        self.assertEqual(doc['score_q24'],{'cell:axis0':0,'cell:axis1':1})
        self.assertFalse(doc['cell_parameters_trained'])
        self.assertFalse(doc['production_authorized'])

    def test_no_reviewer_never_numeric(self):
        s,e,r=fixtures()
        with self.assertRaises(BridgeError):
            shadow_two_cells(s,encode(e),b'{}',now_ms=1000000)

    def test_synthetic_feature_drift_never_numeric(self):
        s,e,r=fixtures()
        changed=copy.deepcopy(e)
        changed['values_q24'][0]=42
        with self.assertRaises(BridgeError):
            shadow_two_cells(s,encode(changed),encode(r),now_ms=1000000)

if __name__=='__main__':unittest.main()
