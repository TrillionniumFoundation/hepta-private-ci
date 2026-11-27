import unittest
import numpy as np
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from factorized_source import FactorizedSourceModel,MODE as FACTOR_MODE
from matched_source import MatchedSourceModel,WRAPPER_MODE
from aligned import all_terms
from transport import TransportProfile
from control import Command
class MatchedTests(unittest.TestCase):
    def pair(self,rep):
        old=(SourceSceneModel(202,12,192,seed=17,mode=SOURCE_MODE) if rep=='direct' else FactorizedSourceModel(202,12,192,seed=17,mode=FACTOR_MODE))
        return old,MatchedSourceModel(202,12,192,seed=17,representation=rep,wrapper_mode=WRAPPER_MODE)
    def test_supervised_tensor_step_and_work_parity(self):
        x=np.arange(404).reshape(2,202)/404;y=np.array([1,5]);counts=[]
        for rep in ('direct','factor'):
            old,new=self.pair(rep)
            for a,b in zip(old.forward(x),new.forward(x)):np.testing.assert_array_equal(a,b)
            self.assertEqual(old.supervised_step(x,y),new.supervised_step(x,y))
            for key in old.params:np.testing.assert_array_equal(old.params[key],new.params[key])
            self.assertEqual(old.digest(),new.digest());counts.append(new.matched_work)
        self.assertEqual(counts[0],counts[1]);self.assertEqual(counts[0]['raw_forward_calls'],3);self.assertEqual(counts[0]['raw_parameter_gradient_dicts'],1)
    def test_A_anchor_gradients_and_step_exact(self):
        x=np.arange(404).reshape(2,202)/404;ts=tuple(range(12));y=np.array([0,4]);ft=np.asarray([TransportProfile.destinations(ts,c) for c in (Command(1,0,0),Command(0,1,0))]);r=(np.arange(288).reshape(2,12,12)%23)/22*1.3-.3;counts=[]
        for rep in ('direct','factor'):
            old,new=self.pair(rep);p,q=old.forward(x);t=all_terms(p,q,r,y,ft,ft,ts,ts,1.5);dt=t['aligned_additive'][1]+.2*t['aligned_anchor'][0];di=t['aligned_additive'][2]+.2*t['aligned_anchor'][1]
            a,b=old.gradients(x,dt,di),new.gradients(x,dt,di)
            for key in a:np.testing.assert_array_equal(a[key],b[key])
            old.train_step(x,dt,di);new.train_step(x,dt,di)
            for key in old.params:np.testing.assert_array_equal(old.params[key],new.params[key])
            self.assertEqual(old.digest(),new.digest());counts.append(new.matched_work)
        self.assertEqual(counts[0],counts[1]);self.assertEqual(counts[0]['raw_forward_calls'],2)
    def test_identity_clone_and_checkpoint(self):
        for rep in ('direct','factor'):
            old,new=self.pair(rep);clone=new.clone();self.assertEqual(clone.identity(),new.identity());self.assertEqual(clone.digest(),new.digest());self.assertEqual(clone._moments,{});self.assertEqual(clone.updates,0)
            for k in new.params:self.assertFalse(np.shares_memory(new.params[k],clone.params[k]))
            for fun in (clone.save,MatchedSourceModel.load):
                with self.assertRaises(ValueError):fun(object())
        with self.assertRaises(ValueError):MatchedSourceModel(202,12,192,representation='other',wrapper_mode=WRAPPER_MODE)
        with self.assertRaises(ValueError):MatchedSourceModel(202,12,192,representation='direct',wrapper_mode='old')
