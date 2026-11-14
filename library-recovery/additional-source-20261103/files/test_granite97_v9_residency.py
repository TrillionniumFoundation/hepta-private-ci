"""Negative controls for the actual-weight physical study; no model materials needed."""
from __future__ import annotations
import copy
import unittest
from granite97_v9_residency import (HEAD_SIZE, MODEL_ELEMENTS, MODEL_TENSORS,
                                    MODEL_WEIGHT_BYTES, PROFILES, verify_receipts)


def fixture():
    o=[]
    for mode,n,c in PROFILES:
        delta=200_000_000*c+2*n*HEAD_SIZE
        o.append(dict(mode=mode,logical_cells=n,resident_model_copies=c,
                      unique_model_tensor_storages=c*MODEL_TENSORS,
                      actual_model_weight_bytes=c*MODEL_WEIGHT_BYTES,
                      per_cell_head_scalars=HEAD_SIZE,actual_head_bytes=n*HEAD_SIZE*2,
                      rss_before_bytes=100_000_000,rss_after_bytes=100_000_000+delta,
                      rss_increment_bytes=delta,measured_wall_ns=10000,
                      measured_cpu_ns=9999,forward_calls=0,training_steps=0,
                      authority="DENY_ALL",production_authorized=False))
    return o


class PhysicalWeightResidencyContractTest(unittest.TestCase):
    def test_replay_valid_accounting(self):
        self.assertEqual(MODEL_ELEMENTS,97_441_152)
        self.assertIsNone(verify_receipts(fixture()))

    def test_no_missing_or_extra_arms(self):
        for change in (lambda x:x.pop(),lambda x:x.append(copy.deepcopy(x[-1]))):
            x=fixture();change(x)
            with self.assertRaises(ValueError):verify_receipts(x)

    def test_no_fake_weight_reuse_or_count(self):
        for key,val in (("resident_model_copies",1),("actual_model_weight_bytes",12),
                        ("unique_model_tensor_storages",74)):
            x=fixture();x[1][key]=val
            with self.assertRaises(ValueError):verify_receipts(x)

    def test_head_identity_and_bytes(self):
        x=fixture();x[4]["actual_head_bytes"]-=2
        with self.assertRaises(ValueError):verify_receipts(x)
        x=fixture();x[4]["per_cell_head_scalars"]-=1
        with self.assertRaises(ValueError):verify_receipts(x)

    def test_denies_fake_model_forward_or_training(self):
        for key,val in (("forward_calls",1),("training_steps",100),("production_authorized",True),
                        ("authority","GRANT")):
            x=fixture();x[0][key]=val
            with self.assertRaises(ValueError):verify_receipts(x)

    def test_missing_measured_rss_and_cost(self):
        for key in ("rss_before_bytes","rss_after_bytes","rss_increment_bytes", "measured_cpu_ns","measured_wall_ns"):
            x=fixture();x[3][key]=0
            with self.assertRaises(ValueError):verify_receipts(x)

    def test_fake_shared_advantage_is_denied(self):
        x=fixture()
        x[1]["rss_after_bytes"]=x[0]["rss_after_bytes"]
        x[1]["rss_increment_bytes"]=x[0]["rss_increment_bytes"]
        with self.assertRaises(ValueError):verify_receipts(x)

    def test_changed_measured_cost_or_schema_is_denied(self):
        x=fixture();x[2]["rss_increment_bytes"]+=1
        with self.assertRaises(ValueError):verify_receipts(x)
        x=fixture();x[2]["future_gain"]=True
        with self.assertRaises(ValueError):verify_receipts(x)


if __name__=='__main__': unittest.main()
