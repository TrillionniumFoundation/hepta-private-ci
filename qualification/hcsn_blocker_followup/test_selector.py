import unittest
import numpy as np
from . import selector,metrics


class PolicyChecks(unittest.TestCase):
    def test_inference_uses_only_first_prefix(self):
        rng=np.random.default_rng(4)
        s=rng.random((9,6,2)); g=rng.random((9,6,2)); a=rng.random((9,6,13))
        z=selector.visible(s,g,a)
        s[:,1:]=100.; g[:,1:]=100.; a[:,1:]=100.; a[:,0,8:]=200.
        np.testing.assert_array_equal(z,selector.visible(s,g,a))

    def test_source_weighted_svd_and_profile_gradient(self):
        rng=np.random.default_rng(15)
        x=rng.normal(size=(23,8)); y=rng.normal(size=23)
        w=selector.source_mass(np.repeat([0,1],[5,18]))
        self.assertAlmostEqual(w[:5].sum(),.5)
        matrix=rng.normal(size=(8,4)); direction=rng.normal(size=matrix.shape)
        def objective(mat):
            h=np.tanh(x@mat)
            beta,bias=selector.solve(h,y,w,.1)
            r=h@beta+bias-y
            self.assertAlmostEqual(w@r,0.,places=10)
            np.testing.assert_allclose(h.T@(w*r)+.1*beta,0.,atol=1.e-10)
            grad=x.T@((2*w*r)[:,None]*beta*(1-h*h))
            return w@(r*r)+.1*beta@beta, np.sum(grad*direction)
        _,analytic=objective(matrix);eps=1e-5
        fd=(objective(matrix+eps*direction)[0]-objective(matrix-eps*direction)[0])/(2*eps)
        self.assertAlmostEqual(analytic,fd,places=7)

    def test_equal_price_abstains(self):
        rates=np.array([.299,.30,.31])
        for m in selector.MODELS:
            pred={m:rates,'global':rates}
            np.testing.assert_array_equal(selector.actions(m+'/0.00',pred),[0,0,1])

    def test_source_not_window_is_independent(self):
        ranks=np.array([[1,0],[0,1],[0,1],[1,0]])[:,None,:]
        test={'target':np.zeros(4),'group':np.array(['a','b','b','b']),
              'scores':ranks,'read_scores':1-ranks}
        result=metrics.evaluate(test,np.ones(4,dtype=bool))
        self.assertAlmostEqual(result['oracle_buy_gain'],.7/3)
        self.assertEqual(result['bought'],{'rescue':2,'harm':2,'already_right':0,'both_wrong':0})
        self.assertEqual(metrics.sign_p([1,0,-1]),.75)

if __name__=='__main__':unittest.main()
