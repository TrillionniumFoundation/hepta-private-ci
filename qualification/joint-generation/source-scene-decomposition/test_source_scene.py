import unittest
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE

class SourceSceneTests(unittest.TestCase):
    def model(self):return SourceSceneModel(202,12,192,seed=17,mode=MODE)
    def data(self):return np.arange(404,dtype=float).reshape(2,202)/404
    def test_mask_input_immutable_command_invariance(self):
        model=self.model();x=self.data();original=x.copy();changed=x.copy();changed[:,-10:]+=10
        for a,b in zip(model.forward(x),model.forward(changed)):np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(x,original)
        self.assertFalse(np.shares_memory(model._input(x),x));self.assertTrue(np.all(model._input(x)[:,-10:]==0))
        pt,pi=model.forward(x);dt=pt.copy();di=pi.copy();dt[:,0]-=1;di[:,0]-=1
        a=model.gradients(x,dt/4,di/4);b=model.gradients(changed,dt/4,di/4)
        for key in a:np.testing.assert_array_equal(a[key],b[key])
        self.assertTrue(np.all(a['encoder'][-10:]==0))
    def test_finite_difference_encoder_and_heads(self):
        model=self.model();x=self.data();y=np.array([1,5]);pt,pi=model.forward(x);dt=pt.copy();di=pi.copy();dt[np.arange(2),y]-=1;di[np.arange(2),y]-=1
        grads=model.gradients(x,dt/4,di/4)
        def loss():
            p,q=model.forward(x);return -(np.log(p[np.arange(2),y])+np.log(q[np.arange(2),y])).mean()/2
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            value=model.params[key][index];eps=1e-6
            model.params[key][index]=value+eps;plus=loss();model.params[key][index]=value-eps;minus=loss();model.params[key][index]=value
            self.assertAlmostEqual(float(grads[key][index]),float((plus-minus)/(2*eps)),delta=2e-7)
    def test_clone_mode_digest_isolation(self):
        model=self.model();raw=JointModel(202,12,192,seed=17)
        for key in raw.params:np.testing.assert_array_equal(raw.params[key],model.params[key])
        self.assertNotEqual(raw.digest(),model.digest());model.supervised_step(self.data(),np.array([1,5]));clone=model.clone()
        self.assertIs(type(clone),SourceSceneModel);self.assertEqual(clone.mode,MODE);self.assertEqual(clone.digest(),model.digest());self.assertEqual(clone.updates,0);self.assertEqual(clone._moments,{})
        for key in model.params:self.assertFalse(np.shares_memory(model.params[key],clone.params[key]))
        with self.assertRaises(AttributeError):clone.mode='direct'
    def test_checkpoint_reject_before_io(self):
        model=self.model()
        for function in (model.save,SourceSceneModel.load):
            with self.assertRaisesRegex(ValueError,'checkpoint unsupported'):function(object())
    def test_explicit_mode_and_dimensions(self):
        with self.assertRaises(TypeError):SourceSceneModel(202,12,192)
        with self.assertRaises(ValueError):SourceSceneModel(202,12,192,mode='direct')
        with self.assertRaises(ValueError):SourceSceneModel(192,12,192,mode=MODE)
