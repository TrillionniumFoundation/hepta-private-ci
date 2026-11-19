import unittest
import numpy as np
from reference import rational_row,extended_row

IDENT=np.arange(12)
def fixture():
    p=np.arange(1,13,dtype=float);p/=p.sum();q=np.arange(12,0,-1,dtype=float)**2;q/=q.sum()
    i,j=np.indices((12,12));r=.3*(i==2)+.3*(j==2)+.3*((i==2)&(j==2))-.3*(i!=j)
    return p,q,r

class ReferenceTests(unittest.TestCase):
    def test_extended_matches_exact_normalized_tables_and_gradients(self):
        p,q,r=fixture()
        for rho in (0.,1.5):
            a=rational_row(p,q,r,IDENT,IDENT,IDENT,IDENT,rho,mode='simplex');b=extended_row(p,q,r,IDENT,IDENT,IDENT,IDENT,rho)
            self.assertTrue(a['admitted'] and b['admitted']);self.assertEqual(a['relative_balance'],0)
            for key in ('table','gradient_p','gradient_q'):np.testing.assert_allclose(a[key],b[key],rtol=0,atol=1e-12)

    def test_reference_logweight_directional_derivatives(self):
        p,q,r=fixture();z,w=np.log(p),np.log(q);direction=np.asarray([1,-1]*6,dtype=float)
        for rho in (0.,1.5):
            ref=rational_row(p,q,r,IDENT,IDENT,IDENT,IDENT,rho,mode='simplex')
            for side in (0,1):
                def loss(delta):
                    pp=np.exp(z+delta*direction) if side==0 else p
                    qq=np.exp(w+delta*direction) if side==1 else q
                    return -rational_row(pp,qq,r,IDENT,IDENT,IDENT,IDENT,rho,mode='simplex')['value']
                numeric=(loss(1e-6)-loss(-1e-6))/2e-6
                analytic=float(np.dot(ref['gradient_p' if side==0 else 'gradient_q'],direction))
                self.assertAlmostEqual(numeric,analytic,places=7)

    def test_mass_closure_reference_does_not_silently_repair_represented_mode(self):
        p=np.full(12,1/16);p[0]+=1/4;r=2.**-20;parts=np.asarray([r/2,r/4,r/8,r/16,r/32,r/32]);q=p.copy();q[::2]+=parts;q[1::2]-=parts;q[0]+=2.**-40
        reward=np.eye(12);raw=rational_row(p,q,reward,IDENT,IDENT,IDENT,IDENT,1.5,mode='represented')
        normalized=rational_row(p,q,reward,IDENT,IDENT,IDENT,IDENT,1.5,mode='simplex')
        self.assertFalse(raw['admitted']);self.assertGreater(raw['relative_balance'],0);self.assertTrue(raw['exact_closure_identity'])
        self.assertTrue(normalized['admitted']);self.assertEqual(normalized['relative_balance'],0)
        self.assertIsNone(raw['gradient_p'])

    def test_ties_refused_constants_zero_and_inputs_unchanged(self):
        p,q,r=fixture();copies=[x.copy() for x in (p,q,r)]
        for fn in (lambda *args:rational_row(*args,mode='simplex'),extended_row):
            tied=fn(p,p,r,IDENT,IDENT,IDENT,IDENT,1.5);self.assertFalse(tied['admitted']);self.assertIsNone(tied['gradient_p'])
            const=fn(p,q,r,np.zeros(12,dtype=int),np.ones(12,dtype=int),IDENT,IDENT,1.5)
            self.assertTrue(const['admitted']);np.testing.assert_array_equal(const['gradient_p'],np.zeros(12));np.testing.assert_array_equal(const['gradient_q'],np.zeros(12))
        for a,b in zip((p,q,r),copies):np.testing.assert_array_equal(a,b)

if __name__=='__main__':unittest.main()
