import unittest,itertools,json
import numpy as np
from control import Command,ControlProfile,MODE as CONTROL_MODE
from transport import TransportProfile,TRANSPORT_MODE
from coupling import CouplingProfile,COUPLING_MODE
from normalized import NormalizedCouplingProfile,MODE as BASE_MODE,apply_batch as base_apply
from calibration import TemperatureProfile,MODE,LOWER,UPPER,STEPS,EVALUATIONS,apply_batch,calibrate_marginals,fit_inverse_temperature,nll_stats

SHA='a'*64;MEASUREMENTS={}
def profile():
    ts=tuple((i+3)%12 for i in range(12));ims=tuple((i+7)%12 for i in range(12))
    return NormalizedCouplingProfile(CouplingProfile(TransportProfile(ControlProfile(SHA,ts,ims,CONTROL_MODE),TRANSPORT_MODE),COUPLING_MODE),BASE_MODE)
def rows():
    p=np.asarray([[.8,.2]+[0.]*10]*4);y=np.asarray([0,0,0,1]);return p,y

class CalibrationTests(unittest.TestCase):
    def test_nll_gradient_hessian_centered_differences(self):
        p,y=rows();maximum=0.
        for tau in (.25,1.,4.):
            a=nll_stats(p,y,tau);lo=nll_stats(p,y,tau-1e-5);hi=nll_stats(p,y,tau+1e-5)
            numeric=(hi['nll']-lo['nll'])/2e-5;hess=(hi['gradient']-lo['gradient'])/2e-5
            maximum=max(maximum,abs(numeric-a['gradient']),abs(hess-a['hessian']))
            self.assertLessEqual(abs(numeric-a['gradient']),1e-8);self.assertLessEqual(abs(hess-a['hessian']),1e-8);self.assertGreaterEqual(a['hessian'],0)
        MEASUREMENTS['NLL_gradient_hessian_FD_max_abs']=maximum

    def test_fixed_root_matches_binary_closed_form(self):
        p,y=rows();r=fit_inverse_temperature(p,y);expected=np.log(3)/np.log(4)
        self.assertEqual(r['status'],'interior_bisection');self.assertEqual(r['evaluations'],28);self.assertEqual(r['bisection_steps'],24)
        self.assertLess(abs(r['inverse_temperature']-expected),3e-7);self.assertLessEqual(r['chosen']['nll'],r['baseline']['nll'])
        MEASUREMENTS['binary_root_abs_error']=float(abs(r['inverse_temperature']-expected));MEASUREMENTS['binary_fit']=r

    def test_boundary_and_flat_work_never_early_stops(self):
        p,y=rows()
        cases=((p,np.zeros(4,dtype=int),'upper_boundary',UPPER),(p,np.ones(4,dtype=int),'lower_boundary',LOWER),
               (np.full((4,12),1/12),y,'flat_identity',1.),(np.asarray([[1.]+[0.]*11]*4),np.zeros(4,dtype=int),'flat_identity',1.))
        for pp,yy,status,tau in cases:
            r=fit_inverse_temperature(pp,yy);self.assertEqual(r['evaluations'],EVALUATIONS);self.assertEqual(r['status'],status);self.assertEqual(r['inverse_temperature'],tau)

    def test_all36commands_actual_CDF_support_and_argmax(self):
        commands=tuple(Command(*x) for x in itertools.product(range(4),range(3),range(3)))
        pr=profile();p=np.arange(1,13,dtype=float);p/=p.sum();q=np.arange(12,0,-1,dtype=float)**2;q/=q.sum();p=np.tile(p,(36,1));q=np.tile(q,(36,1))
        base=base_apply(pr,p,q,commands,observed_model_sha256=SHA);joint=base['joint']/base['cdf_total'][:,None,None];a,b=joint.sum(2),joint.sum(1)
        maximum=0.
        for ta,tb in ((1.,1.),(LOWER,UPPER),(UPPER,LOWER)):
            prof=TemperatureProfile(pr,ta,tb,MODE);actual=apply_batch(prof,p,q,commands,observed_model_sha256=SHA)
            np.testing.assert_array_equal(actual['text'].argmax(1),a.argmax(1));np.testing.assert_array_equal(actual['image'].argmax(1),b.argmax(1))
            np.testing.assert_array_equal(actual['text']>0,a>0);np.testing.assert_array_equal(actual['image']>0,b>0)
            if ta==tb==1.:
                maximum=float(np.max(np.abs(actual['joint']/actual['cdf_total'][:,None,None]-joint)));self.assertLessEqual(maximum,1e-12)
        MEASUREMENTS['served_literal_cases']=108;MEASUREMENTS['unit_temperature_joint_max_difference']=maximum

    def test_profile_roundtrip_model_and_mode_binding(self):
        pr=TemperatureProfile(profile(),.5,2.,MODE)
        same=TemperatureProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=MODE);self.assertEqual(same.dumps(),pr.dumps());self.assertNotEqual(pr.key,pr.base.key)
        for mode in (BASE_MODE,'independent'):
            with self.assertRaises(ValueError):TemperatureProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=mode)
        with self.assertRaises(ValueError):TemperatureProfile.loads(pr.dumps(),expected_model_sha256='b'*64,expected_mode=MODE)
        with self.assertRaises(ValueError):TemperatureProfile.loads(pr.base.dumps(),expected_model_sha256=SHA,expected_mode=MODE)
        with self.assertRaises(ValueError):NormalizedCouplingProfile.loads(pr.dumps(),expected_model_sha256=SHA,expected_mode=BASE_MODE)
        doc=json.loads(pr.dumps());doc['profile']['text_inverse_temperature']=float(1.).hex()
        with self.assertRaises(ValueError):TemperatureProfile.loads(json.dumps(doc),expected_model_sha256=SHA,expected_mode=MODE)

    def test_inputs_immutable_and_no_unsupported_target_or_bad_temperature(self):
        p,y=rows();copy=p.copy();yc=y.copy();fit_inverse_temperature(p,y);np.testing.assert_array_equal(p,copy);np.testing.assert_array_equal(y,yc)
        with self.assertRaises(ValueError):fit_inverse_temperature(p,np.full(4,2,dtype=int))
        for tau in (0.,-1.,float('nan'),.01,100.):
            with self.assertRaises(ValueError):TemperatureProfile(profile(),tau,1.,MODE)
        with self.assertRaises(ValueError):nll_stats(p*np.nan,y,1.)

    def test_serving_refuses_numerical_support_loss(self):
        p=np.full((1,12),1e-50);p[0,0]=1.-11e-50;q=np.arange(1,13,dtype=float)[None,:];q/=q.sum()
        pr=TemperatureProfile(profile(),8.,1.,MODE)
        with self.assertRaisesRegex(ValueError,'support/argmax/marginal'):
            apply_batch(pr,p,q,(Command(0,0,0),),observed_model_sha256=SHA)

if __name__=='__main__':unittest.main()
