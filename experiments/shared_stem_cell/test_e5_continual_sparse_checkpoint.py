"""E5 episodic packed SGD: actual CPU optimizer and checkpoint integrity tests.

Uses only synthetic Q24 vectors/labels. Never accepts real Stem/Worker authority.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import torch
import e5_continual_sparse_checkpoint as e

CFG=lambda n=64,a=8: e.config(n,a,20261014,"scope.alpha","c"*64,"d"*64)

class TestEpisodic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)
    def test_cold_restore_exactly_matches_uninterrupted_two_waves(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            a=e.execute(c,tmp,"first")
            b=e.execute(c,tmp,"second")
            verify=e.execute(c,tmp,"verify")
            self.assertTrue(verify["measurement"]["cold_restart_equals_uninterrupted"])
            self.assertEqual(a["checkpoint"]["generation"],1)
            self.assertEqual(b["checkpoint"]["generation"],2)
            self.assertEqual(b["checkpoint"]["previous_sha256"],a["checkpoint"]["body_sha256"])
    def test_only_touched_cells_have_optimizer_history(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            e.execute(c,tmp,"second")
            state,_=e.restore(tmp,"wave2",c,2)
            steps=state["steps"].tolist()
            self.assertEqual(steps.count(6),4)
            self.assertEqual(steps.count(3),8)
            self.assertEqual(steps.count(0),52)
            self.assertEqual(len(state["momentum"]),12)
    def test_dormant_weights_are_original(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first");e.execute(c,tmp,"second")
            learned,_=e.restore(tmp,"wave2",c,2)
            base=e.fresh(c)
            dormant=(learned["steps"]==0)
            for name in base["weights"]:
                self.assertTrue(torch.equal(learned["weights"][name][dormant],base["weights"][name][dormant]))
    def test_continuing_optimizer_not_equivalent_to_reset(self):
        c=CFG()
        state=e.fresh(c);e.wave(state,c,1);control=copy.deepcopy(state)
        e.wave(state,c,2);control["momentum"]={};e.wave(control,c,2)
        self.assertNotEqual(e.state_hash(state),e.state_hash(control))
    def test_sparse_bytes_less_than_dense_frozen_base(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first");r=e.execute(c,tmp,"second")
            self.assertLess(r["checkpoint"]["body_bytes"],c["cells"]*e.PER_HEAD*4)
    def test_uncommitted_body_fails_closed(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            state=e.fresh(c);e.wave(state,c,1)
            with self.assertRaises(RuntimeError):
                e.save_checkpoint(tmp,"wave1",state,c,failpoint=True)
            self.assertTrue((Path(tmp)/"wave1.safetensors").is_file())
            self.assertFalse((Path(tmp)/"wave1.receipt.json").exists())
            with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",c,1)
    def test_stale_scope_fence_or_source(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            for key,bad in (("scope","scope.beta"),("fence","e"*64),("source","f"*64)):
                wrong=dict(c);wrong[key]=bad
                with self.subTest(key=key):
                    with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",wrong,1)
    def test_replayed_generation_denied(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",c,2)
    def test_wrong_parent_denied(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",c,1,"b"*64)
    def test_tampered_body_denied(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            path=Path(tmp)/"wave1.safetensors"
            data=bytearray(path.read_bytes());data[-16]^=7;path.write_bytes(data)
            with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",c,1)
    def test_forged_authority_denied(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            path=Path(tmp)/"wave1.receipt.json"
            payload=e.read(path);payload["production_promotion_permitted"]=True
            path.write_text(json.dumps(payload))
            with self.assertRaises(e.Invalid):e.restore(tmp,"wave1",c,1)
    def test_duplicate_keys_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bad.json"
            path.write_text('{"a":1,"a":2}')
            with self.assertRaises(e.Invalid):e.read(path)
    def test_checkpoint_not_overwritable(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            e.execute(c,tmp,"first")
            state=e.fresh(c);e.wave(state,c,1)
            with self.assertRaises(FileExistsError):
                e.save_checkpoint(tmp,"wave1",state,c)
    def test_invalid_cohort_rejected(self):
        with self.assertRaises(e.Invalid):e.config(33,8,1,"s","c"*64,"d"*64)
    def test_no_production_authority(self):
        c=CFG()
        with tempfile.TemporaryDirectory() as tmp:
            report=e.execute(c,tmp,"first")
            self.assertEqual(report["authority"],"DENY_ALL")
            self.assertFalse(report["production_promotion_permitted"])
            self.assertFalse(report["pretrained_encoder_or_native_worker_verified"])
            self.assertTrue(report["synthetic_feature_and_labels"])

if __name__=="__main__":unittest.main()
