import unittest
import numpy as np
from paired_corruption import paired_images,check_request,MODE
class PairedCorruptionTests(unittest.TestCase):
    def test_paired_formula_lowviews_and_immutability(self):
        clean=np.full((8,8,3),.5);z=np.linspace(-2.,2.,192).reshape(8,8,3);c=clean.copy();old=z.copy();result=paired_images(clean,.1,z,mode=MODE)
        for name,scale in (('freshID',.1),('OOD',.35)):
            full,low=result[name];np.testing.assert_array_equal(full,np.clip(clean+scale*z,0,1));self.assertTrue(((full>=0)&(full<=1)).all())
            np.testing.assert_array_equal(low,full.reshape(4,2,4,2,3).mean(axis=(1,3)).repeat(2,0).repeat(2,1))
        np.testing.assert_array_equal(clean,c);np.testing.assert_array_equal(z,old)
    def test_fixed_literal_random_branch_and_common_latent(self):
        def fixture(seed):
            rng=np.random.default_rng(seed);sigma=float(rng.uniform(.03,.25));z=rng.normal(0.,1.,(8,8,3));return paired_images(np.full((8,8,3),.5),sigma,z,mode=MODE)
        a,b,c=fixture(17),fixture(17),fixture(19)
        for domain in ('freshID','OOD'):
            for x,y in zip(a[domain],b[domain]):np.testing.assert_array_equal(x,y)
            self.assertFalse(np.array_equal(a[domain][0],c[domain][0]))
        zero=paired_images(np.full((8,8,3),.5),.03,np.zeros((8,8,3)),mode=MODE)
        np.testing.assert_array_equal(zero['freshID'][0],zero['OOD'][0])
    def test_refuse_unregistered_endpoints_shapes_nonfinite(self):
        for fold,seed,mode in [(0,3701,MODE),(0,4711,MODE),(2,4701,MODE),(False,4701,MODE),(0,4701,'old')]:
            with self.assertRaises(ValueError):check_request(fold,seed,mode)
        for clean,sigma,z,mode in [(np.zeros((2,2,3)),.1,np.zeros((8,8,3)),MODE),(np.zeros((8,8,3)),.35,np.zeros((8,8,3)),MODE),(np.zeros((8,8,3)),.1,np.full((8,8,3),np.inf),MODE),(np.ones((8,8,3))*2,.1,np.zeros((8,8,3)),MODE),(np.zeros((8,8,3)),.1,np.zeros((8,8,3)),'old')]:
            with self.assertRaises(ValueError):paired_images(clean,sigma,z,mode=mode)
