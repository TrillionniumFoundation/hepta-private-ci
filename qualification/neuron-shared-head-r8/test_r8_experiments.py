"""Shadow-only R8 regression tests."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from r8_experiments import Head, KINDS, fixture, load_features, check_train_valid, cmd_scale

class Tests(unittest.TestCase):
    def test_head_families(self):
        for kind in KINDS:
            h=Head(kind,32,2,2048,7)
            self.assertLessEqual(h.nparams,2048)
            self.assertTrue(np.isfinite(h.probs(np.zeros((3,32),np.float32))).all())

    def test_episode_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            fixture(Path(d))
            a=load_features(Path(d)/"train.npz",labelled=True)
            b=load_features(Path(d)/"valid.npz",labelled=True)
            check_train_valid(a,b)
            with self.assertRaises(ValueError):
                check_train_valid(a,{**b,"group":a["group"][:len(b["group"])]})

    def test_synthetic_scale(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"out.json"
            cmd_scale(argparse.Namespace(cells=64,active=1,train_frequency=0,pattern="same",requests=64,dim=16,kind="film",budget=2048,seed=7,cache_entries=128,max_head_bytes=512*1024*1024,output=str(p)))
            r=json.loads(p.read_text())
            self.assertFalse(r["production_admitted"])
            self.assertEqual(r["ndu_gain"],"NOT_MEASURED")

if __name__=="__main__":
    unittest.main()
