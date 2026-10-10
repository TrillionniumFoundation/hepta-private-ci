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

    def test_gradient_direction_all_head_families(self):
        x=np.array([[0.1,-0.2,0.3,0.4],[-0.5,0.2,0.1,-0.1]],dtype=np.float32)
        y=np.array([0,1])
        for kind in KINDS:
            with self.subTest(kind=kind):
                h=Head(kind,4,2,2048,seed=7)
                out,cache=h.forward(x)
                p=h.probs(x)
                dz=p.copy();dz[np.arange(2),y]-=1;dz/=2
                grads=h.backward(cache,dz)
                name=next(iter(h.p))
                index=(0,)*h.p[name].ndim
                old=float(h.p[name][index])
                eps=0.01
                h.p[name][index]=old+eps
                high=float(-np.log(h.probs(x)[np.arange(2),y]).mean())
                h.p[name][index]=old-eps
                low=float(-np.log(h.probs(x)[np.arange(2),y]).mean())
                h.p[name][index]=old
                self.assertAlmostEqual(float(grads[name][index]),(high-low)/(2*eps),delta=0.01)

    def test_full_train_predict_evaluate_stays_blocked(self):
        from r8_experiments import cmd_train,cmd_predict,cmd_evaluate
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            model=root/"model.npz"
            cmd_train(argparse.Namespace(train=str(root/"train.npz"),valid=str(root/"valid.npz"),
                kind="film",classes=2,budget=2048,steps=25,seed=7,distill=0,
                output=str(model),report=str(root/"training.json")))
            pred=root/"prediction.json"
            cmd_predict(argparse.Namespace(model=str(model),input=str(root/"future_unlabelled.npz"),output=str(pred)))
            cmd_evaluate(argparse.Namespace(candidate=str(pred),baseline=str(root/"no_change.json"),
                outcomes=str(root/"future_outcomes.json"),output=str(root/"evaluation.json")))
            evidence=json.loads((root/"evaluation.json").read_text())
            self.assertEqual(evidence["promotion"],"BLOCKED")
            self.assertTrue(evidence["synthetic_outcome"])
            self.assertFalse(evidence["production_admitted"])
            self.assertEqual(evidence["ndu_gain"],"NOT_MEASURED")

    def test_preflight_rejects_4096_large_heads(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,"allocation preflight"):
                cmd_scale(argparse.Namespace(cells=4096,active=1,train_frequency=0,
                    pattern="distinct",requests=32,dim=256,kind="swiglu",budget=262144,
                    seed=7,cache_entries=128,max_head_bytes=512*1024*1024,
                    output=str(Path(d)/"unexpected.json")))

if __name__=="__main__":
    unittest.main()
