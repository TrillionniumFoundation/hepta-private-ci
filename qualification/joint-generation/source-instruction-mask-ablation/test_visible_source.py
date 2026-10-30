import unittest
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE as MASK_MODE
from visible_source import SourceInstructionVisibleModel,MODE
class VisibleSourceTests(unittest.TestCase):
    def model(self):return SourceInstructionVisibleModel(202,12,192,seed=17,mode=MODE)
    def data(self):return np.arange(404,dtype=float).reshape(2,202)/404
    def test_same_initial_parameters_and_input_copy_no_zero(self):
        model=self.model();raw=JointModel(202,12,192,seed=17);masked=SourceSceneModel(202,12,192,seed=17,mode=MASK_MODE);x=self.data();original=x.copy();clean=model._input(x)
        np.testing.assert_array_equal(clean,x);self.assertFalse(np.shares_memory(clean,x));self.assertTrue(np.any(clean[:,-10:]!=0))
        for key in raw.params:
            np.testing.assert_array_equal(model.params[key],raw.params[key]);np.testing.assert_array_equal(model.params[key],masked.params[key])
        model.forward(x);np.testing.assert_array_equal(x,original)
        self.assertEqual(len({model.digest(),masked.digest(),raw.digest()}),3)
    def test_direct_gradient_equivalence_and_seven_coordinates(self):
        model=self.model();raw=JointModel(202,12,192,seed=17);x=self.data();y=np.array([1,5]);pt,pi=model.forward(x)
        for a,b in zip((pt,pi),raw.forward(x)):np.testing.assert_array_equal(a,b)
        dt=pt.copy();di=pi.copy();dt[np.arange(2),y]-=1;di[np.arange(2),y]-=1
        grads=model.gradients(x,dt/4,di/4);reference=raw.gradients(x,dt/4,di/4)
        for key in grads:np.testing.assert_array_equal(grads[key],reference[key])
        def loss():
            p,q=model.forward(x);return -(np.log(p[np.arange(2),y])+np.log(q[np.arange(2),y])).mean()/2
        for key,index in (('encoder',(0,0)),('encoder',(195,0)),('bias',(0,)),('text',(0,1)),('text_bias',(1,)),('image',(0,5)),('image_bias',(5,))):
            value=model.params[key][index];eps=1e-6
            model.params[key][index]=value+eps;plus=loss();model.params[key][index]=value-eps;minus=loss();model.params[key][index]=value
            self.assertAlmostEqual(float(grads[key][index]),float((plus-minus)/(2*eps)),delta=2e-7)
    def test_clone_mode_digest_and_checkpoint_isolation(self):
        model=self.model();model.supervised_step(self.data(),np.array([1,5]));clone=model.clone()
        self.assertIs(type(clone),SourceInstructionVisibleModel);self.assertEqual(clone.mode,MODE);self.assertEqual(clone.digest(),model.digest());self.assertEqual(clone.updates,0);self.assertEqual(clone._moments,{})
        for key in model.params:self.assertFalse(np.shares_memory(model.params[key],clone.params[key]))
        with self.assertRaises(AttributeError):clone.mode=MASK_MODE
        for function in (clone.save,SourceInstructionVisibleModel.load):
            with self.assertRaisesRegex(ValueError,'checkpoint unsupported'):function(object())
        with self.assertRaises(ValueError):SourceInstructionVisibleModel(202,12,192,mode=MASK_MODE)
        with self.assertRaises(TypeError):SourceInstructionVisibleModel(202,12,192)
        with self.assertRaises(ValueError):SourceInstructionVisibleModel(192,12,192,mode=MODE)
