import json
import unittest
from pathlib import Path
import numpy as np
import evaluate as e

class Controls(unittest.TestCase):
    def test_auroc_perfect(self):
        self.assertEqual(e.metrics(np.array([-1.,1.]),np.array([0,1]))['auroc'],1)
    def test_auroc_tie(self):
        self.assertEqual(e.metrics(np.array([0.,0.]),np.array([0,1]))['auroc'],.5)
    def test_nll_zero(self):
        self.assertAlmostEqual(e.nll(np.zeros(2),np.array([0,1])),np.log(2))
    def test_fit_gradient(self):
        x=np.array([-2.,-1.,0.,1.,2.]); y=np.array([0.,0.,1.,0.,1.]); penalty=.01
        w=e.fit(x,y,penalty); a=np.column_stack([np.ones(5),x]); p=1/(1+np.exp(-a@w))
        np.testing.assert_allclose(a.T@(p-y)/5+[0,penalty*w[1]],0,atol=1e-8)
    def test_fit_permutation(self):
        x=np.array([-2.,-1.,0.,1.,2.]); y=np.array([0.,0.,1.,0.,1.])
        np.testing.assert_allclose(e.fit(x,y,.01),e.fit(x[::-1],y[::-1],.01),atol=1e-10)
    def test_fit_no_test_input(self):
        fit=json.loads((e.OUT/'frozen-fit.json').read_text())
        self.assertFalse(any('test' in k for k in fit['fit_input_sha256']))
        source=Path(e.__file__).read_text()
        self.assertLess(source.index("save('frozen-fit.json'"),source.index("rows['test']=load_rows('test')"))
    def test_dot_matches_cosine(self):
        a=np.array([3.,4.]); b=np.array([-4.,3.])
        self.assertAlmostEqual(float((a/np.linalg.norm(a))@(b/np.linalg.norm(b))),0)
    def test_frozen_authority(self):
        r=json.loads((e.OUT/'results.json').read_text())
        self.assertEqual(r['authority'],'DENY_ALL'); self.assertFalse(r['production_activation_allowed'])

if __name__=='__main__': unittest.main()
