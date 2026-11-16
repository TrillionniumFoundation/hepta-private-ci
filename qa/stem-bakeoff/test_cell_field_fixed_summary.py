import unittest
import hashlib
from pathlib import Path
import numpy as np

from cell_field_fixed_summary import (inherited_scales, quadratic_observe,
                               scaled_jacobian, projection_diagnostics,
                               predict_observation_projection)


class SummaryTests(unittest.TestCase):
    def test_finite_input_overflow_is_rejected(self):
        with self.assertRaises(ValueError):inherited_scales([1e308,0,0])
        with self.assertRaises(ValueError):scaled_jacobian([[1e308]],[2.])

    def fixture(self,p=3):
        rng=np.random.default_rng(71)
        R=rng.normal(size=(2,p,p)); H=R+R.transpose(0,2,1)
        b=rng.normal(size=(2,p)); c=np.array([.4,.7])
        x=np.r_[rng.normal(size=2*p),np.full(p,.25)]
        return x,H,b,c

    def test_all_physical_jacobian_columns(self):
        x,H,b,c=self.fixture(); _,J=quadratic_observe(x,H,b,c)
        fd=np.zeros_like(J)
        for j in range(len(x)):
            d=np.zeros_like(x);d[j]=1e-6
            fd[:,j]=(quadratic_observe(x+d,H,b,c)[0]-quadratic_observe(x-d,H,b,c)[0])/(2e-6)
        np.testing.assert_allclose(J,fd,rtol=2e-8,atol=2e-8)

    def test_scaled_jacobian_matches_finite_difference(self):
        x,H,b,c=self.fixture();s=inherited_scales(x)
        _,J=quadratic_observe(x,H,b,c);C=scaled_jacobian(J,s)
        fd=np.zeros_like(C)
        for j in range(len(x)):
            d=np.zeros_like(x);d[j]=1e-5*s[j]
            fd[:,j]=(quadratic_observe(x+d,H,b,c)[0]-quadratic_observe(x-d,H,b,c)[0])/(2e-5)
        np.testing.assert_allclose(C,fd,rtol=2e-8,atol=2e-8)

    def test_unequal_fixed_scales_and_stationary_gradient(self):
        x,H,b,c=self.fixture();b=-np.einsum('aij,j->ai',H,x[:3])
        out,J=quadratic_observe(x,H,b,c)
        np.testing.assert_allclose(out[2:],0,atol=1e-14)
        self.assertGreater(float(np.linalg.norm(J[2:,:3])),0)
        s=np.array([.05]*3+[.001]*3+[1e-6]*3);C=scaled_jacobian(J,s)
        for j in range(len(x)):
            d=np.zeros_like(x);d[j]=1e-3*s[j]
            fd=(quadratic_observe(x+d,H,b,c)[0]-quadratic_observe(x-d,H,b,c)[0])/(2e-3)
            np.testing.assert_allclose(C[:,j],fd,atol=1e-11,rtol=1e-7)

    def test_source_snapshots_match_frozen_v3_hashes(self):
        expected={
          'cell_field_control.py':'b91260462b26492e29d17da4daaa7f16be429e3b6f33e4af587bf0471e15780b',
          'cell_field_state.py':'1e30b346070056123cd198413c8d82b24040179f5aa732f25dadf506e795805f',
        }
        for filename,digest in expected.items():
            self.assertEqual(hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest(),digest)

    def test_first_step_charged_maps_match_full_for_both_observations(self):
        rng=np.random.default_rng(8)
        A=rng.normal(size=(2,6,6));E=rng.normal(size=(2,6,3));C=rng.normal(size=(3,4,6))
        u=rng.normal(size=(2,3))
        a,_=predict_observation_projection(A,E,C,u)
        b,_=predict_observation_projection(A,E,C[:,:2],u)
        np.testing.assert_allclose(a[1],b[1],atol=1e-13)
        np.testing.assert_allclose(a[1],C[1,:2]@E[0]@u[0],atol=1e-13)

    def test_fixed_anchor_scale_floors(self):
        np.testing.assert_array_equal(inherited_scales(np.zeros(6)),[.05,.05,.001,.001,1e-6,1e-6])
        x,*_=self.fixture();s=inherited_scales(x);changed=x.copy();changed[:3]*=5
        self.assertFalse(np.array_equal(s,inherited_scales(changed)))
        # Consumers retain s, not the new state's scales.
        np.testing.assert_array_equal(s,inherited_scales(x))

    def test_raw_moment_no_division_by_dimension_or_bias_correction(self):
        x,H,b,c=self.fixture();out,J=quadratic_observe(x,H,b,c)
        g=np.einsum('aij,j->ai',H,x[:3])+b
        np.testing.assert_allclose(out[2:],g@x[3:6])
        changed=x.copy();changed[3:6]*=2
        out2,_=quadratic_observe(changed,H,b,c)
        np.testing.assert_allclose(out2[:2],out[:2]);np.testing.assert_allclose(out2[2:],2*out[2:])
        np.testing.assert_array_equal(J[:,6:],0)

    def test_zero_moment_does_not_remove_moment_observability(self):
        x,H,b,c=self.fixture();x[3:6]=0
        out,J=quadratic_observe(x,H,b,c)
        np.testing.assert_array_equal(out[2:],0);np.testing.assert_array_equal(J[2:,:3],0)
        self.assertGreater(float(np.linalg.norm(J[2:,3:6])),0)

    def test_constant_probes_rank_zero(self):
        out,J=quadratic_observe(np.zeros(6),np.zeros((2,2,2)),np.zeros((2,2)),[1,2])
        diag=projection_diagnostics(J)
        self.assertEqual(diag['rank'],0);np.testing.assert_array_equal(diag['inverse'],0)

    def test_duplicate_probes_no_false_four_dimensional_rank(self):
        x,H,b,c=self.fixture();H[1]=H[0];b[1]=b[0];c[1]=c[0]
        _,J=quadratic_observe(x,H,b,c)
        self.assertEqual(projection_diagnostics(J)['rank'],2)

    def test_row_normalization_can_change_truncated_rank(self):
        C=np.diag([1.,1e-12])
        self.assertEqual(projection_diagnostics(C)['rank'],1)
        self.assertEqual(projection_diagnostics(np.diag([1.,1e12])@C)['rank'],2)
        # Thus normalization is a new numerical method, not harmless presentation.

    def test_full_row_rank_row_scale_equivalence_without_truncation(self):
        C=np.array([[1.,2.,0.],[0.,1.,1.]])
        R=np.diag([2.,.3])
        np.testing.assert_allclose(np.linalg.pinv(R@C)@R@C,np.linalg.pinv(C)@C,atol=1e-14)

    def test_parameter_dimensions_and_invalid_input(self):
        for p in (36,52):
            x,H,b,c=self.fixture(p);out,J=quadratic_observe(x,H,b,c)
            self.assertEqual(out.shape,(4,));self.assertEqual(J.shape,(4,3*p))
        x,H,b,c=self.fixture();H[0,0,1]+=1
        with self.assertRaises(ValueError):quadratic_observe(x,H,b,c)
        with self.assertRaises(ValueError):inherited_scales([0,0,-1])
        with self.assertRaises(ValueError):projection_diagnostics([[np.nan]])

    def test_extended_projection_preserves_observed_hidden_state(self):
        A=np.tile([[0.,1.,0.],[1.,0.,0.],[0.,0.,1.]],(3,1,1))
        E=np.tile([[1.],[0.],[0.]],(3,1,1))
        C=np.tile([[1.,0.,0.],[2.,0.,0.],[0.,1.,0.],[0.,2.,0.]],(4,1,1))
        u=np.array([[1.],[0.],[0.]])
        extended,all_outputs=predict_observation_projection(A,E,C,u)
        loss2,_=predict_observation_projection(A,E,C[:,:2],u)
        np.testing.assert_allclose(extended,[[0,0],[1,2],[0,0],[1,2]],atol=1e-14)
        np.testing.assert_allclose(loss2,[[0,0],[1,2],[0,0],[0,0]],atol=1e-14)
        np.testing.assert_array_equal(extended,all_outputs[:,:2])

    def test_redundant_summary_projection_equals_loss2(self):
        A=np.tile([[1.,.5,0.],[0.,1.,0.],[0.,0.,1.]],(3,1,1))
        E=np.tile([[1.],[0.],[0.]],(3,1,1))
        C2=np.tile([[1.,0.,0.],[2.,0.,0.]],(4,1,1))
        C4=np.concatenate([C2,C2],axis=1);u=np.array([[1.],[0.],[0.]])
        a,_=predict_observation_projection(A,E,C2,u)
        b,_=predict_observation_projection(A,E,C4,u)
        np.testing.assert_allclose(a,b,atol=1e-14)


if __name__=='__main__':unittest.main()
