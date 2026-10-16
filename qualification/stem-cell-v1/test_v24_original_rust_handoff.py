"""Adversarial V24 Rust original-material wire and independent arithmetic tests.

SourceOnly fixtures have synthetic FLOATS and never count as original feature or
native Rust execution. OriginalEvidence requires actual frozen V15/V16 files.
"""
import os
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

import v24_rust_original_handoff as handoff
import v24_rust_original_review as reviewer


def fake():
    rng = np.random.default_rng(24)
    features = rng.normal(size=(4,384)).astype(np.float32) / 16
    split = {"centers":np.zeros((2,384),dtype=np.float32)}
    for k in (0,1):
        split[f"heads.{k}.weight"] = rng.normal(size=(4,384)).astype(np.float32)/100
        split[f"heads.{k}.bias"] = rng.normal(size=(4,)).astype(np.float32)/100
    return features, split


class SourceOnly(unittest.TestCase):
    def test_fleet_cardinality_and_wire_size(self):
        features, split=fake()
        for n in handoff.SIZES:
            frame=handoff.build_frame(features,split,'b'*64,n)
            self.assertLess(len(frame),32*1024)
            reviewer.validate_wire(frame,features,split,'b'*64,n)
            self.assertEqual(frame[:8],handoff.MAGIC)

    def test_duplicate_or_missing_research_scope_rejected(self):
        features,split=fake()
        for bad in [(0,17,23,29,31,37),(11,0,23,29,31,37), (11,17,23,29,0,37)]:
            with self.assertRaises(ValueError):
                handoff.build_frame(features,split,'b'*64,64,scope=bad,request=bad)

    def test_stale_generation_fence_principal_epoch_denied(self):
        features,split=fake()
        for k in range(6):
            req=list(handoff.REF_SCOPE)
            req[k]+=1
            with self.assertRaises(ValueError):
                handoff.build_frame(features,split,'b'*64,64,request=tuple(req))
            valid=bytearray(handoff.build_frame(features,split,'b'*64,64))
            struct.pack_into('<Q',valid,16+6*8+k*8,req[k])
            with self.assertRaises(ValueError):
                reviewer.validate_wire(bytes(valid),features,split,'b'*64,64)

    def test_nonfinite_or_wrong_dimension_is_rejected(self):
        feat,split=fake()
        bad=feat.copy();bad[0,0]=float('nan')
        with self.assertRaises(ValueError):handoff.build_frame(bad,split,'b'*64,64)
        with self.assertRaises(ValueError):handoff.build_frame(feat[:3],split,'b'*64,64)
        with self.assertRaises(ValueError):handoff.build_frame(feat,split,'b'*64,4)
        with self.assertRaises(ValueError):handoff.build_frame(feat,split,'0'*64,64)

    def test_original_byte_changes_not_accepted(self):
        features,split=fake()
        b=bytearray(handoff.build_frame(features,split,'b'*64,64))
        b[16+12*8+96+3] ^= 4
        with self.assertRaises(ValueError):
            reviewer.validate_wire(bytes(b),features,split,'b'*64,64)
        b=bytearray(handoff.build_frame(features,split,'b'*64,64))
        b[-5] ^= 16
        with self.assertRaises(ValueError):
            reviewer.validate_wire(bytes(b),features,split,'b'*64,64)
        with self.assertRaises(ValueError):
            reviewer.validate_wire(handoff.build_frame(features,split,'b'*64,64)+b'X',features,split,'b'*64,64)

    def test_real_one_feature_broadcast_to_many_head_outputs(self):
        features, split=fake()
        for n in (64,256,1024,4096):
            data=reviewer.independent_logits(features,split,n)
            self.assertEqual(data.shape,(4,n,4))
            self.assertTrue(np.array_equal(data[:,0],data[:,2]))
            self.assertFalse(np.array_equal(data[:,0],data[:,1]))

    def test_percentile_contract_no_fake_single_sample_p99(self):
        v=list(range(1,129))
        self.assertAlmostEqual(reviewer.quantile(v,.99),126.73/1e6)
        for bad in ([0]*128,[1,2,3], [float('nan')]*128, [True]*128):
            with self.assertRaises(ValueError):reviewer.quantile(bad,.99)

    def test_create_only_rejects_rewrite_and_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'once'
            handoff.create_only(f,b'bytes')
            with self.assertRaises(ValueError):handoff.create_only(f,b'drift')
            with self.assertRaises(ValueError):handoff.create_only(Path(temp)/'missing'/'f',b'bytes')

    def test_wire_requires_no_heldout_label(self):
        feat,split=fake()
        w=handoff.build_frame(feat,split,'b'*64,64)
        self.assertNotIn(b'label',w)
        self.assertEqual(len(w),8+8+12*8+96+(4*384+2*1540)*4)

    def test_has_no_prod_authority_by_design(self):
        feat,split=fake()
        w=handoff.build_frame(feat,split,'b'*64,64)
        self.assertNotIn(b'FINAL_USE',w)
        self.assertNotIn(b'PROMOTED',w)
        self.assertEqual(handoff.SIZES,(64,256,1024,4096))


@unittest.skipUnless(os.environ.get('HEPTA_V24_ORIGINAL_INPUTS') and
                     os.environ.get('HEPTA_V24_ORIGINAL_V15') and
                     os.environ.get('HEPTA_V24_ORIGINAL_V16'),
                     'Original V24 data not staged')
class OriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.inputs=Path(os.environ['HEPTA_V24_ORIGINAL_INPUTS'])
        cls.v15=Path(os.environ['HEPTA_V24_ORIGINAL_V15'])
        cls.v16=Path(os.environ['HEPTA_V24_ORIGINAL_V16'])
        cls.manifest=handoff.prepare(cls.inputs,cls.v15,cls.v16,cls.root/'private')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_all_four_actual_original_frozen_frames(self):
        original,split,mean_sha=reviewer.read_original(self.inputs,self.v15,self.v16)
        self.assertEqual(self.manifest['source_feature_sha256'],handoff.SRC_SHA)
        for n in handoff.SIZES:
            wire=(self.root/'private'/f'frame-{n}.bin').read_bytes()
            reviewer.validate_wire(wire,original,split,mean_sha,n)
            self.assertEqual(self.manifest[f'frame_sha256_{n}'],handoff.sha(wire))

    def test_original_binary_readback_and_denied_new_model_claim(self):
        self.assertTrue(self.manifest['two_original_trained_head_values_replicated'])
        self.assertFalse(self.manifest['rust_worker_driver_integrated'])
        self.assertFalse(self.manifest['q24_parity_qualified'])
        self.assertFalse(self.manifest['production_authorized'])
        self.assertEqual(self.manifest['original_train_rows'],4)

    def test_no_held_labels_in_original_input_frames(self):
        self.assertTrue(all((self.root/'private'/f'frame-{n}.bin').stat().st_size<32000
                            for n in handoff.SIZES))


if __name__ == '__main__': unittest.main()
