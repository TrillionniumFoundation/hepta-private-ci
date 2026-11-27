import tempfile
import unittest
from pathlib import Path

import numpy as np

from content_block.learning import BlockAdam, HEADS, compile_library, heads_step, heads_work
from content_block.evidence import inactive_digest
from independent.accounting import BudgetExceeded, WorkLedger
from independent.learning import CachedObjective, CONTENT_PARAMETERS, step_work
from independent.native_adam import NativeAdam
from model import JointModel


class BlockLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.library = compile_library(Path(cls.temp.name)/"build/adam.so")["library"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_native_joint_and_heads_match_numpy_with_per_parameter_clocks(self):
        for arm in ("H","A"):
            actual = JointModel(202,12,192,seed=79)
            expected = actual.clone()
            optimizer = BlockAdam(actual,self.library)
            obj = CachedObjective(arm,actual,optimizer=optimizer)
            rng = np.random.default_rng(99)
            for index in range(8):
                x,y = rng.normal(size=(4,202)), rng.integers(12,size=4)
                p,q = expected.forward(x)
                _,dt,di = obj.policy_gradients(p,q,y)
                grads = expected.gradients(x,dt,di)
                if index%2:
                    grads = {k:grads[k] for k in HEADS}
                    before = inactive_digest(actual)
                    heads_step(obj,actual,x,y,.003,WorkLedger("heads"))
                    self.assertEqual(before,inactive_digest(actual))
                else:
                    obj.step(actual,x,y,.003,ledger=WorkLedger("joint"))
                expected.apply_gradients(grads,.003)
                for key in actual.params:
                    np.testing.assert_array_equal(actual.params[key],expected.params[key])
                for key in CONTENT_PARAMETERS:
                    am,av,ac = actual._moments[key]
                    em,ev,ec = expected._moments[key]
                    np.testing.assert_array_equal(am,em)
                    np.testing.assert_array_equal(av,ev)
                    self.assertEqual(ac,ec)
            self.assertEqual({k:s[2] for k,s in actual._moments.items()},
                             {k:4 if k in CONTENT_PARAMETERS[:2] else 8 for k in CONTENT_PARAMETERS})

    def test_heads_gradients_match_finite_difference(self):
        rng = np.random.default_rng(101)
        for arm in ("H","A"):
            model=JointModel(202,12,192,seed=81)
            objective=CachedObjective(arm,model)
            x,y=rng.normal(size=(4,202)), np.array([0,3,7,11])
            p,q=model.forward(x)
            _,dt,di=objective.policy_gradients(p,q,y)
            gradients=model.gradients(x,dt,di)
            for key in HEADS:
                index=tuple(0 for _ in model.params[key].shape)
                original,eps=model.params[key][index],1e-6
                model.params[key][index]=original+eps
                plus=objective.policy_gradients(*model.forward(x),y)[0]
                model.params[key][index]=original-eps
                minus=objective.policy_gradients(*model.forward(x),y)[0]
                model.params[key][index]=original
                self.assertAlmostEqual(gradients[key][index],(plus-minus)/(2*eps),places=8)

    def test_standard_joint_matches_strong_saved_original_native_kernel(self):
        original=Path(__file__).resolve().parents[1]/"runs/content-control-train-r2-20261023/build/libjoint.so"
        for arm in ("H","A"):
            actual=JointModel(202,12,192,seed=87)
            expected=actual.clone()
            new=CachedObjective(arm,actual,optimizer=BlockAdam(actual,self.library))
            old=CachedObjective(arm,expected,optimizer=NativeAdam(expected,original))
            rng=np.random.default_rng(103)
            for _ in range(3):
                x,y=rng.normal(size=(4,202)),rng.integers(12,size=4)
                self.assertEqual(new.step(actual,x,y,.003),old.step(expected,x,y,.003))
                for key in actual.params: np.testing.assert_array_equal(actual.params[key],expected.params[key])
                for key in CONTENT_PARAMETERS:
                    np.testing.assert_array_equal(actual._moments[key][0],expected._moments[key][0])
                    np.testing.assert_array_equal(actual._moments[key][1],expected._moments[key][1])

    def test_heads_first_preserves_absent_encoder_moments_and_rejects_partial_sets(self):
        model=JointModel(202,12,192,seed=83)
        optimizer=BlockAdam(model,self.library)
        gradients={k:np.full_like(model.params[k],100.) for k in HEADS}
        before=inactive_digest(model)
        optimizer.apply_gradients(model,gradients,.003)
        self.assertEqual(before,inactive_digest(model))
        self.assertEqual(set(model._moments),set(HEADS))
        state={k:v.copy() for k,v in model.params.items()}
        with self.assertRaises(ValueError):
            optimizer.apply_gradients(model,{"text":gradients["text"]},.003)
        for k in state: np.testing.assert_array_equal(state[k],model.params[k])

    def test_heads_inventory_deletes_encoder_work_and_admission_is_atomic(self):
        model=JointModel(202,12,192,seed=85)
        optimizer=BlockAdam(model,self.library)
        objective=CachedObjective("A",model,optimizer=optimizer)
        full,head=step_work(model.dimensions,"A",64),heads_work(model.dimensions,"A",64)
        self.assertEqual(full["macs"]-head["macs"],462848)
        self.assertTrue(all(0<=head[k]<=v for k,v in full.items()))
        ledger=WorkLedger("heads",total_cap=0)
        with self.assertRaises(BudgetExceeded):
            heads_step(objective,model,np.zeros((1,202)),np.array([0]),.003,ledger)
        self.assertEqual(model.updates,0)
        self.assertEqual(model._moments,{})


if __name__=="__main__": unittest.main()
